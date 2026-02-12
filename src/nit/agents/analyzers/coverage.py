"""CoverageAnalyzer agent — analyzes coverage data and identifies test gaps.

This agent (task 1.19):
1. Runs coverage tool via adapters → parses report → maps coverage to source files
2. Identifies untested files (zero coverage)
3. Identifies undertested functions (public functions with no test coverage)
4. Identifies dead zones (high cyclomatic complexity + no coverage)
5. Identifies stale tests (tests referencing code that no longer exists)
6. Generates gap report: prioritized list of files/functions needing tests
7. Creates BuildTask entries for each gap
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from nit.adapters.coverage import (
    CoveragePyAdapter,
    GcovAdapter,
    GoCoverAdapter,
    IstanbulAdapter,
    JaCoCoAdapter,
)
from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.agents.builders.unit import BuildTask
from nit.parsing.languages import extract_from_file
from nit.parsing.treesitter import detect_language

if TYPE_CHECKING:
    from nit.adapters.coverage.base import (
        CoverageAdapter,
        CoverageReport,
        FileCoverage,
        FunctionCoverage,
    )
    from nit.parsing.treesitter import FunctionInfo

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────


class GapPriority(Enum):
    """Priority level for test gaps (used in gap report sorting)."""

    CRITICAL = "critical"  # High complexity, zero coverage, or critical domain
    HIGH = "high"  # Public API, recent changes, moderate complexity
    MEDIUM = "medium"  # Regular code with no coverage
    LOW = "low"  # Simple code, low risk


# Cyclomatic complexity thresholds
COMPLEXITY_HIGH = 10  # High complexity threshold
COMPLEXITY_MODERATE = 5  # Moderate complexity threshold

# Coverage thresholds
UNDERTESTED_THRESHOLD = 50.0  # Functions below this coverage % are undertested
COVERAGE_LOW = 25.0  # Low coverage threshold for high priority
COVERAGE_MODERATE = 50.0  # Moderate coverage threshold for public APIs


# ── Data models ──────────────────────────────────────────────────


@dataclass
class CoverageAnalysisTask(TaskInput):
    """Task input for coverage analysis."""

    task_type: str = "analyze_coverage"
    """Type of task (defaults to 'analyze_coverage')."""

    target: str = ""
    """Target for the task (defaults to project_root)."""

    project_root: str = ""
    """Root directory of the project to analyze."""

    coverage_threshold: float = 80.0
    """Target coverage percentage (default: 80%)."""

    def __post_init__(self) -> None:
        """Initialize base TaskInput fields if not already set."""
        if not self.target and self.project_root:
            self.target = self.project_root


@dataclass
class FunctionGap:
    """Represents a function that needs test coverage."""

    file_path: str
    """Path to the source file containing this function."""

    function_name: str
    """Name of the function."""

    line_number: int
    """Starting line number of the function."""

    end_line: int
    """Ending line number of the function."""

    coverage_percentage: float
    """Current coverage percentage for this function (0.0-100.0)."""

    complexity: int
    """Cyclomatic complexity estimate."""

    is_public: bool
    """Whether this is a public function/method."""

    priority: GapPriority
    """Priority level for generating tests."""


@dataclass
class StaleTest:
    """Represents a test file that references non-existent code."""

    test_file: str
    """Path to the stale test file."""

    missing_imports: list[str]
    """Import statements that don't resolve to existing code."""

    reason: str
    """Human-readable explanation of why this test is stale."""


@dataclass
class CoverageGapReport:
    """Complete gap analysis report."""

    untested_files: list[str] = field(default_factory=list)
    """Files with 0% coverage."""

    function_gaps: list[FunctionGap] = field(default_factory=list)
    """Functions needing test coverage, sorted by priority."""

    stale_tests: list[StaleTest] = field(default_factory=list)
    """Tests referencing code that no longer exists."""

    overall_coverage: float = 0.0
    """Overall project coverage percentage."""

    target_coverage: float = 80.0
    """Target coverage percentage."""

    def get_prioritized_gaps(self) -> list[FunctionGap]:
        """Return function gaps sorted by priority (critical first)."""
        priority_order = {
            GapPriority.CRITICAL: 0,
            GapPriority.HIGH: 1,
            GapPriority.MEDIUM: 2,
            GapPriority.LOW: 3,
        }
        return sorted(self.function_gaps, key=lambda g: priority_order[g.priority])


# ── CoverageAnalyzer ─────────────────────────────────────────────


class CoverageAnalyzer(BaseAgent):
    """Agent that analyzes coverage data and identifies test gaps.

    Uses coverage adapters to run coverage tools, parses reports,
    analyzes source code with tree-sitter to identify untested functions,
    calculates cyclomatic complexity, and generates prioritized BuildTasks.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        complexity_threshold: int = COMPLEXITY_HIGH,
        undertested_threshold: float = UNDERTESTED_THRESHOLD,
    ) -> None:
        """Initialize the CoverageAnalyzer.

        Args:
            project_root: Root directory of the project.
            complexity_threshold: Complexity above which functions are high-priority.
            undertested_threshold: Coverage % below which functions are undertested.
        """
        self._root = project_root
        self._complexity_threshold = complexity_threshold
        self._undertested_threshold = undertested_threshold
        # Initialize available coverage adapters
        self._coverage_adapters: list[CoverageAdapter] = [
            CoveragePyAdapter(),
            IstanbulAdapter(),
            GcovAdapter(),
            GoCoverAdapter(),
            JaCoCoAdapter(),
        ]

    @property
    def name(self) -> str:
        """Unique name identifying this agent."""
        return "coverage_analyzer"

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return "Analyzes coverage data and identifies test gaps with prioritization"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute coverage analysis.

        Args:
            task: A CoverageAnalysisTask specifying the project root.

        Returns:
            TaskOutput with CoverageGapReport in result['gap_report'] and
            list of BuildTask in result['build_tasks'].
        """
        if not isinstance(task, CoverageAnalysisTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a CoverageAnalysisTask instance"],
            )

        try:
            project_root = Path(task.project_root)
            if not project_root.exists():
                return TaskOutput(
                    status=TaskStatus.FAILED,
                    errors=[f"Project root does not exist: {project_root}"],
                )

            logger.info("Running coverage analysis on %s", project_root)

            # Step 1: Run coverage tool and get report (task 1.19.1)
            coverage_report = await self._run_coverage(project_root)
            if coverage_report is None:
                return TaskOutput(
                    status=TaskStatus.FAILED,
                    errors=["No coverage adapter found or coverage collection failed"],
                )

            logger.info("Coverage collected: %.1f%% overall", coverage_report.overall_line_coverage)

            # Step 2: Identify gaps (tasks 1.19.2, 1.19.3)
            gap_report = self._analyze_gaps(coverage_report, task.coverage_threshold)

            logger.info(
                "Gap analysis complete: %d untested files, %d function gaps, %d stale tests",
                len(gap_report.untested_files),
                len(gap_report.function_gaps),
                len(gap_report.stale_tests),
            )

            # Step 3: Generate BuildTasks (task 1.19.5)
            build_tasks = self._create_build_tasks(gap_report)

            logger.info("Created %d build tasks", len(build_tasks))

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "gap_report": gap_report,
                    "build_tasks": build_tasks,
                    "coverage_report": coverage_report,
                },
            )

        except Exception as exc:
            logger.exception("Unexpected error during coverage analysis")
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Unexpected error: {exc}"],
            )

    async def _run_coverage(self, project_root: Path) -> CoverageReport | None:
        """Run coverage tool and return unified report.

        Args:
            project_root: Root directory of the project.

        Returns:
            CoverageReport or None if no adapter found.
        """
        # Try to find a coverage adapter that can run in this project
        for adapter in self._coverage_adapters:
            if adapter.detect(project_root):
                logger.info("Using coverage adapter: %s", adapter.name)
                try:
                    return await adapter.run_coverage(project_root)
                except Exception as exc:
                    logger.warning("Coverage adapter %s failed: %s", adapter.name, exc)

        logger.warning("No coverage adapter could run for %s", project_root)
        return None

    def _analyze_gaps(
        self, coverage_report: CoverageReport, target_coverage: float
    ) -> CoverageGapReport:
        """Analyze coverage report and identify all gaps.

        Args:
            coverage_report: Unified coverage report from adapter.
            target_coverage: Target coverage percentage.

        Returns:
            CoverageGapReport with all identified gaps.
        """
        # Directories to exclude from analysis
        exclude_dirs = {
            "node_modules",
            ".venv",
            "venv",
            ".git",
            "build",
            "dist",
            "__pycache__",
            ".pytest_cache",
            "coverage",
            ".coverage",
            "site-packages",
        }

        gap_report = CoverageGapReport(
            overall_coverage=coverage_report.overall_line_coverage,
            target_coverage=target_coverage,
        )

        # Task 1.19.2: Identify untested files (0% coverage)
        all_untested = coverage_report.get_uncovered_files()
        gap_report.untested_files = [
            f for f in all_untested if not any(excluded in f for excluded in exclude_dirs)
        ]

        # Task 1.19.2: Identify undertested functions
        for file_path, file_coverage in coverage_report.files.items():
            # Skip files in excluded directories
            if any(excluded in file_path for excluded in exclude_dirs):
                continue

            function_gaps = self._analyze_file_gaps(file_path, file_coverage)
            gap_report.function_gaps.extend(function_gaps)

        # Task 1.19.3: Identify stale tests
        gap_report.stale_tests = self._identify_stale_tests(coverage_report)

        return gap_report

    def _analyze_file_gaps(self, file_path: str, file_coverage: FileCoverage) -> list[FunctionGap]:
        """Analyze a single file for function-level coverage gaps.

        Args:
            file_path: Path to the source file.
            file_coverage: Coverage data for this file.

        Returns:
            List of FunctionGap for functions needing tests.
        """
        gaps: list[FunctionGap] = []

        # Parse the source file to get all functions
        full_path = self._root / file_path
        if not full_path.exists():
            return gaps

        try:
            language = detect_language(full_path)
            if not language:
                return gaps

            parse_result = extract_from_file(str(full_path))

            # Build a map of coverage by function
            coverage_map = {func.name: func for func in file_coverage.functions if func.name}

            # Analyze each function
            for func_info in parse_result.functions:
                gap = self._analyze_function(file_path, func_info, coverage_map.get(func_info.name))
                if gap:
                    gaps.append(gap)

        except Exception as exc:
            logger.debug("Failed to analyze file %s: %s", file_path, exc)

        return gaps

    def _analyze_function(
        self,
        file_path: str,
        func_info: FunctionInfo,
        coverage_data: FunctionCoverage | None,
    ) -> FunctionGap | None:
        """Analyze a single function for coverage gaps.

        Args:
            file_path: Path to the source file.
            func_info: Function information from tree-sitter.
            coverage_data: Coverage data for this function (or None if uncovered).

        Returns:
            FunctionGap if the function needs testing, else None.
        """
        # Calculate coverage percentage
        coverage_pct = 100.0 if coverage_data and coverage_data.is_covered else 0.0

        # Skip if function is well-tested
        if coverage_pct >= self._undertested_threshold:
            return None

        # Calculate cyclomatic complexity
        complexity = self._estimate_complexity(func_info)

        # Determine if this is a public function
        is_public = self._is_public_function(func_info)

        # Skip private functions with low complexity and some coverage
        if not is_public and complexity < COMPLEXITY_MODERATE and coverage_pct > 0:
            return None

        # Determine priority (task 1.19.4)
        priority = self._calculate_priority(complexity, coverage_pct, is_public=is_public)

        return FunctionGap(
            file_path=file_path,
            function_name=func_info.name,
            line_number=func_info.start_line,
            end_line=func_info.end_line,
            coverage_percentage=coverage_pct,
            complexity=complexity,
            is_public=is_public,
            priority=priority,
        )

    def _estimate_complexity(self, func_info: FunctionInfo) -> int:
        """Estimate cyclomatic complexity of a function.

        Args:
            func_info: Function information from tree-sitter.

        Returns:
            Estimated cyclomatic complexity (1 = simple, 10+ = complex).
        """
        # Base complexity is 1
        complexity = 1

        # Count decision points in the function body
        body = func_info.body_text.lower()

        # Decision keywords that add complexity
        decision_keywords = [
            r"\bif\b",
            r"\belse\b",
            r"\belif\b",
            r"\bfor\b",
            r"\bwhile\b",
            r"\bcase\b",
            r"\bcatch\b",
            r"\bexcept\b",
            r"\band\b",
            r"\bor\b",
            r"\?\s*:",  # Ternary operator
        ]

        for pattern in decision_keywords:
            complexity += len(re.findall(pattern, body))

        return complexity

    def _is_public_function(self, func_info: FunctionInfo) -> bool:
        """Determine if a function is public (part of the API).

        Args:
            func_info: Function information from tree-sitter.

        Returns:
            True if the function is public, False if private/internal.
        """
        # Python: functions starting with single _ are private (but __ dunder methods are public)
        if func_info.name.startswith("_") and not func_info.name.startswith("__"):
            return False

        # JavaScript/TypeScript: functions starting with _ are conventionally private
        # (but Python dunder methods like __init__ are already excluded above)
        if func_info.name.startswith("_") and not func_info.name.startswith("__"):
            return False

        # Check for private decorators (e.g., @private in Python)
        # Return True if no private decorator found
        return not any("private" in dec.lower() for dec in func_info.decorators)

    def _calculate_priority(
        self, complexity: int, coverage_pct: float, *, is_public: bool
    ) -> GapPriority:
        """Calculate priority for test generation.

        Args:
            complexity: Cyclomatic complexity.
            coverage_pct: Current coverage percentage.
            is_public: Whether this is a public function.

        Returns:
            Priority level for this gap.
        """
        # Critical: high complexity + zero coverage
        if complexity >= self._complexity_threshold and coverage_pct == 0.0:
            return GapPriority.CRITICAL

        # Critical: public API with zero coverage
        if is_public and coverage_pct == 0.0:
            return GapPriority.CRITICAL

        # High: moderate complexity + low coverage
        if complexity >= COMPLEXITY_MODERATE and coverage_pct < COVERAGE_LOW:
            return GapPriority.HIGH

        # High: public API with low coverage
        if is_public and coverage_pct < COVERAGE_MODERATE:
            return GapPriority.HIGH

        # Medium: some coverage but below threshold
        if coverage_pct > 0.0:
            return GapPriority.MEDIUM

        # Low: everything else
        return GapPriority.LOW

    def _identify_stale_tests(self, coverage_report: CoverageReport) -> list[StaleTest]:
        """Identify test files that reference non-existent code.

        Args:
            coverage_report: Coverage report with all source files.

        Returns:
            List of StaleTest entries.
        """
        stale_tests: list[StaleTest] = []

        # Directories to exclude from scanning
        exclude_dirs = {
            "node_modules",
            ".venv",
            "venv",
            ".git",
            "build",
            "dist",
            "__pycache__",
            ".pytest_cache",
            "coverage",
            ".coverage",
        }

        # Find all test files in the project
        test_patterns = ["**/test_*.py", "**/*_test.py", "**/*.test.ts", "**/*.spec.ts"]
        test_files: list[Path] = []

        for pattern in test_patterns:
            for file in self._root.glob(pattern):
                # Skip files in excluded directories
                if any(excluded in file.parts for excluded in exclude_dirs):
                    continue
                test_files.append(file)

        # Check each test file for imports that don't resolve
        for test_file in test_files:
            missing_imports = self._check_test_imports(test_file, coverage_report)
            if missing_imports:
                stale = StaleTest(
                    test_file=str(test_file.relative_to(self._root)),
                    missing_imports=missing_imports,
                    reason=f"Test imports {len(missing_imports)} module(s) that no longer exist",
                )
                stale_tests.append(stale)

        return stale_tests

    def _check_test_imports(self, test_file: Path, coverage_report: CoverageReport) -> list[str]:
        """Check if a test file imports non-existent modules.

        Args:
            test_file: Path to the test file.
            coverage_report: Coverage report with all source files.

        Returns:
            List of import statements that don't resolve.
        """
        missing: list[str] = []

        try:
            content = test_file.read_text(encoding="utf-8", errors="ignore")

            # Extract import statements (simple regex approach)
            import_patterns = [
                r"^from\s+([\w.]+)\s+import",  # Python: from X import
                r"^import\s+([\w.]+)",  # Python: import X
                r"^import\s+.*from\s+['\"]([^'\"]+)['\"]",  # JS/TS: import from
            ]

            for pattern in import_patterns:
                for match in re.finditer(pattern, content, re.MULTILINE):
                    module = match.group(1)
                    if self._is_project_module(module) and not self._module_exists(
                        module, coverage_report
                    ):
                        missing.append(module)

        except Exception as exc:
            logger.debug("Failed to check imports in %s: %s", test_file, exc)

        return missing

    def _is_project_module(self, module: str) -> bool:
        """Check if a module appears to be project-local (not stdlib/third-party).

        A module is considered project-local when its top-level package exists
        as a directory or ``.py`` file under the project root (or ``src/``).
        Standard-library modules are always excluded.

        Args:
            module: Dotted module name (e.g., ``nit.cli``, ``pathlib``).

        Returns:
            True if the module likely belongs to this project.
        """
        top_level = module.split(".", maxsplit=1)[0]

        # Standard library is never project-local
        if top_level in sys.stdlib_module_names:
            return False

        # Check if a matching package dir or single-file module lives in the project
        for base in (self._root, self._root / "src"):
            if (base / top_level).is_dir() or (base / f"{top_level}.py").is_file():
                return True

        return False

    def _module_exists(self, module: str, coverage_report: CoverageReport) -> bool:
        """Check if a module exists in the current source code.

        Args:
            module: Module name (e.g., 'myapp.utils.helpers').
            coverage_report: Coverage report with all source files.

        Returns:
            True if the module exists, False otherwise.
        """
        # Convert module name to potential file paths
        # e.g., myapp.utils.helpers -> myapp/utils/helpers.py
        module_path = module.replace(".", "/")
        potential_paths = [
            f"{module_path}.py",
            f"{module_path}.ts",
            f"{module_path}.js",
            f"{module_path}/__init__.py",
            f"{module_path}/index.ts",
            f"{module_path}/index.js",
        ]

        # Check if any of these paths exist in the coverage report
        for file_path in coverage_report.files:
            if any(file_path.endswith(p) for p in potential_paths):
                return True

        return False

    def _create_build_tasks(self, gap_report: CoverageGapReport) -> list[BuildTask]:
        """Create BuildTask entries for each identified gap.

        Args:
            gap_report: Gap analysis report.

        Returns:
            List of BuildTask ready for UnitBuilder to pick up.
        """
        tasks: list[BuildTask] = []

        # Create tasks for untested files (highest priority)
        for file_path in gap_report.untested_files:
            task = BuildTask(
                task_type="build_unit_test",
                source_file=file_path,
                target=file_path,
                context={"priority": "critical", "reason": "untested_file"},
            )
            tasks.append(task)

        # Create tasks for function gaps (sorted by priority)
        for gap in gap_report.get_prioritized_gaps():
            # Skip if we already have a task for the entire file
            if gap.file_path in gap_report.untested_files:
                continue

            task = BuildTask(
                task_type="build_unit_test",
                source_file=gap.file_path,
                target=gap.file_path,
                context={
                    "priority": gap.priority.value,
                    "reason": "function_gap",
                    "function_name": gap.function_name,
                    "complexity": gap.complexity,
                    "coverage": gap.coverage_percentage,
                },
            )
            tasks.append(task)

        return tasks
