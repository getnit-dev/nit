"""Base classes and data models for coverage adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class LineCoverage:
    """Coverage data for a single line of code."""

    line_number: int
    execution_count: int

    @property
    def is_covered(self) -> bool:
        """Return True if this line was executed at least once."""
        return self.execution_count > 0


@dataclass
class FunctionCoverage:
    """Coverage data for a single function."""

    name: str
    line_number: int
    execution_count: int

    @property
    def is_covered(self) -> bool:
        """Return True if this function was executed at least once."""
        return self.execution_count > 0


@dataclass
class BranchCoverage:
    """Coverage data for a single branch (if/else, switch, ternary, etc.)."""

    line_number: int
    branch_id: int
    taken_count: int
    total_count: int

    @property
    def coverage_percentage(self) -> float:
        """Return branch coverage as a percentage (0.0-100.0)."""
        if self.total_count == 0:
            return 100.0
        return (self.taken_count / self.total_count) * 100.0


@dataclass
class FileCoverage:
    """Coverage data for a single source file."""

    file_path: str
    lines: list[LineCoverage] = field(default_factory=list)
    functions: list[FunctionCoverage] = field(default_factory=list)
    branches: list[BranchCoverage] = field(default_factory=list)

    @property
    def line_coverage_percentage(self) -> float:
        """Return line coverage percentage (0.0-100.0)."""
        if not self.lines:
            return 100.0
        covered = sum(1 for line in self.lines if line.is_covered)
        return (covered / len(self.lines)) * 100.0

    @property
    def function_coverage_percentage(self) -> float:
        """Return function coverage percentage (0.0-100.0)."""
        if not self.functions:
            return 100.0
        covered = sum(1 for func in self.functions if func.is_covered)
        return (covered / len(self.functions)) * 100.0

    @property
    def branch_coverage_percentage(self) -> float:
        """Return branch coverage percentage (0.0-100.0)."""
        if not self.branches:
            return 100.0
        total_taken = sum(branch.taken_count for branch in self.branches)
        total_count = sum(branch.total_count for branch in self.branches)
        if total_count == 0:
            return 100.0
        return (total_taken / total_count) * 100.0


@dataclass
class CoverageReport:
    """Unified coverage report across all files in a project.

    This is the unified format that all coverage adapters (Istanbul, coverage.py,
    gcov, JaCoCo, etc.) translate their native reports into.
    """

    files: dict[str, FileCoverage] = field(default_factory=dict)

    @property
    def overall_line_coverage(self) -> float:
        """Return overall line coverage percentage across all files."""
        if not self.files:
            return 100.0
        total_lines = sum(len(file.lines) for file in self.files.values())
        if total_lines == 0:
            return 100.0
        covered_lines = sum(
            sum(1 for line in file.lines if line.is_covered) for file in self.files.values()
        )
        return (covered_lines / total_lines) * 100.0

    @property
    def overall_function_coverage(self) -> float:
        """Return overall function coverage percentage across all files."""
        if not self.files:
            return 100.0
        total_functions = sum(len(file.functions) for file in self.files.values())
        if total_functions == 0:
            return 100.0
        covered_functions = sum(
            sum(1 for func in file.functions if func.is_covered) for file in self.files.values()
        )
        return (covered_functions / total_functions) * 100.0

    @property
    def overall_branch_coverage(self) -> float:
        """Return overall branch coverage percentage across all files."""
        if not self.files:
            return 100.0
        total_taken = sum(
            sum(branch.taken_count for branch in file.branches) for file in self.files.values()
        )
        total_count = sum(
            sum(branch.total_count for branch in file.branches) for file in self.files.values()
        )
        if total_count == 0:
            return 100.0
        return (total_taken / total_count) * 100.0

    def get_uncovered_files(self) -> list[str]:
        """Return list of file paths with 0% line coverage."""
        return [
            path
            for path, file_cov in self.files.items()
            if file_cov.line_coverage_percentage == 0.0
        ]

    def get_partially_covered_files(self, threshold: float = 80.0) -> list[tuple[str, float]]:
        """Return list of (file_path, coverage_pct) with coverage below threshold."""
        return [
            (path, file_cov.line_coverage_percentage)
            for path, file_cov in self.files.items()
            if 0.0 < file_cov.line_coverage_percentage < threshold
        ]


class CoverageAdapter(ABC):
    """Abstract base class for coverage tool adapters.

    Each concrete adapter knows how to run a coverage tool (Istanbul, coverage.py,
    gcov, JaCoCo, etc.) and parse its output into the unified CoverageReport format.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Coverage tool identifier (e.g. 'istanbul', 'coverage.py', 'gcov')."""

    @property
    @abstractmethod
    def language(self) -> str:
        """Primary language (e.g. 'typescript', 'python', 'cpp')."""

    @abstractmethod
    def detect(self, project_path: Path) -> bool:
        """Return True if this coverage tool can be used in project_path."""

    @abstractmethod
    async def run_coverage(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = 120.0,
    ) -> CoverageReport:
        """Run coverage collection and return unified report.

        Args:
            project_path: Root of the project to collect coverage for.
            test_files: Specific test files to run. None runs all.
            timeout: Maximum seconds to wait for coverage collection.

        Returns:
            A CoverageReport with unified coverage data.
        """

    @abstractmethod
    def parse_coverage_file(self, coverage_file: Path) -> CoverageReport:
        """Parse a coverage report file into unified format.

        Args:
            coverage_file: Path to the native coverage report file.

        Returns:
            A CoverageReport with parsed coverage data.
        """
