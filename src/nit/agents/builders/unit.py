"""UnitBuilder agent — generates unit tests using framework adapters and LLM.

This agent:
1. Receives a BuildTask specifying a source file to test
2. Assembles context (source code, AST, patterns, dependencies)
3. Selects the appropriate test framework adapter
4. Generates a prompt using the adapter's template
5. Calls the LLM to generate test code
6. Validates and runs the test with self-iteration (1.16.2, 1.16.3)
7. Classifies failures and updates memory (1.16.4, 1.16.5)
8. Returns the generated and validated test code
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from nit.adapters.registry import get_registry
from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.llm.context import ContextAssembler
from nit.llm.engine import GenerationRequest, LLMError, LLMMessage
from nit.memory.global_memory import GlobalMemory
from nit.memory.helpers import get_memory_context, inject_memory_into_messages

if TYPE_CHECKING:
    from nit.adapters.base import RunResult, TestFrameworkAdapter, ValidationResult
    from nit.llm.engine import LLMEngine

logger = logging.getLogger(__name__)

# Constants for failure classification
TIMEOUT_THRESHOLD_MS = 50000  # 50 seconds


class FailureType(Enum):
    """Classification of test generation failures (task 1.16.4)."""

    TEST_BUG = "test_bug"
    """Error in generated test code (syntax, logic, assertions)."""

    CODE_BUG = "code_bug"
    """Actual bug found in source code being tested."""

    MISSING_DEP = "missing_dep"
    """Missing dependency or infrastructure issue."""

    TIMEOUT = "timeout"
    """Test execution timed out."""

    UNKNOWN = "unknown"
    """Unable to classify the failure."""


@dataclass
class ValidationAttempt:
    """Record of a single validation attempt in the self-iteration loop."""

    attempt: int
    """Attempt number (1-indexed)."""

    test_code: str
    """Generated test code for this attempt."""

    syntax_valid: bool
    """Whether syntax validation passed."""

    syntax_errors: list[str]
    """Syntax validation errors, if any."""

    test_result: RunResult | None
    """Test execution result, if tests ran."""

    failure_type: FailureType | None
    """Classification of failure, if test failed."""

    error_message: str
    """Error message to feed back to LLM for retry."""


@dataclass
class BuildTask(TaskInput):
    """Task input for generating a test file.

    Extends TaskInput with specific fields for test generation.
    """

    task_type: str = "build_unit_test"
    """Type of task (defaults to 'build_unit_test')."""

    target: str = ""
    """Target for the task (defaults to source_file)."""

    source_file: str = ""
    """Path to the source file to generate tests for."""

    framework: str = ""
    """Name of the test framework to use (e.g. 'vitest', 'pytest')."""

    output_file: str = ""
    """Optional: path where the generated test should be written."""

    def __post_init__(self) -> None:
        """Initialize base TaskInput fields if not already set."""
        if not self.target and self.source_file:
            self.target = self.source_file


class UnitBuilder(BaseAgent):
    """Agent that generates unit tests for source files.

    Uses ContextAssembler to gather source information, selects the
    appropriate test framework adapter, generates a prompt, and calls
    the LLM to produce test code.
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
        """Initialize the UnitBuilder agent.

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
        return "unit_builder"

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return "Generates unit tests for source files using LLM and framework adapters"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute the test generation pipeline.

        Args:
            task: A BuildTask specifying the source file and framework.

        Returns:
            TaskOutput with generated test code in result['test_code'],
            or errors if generation failed.
        """
        if not isinstance(task, BuildTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a BuildTask instance"],
            )

        try:
            logger.info(
                "Generating tests for %s using %s",
                task.source_file,
                task.framework,
            )

            # Step 1: Parse source and assemble context
            source_path = self._resolve_path(task.source_file)
            context = self._context_assembler.assemble(source_path)
            logger.debug(
                "Assembled context: %d tokens, %d functions, %d classes",
                context.total_tokens,
                len(context.parse_result.functions),
                len(context.parse_result.classes),
            )

            # Step 2: Get the adapter for this framework
            adapter = self._registry.get_test_adapter(task.framework)
            if adapter is None:
                return TaskOutput(
                    status=TaskStatus.FAILED,
                    errors=[f"No adapter found for framework: {task.framework}"],
                )

            # Verify the adapter detects the framework in this project
            if not adapter.detect(self._root):
                logger.warning(
                    "Adapter %s does not detect framework in project root %s",
                    task.framework,
                    self._root,
                )

            # Step 3: Check memory for patterns (task 1.15.5)
            memory_context = self._get_memory_context(task.framework)

            # Step 4: Get the prompt template from the adapter
            prompt_template = adapter.get_prompt_template()
            rendered_prompt = prompt_template.render(context)

            # Add memory context to the prompt if available
            if memory_context:
                self._add_memory_to_prompt(rendered_prompt, memory_context)

            logger.debug(
                "Rendered prompt with %d messages for template: %s",
                len(rendered_prompt.messages),
                prompt_template.name,
            )

            # Step 5: Call LLM to generate test code
            request = GenerationRequest(messages=rendered_prompt.messages)
            response = await self._llm.generate(request)
            test_code = response.text.strip()

            logger.info(
                "Generated %d characters of test code (%d tokens used)",
                len(test_code),
                response.total_tokens,
            )

            # Step 6: Validation pipeline with self-iteration (task 1.16.2, 1.16.3)
            validation_attempts, final_test_code, final_attempt = (
                await self._run_validation_pipeline(test_code, adapter, task, request)
            )

            # Step 7: Update memory on generation outcomes (task 1.16.5)
            if self._memory:
                if final_attempt:
                    self._update_memory_from_validation(
                        task.framework, validation_attempts, final_attempt
                    )
                elif not self._enable_validation:
                    # Update memory for successful generation without validation
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
                else True  # No validation was run
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
                    "final_failure_type": (
                        final_attempt.failure_type.value
                        if final_attempt and final_attempt.failure_type
                        else None
                    ),
                },
                errors=(
                    [final_attempt.error_message]
                    if final_attempt and not validation_success
                    else []
                ),
            )

        except ValueError as exc:
            # Language detection or path resolution errors
            logger.error("Invalid input: %s", exc)
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Invalid input: {exc}"],
            )

        except LLMError as exc:
            # LLM-related errors (auth, rate limit, connection)
            logger.error("LLM error: %s", exc)
            if self._memory:
                self._memory.update_stats(successful=False)
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"LLM error: {exc}"],
            )

        except Exception as exc:
            # Catch-all for unexpected errors
            logger.exception("Unexpected error during test generation")
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

    def _get_memory_context(self, framework: str) -> dict[str, list[str]] | None:
        """Get memory context for test generation.

        Retrieves known patterns and failed patterns from GlobalMemory
        to guide test generation (task 1.15.5).

        Args:
            framework: The test framework being used.

        Returns:
            Dictionary with 'known_patterns' and 'failed_patterns' lists,
            or None if memory is disabled.
        """
        return get_memory_context(
            self._memory,
            known_filter_key="language",
            failed_filter_key="framework",
            filter_value=framework,
        )

    def _add_memory_to_prompt(
        self, rendered_prompt: object, memory_context: dict[str, list[str]]
    ) -> None:
        """Add memory context to the rendered prompt.

        Appends known and failed patterns to the prompt messages
        to guide LLM generation.

        Args:
            rendered_prompt: The rendered prompt object.
            memory_context: Dictionary with pattern lists.
        """
        if not hasattr(rendered_prompt, "messages") or not memory_context:
            return

        inject_memory_into_messages(rendered_prompt.messages, memory_context)

    async def _run_validation_pipeline(
        self,
        test_code: str,
        adapter: TestFrameworkAdapter,
        task: BuildTask,
        request: GenerationRequest,
    ) -> tuple[list[ValidationAttempt], str, ValidationAttempt | None]:
        """Run the validation pipeline with retry logic (task 1.16.2, 1.16.3).

        Args:
            test_code: Initial generated test code.
            adapter: Test framework adapter.
            task: Build task.
            request: Original generation request for retries.

        Returns:
            Tuple of (validation_attempts, final_test_code, final_attempt).
        """
        validation_attempts: list[ValidationAttempt] = []
        final_test_code = test_code
        final_attempt: ValidationAttempt | None = None

        if not self._enable_validation:
            return validation_attempts, final_test_code, final_attempt

        # Determine test file path
        test_file = self._determine_test_file_path(task, adapter)

        try:
            # First attempt
            logger.info("Validating and running generated test")
            attempt = await self._validate_and_run_test(test_code, adapter, test_file)
            validation_attempts.append(attempt)

            # Self-iteration loop: retry up to max_retries times
            retry_count = 0
            should_retry = (retry_count < self._max_retries and not attempt.syntax_valid) or (
                attempt.test_result is not None and not attempt.test_result.success
            )

            while should_retry:
                logger.info(
                    "Retry %d/%d: Previous attempt failed with %s",
                    retry_count + 1,
                    self._max_retries,
                    attempt.failure_type.value if attempt.failure_type else "unknown",
                )

                # Generate new test with feedback
                try:
                    new_test_code = await self._retry_with_feedback(request, attempt)
                    retry_count += 1

                    # Validate the new attempt
                    attempt = await self._validate_and_run_test(new_test_code, adapter, test_file)
                    attempt.attempt = retry_count + 1
                    validation_attempts.append(attempt)

                    # If successful, use this version
                    if attempt.syntax_valid and (
                        attempt.test_result is None or attempt.test_result.success
                    ):
                        final_test_code = new_test_code
                        logger.info("Retry succeeded on attempt %d", retry_count + 1)
                        break

                except Exception as exc:
                    logger.error("Error during retry: %s", exc)
                    break

                # Update retry condition
                should_retry = (retry_count < self._max_retries and not attempt.syntax_valid) or (
                    attempt.test_result is not None and not attempt.test_result.success
                )

            final_attempt = validation_attempts[-1] if validation_attempts else None

        finally:
            # Clean up temporary test file
            try:
                if test_file.exists():
                    test_file.unlink()
            except Exception as exc:
                logger.warning("Could not remove temporary test file: %s", exc)

        return validation_attempts, final_test_code, final_attempt

    async def _validate_and_run_test(
        self,
        test_code: str,
        adapter: TestFrameworkAdapter,
        test_file: Path,
    ) -> ValidationAttempt:
        """Validate test syntax and execute the test (task 1.16.2).

        Args:
            test_code: Generated test code to validate.
            adapter: Test framework adapter for validation and execution.
            test_file: Path where test will be written temporarily.

        Returns:
            ValidationAttempt with validation and execution results.
        """
        attempt = ValidationAttempt(
            attempt=1,
            test_code=test_code,
            syntax_valid=False,
            syntax_errors=[],
            test_result=None,
            failure_type=None,
            error_message="",
        )

        # Step 1: Syntax validation using tree-sitter
        logger.debug("Validating test syntax with tree-sitter")
        validation_result: ValidationResult = adapter.validate_test(test_code)

        if not validation_result.valid:
            logger.warning("Test syntax validation failed: %s", validation_result.errors)
            attempt.syntax_errors = validation_result.errors
            attempt.error_message = "Syntax validation errors:\n" + "\n".join(
                validation_result.errors
            )
            attempt.failure_type = FailureType.TEST_BUG
            return attempt

        attempt.syntax_valid = True
        logger.debug("Test syntax validation passed")

        # Step 2: Write test to temporary file and execute
        try:
            # Ensure parent directory exists
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text(test_code, encoding="utf-8")
            logger.debug("Wrote test to %s", test_file)

            # Run the test via adapter
            logger.debug("Executing test via adapter")
            test_result = await adapter.run_tests(
                self._root,
                test_files=[test_file],
                timeout=60.0,
            )
            attempt.test_result = test_result

            if test_result.success:
                logger.info("Test execution passed!")
                return attempt

            # Test failed - classify the failure
            logger.warning("Test execution failed: %s failures", test_result.failed)
            attempt.failure_type = self._classify_failure(test_result)
            attempt.error_message = self._extract_error_message(test_result)

            return attempt

        except Exception as exc:
            logger.exception("Error during test execution")
            attempt.error_message = f"Execution error: {exc}"
            attempt.failure_type = FailureType.UNKNOWN
            return attempt

    def _classify_failure(self, test_result: RunResult) -> FailureType:
        """Classify test failure type (task 1.16.4).

        Distinguishes between:
        - TEST_BUG: Error in generated test (syntax, assertions, mocking)
        - CODE_BUG: Actual bug found in source code
        - MISSING_DEP: Infrastructure issue (missing deps, imports)
        - TIMEOUT: Test execution timed out
        - UNKNOWN: Unable to classify

        Args:
            test_result: Result from test execution.

        Returns:
            FailureType classification.
        """
        # Check for timeout indicators
        if test_result.duration_ms > TIMEOUT_THRESHOLD_MS:
            return FailureType.TIMEOUT

        # Analyze error messages from failed test cases
        for test_case in test_result.test_cases:
            if test_case.failure_message:
                msg_lower = test_case.failure_message.lower()

                # Missing dependency patterns
                if any(
                    pattern in msg_lower
                    for pattern in [
                        "modulenotfounderror",
                        "cannot find module",
                        "import error",
                        "no module named",
                        "module not found",
                        "cannot resolve",
                    ]
                ):
                    return FailureType.MISSING_DEP

                # Test bug patterns (assertion errors, mocking issues)
                if any(
                    pattern in msg_lower
                    for pattern in [
                        "assertionerror",
                        "expected",
                        "but got",
                        "mock",
                        "spy",
                        "stub",
                        "undefined is not",
                        "cannot read property",
                        "typeerror",
                    ]
                ):
                    return FailureType.TEST_BUG

                # Code bug patterns (logic errors in source code)
                if any(
                    pattern in msg_lower
                    for pattern in [
                        "division by zero",
                        "null pointer",
                        "index out of bounds",
                        "stack overflow",
                        "maximum call stack",
                        "recursive",
                    ]
                ):
                    return FailureType.CODE_BUG

        # Default to test bug (most common case - generated test has issues)
        return FailureType.TEST_BUG

    def _extract_error_message(self, test_result: RunResult) -> str:
        """Extract error message from test result for LLM feedback.

        Args:
            test_result: Result from test execution.

        Returns:
            Formatted error message for LLM.
        """
        errors = [
            f"Test '{test_case.name}' failed:\n{test_case.failure_message}"
            for test_case in test_result.test_cases
            if test_case.failure_message
        ]

        if not errors and test_result.raw_output:
            # Fallback to raw output if no structured errors
            return f"Test execution failed:\n{test_result.raw_output[-500:]}"

        return "\n\n".join(errors[:3])  # Limit to first 3 errors

    async def _retry_with_feedback(
        self,
        original_prompt: GenerationRequest,
        previous_attempt: ValidationAttempt,
    ) -> str:
        """Retry test generation with feedback from previous failure (task 1.16.3).

        Args:
            original_prompt: Original generation request.
            previous_attempt: Previous validation attempt with error info.

        Returns:
            New test code generated with feedback.
        """
        # Build feedback message
        failure_type_str = (
            previous_attempt.failure_type.value if previous_attempt.failure_type else "unknown"
        )
        feedback_parts = [
            "The previous test generation attempt failed. Please fix the following issues:",
            "",
            f"**Failure Type:** {failure_type_str}",
            "",
            "**Error Details:**",
            previous_attempt.error_message,
            "",
            "**Previous Test Code:**",
            "```",
            previous_attempt.test_code[:1000],  # Limit to first 1000 chars
            "```",
            "",
            "Please generate a corrected version of the test that addresses these issues.",
        ]

        feedback_message = "\n".join(feedback_parts)

        # Create new request with feedback
        retry_messages = list(original_prompt.messages)
        retry_messages.append(LLMMessage(role="user", content=feedback_message))

        logger.debug("Retrying with feedback: %d messages", len(retry_messages))

        request = GenerationRequest(messages=retry_messages)
        response = await self._llm.generate(request)

        return response.text.strip()

    def _determine_test_file_path(self, task: BuildTask, adapter: TestFrameworkAdapter) -> Path:
        """Determine where to write the test file for validation.

        Uses task.output_file if provided, otherwise creates a temporary
        test file in the appropriate location.

        Args:
            task: Build task with source file info.
            adapter: Test framework adapter for naming conventions.

        Returns:
            Path where test file should be written.
        """
        if task.output_file:
            return self._resolve_path(task.output_file)

        # Create temporary test file path
        source_path = self._resolve_path(task.source_file)
        source_name = source_path.stem

        # Get file extension from adapter's test pattern
        patterns = adapter.get_test_pattern()
        ext = ".test.ts"  # default
        if patterns:
            # Extract extension from first pattern (e.g., "**/*.test.ts" -> ".test.ts")
            pattern = patterns[0]
            if pattern.endswith(".py"):
                ext = ".py"
            elif pattern.endswith(".test.ts"):
                ext = ".test.ts"
            elif pattern.endswith(".spec.ts"):
                ext = ".spec.ts"
            elif pattern.endswith(".test.js"):
                ext = ".test.js"

        # Use temp directory
        temp_dir = Path(tempfile.gettempdir()) / "nit_tests"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # For Python, use test_ prefix
        test_name = f"test_{source_name}{ext}" if ext.endswith(".py") else f"{source_name}{ext}"

        return temp_dir / test_name

    def _update_memory_from_validation(
        self,
        framework: str,
        attempts: list[ValidationAttempt],
        final_attempt: ValidationAttempt,
    ) -> None:
        """Update memory based on validation outcomes (task 1.16.5).

        Records what worked, what failed, and why to improve future generations.

        Args:
            framework: Test framework used.
            attempts: All validation attempts made.
            final_attempt: The final attempt result.
        """
        if not self._memory:
            return

        success = final_attempt.syntax_valid and (
            final_attempt.test_result is None or final_attempt.test_result.success
        )

        # Update generation stats
        self._memory.update_stats(
            successful=success,
            tests_generated=1,
            tests_passing=(
                final_attempt.test_result.passed
                if final_attempt.test_result
                else (1 if success else 0)
            ),
        )

        # Record patterns
        if success:
            # Extract successful patterns from final test code
            pattern = (
                f"Test generated successfully for {framework} after {len(attempts)} attempt(s)"
            )
            self._memory.add_known_pattern(
                pattern=pattern,
                context={"framework": framework, "attempts": len(attempts)},
            )
            logger.debug("Recorded successful pattern in memory")

        # Record failed pattern
        elif final_attempt.failure_type and final_attempt.error_message:
            pattern = f"{final_attempt.failure_type.value}: {final_attempt.error_message[:100]}"
            self._memory.add_failed_pattern(
                pattern=pattern,
                reason=final_attempt.error_message,
                context={"framework": framework},
            )
            logger.debug("Recorded failed pattern in memory")

        # If we had multiple attempts, record that iteration was needed
        if len(attempts) > 1:
            for idx, attempt in enumerate(attempts[:-1]):
                if attempt.failure_type:
                    self._memory.add_failed_pattern(
                        pattern=f"Attempt {idx + 1} failed with {attempt.failure_type.value}",
                        reason=attempt.error_message[:200],
                        context={"framework": framework, "attempt": idx + 1},
                    )
