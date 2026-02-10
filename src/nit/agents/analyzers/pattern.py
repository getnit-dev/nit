"""PatternAnalyzer agent — extracts test conventions from existing test files.

This agent:
1. Scans existing test files in a project
2. Extracts naming conventions (describe/it vs test_function vs class-based)
3. Extracts assertion styles (expect/assert/should)
4. Extracts mocking patterns (vi.mock/unittest.mock/pytest.fixture)
5. Extracts import conventions
6. Stores extracted conventions in memory as a "convention profile"
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.llm.context import DetectedTestPattern
from nit.memory.global_memory import GlobalMemory
from nit.parsing.languages import extract_from_source
from nit.parsing.treesitter import detect_language

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

# Test file patterns by language
_TEST_FILE_PATTERNS: dict[str, list[str]] = {
    "python": ["test_*.py", "*_test.py"],
    "javascript": ["*.test.js", "*.spec.js"],
    "typescript": ["*.test.ts", "*.spec.ts", "*.test.tsx", "*.spec.tsx"],
    "tsx": ["*.test.tsx", "*.spec.tsx"],
    "java": ["*Test.java", "*Tests.java"],
    "go": ["*_test.go"],
    "c": ["*_test.c", "test_*.c"],
    "cpp": ["*_test.cpp", "test_*.cpp", "*_test.cc", "test_*.cc"],
}

# Naming pattern detection regexes
_NAMING_PATTERNS = {
    "function": re.compile(r"^\s*(?:async\s+)?(?:def|function)\s+test_\w+", re.MULTILINE),
    "class": re.compile(r"^\s*class\s+Test\w+|^\s*class\s+\w+Test", re.MULTILINE | re.IGNORECASE),
    "describe": re.compile(r"\bdescribe\s*\(", re.MULTILINE),
}

# Assertion style detection patterns
_ASSERTION_PATTERNS = {
    "assert": re.compile(r"\bassert\s+", re.MULTILINE),
    "expect": re.compile(r"\bexpect\s*\(", re.MULTILINE),
    "should": re.compile(r"\.should\b", re.MULTILINE),
}

# Mocking pattern detection
_MOCKING_PATTERNS = {
    "pytest.fixture": re.compile(r"@pytest\.fixture\b", re.MULTILINE),
    "unittest.mock": re.compile(r"\bunittest\.mock\b|\bfrom unittest import mock\b", re.MULTILINE),
    "mock.patch": re.compile(r"@mock\.patch\b|@patch\b", re.MULTILINE),
    "vi.mock": re.compile(r"\bvi\.mock\s*\(", re.MULTILINE),
    "jest.mock": re.compile(r"\bjest\.mock\s*\(", re.MULTILINE),
    "vitest.mock": re.compile(r"\bvitest\.mock\s*\(", re.MULTILINE),
}

# Import pattern extraction
_IMPORT_PATTERNS = {
    "python": re.compile(
        r"^(?:from\s+[\w.]+\s+import\s+[\w,\s*()]+|import\s+[\w.,\s]+)", re.MULTILINE
    ),
    "javascript": re.compile(
        r"^import\s+(?:[\w{},\s*]+\s+from\s+)?['\"][\w./@-]+['\"]", re.MULTILINE
    ),
    "typescript": re.compile(
        r"^import\s+(?:[\w{},\s*]+\s+from\s+)?['\"][\w./@-]+['\"]", re.MULTILINE
    ),
}


# ── Data models ──────────────────────────────────────────────────


@dataclass
class PatternAnalysisTask(TaskInput):
    """Task input for analyzing test patterns in a project."""

    task_type: str = "analyze_patterns"
    """Type of task (defaults to 'analyze_patterns')."""

    target: str = ""
    """Target for the task (defaults to project_root)."""

    project_root: str = ""
    """Root directory of the project to analyze."""

    language: str = ""
    """Optional: limit analysis to a specific language."""

    max_files: int = 50
    """Maximum number of test files to analyze."""

    def __post_init__(self) -> None:
        """Initialize base TaskInput fields if not already set."""
        if not self.target and self.project_root:
            self.target = self.project_root


@dataclass
class _PatternStats:
    """Internal helper for collecting pattern statistics."""

    naming_counter: Counter[str] = field(default_factory=Counter)
    assertion_counter: Counter[str] = field(default_factory=Counter)
    mocking_counter: Counter[str] = field(default_factory=Counter)
    import_counter: Counter[str] = field(default_factory=Counter)
    sample_tests: list[str] = field(default_factory=list)


@dataclass
class ConventionProfile:
    """Extracted conventions from existing test files.

    This is an enhanced version of TestPattern with aggregated
    statistics from multiple test files.
    """

    language: str
    """Programming language of the analyzed tests."""

    naming_style: str = "unknown"
    """Primary naming convention (function/class/describe)."""

    naming_counts: dict[str, int] = field(default_factory=dict)
    """Counts of each naming style seen."""

    assertion_style: str = "unknown"
    """Primary assertion style (assert/expect/should)."""

    assertion_counts: dict[str, int] = field(default_factory=dict)
    """Counts of each assertion style seen."""

    mocking_patterns: list[str] = field(default_factory=list)
    """All detected mocking approaches."""

    mocking_counts: dict[str, int] = field(default_factory=dict)
    """Counts of each mocking pattern seen."""

    common_imports: list[str] = field(default_factory=list)
    """Most common test imports (top 10)."""

    sample_tests: list[str] = field(default_factory=list)
    """Sample test function bodies (up to 3)."""

    files_analyzed: int = 0
    """Number of test files analyzed."""

    def to_test_pattern(self) -> DetectedTestPattern:
        """Convert to a DetectedTestPattern for use in ContextAssembler."""
        return DetectedTestPattern(
            naming_style=self.naming_style,
            assertion_style=self.assertion_style,
            mocking_patterns=self.mocking_patterns,
            imports=self.common_imports[:5],  # Top 5 imports
            sample_test=self.sample_tests[0] if self.sample_tests else "",
        )


# ── PatternAnalyzer ──────────────────────────────────────────────


class PatternAnalyzer(BaseAgent):
    """Agent that analyzes existing test files to extract conventions.

    Scans test files in the project, uses tree-sitter and regex patterns
    to detect naming conventions, assertion styles, mocking patterns, and
    import conventions. Aggregates results into a ConventionProfile.
    """

    def __init__(
        self, *, max_files: int = 50, sample_size: int = 3, enable_memory: bool = True
    ) -> None:
        """Initialize the PatternAnalyzer.

        Args:
            max_files: Maximum number of test files to analyze.
            sample_size: Number of sample test bodies to extract.
            enable_memory: Whether to save results to GlobalMemory.
        """
        self._max_files = max_files
        self._sample_size = sample_size
        self._enable_memory = enable_memory

    @property
    def name(self) -> str:
        """Unique name identifying this agent."""
        return "pattern_analyzer"

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return "Analyzes existing test files to extract naming, assertion, and mocking conventions"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute pattern analysis on the project's test files.

        Args:
            task: A PatternAnalysisTask specifying the project root.

        Returns:
            TaskOutput with ConventionProfile in result['profile'].
        """
        if not isinstance(task, PatternAnalysisTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a PatternAnalysisTask instance"],
            )

        try:
            project_root = Path(task.project_root)
            if not project_root.exists():
                return TaskOutput(
                    status=TaskStatus.FAILED,
                    errors=[f"Project root does not exist: {project_root}"],
                )

            logger.info("Analyzing test patterns in %s", project_root)

            # Find test files
            test_files = self._find_test_files(project_root, task.language, task.max_files)
            if not test_files:
                logger.warning("No test files found in %s", project_root)
                return TaskOutput(
                    status=TaskStatus.COMPLETED,
                    result={
                        "profile": ConventionProfile(
                            language=task.language or "unknown",
                            files_analyzed=0,
                        ),
                    },
                )

            logger.info("Found %d test files to analyze", len(test_files))

            # Analyze each test file
            stats = _PatternStats()

            for test_file in test_files:
                try:
                    self._analyze_file(test_file, stats)
                except Exception as exc:
                    logger.warning("Failed to analyze %s: %s", test_file, exc)

            # Build the convention profile
            language = (
                task.language
                or (detect_language(test_files[0]) if test_files else None)
                or "unknown"
            )
            profile = self._build_profile(
                language=language,
                stats=stats,
                files_analyzed=len(test_files),
            )

            logger.info(
                "Pattern analysis complete: naming=%s, assertion=%s, %d files",
                profile.naming_style,
                profile.assertion_style,
                profile.files_analyzed,
            )

            # Seed memory with extracted conventions (task 1.15.4)
            if self._enable_memory:
                self._seed_memory(project_root, profile)

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "profile": profile,
                },
            )

        except Exception as exc:
            logger.exception("Unexpected error during pattern analysis")
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Unexpected error: {exc}"],
            )

    def _find_test_files(self, root: Path, language: str, max_files: int) -> list[Path]:
        """Find test files in the project directory.

        Args:
            root: Project root directory.
            language: Optional language filter.
            max_files: Maximum number of files to return.

        Returns:
            List of test file paths.
        """
        test_files = []

        # Determine which patterns to use
        if language and language in _TEST_FILE_PATTERNS:
            patterns = _TEST_FILE_PATTERNS[language]
        else:
            # Use all patterns
            patterns = [
                pattern
                for lang_patterns in _TEST_FILE_PATTERNS.values()
                for pattern in lang_patterns
            ]

        # Search for test files
        for pattern in patterns:
            matches = list(root.rglob(pattern))
            test_files.extend(matches)

            if len(test_files) >= max_files:
                break

        # Deduplicate and limit
        return list(dict.fromkeys(test_files))[:max_files]

    def _analyze_file(self, file_path: Path, stats: _PatternStats) -> None:
        """Analyze a single test file and update statistics.

        Args:
            file_path: Path to the test file.
            stats: Pattern statistics to update.
        """
        content = file_path.read_text(encoding="utf-8", errors="ignore")

        # Detect naming conventions
        for style, pattern in _NAMING_PATTERNS.items():
            matches = pattern.findall(content)
            if matches:
                stats.naming_counter[style] += len(matches)

        # Detect assertion styles
        for style, pattern in _ASSERTION_PATTERNS.items():
            matches = pattern.findall(content)
            if matches:
                stats.assertion_counter[style] += len(matches)

        # Detect mocking patterns
        for pattern_name, pattern in _MOCKING_PATTERNS.items():
            if pattern.search(content):
                stats.mocking_counter[pattern_name] += 1

        # Extract imports
        lang = detect_language(file_path)
        if lang in _IMPORT_PATTERNS:
            import_pattern = _IMPORT_PATTERNS[lang]
            imports = import_pattern.findall(content)
            for imp in imports:
                stats.import_counter[imp.strip()] += 1

        # Extract sample test function (if we need more samples)
        if len(stats.sample_tests) < self._sample_size and lang:
            sample = self._extract_sample_test(content, lang)
            if sample:
                stats.sample_tests.append(sample)

    def _extract_sample_test(self, content: str, language: str) -> str:
        """Extract a representative test function body from content.

        Args:
            content: Test file content.
            language: Programming language.

        Returns:
            Sample test function body (or empty string if none found).
        """
        # Try to parse with tree-sitter to get a clean function body
        try:
            parse_result = extract_from_source(content.encode("utf-8"), language)
            if parse_result.functions:
                # Get the first test function
                func = parse_result.functions[0]
                # Extract just the function definition
                lines = content.splitlines()
                if func.start_line < len(lines) and func.end_line <= len(lines):
                    func_lines = lines[func.start_line : func.end_line]
                    return "\n".join(func_lines)
        except Exception as exc:
            logger.debug("Failed to extract sample with tree-sitter: %s", exc)

        # Fallback: use regex to extract a simple test function
        # Python: def test_xxx(): ...
        if language == "python":
            match = re.search(
                r"(def test_\w+\([^)]*\):(?:\n(?:    |\t).+)+)",
                content,
                re.MULTILINE,
            )
            if match:
                return match.group(1)

        # JS/TS: test('...', () => { ... })
        if language in ("javascript", "typescript", "tsx"):
            match = re.search(
                r"((?:test|it)\s*\(['\"][\w\s]+['\"]\s*,\s*(?:async\s+)?\([^)]*\)\s*=>\s*\{[^}]+\})",
                content,
                re.MULTILINE | re.DOTALL,
            )
            if match:
                return match.group(1)[:200]  # Limit to 200 chars

        return ""

    def _build_profile(
        self, language: str, stats: _PatternStats, files_analyzed: int
    ) -> ConventionProfile:
        """Build a ConventionProfile from collected statistics.

        Args:
            language: Programming language.
            stats: Pattern statistics collected from test files.
            files_analyzed: Number of files analyzed.

        Returns:
            ConventionProfile with aggregated results.
        """
        # Determine primary naming style
        naming_style = (
            stats.naming_counter.most_common(1)[0][0] if stats.naming_counter else "unknown"
        )

        # Determine primary assertion style
        assertion_style = (
            stats.assertion_counter.most_common(1)[0][0] if stats.assertion_counter else "unknown"
        )

        # Get all detected mocking patterns
        mocking_patterns = list(stats.mocking_counter.keys())

        # Get top 10 most common imports
        common_imports = [imp for imp, _ in stats.import_counter.most_common(10)]

        return ConventionProfile(
            language=language,
            naming_style=naming_style,
            naming_counts=dict(stats.naming_counter),
            assertion_style=assertion_style,
            assertion_counts=dict(stats.assertion_counter),
            mocking_patterns=mocking_patterns,
            mocking_counts=dict(stats.mocking_counter),
            common_imports=common_imports,
            sample_tests=stats.sample_tests,
            files_analyzed=files_analyzed,
        )

    def _seed_memory(self, project_root: Path, profile: ConventionProfile) -> None:
        """Seed GlobalMemory with extracted conventions.

        This implements task 1.15.4: on first run, PatternAnalyzer
        populates memory from existing tests.

        Args:
            project_root: Root directory of the project.
            profile: The extracted convention profile.
        """
        try:
            memory = GlobalMemory(project_root)

            # Store conventions in memory
            conventions = {
                "language": profile.language,
                "naming_style": profile.naming_style,
                "naming_counts": profile.naming_counts,
                "assertion_style": profile.assertion_style,
                "assertion_counts": profile.assertion_counts,
                "mocking_patterns": profile.mocking_patterns,
                "mocking_counts": profile.mocking_counts,
                "common_imports": profile.common_imports,
                "sample_tests": profile.sample_tests,
                "files_analyzed": profile.files_analyzed,
            }
            memory.set_conventions(conventions)

            # Add successful patterns to known_patterns
            for style, count in profile.naming_counts.items():
                if count > 0:
                    memory.add_known_pattern(
                        f"naming_style:{style}",
                        context={"count": count, "language": profile.language},
                    )

            for style, count in profile.assertion_counts.items():
                if count > 0:
                    memory.add_known_pattern(
                        f"assertion_style:{style}",
                        context={"count": count, "language": profile.language},
                    )

            for pattern, count in profile.mocking_counts.items():
                if count > 0:
                    memory.add_known_pattern(
                        f"mocking_pattern:{pattern}",
                        context={"count": count, "language": profile.language},
                    )

            logger.info(
                "Seeded GlobalMemory with conventions from %d test files", profile.files_analyzed
            )

        except Exception as exc:
            logger.warning("Failed to seed memory: %s", exc)
