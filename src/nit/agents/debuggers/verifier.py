"""BugVerifier agent — confirms suspected bugs with minimal reproduction tests.

This agent (task 3.9.2):
1. Takes a suspected bug from BugAnalyzer
2. Creates a minimal reproduction test case
3. Runs the test to confirm the bug is real
4. Returns confirmation with reproduction details
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.llm.engine import GenerationRequest, LLMMessage

if TYPE_CHECKING:
    from pathlib import Path

    from nit.adapters.base import TestFrameworkAdapter
    from nit.agents.analyzers.bug import BugReport
    from nit.llm.engine import LLMEngine

logger = logging.getLogger(__name__)

# Configuration constants
MIN_WORD_LENGTH_FOR_MATCHING = 4  # Minimum word length to extract for error matching
ERROR_MATCH_THRESHOLD = 0.5  # Minimum ratio of matching terms to confirm bug reproduction


@dataclass
class BugVerificationTask(TaskInput):
    """Task input for bug verification."""

    task_type: str = "verify_bug"
    """Type of task (defaults to 'verify_bug')."""

    target: str = ""
    """Target file being verified."""

    bug_report: BugReport | None = None
    """Bug report from BugAnalyzer."""

    source_code: str = ""
    """Source code containing the bug."""

    adapter: TestFrameworkAdapter | None = None
    """Test framework adapter to use for verification."""


@dataclass
class VerificationResult:
    """Result of bug verification."""

    is_confirmed: bool
    """Whether the bug was confirmed."""

    reproduction_test: str
    """The minimal reproduction test code."""

    test_output: str
    """Output from running the reproduction test."""

    confidence: float
    """Confidence level (0.0-1.0) that the bug is real."""

    notes: str = ""
    """Additional notes about the verification."""


class BugVerifier(BaseAgent):
    """Confirms suspected bugs by creating and running minimal reproduction tests."""

    def __init__(
        self,
        llm_engine: LLMEngine,
        project_root: Path,
    ) -> None:
        """Initialize the BugVerifier.

        Args:
            llm_engine: LLM engine for generating reproduction tests.
            project_root: Root directory of the project.
        """
        super().__init__()
        self._llm = llm_engine
        self._project_root = project_root

    @property
    def name(self) -> str:
        """Return the agent name."""
        return "BugVerifier"

    @property
    def description(self) -> str:
        """Return the agent description."""
        return "Confirms suspected bugs with minimal reproduction test cases"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute bug verification.

        Args:
            task: A BugVerificationTask specifying the bug to verify.

        Returns:
            TaskOutput with VerificationResult in result['verification'].
        """
        if not isinstance(task, BugVerificationTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a BugVerificationTask instance"],
            )

        if not task.bug_report:
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Bug report is required for verification"],
            )

        if not task.adapter:
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Test adapter is required for verification"],
            )

        try:
            logger.info("Verifying bug: %s", task.bug_report.title)

            # Step 1: Generate minimal reproduction test
            repro_test = await self._generate_reproduction_test(
                task.bug_report, task.source_code, task.adapter
            )

            # Step 2: Write test to temporary file
            test_file = self._create_temp_test_file(repro_test, task.adapter)

            # Step 3: Run the test
            test_output = await self._run_reproduction_test(test_file, task.adapter)

            # Step 4: Analyze results
            is_confirmed = self._check_bug_reproduced(test_output, task.bug_report.error_message)

            # Calculate confidence based on reproduction
            confidence = 0.95 if is_confirmed else 0.3

            verification = VerificationResult(
                is_confirmed=is_confirmed,
                reproduction_test=repro_test,
                test_output=test_output,
                confidence=confidence,
                notes=self._generate_verification_notes(
                    is_confirmed=is_confirmed,
                    test_output=test_output,
                ),
            )

            logger.info(
                "Bug verification complete: %s (confidence: %.2f)",
                "CONFIRMED" if is_confirmed else "NOT REPRODUCED",
                confidence,
            )

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "verification": verification,
                    "is_confirmed": is_confirmed,
                },
            )

        except Exception as e:
            logger.exception("Bug verification failed: %s", e)
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Verification error: {e}"],
            )

    async def _generate_reproduction_test(
        self,
        bug_report: BugReport,
        source_code: str,
        adapter: TestFrameworkAdapter,
    ) -> str:
        """Generate a minimal reproduction test for the bug.

        Args:
            bug_report: The bug report to reproduce.
            source_code: Source code containing the bug.
            adapter: Test framework adapter.

        Returns:
            Generated test code.
        """
        # Build prompt for reproduction test generation
        system_prompt = f"""You are an expert at writing minimal reproduction test cases.
Create a focused test that reproduces the following bug:

Bug Type: {bug_report.bug_type.value}
Error: {bug_report.error_message}
Location: {bug_report.location.file_path}
{f"Function: {bug_report.location.function_name}" if bug_report.location.function_name else ""}

The test should:
1. Be as minimal as possible (< 20 lines)
2. Focus only on reproducing the bug
3. Use the {adapter.name} testing framework
4. Not include any assertions that would pass - we want it to fail
5. Be self-contained with minimal setup

Source code context:
```
{source_code[:1000]}  # Truncate to keep prompt manageable
```

Generate ONLY the test code, no explanations."""

        user_prompt = f"Write a minimal reproduction test for this {bug_report.bug_type.value} bug."

        request = GenerationRequest(
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ],
            temperature=0.1,  # Low temperature for focused, deterministic output
            max_tokens=1000,  # Short test
        )

        response = await self._llm.generate(request)
        test_code = response.text.strip()

        # Clean up code fences if present
        if test_code.startswith("```"):
            lines = test_code.split("\n")
            # Remove first and last line if they're code fences
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            test_code = "\n".join(lines)

        return test_code

    def _create_temp_test_file(self, test_code: str, adapter: TestFrameworkAdapter) -> Path:
        """Create a temporary test file for verification.

        Args:
            test_code: The test code to write.
            adapter: Test framework adapter for determining file extension.

        Returns:
            Path to the temporary test file.
        """
        # Create a temp directory for verification tests
        temp_dir = self._project_root / ".nit" / "tmp" / "verification"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Determine file extension based on adapter
        # This is a simplified approach - ideally we'd query the adapter
        extension_map = {
            "pytest": ".py",
            "vitest": ".test.ts",
            "jest": ".test.js",
            "gtest": ".cpp",
            "junit": ".java",
            "go": "_test.go",
        }

        adapter_name = adapter.name.lower()
        extension = ".test.txt"  # default
        for name, ext in extension_map.items():
            if name in adapter_name:
                extension = ext
                break

        # Create unique test file
        timestamp = int(time.time() * 1000)
        test_file = temp_dir / f"bug_repro_{timestamp}{extension}"

        test_file.write_text(test_code, encoding="utf-8")
        logger.debug("Created reproduction test: %s", test_file)

        return test_file

    async def _run_reproduction_test(self, test_file: Path, adapter: TestFrameworkAdapter) -> str:
        """Run the reproduction test.

        Args:
            test_file: Path to the test file.
            adapter: Test framework adapter.

        Returns:
            Test output (raw_output from result).
        """
        try:
            # Run the test
            result = await adapter.run_tests(
                self._project_root,
                test_files=[test_file],
                timeout=30.0,
            )

            return result.raw_output

        except Exception as e:
            return f"Test execution failed: {e}"

    def _check_bug_reproduced(self, test_output: str, expected_error: str) -> bool:
        """Check if the bug was reproduced in the test output.

        Args:
            test_output: Output from running the test.
            expected_error: The expected error message from the bug report.

        Returns:
            True if the bug was reproduced.
        """
        # The test should fail with an error similar to the expected error
        if not test_output:
            return False

        # Check if the output contains failure indicators
        failure_indicators = [
            "error",
            "exception",
            "failed",
            "failure",
            "assert",
            "FAIL",
            "ERROR",
        ]

        has_failure = any(indicator in test_output.lower() for indicator in failure_indicators)

        if not has_failure:
            return False

        # Check if the error message matches
        # Extract key terms from expected error (words with 4+ characters)
        pattern = rf"\b\w{{{MIN_WORD_LENGTH_FOR_MATCHING},}}\b"
        error_terms = re.findall(pattern, expected_error.lower())

        # Check if at least ERROR_MATCH_THRESHOLD of significant terms appear in output
        if not error_terms:
            return has_failure  # If no terms to match, rely on failure indicators

        matches = sum(1 for term in error_terms if term in test_output.lower())
        match_ratio = matches / len(error_terms)

        return match_ratio >= ERROR_MATCH_THRESHOLD

    def _generate_verification_notes(self, *, is_confirmed: bool, test_output: str) -> str:
        """Generate notes about the verification process.

        Args:
            is_confirmed: Whether the bug was confirmed.
            test_output: Output from the reproduction test.

        Returns:
            Verification notes.
        """
        if is_confirmed:
            return "Bug successfully reproduced. Test failed with expected error pattern."

        # Try to explain why verification failed
        if "passed" in test_output.lower() or "ok" in test_output.lower():
            return (
                "Bug could not be reproduced - test passed unexpectedly. "
                "The bug may have been fixed already or the reproduction test is incorrect."
            )

        if "timeout" in test_output.lower():
            return "Test timed out during verification. The bug may cause an infinite loop or hang."

        if not test_output.strip():
            return "No output from test execution. The test may not have run successfully."

        return (
            "Bug could not be conclusively reproduced. "
            "The error pattern did not match expectations."
        )
