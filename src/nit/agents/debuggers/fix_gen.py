"""FixGenerator agent — generates code fixes for confirmed bugs.

This agent (task 3.9.5):
1. Takes a confirmed bug with root cause analysis
2. Generates a code fix addressing the root cause
3. Outputs the fix as a patch or modified source code
4. Provides explanation of the fix
5. Ensures the fix follows project conventions
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.llm.engine import GenerationRequest, LLMMessage
from nit.memory.global_memory import GlobalMemory
from nit.memory.helpers import get_memory_context, inject_memory_into_messages, record_outcome

if TYPE_CHECKING:
    from pathlib import Path

    from nit.agents.analyzers.bug import BugReport
    from nit.agents.debuggers.root_cause import RootCause
    from nit.llm.engine import LLMEngine

logger = logging.getLogger(__name__)

# Fix generation thresholds
MIN_FIX_LENGTH = 10  # Minimum length for a valid fix
MIN_FIX_RATIO = 0.5  # Minimum ratio of fix length to original code length
MAX_REPRO_TEST_LENGTH = 500  # Maximum length of reproduction test to include in prompt
EXPLANATION_SEPARATOR_COUNT = 2  # Expected number of parts when splitting by explanation marker
HIGH_ROOT_CAUSE_CONFIDENCE = 0.8  # Confidence threshold for root cause clarity


@dataclass
class FixGenerationTask(TaskInput):
    """Task input for fix generation."""

    task_type: str = "generate_fix"
    """Type of task (defaults to 'generate_fix')."""

    target: str = ""
    """Target file to fix."""

    bug_report: BugReport | None = None
    """Bug report from BugAnalyzer."""

    root_cause: RootCause | None = None
    """Root cause analysis."""

    source_code: str = ""
    """Original source code with the bug."""

    reproduction_test: str = ""
    """Reproduction test code (if available)."""


@dataclass
class GeneratedFix:
    """A generated code fix."""

    fixed_code: str
    """The fixed source code."""

    patch: str
    """Unified diff patch of the changes."""

    explanation: str
    """Explanation of what the fix does and why."""

    changed_lines: list[int]
    """Line numbers that were changed."""

    safety_notes: list[str]
    """Important safety/compatibility notes about the fix."""

    confidence: float = 0.7
    """Confidence level (0.0-1.0) that the fix is correct."""


class FixGenerator(BaseAgent):
    """Generates code fixes for confirmed bugs using LLM."""

    def __init__(
        self,
        llm_engine: LLMEngine,
        project_root: Path,
        *,
        enable_memory: bool = True,
    ) -> None:
        """Initialize the FixGenerator.

        Args:
            llm_engine: LLM engine for generating fixes.
            project_root: Root directory of the project.
            enable_memory: Whether to use GlobalMemory for pattern learning.
        """
        super().__init__()
        self._llm = llm_engine
        self._project_root = project_root
        self._memory = GlobalMemory(project_root) if enable_memory else None

    @property
    def name(self) -> str:
        """Return the agent name."""
        return "FixGenerator"

    @property
    def description(self) -> str:
        """Return the agent description."""
        return "Generates code fixes for confirmed bugs"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute fix generation.

        Args:
            task: A FixGenerationTask specifying the bug to fix.

        Returns:
            TaskOutput with GeneratedFix in result['fix'].
        """
        if not isinstance(task, FixGenerationTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a FixGenerationTask instance"],
            )

        if not task.bug_report or not task.root_cause:
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Bug report and root cause analysis are required"],
            )

        try:
            logger.info("Generating fix for: %s", task.bug_report.title)

            # Step 1: Generate the fix using LLM
            fixed_code, explanation = await self._generate_fix_with_llm(
                task.bug_report,
                task.root_cause,
                task.source_code,
                task.reproduction_test,
            )

            # Step 2: Create a patch
            patch = self._create_patch(task.source_code, fixed_code, task.target)

            # Step 3: Identify changed lines
            changed_lines = self._identify_changed_lines(task.source_code, fixed_code)

            # Step 4: Generate safety notes
            safety_notes = self._generate_safety_notes(task.bug_report, task.root_cause, fixed_code)

            # Step 5: Calculate confidence
            confidence = self._calculate_fix_confidence(
                task.bug_report, task.root_cause, fixed_code
            )

            fix = GeneratedFix(
                fixed_code=fixed_code,
                patch=patch,
                explanation=explanation,
                changed_lines=changed_lines,
                safety_notes=safety_notes,
                confidence=confidence,
            )

            logger.info(
                "Generated fix with %d line changes (confidence: %.2f)",
                len(changed_lines),
                confidence,
            )

            record_outcome(
                self._memory,
                successful=True,
                domain="fix_generation",
                context_dict={
                    "domain": "debugging",
                    "bug_type": task.bug_report.bug_type.value,
                },
            )

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "fix": fix,
                },
            )

        except Exception as e:
            logger.exception("Fix generation failed: %s", e)
            record_outcome(
                self._memory,
                successful=False,
                domain="fix_generation",
                context_dict={"domain": "debugging"},
                error_message=str(e),
            )
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Fix generation error: {e}"],
            )

    async def _generate_fix_with_llm(
        self,
        bug_report: BugReport,
        root_cause: RootCause,
        source_code: str,
        reproduction_test: str,
    ) -> tuple[str, str]:
        """Generate a fix using LLM.

        Args:
            bug_report: The bug report.
            root_cause: Root cause analysis.
            source_code: Original source code.
            reproduction_test: Reproduction test.

        Returns:
            Tuple of (fixed_code, explanation).
        """
        # Build comprehensive prompt
        system_prompt = """You are an expert software engineer specializing in bug fixes.

Generate a minimal, correct code fix that:
1. Addresses the root cause, not just the symptoms
2. Follows the existing code style and conventions
3. Adds necessary validation/error handling
4. Does not introduce new bugs or regressions
5. Is as minimal as possible - only change what's necessary

Provide the COMPLETE fixed source code, not just a snippet."""

        context_parts = [
            "## Bug Information",
            f"**Type**: {bug_report.bug_type.value}",
            f"**Severity**: {bug_report.severity.value}",
            f"**Error**: {bug_report.error_message}",
            "",
            "## Root Cause Analysis",
            f"**Category**: {root_cause.category}",
            f"**Description**: {root_cause.description}",
        ]

        if root_cause.missing_checks:
            context_parts.append("\n**Missing Validations**:")
            context_parts.extend(f"- {check}" for check in root_cause.missing_checks)

        if root_cause.incorrect_assumptions:
            context_parts.append("\n**Incorrect Assumptions**:")
            context_parts.extend(
                f"- {assumption}" for assumption in root_cause.incorrect_assumptions
            )

        context_parts.extend(
            [
                "",
                "## Original Source Code",
                "```",
                source_code,
                "```",
            ]
        )

        if reproduction_test:
            context_parts.extend(
                [
                    "",
                    "## Reproduction Test",
                    "```",
                    reproduction_test[:MAX_REPRO_TEST_LENGTH],
                    "```",
                ]
            )

        context_parts.extend(
            [
                "",
                "## Fix Instructions",
                "",
                "Generate the COMPLETE fixed source code with all necessary changes.",
                "Then, on a new line after '---EXPLANATION---', explain what you changed and why.",
                "",
                "Format:",
                "```",
                "<complete fixed code>",
                "```",
                "---EXPLANATION---",
                "<explanation of the fix>",
            ]
        )

        user_prompt = "\n".join(context_parts)

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        memory_context = get_memory_context(
            self._memory,
            known_filter_key="domain",
            failed_filter_key="domain",
            filter_value="debugging",
        )
        inject_memory_into_messages(messages, memory_context)

        request = GenerationRequest(
            messages=messages,
            temperature=0.2,  # Low temperature for precise fixes
            max_tokens=4000,  # Enough for full file + explanation
        )

        response = await self._llm.generate(request)
        response_text = response.text.strip()

        # Parse the response
        fixed_code, explanation = self._parse_fix_response(response_text, source_code)

        return fixed_code, explanation

    def _parse_fix_response(self, response_text: str, original_code: str) -> tuple[str, str]:
        """Parse LLM response to extract fixed code and explanation.

        Args:
            response_text: LLM response.
            original_code: Original source code as fallback.

        Returns:
            Tuple of (fixed_code, explanation).
        """
        # Split by explanation marker
        parts = response_text.split("---EXPLANATION---")

        if len(parts) == EXPLANATION_SEPARATOR_COUNT:
            code_part = parts[0].strip()
            explanation = parts[1].strip()
        else:
            # Try to find code block
            code_part = response_text
            explanation = "Fix generated to address the identified bug."

        # Extract code from code fences if present
        code_blocks = re.findall(r"```(?:\w+)?\n(.*?)\n```", code_part, re.DOTALL)

        fixed_code = (
            code_blocks[0].strip()
            if code_blocks
            else code_part.strip()  # No code block found, use the whole response as code
        )

        # Validate that we got something reasonable
        if len(fixed_code) < MIN_FIX_LENGTH or len(fixed_code) < len(original_code) * MIN_FIX_RATIO:
            # Fix seems too short, might be incomplete
            logger.warning("Generated fix seems incomplete, using original code")
            fixed_code = original_code
            explanation = "Fix generation may be incomplete. Manual review required."

        return fixed_code, explanation

    def _create_patch(self, original: str, fixed: str, file_path: str) -> str:
        """Create a unified diff patch.

        Args:
            original: Original source code.
            fixed: Fixed source code.
            file_path: File path for patch header.

        Returns:
            Unified diff patch string.
        """
        original_lines = original.splitlines(keepends=True)
        fixed_lines = fixed.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            fixed_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )

        return "".join(diff)

    def _identify_changed_lines(self, original: str, fixed: str) -> list[int]:
        """Identify which lines were changed.

        Args:
            original: Original source code.
            fixed: Fixed source code.

        Returns:
            List of changed line numbers (1-indexed).
        """
        original_lines = original.splitlines()
        fixed_lines = fixed.splitlines()

        matcher = difflib.SequenceMatcher(None, original_lines, fixed_lines)
        changed_lines: list[int] = []

        for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
            if tag in ("replace", "delete", "insert"):
                # Add original line numbers that were affected (1-indexed)
                changed_lines.extend(range(i1 + 1, i2 + 1))

        return sorted(set(changed_lines))

    def _generate_safety_notes(
        self,
        bug_report: BugReport,
        root_cause: RootCause,
        fixed_code: str,
    ) -> list[str]:
        """Generate safety and compatibility notes for the fix.

        Args:
            bug_report: The bug report.
            root_cause: Root cause analysis.
            fixed_code: Fixed code.

        Returns:
            List of safety notes.
        """
        notes = []

        # Check for security-related fixes
        if bug_report.bug_type.value == "security_vulnerability":
            notes.append("Security fix - thorough security review recommended before deployment")

        # Check for error handling additions
        if "try" in fixed_code.lower() and "try" not in root_cause.affected_code.lower():
            notes.append("Added error handling - verify all error cases are properly covered")

        # Check for null checks
        if any(
            keyword in fixed_code.lower() for keyword in ["if not", "if !", "== null", "is none"]
        ):
            notes.append("Added validation checks - ensure they don't break valid use cases")

        # Check for data type changes
        if "type" in root_cause.description.lower():
            notes.append("Type-related fix - verify compatibility with all call sites")

        # General note
        notes.append("Run all existing tests to ensure no regressions were introduced")

        return notes

    def _calculate_fix_confidence(
        self,
        bug_report: BugReport,
        root_cause: RootCause,
        fixed_code: str,
    ) -> float:
        """Calculate confidence in the generated fix.

        Args:
            bug_report: The bug report.
            root_cause: Root cause analysis.
            fixed_code: Fixed code.

        Returns:
            Confidence level (0.0-1.0).
        """
        confidence = 0.6  # Base confidence

        # Increase confidence based on root cause clarity
        if root_cause.confidence > HIGH_ROOT_CAUSE_CONFIDENCE:
            confidence += 0.15

        # Increase if missing checks were identified and likely added
        if root_cause.missing_checks and any(
            keyword in fixed_code.lower()
            for keyword in ["if", "null", "none", "undefined", "check"]
        ):
            confidence += 0.1

        # Increase for well-known bug types
        if bug_report.bug_type.value in [
            "null_dereference",
            "type_error",
            "index_error",
        ]:
            confidence += 0.05

        # Decrease for complex categories
        if root_cause.category in ["race_condition", "logic_error"]:
            confidence -= 0.1

        return min(1.0, max(0.0, confidence))
