"""DiffAnalyzer agent — analyzes git diffs to identify changed files for PR mode.

This agent (task 2.2):
1. Uses git diff to identify changed files only
2. Maps changed source files to their corresponding test files (and vice versa)
3. Generates delta-focused work list: only analyze/generate for changed code
4. Supports PR mode for CI/CD integration
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

# Git diff parsing constants
MIN_DIFF_PARTS = 2
NUMSTAT_PARTS = 3
RENAMED_PARTS = 3

# Display limits for CLI output
MAX_FILES_DISPLAY = 20
MAX_MAPPINGS_DISPLAY = 15


class ChangeType(Enum):
    """Type of change detected in git diff."""

    ADDED = "added"  # New file
    MODIFIED = "modified"  # Modified file
    DELETED = "deleted"  # Deleted file
    RENAMED = "renamed"  # Renamed file


# Test file patterns for different languages
TEST_FILE_PATTERNS = {
    # Python
    "python": [
        (r"^src/([^/]+)\.py$", r"tests/test_\1.py"),  # src/foo.py -> tests/test_foo.py
        (r"^([^/]+)\.py$", r"test_\1.py"),  # foo.py -> test_foo.py
        (r"^src/(.+)\.py$", r"tests/\1_test.py"),  # src/bar/foo.py -> tests/bar/foo_test.py
    ],
    # JavaScript/TypeScript
    "javascript": [
        (r"^(.+)\.(ts|js|tsx|jsx)$", r"\1.test.\2"),  # foo.ts -> foo.test.ts
        (r"^(.+)\.(ts|js|tsx|jsx)$", r"\1.spec.\2"),  # foo.ts -> foo.spec.ts
        (r"^src/(.+)\.(ts|js|tsx|jsx)$", r"tests/\1.test.\2"),  # src/foo.ts -> tests/foo.test.ts
        (r"^(.+)\.(ts|js|tsx|jsx)$", r"__tests__/\1.test.\2"),  # foo.ts -> __tests__/foo.test.ts
    ],
    # Java
    "java": [
        (r"^(.+)\.java$", r"\1Test.java"),  # Foo.java -> FooTest.java
        (r"^src/main/java/(.+)\.java$", r"src/test/java/\1Test.java"),
    ],
    # Go
    "go": [
        (r"^(.+)\.go$", r"\1_test.go"),  # foo.go -> foo_test.go
    ],
    # C/C++
    "cpp": [
        (r"^(.+)\.(cpp|cc|cxx)$", r"\1_test.\2"),  # foo.cpp -> foo_test.cpp
        (r"^(.+)\.(cpp|cc|cxx)$", r"tests/\1_test.\2"),  # foo.cpp -> tests/foo_test.cpp
    ],
    # Rust
    "rust": [
        (r"^src/(.+)\.rs$", r"tests/\1_test.rs"),  # src/foo.rs -> tests/foo_test.rs
    ],
}


# ── Data models ──────────────────────────────────────────────────


@dataclass
class FileChange:
    """Represents a changed file in git diff."""

    path: str
    """Path to the changed file."""

    change_type: ChangeType
    """Type of change (added, modified, deleted, renamed)."""

    old_path: str | None = None
    """Original path if renamed."""

    lines_added: int = 0
    """Number of lines added."""

    lines_removed: int = 0
    """Number of lines removed."""


@dataclass
class FileMapping:
    """Mapping between source file and its test file."""

    source_file: str
    """Path to the source file."""

    test_file: str
    """Path to the corresponding test file."""

    exists: bool = False
    """Whether the test file exists."""


@dataclass
class DiffAnalysisTask(TaskInput):
    """Task input for diff analysis."""

    task_type: str = "analyze_diff"
    """Type of task (defaults to 'analyze_diff')."""

    target: str = ""
    """Target for the task (defaults to project_root)."""

    project_root: str = ""
    """Root directory of the project to analyze."""

    base_ref: str = "HEAD"
    """Base git ref to compare against (default: HEAD)."""

    compare_ref: str | None = None
    """Ref to compare (default: working directory)."""

    include_untracked: bool = False
    """Whether to include untracked files."""

    def __post_init__(self) -> None:
        """Initialize base TaskInput fields if not already set."""
        if not self.target and self.project_root:
            self.target = self.project_root


@dataclass
class DiffAnalysisResult:
    """Result of diff analysis."""

    changed_files: list[FileChange] = field(default_factory=list)
    """All changed files detected."""

    changed_source_files: list[str] = field(default_factory=list)
    """Changed source files (excluding tests)."""

    changed_test_files: list[str] = field(default_factory=list)
    """Changed test files."""

    file_mappings: list[FileMapping] = field(default_factory=list)
    """Mappings between source files and their tests."""

    affected_source_files: list[str] = field(default_factory=list)
    """Source files that should be analyzed (changed + mapped from changed tests)."""

    total_lines_added: int = 0
    """Total lines added across all changes."""

    total_lines_removed: int = 0
    """Total lines removed across all changes."""


# ── DiffAnalyzer ─────────────────────────────────────────────────


class DiffAnalyzer(BaseAgent):
    """Agent that analyzes git diffs to identify changed files for PR mode.

    Uses git diff to identify changed files, maps source files to their
    corresponding test files, and generates a delta-focused work list
    for efficient analysis of only what changed.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the DiffAnalyzer.

        Args:
            project_root: Root directory of the project.
        """
        self._root = project_root

    @property
    def name(self) -> str:
        """Unique name identifying this agent."""
        return "diff_analyzer"

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return "Analyzes git diffs to identify changed files for delta-focused testing"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute diff analysis.

        Args:
            task: A DiffAnalysisTask specifying the project root and git refs.

        Returns:
            TaskOutput with DiffAnalysisResult in result['diff_result'].
        """
        if not isinstance(task, DiffAnalysisTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a DiffAnalysisTask instance"],
            )

        try:
            project_root = Path(task.project_root)
            if not project_root.exists():
                return TaskOutput(
                    status=TaskStatus.FAILED,
                    errors=[f"Project root does not exist: {project_root}"],
                )

            # Check if this is a git repository
            if not (project_root / ".git").exists():
                return TaskOutput(
                    status=TaskStatus.FAILED,
                    errors=[f"Not a git repository: {project_root}"],
                )

            logger.info(
                "Running diff analysis on %s (base: %s, compare: %s)",
                project_root,
                task.base_ref,
                task.compare_ref or "working directory",
            )

            # Step 1: Get changed files from git diff (task 2.2.1)
            changed_files = self._get_changed_files(
                project_root,
                task.base_ref,
                task.compare_ref,
                include_untracked=task.include_untracked,
            )

            logger.info("Detected %d changed files", len(changed_files))

            # Step 2: Separate source files from test files
            result = self._categorize_changes(changed_files)

            # Step 3: Map source files to test files (task 2.2.2)
            result.file_mappings = self._map_files_to_tests(
                result.changed_source_files, project_root
            )

            # Step 4: Include source files affected by test changes
            affected_by_tests = self._get_source_from_tests(result.changed_test_files, project_root)
            result.affected_source_files = sorted(
                set(result.changed_source_files) | affected_by_tests
            )

            logger.info(
                "Analysis complete: %d source files, %d test files, %d total affected",
                len(result.changed_source_files),
                len(result.changed_test_files),
                len(result.affected_source_files),
            )

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={"diff_result": result},
            )

        except subprocess.CalledProcessError as exc:
            logger.exception("Git command failed")
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Git command failed: {exc}"],
            )
        except Exception as exc:
            logger.exception("Unexpected error during diff analysis")
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Unexpected error: {exc}"],
            )

    def _get_changed_files(
        self,
        project_root: Path,
        base_ref: str,
        compare_ref: str | None,
        *,
        include_untracked: bool,
    ) -> list[FileChange]:
        """Get changed files from git diff.

        Args:
            project_root: Root directory of the project.
            base_ref: Base git ref to compare against.
            compare_ref: Ref to compare (None for working directory).
            include_untracked: Whether to include untracked files.

        Returns:
            List of FileChange entries.
        """
        changed_files: list[FileChange] = []

        # Build git diff command
        if compare_ref:
            # Compare two refs
            cmd = ["git", "diff", "--numstat", "--name-status", f"{base_ref}...{compare_ref}"]
        else:
            # Compare against working directory
            cmd = ["git", "diff", "--numstat", "--name-status", base_ref]

        # Run git diff
        result = subprocess.run(  # noqa: S603
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )

        # Parse output
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            file_change = self._parse_diff_line(line)
            if file_change:
                changed_files.append(file_change)

        # Include untracked files if requested
        if include_untracked and not compare_ref:
            untracked = self._get_untracked_files(project_root)
            changed_files.extend(untracked)

        return changed_files

    def _parse_diff_line(self, line: str) -> FileChange | None:
        """Parse a single line of git diff output.

        Args:
            line: Line from git diff output.

        Returns:
            FileChange or None if the line couldn't be parsed.
        """
        # Git diff output format: "<added>\t<removed>\t<file>"
        # Or for status: "<status>\t<file>" or "<status>\t<old_file>\t<new_file>"
        parts = line.split("\t")

        if len(parts) < MIN_DIFF_PARTS:
            return None

        # Check if first part is a status letter
        if len(parts[0]) == 1 and parts[0].isalpha():
            return self._parse_status_line(parts)

        # Check if it's a numstat line
        if len(parts) == NUMSTAT_PARTS:
            return self._parse_numstat_line(parts)

        return None

    def _parse_status_line(self, parts: list[str]) -> FileChange | None:
        """Parse a status line from git diff.

        Args:
            parts: Split parts of the diff line.

        Returns:
            FileChange or None.
        """
        status = parts[0].upper()
        status_map = {
            "A": (parts[1], ChangeType.ADDED, None),
            "M": (parts[1], ChangeType.MODIFIED, None),
            "D": (parts[1], ChangeType.DELETED, None),
        }

        if status in status_map:
            path, change_type, old_path = status_map[status]
            return FileChange(path=path, change_type=change_type, old_path=old_path)

        if status == "R" and len(parts) >= RENAMED_PARTS:
            return FileChange(
                path=parts[2],
                old_path=parts[1],
                change_type=ChangeType.RENAMED,
            )

        return None

    def _parse_numstat_line(self, parts: list[str]) -> FileChange | None:
        """Parse a numstat line from git diff.

        Args:
            parts: Split parts of the diff line.

        Returns:
            FileChange or None if parsing fails.
        """
        try:
            added = int(parts[0]) if parts[0] != "-" else 0
            removed = int(parts[1]) if parts[1] != "-" else 0
            return FileChange(
                path=parts[2],
                change_type=ChangeType.MODIFIED,
                lines_added=added,
                lines_removed=removed,
            )
        except ValueError:
            return None

    def _get_untracked_files(self, project_root: Path) -> list[FileChange]:
        """Get untracked files from git status.

        Args:
            project_root: Root directory of the project.

        Returns:
            List of FileChange entries for untracked files.
        """
        # Git commands are safe - we validate git repo exists and use hardcoded commands
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],  # noqa: S607
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )

        return [
            FileChange(path=line, change_type=ChangeType.ADDED)
            for line in result.stdout.strip().split("\n")
            if line
        ]

    def _categorize_changes(self, changed_files: list[FileChange]) -> DiffAnalysisResult:
        """Categorize changed files into source files and test files.

        Args:
            changed_files: List of all changed files.

        Returns:
            DiffAnalysisResult with categorized files.
        """
        result = DiffAnalysisResult(changed_files=changed_files)

        for change in changed_files:
            # Accumulate line counts
            result.total_lines_added += change.lines_added
            result.total_lines_removed += change.lines_removed

            # Skip deleted files
            if change.change_type == ChangeType.DELETED:
                continue

            # Check if it's a test file
            if self._is_test_file(change.path):
                result.changed_test_files.append(change.path)
            # Only include source files with relevant extensions
            elif self._is_source_file(change.path):
                result.changed_source_files.append(change.path)

        return result

    def _is_test_file(self, path: str) -> bool:
        """Check if a file is a test file based on naming conventions.

        Args:
            path: Path to the file.

        Returns:
            True if the file is a test file, False otherwise.
        """
        path_lower = path.lower()

        # Common test file patterns (case-insensitive matching)
        test_patterns = [
            r"test_.*\.py$",
            r".*_test\.py$",
            r".*\.test\.(ts|js|tsx|jsx)$",
            r".*\.spec\.(ts|js|tsx|jsx)$",
            r".*test\.java$",  # Lowercase for case-insensitive check
            r".*_test\.go$",
            r".*_test\.(cpp|cc|cxx|c|h|hpp)$",
            r"test_.*\.rs$",
        ]

        # Check for test directory
        if "/test/" in path or "/tests/" in path or "/__tests__/" in path:
            return True

        # Check patterns
        return any(re.search(pattern, path_lower) for pattern in test_patterns)

    def _is_source_file(self, path: str) -> bool:
        """Check if a file is a source file (has a supported extension).

        Args:
            path: Path to the file.

        Returns:
            True if the file is a source file, False otherwise.
        """
        # Supported source file extensions
        source_extensions = {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".java",
            ".go",
            ".rs",
            ".c",
            ".cpp",
            ".cc",
            ".cxx",
            ".h",
            ".hpp",
            ".cs",
            ".rb",
            ".php",
        }

        path_obj = Path(path)
        return path_obj.suffix in source_extensions

    def _map_files_to_tests(
        self, source_files: Sequence[str], project_root: Path
    ) -> list[FileMapping]:
        """Map source files to their corresponding test files.

        Args:
            source_files: List of source file paths.
            project_root: Root directory of the project.

        Returns:
            List of FileMapping entries.
        """
        mappings: list[FileMapping] = []

        for source_file in source_files:
            # Detect language from extension
            language = self._detect_language(source_file)
            if not language:
                continue

            # Try to find corresponding test file
            test_file = self._find_test_file(source_file, language, project_root)

            if test_file:
                mappings.append(
                    FileMapping(
                        source_file=source_file,
                        test_file=test_file,
                        exists=True,
                    )
                )
            else:
                # Generate potential test file path
                potential_test = self._generate_test_path(source_file, language)
                if potential_test:
                    mappings.append(
                        FileMapping(
                            source_file=source_file,
                            test_file=potential_test,
                            exists=False,
                        )
                    )

        return mappings

    def _detect_language(self, path: str) -> str | None:
        """Detect language from file extension.

        Args:
            path: Path to the file.

        Returns:
            Language identifier or None.
        """
        ext = Path(path).suffix

        language_map = {
            ".py": "python",
            ".ts": "javascript",
            ".tsx": "javascript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".java": "java",
            ".go": "go",
            ".cpp": "cpp",
            ".cc": "cpp",
            ".cxx": "cpp",
            ".c": "cpp",
            ".h": "cpp",
            ".hpp": "cpp",
            ".rs": "rust",
        }

        return language_map.get(ext)

    def _find_test_file(self, source_file: str, language: str, project_root: Path) -> str | None:
        """Find existing test file for a source file.

        Args:
            source_file: Path to the source file.
            language: Language identifier.
            project_root: Root directory of the project.

        Returns:
            Path to test file if found, None otherwise.
        """
        patterns = TEST_FILE_PATTERNS.get(language, [])

        for src_pattern, test_pattern in patterns:
            match = re.match(src_pattern, source_file)
            if match:
                # Generate test path from pattern
                try:
                    test_path = re.sub(src_pattern, test_pattern, source_file)
                    full_path = project_root / test_path
                    if full_path.exists():
                        return test_path
                except Exception as exc:
                    logger.debug("Failed to match test pattern %s: %s", test_pattern, exc)
                    continue

        return None

    def _generate_test_path(self, source_file: str, language: str) -> str | None:
        """Generate potential test file path for a source file.

        Args:
            source_file: Path to the source file.
            language: Language identifier.

        Returns:
            Potential test file path.
        """
        patterns = TEST_FILE_PATTERNS.get(language, [])

        if patterns:
            src_pattern, test_pattern = patterns[0]  # Use first pattern as default
            try:
                return re.sub(src_pattern, test_pattern, source_file)
            except Exception as exc:
                logger.debug("Failed to generate test path for %s: %s", source_file, exc)

        return None

    def _get_source_from_tests(self, test_files: Sequence[str], project_root: Path) -> set[str]:
        """Get source files corresponding to changed test files.

        Args:
            test_files: List of test file paths.
            project_root: Root directory of the project.

        Returns:
            Set of source file paths.
        """
        source_files: set[str] = set()

        for test_file in test_files:
            # Detect language
            language = self._detect_language(test_file)
            if not language:
                continue

            # Try to reverse-map test file to source file
            source_file = self._find_source_file(test_file, language, project_root)
            if source_file:
                source_files.add(source_file)

        return source_files

    def _find_source_file(self, test_file: str, language: str, project_root: Path) -> str | None:
        """Find source file corresponding to a test file.

        Args:
            test_file: Path to the test file.
            language: Language identifier.
            project_root: Root directory of the project.

        Returns:
            Path to source file if found, None otherwise.
        """
        # Use simple string transformations to find source files
        # This is more reliable than trying to reverse regex patterns

        potential_sources: list[str] = []

        if language == "python":
            # tests/test_foo.py -> src/foo.py
            if test_file.startswith("tests/test_"):
                name = test_file[len("tests/test_") : -3]  # Remove prefix and .py
                potential_sources.append(f"src/{name}.py")
                potential_sources.append(f"{name}.py")

            # test_foo.py -> foo.py or src/foo.py
            if test_file.startswith("test_"):
                name = test_file[5:-3]  # Remove test_ and .py
                potential_sources.append(f"src/{name}.py")
                potential_sources.append(f"{name}.py")

        elif language == "javascript":
            # foo.test.ts -> src/foo.ts
            if ".test." in test_file:
                source = test_file.replace(".test.", ".")
                potential_sources.append(source)
                if not source.startswith("src/"):
                    potential_sources.append(f"src/{source}")

        # Check if any potential source file exists
        for source_path in potential_sources:
            full_path = project_root / source_path
            if full_path.exists():
                return source_path

        return None
