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
from nit.adapters.coverage.coverlet_adapter import CoverletAdapter
from nit.adapters.coverage.gcov import GcovAdapter
from nit.adapters.coverage.go_cover_adapter import GoCoverAdapter
from nit.adapters.coverage.istanbul import IstanbulAdapter
from nit.adapters.coverage.jacoco import JaCoCoAdapter
from nit.adapters.coverage.tarpaulin import TarpaulinAdapter

__all__ = [
    "BranchCoverage",
    "CoverageAdapter",
    "CoveragePyAdapter",
    "CoverageReport",
    "CoverletAdapter",
    "FileCoverage",
    "FunctionCoverage",
    "GcovAdapter",
    "GoCoverAdapter",
    "IstanbulAdapter",
    "JaCoCoAdapter",
    "LineCoverage",
    "TarpaulinAdapter",
]
