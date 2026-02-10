"""Coverage adapters for unified coverage reporting."""

from nit.adapters.coverage.base import (
    BranchCoverage,
    CoverageAdapter,
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    LineCoverage,
)
from nit.adapters.coverage.coverage_py_adapter import CoveragePyAdapter
from nit.adapters.coverage.istanbul import IstanbulAdapter

__all__ = [
    "BranchCoverage",
    "CoverageAdapter",
    "CoveragePyAdapter",
    "CoverageReport",
    "FileCoverage",
    "FunctionCoverage",
    "IstanbulAdapter",
    "LineCoverage",
]
