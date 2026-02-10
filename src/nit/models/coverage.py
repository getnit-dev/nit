"""Coverage report models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PackageCoverage:
    """Coverage metrics for a single package."""

    name: str
    """Package name."""

    line_coverage: float
    """Line coverage percentage (0.0 to 1.0)."""

    function_coverage: float
    """Function coverage percentage (0.0 to 1.0)."""

    branch_coverage: float
    """Branch coverage percentage (0.0 to 1.0)."""


@dataclass
class CoverageReport:
    """Complete coverage report for a project."""

    packages: dict[str, PackageCoverage]
    """Coverage metrics per package."""

    overall_line_coverage: float
    """Overall line coverage percentage (0.0 to 1.0)."""

    overall_function_coverage: float
    """Overall function coverage percentage (0.0 to 1.0)."""

    overall_branch_coverage: float
    """Overall branch coverage percentage (0.0 to 1.0)."""
