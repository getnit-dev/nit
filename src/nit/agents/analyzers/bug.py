"""BugAnalyzer agent — detects actual code bugs during test generation/execution.

This agent (task 3.9.1):
1. Analyzes test execution failures to distinguish test bugs from code bugs
2. Detects common bug patterns: NaN returns, null/undefined dereference, uncaught exceptions
3. Extracts error details: type, message, stack trace, affected code location
4. Classifies bugs by severity and type
5. Produces BugReport entries for confirmed code bugs
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.llm.engine import GenerationRequest
from nit.llm.prompts.bug_analysis import BugAnalysisContext, BugAnalysisPrompt

if TYPE_CHECKING:
    from nit.adapters.base import CaseResult as TestCaseResult
    from nit.llm.engine import LLMEngine

logger = logging.getLogger(__name__)

# Confidence thresholds
MIN_STACK_TRACE_LENGTH = 50  # Minimum length for a meaningful stack trace
LOW_CONFIDENCE_THRESHOLD = 0.6  # Threshold for using LLM analysis


class BugType(Enum):
    """Types of bugs detected by the analyzer."""

    NULL_DEREFERENCE = "null_dereference"
    UNDEFINED_VARIABLE = "undefined_variable"
    TYPE_ERROR = "type_error"
    ARITHMETIC_ERROR = "arithmetic_error"  # NaN, division by zero, overflow
    INDEX_ERROR = "index_error"  # Out of bounds
    ASSERTION_ERROR = "assertion_error"  # Failed assertion in production code
    UNCAUGHT_EXCEPTION = "uncaught_exception"
    LOGIC_ERROR = "logic_error"  # Wrong behavior, not an exception
    RESOURCE_LEAK = "resource_leak"  # File handles, connections not closed
    RACE_CONDITION = "race_condition"
    SECURITY_VULNERABILITY = "security_vulnerability"
    UNKNOWN = "unknown"


class BugSeverity(Enum):
    """Severity levels for detected bugs."""

    CRITICAL = "critical"  # Security issues, data corruption, crashes
    HIGH = "high"  # Major functionality broken
    MEDIUM = "medium"  # Important features affected
    LOW = "low"  # Minor issues, edge cases
    INFO = "info"  # Potential issues, code smells


# Bug detection patterns (error message patterns)
BUG_PATTERNS: dict[BugType, list[str]] = {
    BugType.NULL_DEREFERENCE: [
        r"Cannot read propert(?:y|ies) .* of null",
        r"Cannot read propert(?:y|ies) .* of undefined",
        r"null pointer dereference",
        r"NoneType.*has no attribute",
        r"'NoneType' object",
        r"cannot access member .* of null",
        r"null reference exception",
        r"NPE",
        r"NullPointerException",
    ],
    BugType.UNDEFINED_VARIABLE: [
        r"ReferenceError: .* is not defined",
        r"NameError: name .* is not defined",
        r"undefined variable",
        r"undeclared identifier",
    ],
    BugType.TYPE_ERROR: [
        r"TypeError",
        r"type mismatch",
        r"cannot convert .* to .*",
        r"expected .*, got .*",
        r"is not a function",
        r"is not callable",
    ],
    BugType.ARITHMETIC_ERROR: [
        r"NaN",
        r"division by zero",
        r"ZeroDivisionError",
        r"arithmetic overflow",
        r"ArithmeticException",
        r"floating point exception",
    ],
    BugType.INDEX_ERROR: [
        r"IndexError",
        r"index out of (bounds|range)",
        r"ArrayIndexOutOfBoundsException",
        r"out of bounds",
    ],
    BugType.ASSERTION_ERROR: [
        r"AssertionError(?! in test)",  # Assertion in prod code, not test
        r"assertion failed",
        r"invariant violation",
    ],
    BugType.UNCAUGHT_EXCEPTION: [
        r"Uncaught ",
        r"Unhandled ",
        r"uncaught exception",
        r"unhandled rejection",
    ],
    BugType.SECURITY_VULNERABILITY: [
        r"SQL injection",
        r"XSS",
        r"CSRF",
        r"insecure",
        r"vulnerable",
        r"security",
    ],
}

# Severity rules based on bug type
SEVERITY_RULES: dict[BugType, BugSeverity] = {
    BugType.SECURITY_VULNERABILITY: BugSeverity.CRITICAL,
    BugType.NULL_DEREFERENCE: BugSeverity.HIGH,
    BugType.UNCAUGHT_EXCEPTION: BugSeverity.HIGH,
    BugType.TYPE_ERROR: BugSeverity.MEDIUM,
    BugType.ARITHMETIC_ERROR: BugSeverity.MEDIUM,
    BugType.INDEX_ERROR: BugSeverity.MEDIUM,
    BugType.UNDEFINED_VARIABLE: BugSeverity.MEDIUM,
    BugType.ASSERTION_ERROR: BugSeverity.MEDIUM,
    BugType.LOGIC_ERROR: BugSeverity.MEDIUM,
    BugType.RACE_CONDITION: BugSeverity.HIGH,
    BugType.RESOURCE_LEAK: BugSeverity.LOW,
    BugType.UNKNOWN: BugSeverity.LOW,
}


@dataclass
class BugLocation:
    """Location of a bug in source code."""

    file_path: str
    """Path to the file containing the bug."""

    line_number: int | None = None
    """Line number where bug occurs (if known)."""

    column_number: int | None = None
    """Column number where bug occurs (if known)."""

    function_name: str | None = None
    """Name of the function containing the bug (if known)."""

    code_snippet: str | None = None
    """Code snippet showing the bug context."""


@dataclass
class BugReport:
    """Detailed bug report from analysis."""

    bug_type: BugType
    """Type of bug detected."""

    severity: BugSeverity
    """Severity level of the bug."""

    title: str
    """Short, descriptive title of the bug."""

    description: str
    """Detailed description of the bug."""

    location: BugLocation
    """Where the bug is located in the code."""

    error_message: str
    """The original error message."""

    stack_trace: str | None = None
    """Full stack trace (if available)."""

    reproduction_steps: list[str] = field(default_factory=list)
    """Steps to reproduce the bug."""

    is_code_bug: bool = True
    """True if this is a code bug, False if it's a test bug."""

    confidence: float = 1.0
    """Confidence level (0.0-1.0) that this is a real bug."""

    metadata: dict[str, str] = field(default_factory=dict)
    """Additional metadata about the bug."""


@dataclass
class BugAnalysisTask(TaskInput):
    """Task input for bug analysis."""

    task_type: str = "analyze_bug"
    """Type of task (defaults to 'analyze_bug')."""

    target: str = ""
    """Target file or test being analyzed."""

    test_result: TestCaseResult | None = None
    """Test result containing the failure."""

    error_message: str = ""
    """Error message from test execution."""

    stack_trace: str = ""
    """Stack trace from the error."""

    source_file: str = ""
    """Source file being tested."""


@dataclass
class LLMBugAnalysisResult:
    """Result from LLM-based bug analysis."""

    bug_type: BugType = BugType.UNKNOWN
    """Bug type identified by LLM."""

    severity: BugSeverity = BugSeverity.MEDIUM
    """Severity level."""

    title: str = ""
    """Bug title."""

    description: str = ""
    """Bug description."""

    confidence: float = 0.7
    """Confidence in the analysis (0.0-1.0)."""

    root_cause: str = ""
    """Root cause analysis."""

    missing_validations: list[str] = field(default_factory=list)
    """List of missing validations identified."""


class BugAnalyzer(BaseAgent):
    """Analyzes test failures to detect actual code bugs."""

    def __init__(
        self,
        llm_engine: LLMEngine | None = None,
        *,
        enable_llm_analysis: bool = True,
        llm_confidence_threshold: float = 0.7,
        project_root: Path | None = None,
    ) -> None:
        """Initialize the BugAnalyzer.

        Args:
            llm_engine: Optional LLM engine for semantic bug analysis.
            enable_llm_analysis: Whether to use LLM for UNKNOWN bugs (keyword-only).
            llm_confidence_threshold: Minimum confidence for LLM results (keyword-only).
            project_root: Project root directory for reading source files (keyword-only).
        """
        super().__init__()
        self.llm_engine = llm_engine
        self.enable_llm_analysis = enable_llm_analysis
        self.llm_confidence_threshold = llm_confidence_threshold
        self.project_root = project_root or Path.cwd()

    @property
    def name(self) -> str:
        """Return the agent name."""
        return "BugAnalyzer"

    @property
    def description(self) -> str:
        """Return the agent description."""
        return "Detects actual code bugs during test generation and execution"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute bug analysis.

        Args:
            task: A BugAnalysisTask specifying the test failure to analyze.

        Returns:
            TaskOutput with BugReport in result['bug_report'] if a code bug is detected.
        """
        if not isinstance(task, BugAnalysisTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a BugAnalysisTask instance"],
            )

        try:
            logger.info("Analyzing potential bug in %s", task.target)

            # Determine if this is a test bug or code bug
            is_code_bug = self._is_code_bug(task.error_message, task.stack_trace, task.source_file)

            if not is_code_bug:
                logger.info("Determined to be a test bug, not a code bug")
                return TaskOutput(
                    status=TaskStatus.COMPLETED,
                    result={
                        "is_code_bug": False,
                        "reason": "Error originated in test code, not production code",
                    },
                )

            # Detect bug type and severity using pattern-based approach
            bug_type = self._detect_bug_type(task.error_message)
            severity = SEVERITY_RULES.get(bug_type, BugSeverity.MEDIUM)
            confidence = self._calculate_confidence(bug_type, task.stack_trace)

            # Extract bug location
            location = self._extract_location(task.stack_trace, task.source_file)

            # Use LLM for UNKNOWN bugs or low confidence pattern matches
            if self._should_use_llm(bug_type, confidence):
                llm_result = await self._analyze_with_llm(task)
                if llm_result and llm_result.confidence >= self.llm_confidence_threshold:
                    # Use LLM results
                    bug_type = llm_result.bug_type
                    severity = llm_result.severity
                    confidence = llm_result.confidence
                    title = llm_result.title
                    description = llm_result.description
                    metadata = {"analysis_method": "llm", "root_cause": llm_result.root_cause}
                else:
                    # Fall back to pattern-based
                    title = self._generate_title(bug_type, location)
                    description = self._generate_description(task.error_message, bug_type)
                    metadata = {"analysis_method": "pattern"}
            else:
                # Use pattern-based results
                title = self._generate_title(bug_type, location)
                description = self._generate_description(task.error_message, bug_type)
                metadata = {"analysis_method": "pattern"}

            # Create bug report
            bug_report = BugReport(
                bug_type=bug_type,
                severity=severity,
                title=title,
                description=description,
                location=location,
                error_message=task.error_message,
                stack_trace=task.stack_trace,
                is_code_bug=True,
                confidence=confidence,
                metadata=metadata,
            )

            logger.info(
                "Detected %s bug: %s (severity: %s)",
                bug_type.value,
                bug_report.title,
                severity.value,
            )

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "is_code_bug": True,
                    "bug_report": bug_report,
                },
            )

        except Exception as e:
            logger.exception("Bug analysis failed: %s", e)
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Bug analysis error: {e}"],
            )

    def _is_code_bug(self, _error_message: str, stack_trace: str, source_file: str) -> bool:
        """Determine if the error is a code bug or a test bug.

        Args:
            _error_message: The error message (unused, reserved for future use).
            stack_trace: The stack trace.
            source_file: The source file being tested.

        Returns:
            True if this is a code bug, False if it's a test bug.
        """
        # If no stack trace, can't determine reliably
        if not stack_trace:
            return False

        # Parse stack trace to find where error originated
        lines = stack_trace.split("\n")

        # Look for the topmost frame in the stack trace
        for line in lines:
            # Skip empty lines and common test framework markers
            if not line.strip():
                continue

            # Common test file patterns
            if any(pattern in line.lower() for pattern in ["test_", "_test.", ".spec.", ".test."]):
                continue

            # Check if the error originated in the source file
            if source_file and source_file in line:
                return True

            # If we see a node_modules or site-packages frame first,
            # it's likely a usage error in the test
            if "node_modules" in line or "site-packages" in line:
                continue

        # Default to test bug if we can't determine
        return False

    def _detect_bug_type(self, error_message: str) -> BugType:
        """Detect the type of bug from the error message.

        Args:
            error_message: The error message to analyze.

        Returns:
            Detected bug type.
        """
        for bug_type, patterns in BUG_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, error_message, re.IGNORECASE):
                    return bug_type

        return BugType.UNKNOWN

    def _extract_location(self, stack_trace: str, source_file: str) -> BugLocation:
        """Extract bug location from stack trace.

        Args:
            stack_trace: The stack trace.
            source_file: The source file being tested.

        Returns:
            BugLocation with extracted information.
        """
        location = BugLocation(file_path=source_file)

        if not stack_trace:
            return location

        # Try to parse location from stack trace
        # Common formats:
        # JavaScript: at functionName (file.js:123:45)
        # Python: File "file.py", line 123, in functionName
        # C++/Go: file.cpp:123:45: error

        lines = stack_trace.split("\n")
        for line in lines:
            # JavaScript/TypeScript stack trace
            match = re.search(r"at (\w+) \((.+):(\d+):(\d+)\)", line)
            if match:
                function_name, file_path, line_num, col_num = match.groups()
                if source_file in file_path:
                    location.function_name = function_name
                    location.file_path = file_path
                    location.line_number = int(line_num)
                    location.column_number = int(col_num)
                    break

            # Python stack trace
            match = re.search(r'File "(.+)", line (\d+), in (\w+)', line)
            if match:
                file_path, line_num, function_name = match.groups()
                if source_file in file_path:
                    location.file_path = file_path
                    location.line_number = int(line_num)
                    location.function_name = function_name
                    break

            # C/C++/Go stack trace
            match = re.search(r"(.+):(\d+):(\d+)", line)
            if match:
                file_path, line_num, col_num = match.groups()
                if source_file in file_path:
                    location.file_path = file_path
                    location.line_number = int(line_num)
                    location.column_number = int(col_num)
                    break

        return location

    def _generate_title(self, bug_type: BugType, location: BugLocation) -> str:
        """Generate a descriptive title for the bug.

        Args:
            bug_type: Type of the bug.
            location: Location of the bug.

        Returns:
            Bug title.
        """
        type_name = bug_type.value.replace("_", " ").title()

        if location.function_name:
            return f"{type_name} in {location.function_name}"

        file_name = Path(location.file_path).name
        if location.line_number:
            return f"{type_name} in {file_name}:{location.line_number}"

        return f"{type_name} in {file_name}"

    def _generate_description(self, error_message: str, bug_type: BugType) -> str:
        """Generate a detailed description of the bug.

        Args:
            error_message: The error message.
            bug_type: Type of the bug.

        Returns:
            Bug description.
        """
        descriptions = {
            BugType.NULL_DEREFERENCE: (
                "Attempting to access a property or method on a null or undefined value."
            ),
            BugType.UNDEFINED_VARIABLE: "Referencing a variable that has not been defined.",
            BugType.TYPE_ERROR: "Operation performed on incompatible types.",
            BugType.ARITHMETIC_ERROR: (
                "Invalid arithmetic operation (division by zero, NaN, overflow)."
            ),
            BugType.INDEX_ERROR: (
                "Attempting to access an array or collection with an invalid index."
            ),
            BugType.ASSERTION_ERROR: (
                "Assertion failed in production code, indicating an invariant violation."
            ),
            BugType.UNCAUGHT_EXCEPTION: (
                "An exception was thrown but not caught, causing the program to crash."
            ),
            BugType.SECURITY_VULNERABILITY: "Potential security issue detected.",
            BugType.UNKNOWN: "An error occurred during execution.",
        }

        base_description = descriptions.get(bug_type, "An error occurred.")
        return f"{base_description}\n\nError: {error_message}"

    def _calculate_confidence(self, bug_type: BugType, stack_trace: str) -> float:
        """Calculate confidence level that this is a real bug.

        Args:
            bug_type: Type of the bug.
            stack_trace: The stack trace.

        Returns:
            Confidence level (0.0-1.0).
        """
        # Higher confidence for well-known bug patterns
        if bug_type in [
            BugType.NULL_DEREFERENCE,
            BugType.UNDEFINED_VARIABLE,
            BugType.TYPE_ERROR,
            BugType.ARITHMETIC_ERROR,
        ]:
            confidence = 0.9
        elif bug_type == BugType.UNKNOWN:
            confidence = 0.5
        else:
            confidence = 0.7

        # Increase confidence if we have a meaningful stack trace
        if stack_trace and len(stack_trace) > MIN_STACK_TRACE_LENGTH:
            confidence = min(1.0, confidence + 0.1)

        return confidence

    def _should_use_llm(self, bug_type: BugType, confidence: float) -> bool:
        """Determine if LLM analysis should be used.

        Args:
            bug_type: Detected bug type from patterns.
            confidence: Confidence from pattern-based detection.

        Returns:
            True if LLM should be used.
        """
        if not self.enable_llm_analysis or not self.llm_engine:
            return False

        # Use LLM for UNKNOWN bugs or low confidence
        return bug_type == BugType.UNKNOWN or confidence < LOW_CONFIDENCE_THRESHOLD

    async def _analyze_with_llm(self, task: BugAnalysisTask) -> LLMBugAnalysisResult | None:
        """Analyze bug using LLM.

        Args:
            task: Bug analysis task.

        Returns:
            LLM bug analysis result or None if analysis fails.
        """
        if not self.llm_engine:
            return None

        try:
            # Read source code context
            source_code = self._read_source_code(task.source_file)
            if not source_code:
                logger.warning("Could not read source file for LLM analysis")
                return None

            # Detect language
            language = self._detect_language(task.source_file)

            # Build bug analysis prompt
            context = BugAnalysisContext(
                error_message=task.error_message,
                stack_trace=task.stack_trace,
                source_code=source_code,
                language=language,
                file_path=task.source_file,
            )

            prompt = BugAnalysisPrompt()
            rendered = prompt.render_bug_analysis(context)

            # Call LLM
            request = GenerationRequest(messages=rendered.messages)
            response = await self.llm_engine.generate(request)

            # Parse response
            return self._parse_bug_analysis_response(response.text)

        except Exception as e:
            logger.warning("LLM bug analysis failed: %s", e)
            return None

    def _read_source_code(self, source_file: str) -> str:
        """Read source code file.

        Args:
            source_file: Path to source file.

        Returns:
            Source code content or empty string.
        """
        try:
            source_path = self.project_root / source_file
            if not source_path.exists():
                return ""
            return source_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning("Failed to read source file %s: %s", source_file, e)
            return ""

    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension.

        Args:
            file_path: Path to the file.

        Returns:
            Language name.
        """
        ext = Path(file_path).suffix.lower()
        language_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".cs": "csharp",
        }
        return language_map.get(ext, "unknown")

    def _parse_bug_analysis_response(self, response: str) -> LLMBugAnalysisResult | None:
        """Parse LLM response into bug analysis result.

        Args:
            response: LLM response text.

        Returns:
            Parsed result or None if parsing fails.
        """
        try:
            # Extract fields using regex
            bug_type_match = re.search(r"\*\*Bug Type\*\*:\s*(\w+)", response, re.IGNORECASE)
            is_code_bug_match = re.search(
                r"\*\*Is Code Bug\*\*:\s*(true|false)", response, re.IGNORECASE
            )
            location_match = re.search(
                r"\*\*Location\*\*:\s*(.+?)(?=\*\*|$)", response, re.IGNORECASE | re.DOTALL
            )
            root_cause_match = re.search(
                r"\*\*Root Cause\*\*:\s*(.+?)(?=\*\*|$)", response, re.IGNORECASE | re.DOTALL
            )

            # If LLM says it's not a code bug, return None
            if is_code_bug_match and is_code_bug_match.group(1).lower() == "false":
                return None

            # Parse bug type
            bug_type = BugType.UNKNOWN
            if bug_type_match:
                type_str = bug_type_match.group(1).lower()
                try:
                    bug_type = BugType(type_str)
                except ValueError:
                    # Try to map common variations
                    type_map = {
                        "null": BugType.NULL_DEREFERENCE,
                        "type": BugType.TYPE_ERROR,
                        "undefined": BugType.UNDEFINED_VARIABLE,
                        "arithmetic": BugType.ARITHMETIC_ERROR,
                        "index": BugType.INDEX_ERROR,
                    }
                    for key, value in type_map.items():
                        if key in type_str:
                            bug_type = value
                            break

            # Build result
            location_str = location_match.group(1).strip()[:50] if location_match else "in code"
            return LLMBugAnalysisResult(
                bug_type=bug_type,
                severity=SEVERITY_RULES.get(bug_type, BugSeverity.MEDIUM),
                title=f"{bug_type.value}: {location_str}",
                description=root_cause_match.group(1).strip() if root_cause_match else "",
                confidence=0.8,  # High confidence for LLM analysis
                root_cause=root_cause_match.group(1).strip() if root_cause_match else "",
            )

        except Exception as e:
            logger.warning("Failed to parse LLM bug analysis response: %s", e)
            return None
