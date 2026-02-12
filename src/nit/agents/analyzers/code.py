"""CodeAnalyzer agent — performs deep code analysis using tree-sitter.

This agent (task 1.20):
1. Parses source files with tree-sitter → extracts structured code map
2. Calculates cyclomatic complexity per function
3. Builds call graphs (which functions call which)
4. Detects side effects (DB, filesystem, HTTP, external services)
5. Provides detailed code metrics for prioritization
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.parsing.languages import extract_from_file
from nit.parsing.treesitter import detect_language

if TYPE_CHECKING:
    from nit.parsing.treesitter import ClassInfo, FunctionInfo, ImportInfo, ParseResult

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

# Complexity thresholds
COMPLEXITY_THRESHOLD_HIGH = 10  # Functions with complexity > 10 are complex
COMPLEXITY_THRESHOLD_MODERATE = 5  # Functions with complexity 5-10 are moderate


class SideEffectType(Enum):
    """Types of side effects detected in code."""

    DATABASE = "database"
    FILESYSTEM = "filesystem"
    HTTP = "http"
    EXTERNAL_PROCESS = "external_process"
    LOGGING = "logging"
    UNKNOWN = "unknown"


# Side effect detection patterns (import module patterns)
SIDE_EFFECT_PATTERNS = {
    SideEffectType.DATABASE: [
        r"\bsqlalchemy\b",
        r"\bdjango\.db\b",
        r"\bpsycopg\d?\b",
        r"\bmysql\b",
        r"\bpymongo\b",
        r"\bsqlite3\b",
        r"\bpg\b",
        r"\bmssql\b",
        r"\boracle\b",
        r"\bsequelize\b",
        r"\bmongoose\b",
        r"\bprisma\b",
        r"\bdrizzle\b",
    ],
    SideEffectType.FILESYSTEM: [
        r"\bopen\(",
        r"\bfs\.",
        r"\bpath\.",
        r"\bshutil\b",
        r"\bos\.path\b",
        r"\bpathlib\b",
        r"\bfile_get_contents\b",
        r"\bfile_put_contents\b",
    ],
    SideEffectType.HTTP: [
        r"\brequests\b",
        r"\bhttpx\b",
        r"\baxios\b",
        r"\bfetch\(",
        r"\bhttp\b",
        r"\bhttps\b",
        r"\burl",
        r"\baiohttp\b",
        r"\bgot\b",
        r"\bsuperagent\b",
    ],
    SideEffectType.EXTERNAL_PROCESS: [
        r"\bsubprocess\b",
        r"\bchild_process\b",
        r"\bexec\(",
        r"\bspawn\(",
        r"\bpopen\b",
    ],
    SideEffectType.LOGGING: [
        r"\blogging\b",
        r"\bwarn\(",
        r"\blog\(",
        r"\bconsole\.",
        r"\bprint\(",
    ],
}

# Call expression patterns for side effect detection
CALL_PATTERNS = {
    SideEffectType.FILESYSTEM: [
        r"\bopen\(",
        r"\breadFile\(",
        r"\bwriteFile\(",
        r"\bwriteFileSync\(",
        r"\breadFileSync\(",
        r"\bread_text\(",
        r"\bwrite_text\(",
        r"\bunlink\(",
        r"\brm\(",
        r"\bmkdir\(",
    ],
    SideEffectType.HTTP: [
        r"\bfetch\(",
        r"\bget\(",
        r"\bpost\(",
        r"\bput\(",
        r"\bdelete\(",
        r"\brequest\(",
        r"\baxios\.",
    ],
    SideEffectType.EXTERNAL_PROCESS: [
        r"\bexec\(",
        r"\bspawn\(",
        r"\bpopen\(",
        r"\brun\(",
    ],
}


# ── Data models ──────────────────────────────────────────────────


@dataclass
class ComplexityMetrics:
    """Cyclomatic complexity metrics for a function."""

    cyclomatic: int
    """Cyclomatic complexity (1 + decision points)."""

    decision_points: dict[str, int] = field(default_factory=dict)
    """Count of each type of decision point (if, for, while, etc.)."""

    @property
    def is_complex(self) -> bool:
        """Whether this function is considered complex (>10)."""
        return self.cyclomatic > COMPLEXITY_THRESHOLD_HIGH

    @property
    def is_moderate(self) -> bool:
        """Whether this function has moderate complexity (5-10)."""
        return COMPLEXITY_THRESHOLD_MODERATE <= self.cyclomatic <= COMPLEXITY_THRESHOLD_HIGH


@dataclass
class SideEffect:
    """Detected side effect in a function."""

    type: SideEffectType
    """Type of side effect."""

    evidence: str
    """Evidence string (import name or call pattern)."""

    line_number: int = 0
    """Line number where detected."""


@dataclass
class FunctionCall:
    """Represents a function call within another function."""

    caller: str
    """Name of the calling function."""

    callee: str
    """Name of the called function."""

    line_number: int
    """Line number of the call."""


@dataclass
class CodeMap:
    """Structured code map extracted from a source file."""

    file_path: str
    """Path to the source file."""

    language: str
    """Programming language."""

    functions: list[FunctionInfo] = field(default_factory=list)
    """All functions in the file."""

    classes: list[ClassInfo] = field(default_factory=list)
    """All classes in the file."""

    imports: list[ImportInfo] = field(default_factory=list)
    """All imports in the file."""

    complexity_map: dict[str, ComplexityMetrics] = field(default_factory=dict)
    """Complexity metrics per function (keyed by function name)."""

    side_effects_map: dict[str, list[SideEffect]] = field(default_factory=dict)
    """Side effects per function (keyed by function name)."""

    call_graph: list[FunctionCall] = field(default_factory=list)
    """All function calls in the file."""

    has_errors: bool = False
    """Whether the file has parse errors."""

    parse_result: Any = None
    """Cached ParseResult for downstream consumers (e.g., IntegrationDepsDetector)."""


@dataclass
class CodeAnalysisTask(TaskInput):
    """Task input for code analysis."""

    task_type: str = "analyze_code"
    """Type of task (defaults to 'analyze_code')."""

    target: str = ""
    """Target for the task (defaults to file_path)."""

    file_path: str = ""
    """Path to the source file to analyze."""

    def __post_init__(self) -> None:
        """Initialize base TaskInput fields if not already set."""
        if not self.target and self.file_path:
            self.target = self.file_path


# ── CodeAnalyzer ─────────────────────────────────────────────────


class CodeAnalyzer(BaseAgent):
    """Agent that performs deep code analysis using tree-sitter.

    Extracts structured code maps, calculates complexity, builds call graphs,
    and detects side effects for prioritization and risk analysis.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        """Initialize the CodeAnalyzer.

        Args:
            project_root: Root directory of the project (optional).
        """
        self._root = project_root

    @property
    def name(self) -> str:
        """Unique name identifying this agent."""
        return "code_analyzer"

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return "Performs deep code analysis: complexity, call graphs, side effects"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute code analysis.

        Args:
            task: A CodeAnalysisTask specifying the file to analyze.

        Returns:
            TaskOutput with CodeMap in result['code_map'].
        """
        if not isinstance(task, CodeAnalysisTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a CodeAnalysisTask instance"],
            )

        try:
            file_path = Path(task.file_path)
            if not file_path.exists():
                return TaskOutput(
                    status=TaskStatus.FAILED,
                    errors=[f"File does not exist: {file_path}"],
                )

            logger.info("Analyzing code in %s", file_path)

            # Step 1: Parse source file (task 1.20.1)
            code_map = self.analyze_file(file_path)

            logger.info(
                "Code analysis complete: %d functions, %d classes, %d imports",
                len(code_map.functions),
                len(code_map.classes),
                len(code_map.imports),
            )

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={"code_map": code_map},
            )

        except Exception as exc:
            logger.exception("Unexpected error during code analysis")
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Unexpected error: {exc}"],
            )

    def analyze_file(self, file_path: Path) -> CodeMap:
        """Analyze a single source file and extract complete code map.

        Args:
            file_path: Path to the source file.

        Returns:
            CodeMap with all extracted information.
        """
        # Detect language
        language = detect_language(file_path)
        if not language:
            return CodeMap(
                file_path=str(file_path),
                language="unknown",
                has_errors=True,
            )

        # Parse with tree-sitter
        try:
            parse_result = extract_from_file(str(file_path))
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", file_path, exc)
            return CodeMap(
                file_path=str(file_path),
                language=language,
                has_errors=True,
            )

        # Build code map
        code_map = CodeMap(
            file_path=str(file_path),
            language=parse_result.language,
            functions=parse_result.functions,
            classes=parse_result.classes,
            imports=parse_result.imports,
            has_errors=parse_result.has_errors,
        )

        # Cache parse_result for downstream consumers
        code_map.parse_result = parse_result

        # Task 1.20.2: Calculate complexity for each function
        for func in parse_result.functions:
            code_map.complexity_map[func.name] = self._calculate_complexity(func)

        # Also analyze class methods
        for cls in parse_result.classes:
            for method in cls.methods:
                full_name = f"{cls.name}.{method.name}"
                code_map.complexity_map[full_name] = self._calculate_complexity(method)
                # Add method to functions list for consistency
                code_map.functions.append(method)

        # Task 1.20.3: Build call graph
        code_map.call_graph = self._build_call_graph(parse_result)

        # Task 1.20.4: Detect side effects
        code_map.side_effects_map = self._detect_side_effects(parse_result)

        return code_map

    def _calculate_complexity(self, func: FunctionInfo) -> ComplexityMetrics:
        """Calculate cyclomatic complexity for a function.

        Args:
            func: Function information from tree-sitter.

        Returns:
            ComplexityMetrics with detailed breakdown.
        """
        # Base complexity is 1
        complexity = 1
        decision_points: dict[str, int] = {}

        body = func.body_text

        # Define patterns for each decision point type
        patterns = {
            "if": [r"\bif\b", r"\belif\b", r"\belse\s+if\b"],
            "else": [r"\belse\b"],
            "for": [r"\bfor\b", r"\bforeach\b"],
            "while": [r"\bwhile\b"],
            "case": [r"\bcase\b", r"\bwhen\b"],
            "catch": [r"\bcatch\b", r"\bexcept\b", r"\brescue\b"],
            "and": [r"\band\b", r"&&"],
            "or": [r"\bor\b", r"\|\|"],
            "ternary": [r"\?[^?]*:", r"\bif\b.*\belse\b"],  # Ternary operators
            "match": [r"\bmatch\b"],  # Rust/modern pattern matching
        }

        # Count each type of decision point
        for decision_type, type_patterns in patterns.items():
            count = 0
            for pattern in type_patterns:
                count += len(re.findall(pattern, body, re.IGNORECASE))
            if count > 0:
                decision_points[decision_type] = count
                # Add to total complexity
                # Note: 'else' doesn't add complexity, other keywords do
                if decision_type != "else":
                    complexity += count

        return ComplexityMetrics(
            cyclomatic=complexity,
            decision_points=decision_points,
        )

    def _build_call_graph(self, parse_result: ParseResult) -> list[FunctionCall]:
        """Build a call graph for all functions in the file.

        Args:
            parse_result: Parsed source code.

        Returns:
            List of FunctionCall entries.
        """
        call_graph: list[FunctionCall] = []

        # Build a set of known function names in this file
        known_functions = {f.name for f in parse_result.functions}
        for cls in parse_result.classes:
            known_functions.update(m.name for m in cls.methods)

        # Analyze each function for calls to known functions
        for func in parse_result.functions:
            calls = self._extract_function_calls(func, known_functions)
            call_graph.extend(calls)

        # Also analyze class methods
        for cls in parse_result.classes:
            for method in cls.methods:
                caller_name = f"{cls.name}.{method.name}"
                calls = self._extract_function_calls(method, known_functions, caller_name)
                call_graph.extend(calls)

        return call_graph

    def _extract_function_calls(
        self,
        func: FunctionInfo,
        known_functions: set[str],
        caller_override: str | None = None,
    ) -> list[FunctionCall]:
        """Extract function calls from a function body.

        Args:
            func: Function to analyze.
            known_functions: Set of function names defined in this file.
            caller_override: Override for caller name (for methods).

        Returns:
            List of FunctionCall entries.
        """
        calls: list[FunctionCall] = []
        body = func.body_text
        caller_name = caller_override or func.name

        # Find function calls using regex
        # Matches: function_name( or function_name (
        call_pattern = r"\b([a-zA-Z_]\w*)\s*\("

        for match in re.finditer(call_pattern, body):
            callee = match.group(1)
            # Only track calls to known functions
            if callee in known_functions and callee != func.name:
                # Estimate line number (rough approximation)
                line_offset = body[: match.start()].count("\n")
                line_number = func.start_line + line_offset

                calls.append(
                    FunctionCall(
                        caller=caller_name,
                        callee=callee,
                        line_number=line_number,
                    )
                )

        return calls

    def _detect_side_effects(self, parse_result: ParseResult) -> dict[str, list[SideEffect]]:
        """Detect side effects in all functions.

        Args:
            parse_result: Parsed source code.

        Returns:
            Dictionary mapping function names to their side effects.
        """
        side_effects_map: dict[str, list[SideEffect]] = {}

        # Build import evidence
        import_evidence = self._build_import_evidence(parse_result.imports)

        # Analyze each function
        for func in parse_result.functions:
            side_effects = self._analyze_function_side_effects(func, import_evidence)
            if side_effects:
                side_effects_map[func.name] = side_effects

        # Also analyze class methods
        for cls in parse_result.classes:
            for method in cls.methods:
                side_effects = self._analyze_function_side_effects(method, import_evidence)
                if side_effects:
                    full_name = f"{cls.name}.{method.name}"
                    side_effects_map[full_name] = side_effects

        return side_effects_map

    def _build_import_evidence(self, imports: list[ImportInfo]) -> dict[SideEffectType, list[str]]:
        """Build evidence map from imports.

        Args:
            imports: List of import statements.

        Returns:
            Dictionary mapping side effect types to matching import modules.
        """
        evidence: dict[SideEffectType, list[str]] = {t: [] for t in SideEffectType}

        # Check each import against patterns
        for imp in imports:
            module_text = imp.module.lower()
            for names in imp.names:
                module_text += f" {names.lower()}"

            # Check against each side effect type
            for effect_type, patterns in SIDE_EFFECT_PATTERNS.items():
                for pattern in patterns:
                    if re.search(pattern, module_text, re.IGNORECASE):
                        evidence[effect_type].append(imp.module)
                        break

        return evidence

    def _analyze_function_side_effects(
        self,
        func: FunctionInfo,
        import_evidence: dict[SideEffectType, list[str]],
    ) -> list[SideEffect]:
        """Analyze a single function for side effects.

        Args:
            func: Function to analyze.
            import_evidence: Evidence from imports.

        Returns:
            List of detected side effects.
        """
        side_effects: list[SideEffect] = []
        body = func.body_text.lower()

        # Check import-based evidence
        for effect_type, modules in import_evidence.items():
            if modules:
                # Check if this function uses any of the imported modules
                for module in modules:
                    if module.lower() in body:
                        side_effects.append(
                            SideEffect(
                                type=effect_type,
                                evidence=f"import: {module}",
                                line_number=func.start_line,
                            )
                        )
                        break  # Only add once per type

        # Check call patterns in function body
        for effect_type, patterns in CALL_PATTERNS.items():
            for pattern in patterns:
                matches = list(re.finditer(pattern, body, re.IGNORECASE))
                if matches:
                    # Estimate line number of first match
                    first_match = matches[0]
                    line_offset = body[: first_match.start()].count("\n")
                    line_number = func.start_line + line_offset

                    side_effects.append(
                        SideEffect(
                            type=effect_type,
                            evidence=f"call: {first_match.group(0)}",
                            line_number=line_number,
                        )
                    )
                    break  # Only add once per type

        return side_effects
