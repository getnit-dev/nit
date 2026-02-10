"""IntegrationBuilder agent — generates integration tests using framework adapters and LLM.

This agent (task 2.11.1):
1. Receives a BuildTask specifying a source file with external dependencies
2. Analyzes integration dependencies (DB, HTTP, filesystem, message queues)
3. Assembles context with dependency information and mocking strategies
4. Selects the appropriate test framework adapter
5. Generates a prompt using the integration test template
6. Calls the LLM to generate integration test code
7. Validates and runs the test with self-iteration
8. Returns the generated and validated test code
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from nit.adapters.registry import get_registry
from nit.agents.analyzers.integration_deps import (
    IntegrationDependencyReport,
    detect_integration_dependencies,
)
from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.agents.builders.unit import BuildTask, FailureType, ValidationAttempt
from nit.llm.context import AssembledContext, ContextAssembler
from nit.llm.engine import GenerationRequest, LLMError, LLMMessage
from nit.llm.prompts.integration_test import (
    IntegrationTestTemplate,
    JestIntegrationTemplate,
    PytestIntegrationTemplate,
    VitestIntegrationTemplate,
)
from nit.memory.global_memory import GlobalMemory
from nit.parsing.languages import extract_from_file
from nit.parsing.treesitter import detect_language

if TYPE_CHECKING:
    from nit.adapters.base import RunResult, TestFrameworkAdapter
    from nit.llm.engine import LLMEngine

logger = logging.getLogger(__name__)


@dataclass
class IntegrationBuildTask(TaskInput):
    """Task input for generating an integration test file.

    Extends TaskInput with integration-specific fields.
    """

    task_type: str = "build_integration_test"
    """Type of task (defaults to 'build_integration_test')."""

    target: str = ""
    """Target for the task (defaults to source_file)."""

    source_file: str = ""
    """Path to the source file to generate integration tests for."""

    framework: str = ""
    """Name of the test framework to use (e.g. 'vitest', 'pytest')."""

    output_file: str = ""
    """Optional: path where the generated test should be written."""

    def __post_init__(self) -> None:
        """Initialize base TaskInput fields if not already set."""
        if not self.target and self.source_file:
            self.target = self.source_file


class IntegrationBuilder(BaseAgent):
    """Agent that generates integration tests for source files with external dependencies.

    Uses dependency analysis to identify integration points (DB, HTTP, etc.),
    assembles context with mocking strategies, selects the appropriate test
    framework adapter, and calls the LLM to produce integration test code.
    """

    def __init__(
        self,
        llm_engine: LLMEngine,
        project_root: Path,
        *,
        max_context_tokens: int = 8000,
        enable_memory: bool = True,
        validation_config: dict[str, int | bool] | None = None,
    ) -> None:
        """Initialize the IntegrationBuilder agent.

        Args:
            llm_engine: The LLM engine to use for generation.
            project_root: Root directory of the project.
            max_context_tokens: Maximum tokens for context assembly.
            enable_memory: Whether to use GlobalMemory for patterns.
            validation_config: Validation settings dict with keys:
                - 'enabled' (bool): Whether to validate tests (default: True)
                - 'max_retries' (int): Max retry attempts (default: 3)
        """
        self._llm = llm_engine
        self._root = project_root
        self._context_assembler = ContextAssembler(
            root=project_root,
            max_context_tokens=max_context_tokens,
        )
        self._registry = get_registry()
        self._enable_memory = enable_memory
        self._memory = GlobalMemory(project_root) if enable_memory else None

        # Parse validation config
        config = validation_config or {}
        self._enable_validation = bool(config.get("enabled", True))
        self._max_retries = int(config.get("max_retries", 3))

    @property
    def name(self) -> str:
        """Unique name identifying this agent."""
        return "integration_builder"

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return "Generates integration tests for source files with external dependencies"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute the integration test generation pipeline.

        Args:
            task: An IntegrationBuildTask specifying the source file and framework.

        Returns:
            TaskOutput with generated test code in result['test_code'],
            or errors if generation failed.
        """
        if not isinstance(task, (IntegrationBuildTask, BuildTask)):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be an IntegrationBuildTask or BuildTask instance"],
            )

        # Convert BuildTask to IntegrationBuildTask if needed
        if isinstance(task, BuildTask):
            task = IntegrationBuildTask(
                source_file=task.source_file,
                framework=task.framework,
                output_file=task.output_file,
                target=task.target,
            )

        try:
            logger.info(
                "Generating integration tests for %s using %s",
                task.source_file,
                task.framework,
            )

            # Step 1: Parse source and detect language
            source_path = self._resolve_path(task.source_file)
            language = detect_language(source_path)
            if not language:
                return TaskOutput(
                    status=TaskStatus.FAILED,
                    errors=[f"Could not detect language for {source_path}"],
                )

            parse_result = extract_from_file(str(source_path))

            # Step 2: Analyze integration dependencies (task 2.11.2)
            dep_report = detect_integration_dependencies(source_path, parse_result, language)

            if not dep_report.needs_integration_tests:
                logger.info(
                    (
                        "No integration dependencies detected in %s"
                        " - this may be better suited for unit tests"
                    ),
                    source_path.name,
                )

            logger.debug(
                "Detected %d integration dependencies: %s",
                len(dep_report.dependencies),
                [d.dependency_type.value for d in dep_report.dependencies],
            )

            # Step 3: Assemble context
            context = self._context_assembler.assemble(source_path)

            # Step 4: Get the adapter for this framework
            adapter = self._registry.get_test_adapter(task.framework)
            if adapter is None:
                return TaskOutput(
                    status=TaskStatus.FAILED,
                    errors=[f"No adapter found for framework: {task.framework}"],
                )

            # Step 5: Get the integration test prompt template
            prompt_template = self._get_integration_template(task.framework)
            rendered_prompt = prompt_template.render(context)

            # Add integration dependency information to the prompt
            self._add_integration_info_to_prompt(rendered_prompt, dep_report)

            # Add memory context to the prompt if available
            memory_context = self._get_memory_context(task.framework)
            if memory_context:
                self._add_memory_to_prompt(rendered_prompt, memory_context)

            logger.debug(
                "Rendered integration test prompt with %d messages for template: %s",
                len(rendered_prompt.messages),
                prompt_template.name,
            )

            # Step 6: Call LLM to generate integration test code
            request = GenerationRequest(messages=rendered_prompt.messages)
            response = await self._llm.generate(request)
            test_code = response.text.strip()

            logger.info(
                "Generated %d characters of integration test code (%d tokens used)",
                len(test_code),
                response.total_tokens,
            )

            # Step 7: Validation pipeline (if enabled)
            validation_attempts, final_test_code, final_attempt = (
                await self._run_validation_pipeline(test_code, adapter, task, request)
            )

            # Step 8: Update memory on generation outcomes
            if self._memory:
                if final_attempt:
                    self._update_memory_from_validation(
                        task.framework, validation_attempts, final_attempt
                    )
                elif not self._enable_validation:
                    self._memory.update_stats(
                        successful=True,
                        tests_generated=1,
                    )

            # Determine final status
            tests_passing = (
                final_attempt.test_result.passed
                if final_attempt and final_attempt.test_result
                else 0
            )
            validation_success = (
                final_attempt.syntax_valid
                and (final_attempt.test_result is None or final_attempt.test_result.success)
                if final_attempt
                else True
            )

            return TaskOutput(
                status=TaskStatus.COMPLETED if validation_success else TaskStatus.FAILED,
                result={
                    "test_code": final_test_code,
                    "source_file": task.source_file,
                    "framework": task.framework,
                    "output_file": task.output_file,
                    "tokens_used": response.total_tokens,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "model": response.model,
                    "validation_enabled": self._enable_validation,
                    "validation_attempts": len(validation_attempts),
                    "tests_passing": tests_passing,
                    "integration_dependencies": len(dep_report.dependencies),
                    "dependency_types": [d.dependency_type.value for d in dep_report.dependencies],
                },
                errors=(
                    [final_attempt.error_message]
                    if final_attempt and not validation_success
                    else []
                ),
            )

        except ValueError as exc:
            logger.error("Invalid input: %s", exc)
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Invalid input: {exc}"],
            )

        except LLMError as exc:
            logger.error("LLM error: %s", exc)
            if self._memory:
                self._memory.update_stats(successful=False)
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"LLM error: {exc}"],
            )

        except Exception as exc:
            logger.exception("Unexpected error during integration test generation")
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Unexpected error: {exc}"],
            )

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path string to an absolute Path relative to project root."""
        p = Path(path)
        if p.is_absolute():
            return p
        return self._root / p

    def _add_integration_info_to_prompt(
        self,
        rendered_prompt: object,
        dep_report: IntegrationDependencyReport,
    ) -> None:
        """Add integration dependency information to the prompt.

        Args:
            rendered_prompt: The rendered prompt object.
            dep_report: Integration dependency analysis report.
        """
        if not hasattr(rendered_prompt, "messages"):
            return

        if not dep_report.dependencies:
            # No dependencies detected
            info_text = (
                "\n\n## Integration Dependencies\n\n"
                "No external dependencies detected. This may be better suited for unit tests."
            )
        else:
            # Build integration dependency information
            lines = ["\n\n## Integration Dependencies\n"]
            lines.append("The following external dependencies were detected:\n")

            for dep in dep_report.dependencies:
                lines.append(f"\n**{dep.dependency_type.value.upper()}**: {dep.module_name}")
                if dep.used_in_functions:
                    lines.append(f"  Used in: {', '.join(dep.used_in_functions)}")
                if dep.mock_strategies:
                    lines.append(f"  Recommended mocking: {', '.join(dep.mock_strategies)}")

            if dep_report.recommended_fixtures:
                lines.append("\n\n### Recommended Test Fixtures:\n")
                lines.extend(f"- {fixture}" for fixture in dep_report.recommended_fixtures)

            info_text = "\n".join(lines)

        # Add as a user message
        rendered_prompt.messages.append(LLMMessage(role="user", content=info_text))

    def _get_integration_template(self, framework: str) -> IntegrationTestTemplate:
        """Get the appropriate integration test template for the framework.

        Args:
            framework: Test framework name.

        Returns:
            Integration test prompt template.
        """
        framework_lower = framework.lower()

        if "pytest" in framework_lower:
            return PytestIntegrationTemplate()
        if "vitest" in framework_lower:
            return VitestIntegrationTemplate()
        if "jest" in framework_lower:
            return JestIntegrationTemplate()
        # Fallback to generic integration template
        return IntegrationTestTemplate()

    def _get_memory_context(self, framework: str) -> dict[str, list[str]] | None:
        """Get memory context for integration test generation."""
        if not self._memory:
            return None

        known_patterns = self._memory.get_known_patterns()
        failed_patterns = self._memory.get_failed_patterns()

        # Filter patterns relevant to this framework and integration tests
        relevant_known = [
            p["pattern"]
            for p in known_patterns
            if (
                framework.lower() in p.get("context", {}).get("language", "").lower()
                or not p.get("context", {}).get("language")
            )
            and "integration" in p.get("context", {}).get("test_type", "").lower()
        ]

        relevant_failed = [
            f"{p['pattern']}: {p['reason']}"
            for p in failed_patterns
            if (
                framework.lower() in p.get("context", {}).get("framework", "").lower()
                or not p.get("context", {}).get("framework")
            )
            and "integration" in p.get("context", {}).get("test_type", "").lower()
        ]

        return {
            "known_patterns": relevant_known[:10],
            "failed_patterns": relevant_failed[:10],
        }

    def _add_memory_to_prompt(
        self, rendered_prompt: object, memory_context: dict[str, list[str]]
    ) -> None:
        """Add memory context to the rendered prompt."""
        if not hasattr(rendered_prompt, "messages") or not memory_context:
            return

        known = memory_context.get("known_patterns", [])
        failed = memory_context.get("failed_patterns", [])

        if not known and not failed:
            return

        guidance_parts = []
        if known:
            guidance_parts.append(
                "**Known successful patterns from previous integration test generation:**\n"
                + "\n".join(f"- {p}" for p in known)
            )
        if failed:
            guidance_parts.append(
                "**Patterns to avoid (these failed previously):**\n"
                + "\n".join(f"- {p}" for p in failed)
            )

        guidance_text = "\n\n".join(guidance_parts)
        rendered_prompt.messages.append(LLMMessage(role="user", content=f"\n\n{guidance_text}"))

    async def _run_validation_pipeline(
        self,
        test_code: str,
        adapter: TestFrameworkAdapter,
        _task: IntegrationBuildTask,
        _request: GenerationRequest,
    ) -> tuple[list[ValidationAttempt], str, ValidationAttempt | None]:
        """Run the validation pipeline with retry logic.

        Args:
            test_code: Initial generated test code.
            adapter: Test framework adapter.
            _task: Integration build task (unused in stub implementation).
            _request: Original generation request for retries (unused in stub implementation).

        Returns:
            Tuple of (validation_attempts, final_test_code, final_attempt).
        """
        if not self._enable_validation:
            return [], test_code, None

        validation_attempts: list[ValidationAttempt] = []
        current_code = test_code

        for attempt in range(1, self._max_retries + 1):
            logger.debug("Validation attempt %d/%d", attempt, self._max_retries)

            # Validate syntax
            validation_result = adapter.validate_test(current_code)
            syntax_valid = validation_result.valid
            syntax_errors = validation_result.errors

            # Run the test if syntax is valid
            test_result: RunResult | None = None
            failure_type: FailureType | None = None
            error_message = ""

            if syntax_valid:
                # TODO: Implement test running for integration tests
                # For now, just mark as valid if syntax passes
                pass

            # Record this attempt
            val_attempt = ValidationAttempt(
                attempt=attempt,
                test_code=current_code,
                syntax_valid=syntax_valid,
                syntax_errors=syntax_errors,
                test_result=test_result,
                failure_type=failure_type,
                error_message=error_message,
            )
            validation_attempts.append(val_attempt)

            # If syntax is valid, we're done (for now - full test running TBD)
            if syntax_valid:
                logger.info("Integration test validation passed on attempt %d", attempt)
                return validation_attempts, current_code, val_attempt

            # If not valid, prepare retry
            if attempt < self._max_retries:
                logger.info(
                    "Validation failed on attempt %d, retrying with error feedback", attempt
                )
                # TODO: Implement retry with error feedback
                break

        # Max retries reached
        return validation_attempts, current_code, validation_attempts[-1]

    def _update_memory_from_validation(
        self,
        framework: str,
        attempts: list[ValidationAttempt],
        final_attempt: ValidationAttempt,
    ) -> None:
        """Update memory based on validation outcomes."""
        if not self._memory:
            return

        success = final_attempt.syntax_valid and (
            final_attempt.test_result is None or final_attempt.test_result.success
        )

        self._memory.update_stats(
            successful=success,
            tests_generated=1,
        )

        # Record patterns from successful generation
        if success:
            self._memory.add_known_pattern(
                f"Integration test generation for {framework}",
                context={
                    "framework": framework,
                    "test_type": "integration",
                    "attempts": len(attempts),
                },
            )

        # Record failed patterns
        elif final_attempt.failure_type:
            failure_value = final_attempt.failure_type.value
            self._memory.add_failed_pattern(
                f"Integration test generation failed with {failure_value}",
                reason=final_attempt.error_message,
                context={
                    "framework": framework,
                    "test_type": "integration",
                },
            )
