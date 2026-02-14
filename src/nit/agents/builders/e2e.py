"""E2EBuilder agent — generates E2E tests using Playwright and LLM.

This agent:
1. Receives an E2ETask specifying a route or flow to test
2. Assembles context (route info, handler code, auth config, dependencies)
3. Selects the Playwright adapter
4. Generates a prompt using the E2E template
5. Calls the LLM to generate test code
6. Validates and runs the test with self-iteration
7. Returns the generated and validated test code
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from nit.adapters.registry import get_registry
from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.agents.healers.self_healing import HealingResult, SelfHealingEngine
from nit.llm.context import AssembledContext, ContextAssembler
from nit.llm.engine import GenerationRequest, LLMMessage
from nit.memory.global_memory import GlobalMemory
from nit.memory.helpers import get_memory_context, inject_memory_into_messages, record_outcome
from nit.parsing.treesitter import ParseResult

if TYPE_CHECKING:
    from nit.adapters.base import RunResult, TestFrameworkAdapter, ValidationResult
    from nit.config import AuthConfig
    from nit.llm.engine import LLMEngine
    from nit.models.route import RouteInfo

logger = logging.getLogger(__name__)

# Constants
_DEFAULT_TIMEOUT = 300.0  # E2E tests can take longer
_DEFAULT_MAX_RETRIES = 3


@dataclass
class E2ETask(TaskInput):
    """Task input for generating an E2E test.

    Extends TaskInput with E2E-specific fields.
    """

    task_type: str = "build_e2e_test"
    """Type of task (defaults to 'build_e2e_test')."""

    target: str = ""
    """Target for the task (defaults to route_path)."""

    route_path: str = ""
    """Route path to test (e.g., '/users/:id', '/api/posts')."""

    route_info: RouteInfo | None = None
    """Detailed route information from RouteDiscovery."""

    handler_file: str = ""
    """Path to the file containing the route handler."""

    base_url: str = ""
    """Base URL for the application (e.g., 'http://localhost:3000')."""

    auth_config: AuthConfig | None = None
    """Authentication configuration, if auth is required."""

    output_file: str = ""
    """Optional: path where the generated test should be written."""

    flow_description: str = ""
    """Optional: description of the user flow to test (e.g., 'login → dashboard → settings')."""

    def __post_init__(self) -> None:
        """Initialize base TaskInput fields if not already set."""
        if not self.target and self.route_path:
            self.target = self.route_path


class E2EBuilder(BaseAgent):
    """Agent that generates E2E tests for routes and user flows.

    Uses ContextAssembler to gather route/handler information, selects
    the Playwright adapter, generates a prompt, and calls the LLM to
    produce E2E test code.
    """

    def __init__(
        self,
        llm_engine: LLMEngine,
        project_root: Path,
        *,
        config: dict[str, int | bool | dict[str, int | bool]] | None = None,
    ) -> None:
        """Initialize the E2EBuilder agent.

        Args:
            llm_engine: The LLM engine to use for generation.
            project_root: Root directory of the project.
            config: Configuration dict with keys:
                - 'max_context_tokens' (int): Maximum tokens for context (default: 8000)
                - 'enable_memory' (bool): Whether to use GlobalMemory (default: True)
                - 'enable_self_healing' (bool): Enable self-healing (default: True)
                - 'validation' (dict): Validation settings:
                    - 'enabled' (bool): Whether to validate tests (default: True)
                    - 'max_retries' (int): Max retry attempts (default: 3)
        """
        cfg = config or {}

        self._llm = llm_engine
        self._root = project_root

        # Extract max_context_tokens with proper type handling
        max_context = cfg.get("max_context_tokens", 8000)
        if not isinstance(max_context, int):
            max_context = 8000

        self._context_assembler = ContextAssembler(
            root=project_root,
            max_context_tokens=max_context,
            token_counter=llm_engine.count_tokens,
        )
        self._registry = get_registry()
        self._enable_memory = bool(cfg.get("enable_memory", True))
        self._memory = GlobalMemory(project_root) if self._enable_memory else None
        self._enable_self_healing = bool(cfg.get("enable_self_healing", True))
        self._self_healing_engine: SelfHealingEngine | None = None

        # Parse validation config
        validation_cfg = cfg.get("validation", {})
        if isinstance(validation_cfg, dict):
            self._enable_validation = bool(validation_cfg.get("enabled", True))
            max_retries = validation_cfg.get("max_retries", _DEFAULT_MAX_RETRIES)
            self._max_retries = (
                max_retries if isinstance(max_retries, int) else _DEFAULT_MAX_RETRIES
            )
        else:
            self._enable_validation = True
            self._max_retries = _DEFAULT_MAX_RETRIES

    @property
    def name(self) -> str:
        """Unique name identifying this agent."""
        return "e2e_builder"

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return "Generates E2E tests for routes and user flows using LLM and Playwright"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute the E2E test generation pipeline.

        Args:
            task: An E2ETask specifying the route and flow to test.

        Returns:
            TaskOutput with generated test code in result['test_code'],
            or errors if generation failed.
        """
        if not isinstance(task, E2ETask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be an E2ETask instance"],
            )

        try:
            logger.info(
                "Generating E2E test for route: %s",
                task.route_path or task.flow_description,
            )

            # Step 1: Assemble context for the route/flow
            context = await self._assemble_e2e_context(task)

            # Step 2: Get the Playwright adapter
            adapter = self._registry.get_test_adapter("playwright")
            if adapter is None:
                return TaskOutput(
                    status=TaskStatus.FAILED,
                    errors=["Playwright adapter not found. Is @playwright/test installed?"],
                )

            # Verify Playwright is available in the project
            if not adapter.detect(self._root):
                logger.warning(
                    "Playwright not detected in project root %s. Test may fail to run.",
                    self._root,
                )

            # Step 3: Get the E2E prompt template and render it
            prompt_template = adapter.get_prompt_template()
            rendered_prompt = prompt_template.render(context)

            # Step 3.5: Inject memory patterns into prompt
            memory_context = get_memory_context(
                self._memory,
                known_filter_key="language",
                failed_filter_key="framework",
                filter_value="playwright",
            )
            inject_memory_into_messages(rendered_prompt.messages, memory_context)

            logger.debug(
                "Rendered E2E prompt with %d messages",
                len(rendered_prompt.messages),
            )

            # Step 4: Call LLM to generate test code
            request = GenerationRequest(
                messages=rendered_prompt.messages,
                metadata={
                    "nit_source_file": task.route_path,
                    "nit_template_name": prompt_template.name,
                    "nit_builder_name": self.name,
                    "nit_framework": "playwright",
                },
            )
            response = await self._llm.generate(request)
            test_code = response.text.strip()

            # Clean up markdown code blocks if present
            test_code = self._clean_code_blocks(test_code)

            logger.info(
                "Generated %d characters of E2E test code (%d tokens used)",
                len(test_code),
                response.total_tokens,
            )

            # Step 5: Validation pipeline (optional)
            if self._enable_validation:
                test_code, validation_result = await self._validate_and_retry(
                    test_code, adapter, request, task
                )
            else:
                validation_result = adapter.validate_test(test_code)

            # Step 6: Update memory
            record_outcome(
                self._memory,
                successful=validation_result.valid,
                domain="e2e_test",
                context_dict={"framework": "playwright", "route": task.route_path},
                error_message=(
                    "\n".join(validation_result.errors) if not validation_result.valid else ""
                ),
            )
            if self._memory:
                self._memory.update_stats(
                    successful=validation_result.valid,
                    tests_generated=1,
                )

            return TaskOutput(
                status=TaskStatus.COMPLETED if validation_result.valid else TaskStatus.FAILED,
                result={
                    "test_code": test_code,
                    "route_path": task.route_path,
                    "handler_file": task.handler_file,
                    "output_file": task.output_file,
                    "tokens_used": response.total_tokens,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "model": response.model,
                    "validation_enabled": self._enable_validation,
                    "validation_passed": validation_result.valid,
                    "flow_description": task.flow_description,
                },
                errors=validation_result.errors if not validation_result.valid else [],
            )

        except Exception as e:
            logger.exception("E2E test generation failed")
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"E2E test generation failed: {e!s}"],
            )

    async def _assemble_e2e_context(self, task: E2ETask) -> AssembledContext:
        """Assemble context for E2E test generation.

        This includes:
        - Handler code (if handler_file is provided)
        - Route information
        - Authentication configuration
        - Dependencies
        """
        # If we have a handler file, assemble context for it
        if task.handler_file:
            handler_path = self._resolve_path(task.handler_file)
            context = self._context_assembler.assemble(handler_path)
        else:
            # Create minimal context
            context = AssembledContext(
                source_path="",
                source_code="",
                language="typescript",
                parse_result=ParseResult(
                    language="typescript",
                    functions=[],
                    classes=[],
                    imports=[],
                ),
                related_files=[],
                test_patterns=None,
                total_tokens=0,
            )

        # Attach E2E-specific information to context (dynamic attributes)
        if task.route_info:
            context.route_info = task.route_info

        if task.auth_config:
            context.auth_config = task.auth_config

        if task.base_url:
            context.base_url = task.base_url

        if task.flow_description:
            context.flow_description = task.flow_description

        return context

    def _resolve_path(self, path_str: str) -> Path:
        """Resolve a path string relative to project root."""
        path = Path(path_str)
        if path.is_absolute():
            return path
        return self._root / path

    def _clean_code_blocks(self, code: str) -> str:
        """Remove markdown code blocks if the LLM wrapped the output."""
        lines = code.strip().splitlines()

        # Check if wrapped in code fence
        if lines and lines[0].startswith("```"):
            # Remove first line (opening fence)
            lines = lines[1:]

            # Remove last line if it's a closing fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

        return "\n".join(lines).strip()

    async def _validate_and_retry(
        self,
        test_code: str,
        adapter: TestFrameworkAdapter,
        initial_request: GenerationRequest,
        task: E2ETask,
    ) -> tuple[str, ValidationResult]:
        """Validate test code and retry if needed.

        Includes self-healing capabilities for selector-related failures.

        Returns:
            Tuple of (final_test_code, validation_result)
        """
        current_code = test_code

        for attempt in range(self._max_retries):
            # Syntax validation
            validation_result = adapter.validate_test(current_code)

            if validation_result.valid:
                logger.info("E2E test validation passed on attempt %d", attempt + 1)

                # If syntax is valid, try running the test to check for runtime errors
                if self._enable_self_healing and attempt == 0:
                    # Only run on first attempt to avoid excessive test runs
                    run_result = await self._try_run_test(current_code, adapter, task)

                    if run_result and not run_result.success:
                        # Test failed at runtime - try self-healing
                        logger.info("Test has runtime failures, attempting self-healing")
                        healed_result = await self._apply_self_healing(
                            current_code,
                            run_result,
                            initial_request,
                            adapter,
                            task,
                        )

                        if healed_result.healed:
                            logger.info("Self-healing successful, using healed code")
                            current_code = healed_result.healed_code
                            # Validate healed code
                            validation_result = adapter.validate_test(current_code)

                        if healed_result.is_flaky:
                            logger.warning("Test identified as FLAKY - consider manual review")
                            # Mark in memory if available
                            if self._memory:
                                self._memory.add_failed_pattern(
                                    pattern="flaky_test",
                                    reason=f"Test at {task.route_path} is flaky",
                                )

                return current_code, validation_result

            # If we've exhausted retries, return what we have
            if attempt == self._max_retries - 1:
                logger.warning("E2E test validation failed after %d attempts", self._max_retries)
                return current_code, validation_result

            # Retry with error feedback
            logger.info(
                "E2E test validation failed (attempt %d), retrying with error feedback",
                attempt + 1,
            )

            error_message = "\n".join(validation_result.errors)
            retry_messages = [
                *initial_request.messages,
                LLMMessage(role="assistant", content=current_code),
                LLMMessage(
                    role="user",
                    content=(
                        f"The generated test has syntax errors:\n\n{error_message}\n\n"
                        "Please fix the errors and generate the corrected test code."
                    ),
                ),
            ]

            retry_request = GenerationRequest(messages=retry_messages)
            response = await self._llm.generate(retry_request)
            current_code = self._clean_code_blocks(response.text.strip())

        # Should not reach here, but return last attempt
        return current_code, validation_result

    async def _try_run_test(
        self,
        test_code: str,
        adapter: TestFrameworkAdapter,
        task: E2ETask,
    ) -> RunResult | None:
        """Try running the test to check for runtime errors.

        Returns None if test cannot be run (e.g., no output file).
        """
        if not task.output_file:
            return None

        # Write test to file temporarily for execution
        test_file = self._root / task.output_file
        test_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            test_file.write_text(test_code, encoding="utf-8")

            # Run the test
            return await adapter.run_tests(
                self._root,
                test_files=[test_file],
                timeout=60.0,
            )

        except Exception as e:
            logger.warning("Could not run test for validation: %s", e)
            return None

    async def _apply_self_healing(
        self,
        test_code: str,
        run_result: RunResult,
        initial_request: GenerationRequest,
        adapter: TestFrameworkAdapter,
        task: E2ETask,
    ) -> HealingResult:
        """Apply self-healing to a failing test.

        Returns:
            HealingResult with the outcome of healing attempt.
        """
        # Initialize self-healing engine if not already done
        if self._self_healing_engine is None:
            self._self_healing_engine = SelfHealingEngine(
                llm_engine=self._llm,
                adapter=adapter,
                flaky_test_retries=3,
                max_healing_attempts=2,
            )

        # Attempt healing
        test_file = Path(task.output_file) if task.output_file else None

        healing_result = await self._self_healing_engine.heal_test(
            test_code=test_code,
            run_result=run_result,
            original_request=initial_request,
            project_path=self._root,
            test_file=test_file,
        )

        # Log healing messages
        for msg in healing_result.messages:
            logger.info("Self-healing: %s", msg)

        return healing_result
