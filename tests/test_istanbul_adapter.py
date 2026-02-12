"""Tests for Istanbul coverage adapter (adapters/coverage/istanbul.py).

Covers detection, coverage parsing from Istanbul JSON format, and
unified CoverageReport generation.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.coverage import (
    BranchCoverage,
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    LineCoverage,
)
from nit.adapters.coverage.istanbul import IstanbulAdapter, _has_jest, _has_vitest

# ── Helpers ──────────────────────────────────────────────────────


def _write_file(root: Path, rel: str, content: str) -> None:
    """Write *content* to a file under *root*."""
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def _write_json(root: Path, rel: str, data: dict[str, object]) -> None:
    """Write JSON data to a file under *root*."""
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Sample Istanbul coverage JSON ────────────────────────────────

_SAMPLE_ISTANBUL_COVERAGE = {
    "/project/src/math.ts": {
        "path": "/project/src/math.ts",
        "statementMap": {
            "0": {"start": {"line": 1, "column": 0}, "end": {"line": 1, "column": 20}},
            "1": {"start": {"line": 2, "column": 0}, "end": {"line": 2, "column": 15}},
            "2": {"start": {"line": 5, "column": 0}, "end": {"line": 5, "column": 25}},
            "3": {"start": {"line": 6, "column": 0}, "end": {"line": 6, "column": 15}},
        },
        "fnMap": {
            "0": {
                "name": "add",
                "loc": {"start": {"line": 1, "column": 0}, "end": {"line": 3, "column": 1}},
            },
            "1": {
                "name": "multiply",
                "loc": {"start": {"line": 5, "column": 0}, "end": {"line": 7, "column": 1}},
            },
        },
        "branchMap": {
            "0": {
                "loc": {"start": {"line": 2, "column": 2}, "end": {"line": 2, "column": 20}},
                "type": "if",
                "locations": [
                    {"start": {"line": 2, "column": 2}, "end": {"line": 2, "column": 10}},
                    {"start": {"line": 2, "column": 12}, "end": {"line": 2, "column": 20}},
                ],
            },
        },
        "s": {"0": 10, "1": 8, "2": 5, "3": 0},
        "f": {"0": 10, "1": 0},
        "b": {"0": [8, 2]},
    },
    "/project/src/utils.ts": {
        "path": "/project/src/utils.ts",
        "statementMap": {
            "0": {"start": {"line": 1, "column": 0}, "end": {"line": 1, "column": 30}},
            "1": {"start": {"line": 2, "column": 0}, "end": {"line": 2, "column": 20}},
        },
        "fnMap": {
            "0": {
                "name": "identity",
                "loc": {"start": {"line": 1, "column": 0}, "end": {"line": 3, "column": 1}},
            },
        },
        "branchMap": {},
        "s": {"0": 3, "1": 3},
        "f": {"0": 3},
        "b": {},
    },
}

_EMPTY_FILE_COVERAGE = {
    "/project/src/empty.ts": {
        "path": "/project/src/empty.ts",
        "statementMap": {},
        "fnMap": {},
        "branchMap": {},
        "s": {},
        "f": {},
        "b": {},
    },
}

_UNCOVERED_FILE_COVERAGE = {
    "/project/src/uncovered.ts": {
        "path": "/project/src/uncovered.ts",
        "statementMap": {
            "0": {"start": {"line": 1, "column": 0}, "end": {"line": 1, "column": 20}},
            "1": {"start": {"line": 2, "column": 0}, "end": {"line": 2, "column": 15}},
        },
        "fnMap": {
            "0": {
                "name": "unused",
                "loc": {"start": {"line": 1, "column": 0}, "end": {"line": 3, "column": 1}},
            },
        },
        "branchMap": {},
        "s": {"0": 0, "1": 0},
        "f": {"0": 0},
        "b": {},
    },
}


# ── Tests: Data model ────────────────────────────────────────────


def test_line_coverage_is_covered() -> None:
    """LineCoverage.is_covered should return True when execution_count > 0."""
    covered = LineCoverage(line_number=1, execution_count=5)
    uncovered = LineCoverage(line_number=2, execution_count=0)

    assert covered.is_covered is True
    assert uncovered.is_covered is False


def test_function_coverage_is_covered() -> None:
    """FunctionCoverage.is_covered should return True when executed."""
    covered = FunctionCoverage(name="foo", line_number=1, execution_count=1)
    uncovered = FunctionCoverage(name="bar", line_number=5, execution_count=0)

    assert covered.is_covered is True
    assert uncovered.is_covered is False


def test_branch_coverage_percentage() -> None:
    """BranchCoverage should calculate percentage correctly."""
    full = BranchCoverage(line_number=1, branch_id=0, taken_count=2, total_count=2)
    partial = BranchCoverage(line_number=2, branch_id=1, taken_count=1, total_count=2)
    none = BranchCoverage(line_number=3, branch_id=2, taken_count=0, total_count=2)

    assert full.coverage_percentage == 100.0
    assert partial.coverage_percentage == 50.0
    assert none.coverage_percentage == 0.0


def test_file_coverage_percentages() -> None:
    """FileCoverage should calculate line/function/branch percentages."""
    file_cov = FileCoverage(
        file_path="test.ts",
        lines=[
            LineCoverage(line_number=1, execution_count=1),
            LineCoverage(line_number=2, execution_count=0),
            LineCoverage(line_number=3, execution_count=1),
        ],
        functions=[
            FunctionCoverage(name="foo", line_number=1, execution_count=1),
            FunctionCoverage(name="bar", line_number=5, execution_count=0),
        ],
        branches=[
            BranchCoverage(line_number=2, branch_id=0, taken_count=1, total_count=2),
        ],
    )

    # 2/3 lines covered = 66.67%
    assert abs(file_cov.line_coverage_percentage - 66.67) < 0.1
    # 1/2 functions covered = 50%
    assert file_cov.function_coverage_percentage == 50.0
    # 1/2 branches taken = 50%
    assert file_cov.branch_coverage_percentage == 50.0


def test_coverage_report_overall_percentages() -> None:
    """CoverageReport should calculate overall percentages across files."""
    report = CoverageReport(
        files={
            "file1.ts": FileCoverage(
                file_path="file1.ts",
                lines=[
                    LineCoverage(line_number=1, execution_count=1),
                    LineCoverage(line_number=2, execution_count=0),
                ],
                functions=[
                    FunctionCoverage(name="foo", line_number=1, execution_count=1),
                ],
                branches=[],
            ),
            "file2.ts": FileCoverage(
                file_path="file2.ts",
                lines=[
                    LineCoverage(line_number=1, execution_count=1),
                    LineCoverage(line_number=2, execution_count=1),
                ],
                functions=[
                    FunctionCoverage(name="bar", line_number=1, execution_count=0),
                ],
                branches=[],
            ),
        }
    )

    # 3/4 lines covered = 75%
    assert report.overall_line_coverage == 75.0
    # 1/2 functions covered = 50%
    assert report.overall_function_coverage == 50.0


def test_coverage_report_uncovered_files() -> None:
    """CoverageReport.get_uncovered_files should return files with 0% coverage."""
    report = CoverageReport(
        files={
            "covered.ts": FileCoverage(
                file_path="covered.ts",
                lines=[LineCoverage(line_number=1, execution_count=1)],
            ),
            "uncovered.ts": FileCoverage(
                file_path="uncovered.ts",
                lines=[LineCoverage(line_number=1, execution_count=0)],
            ),
        }
    )

    uncovered = report.get_uncovered_files()
    assert uncovered == ["uncovered.ts"]


def test_coverage_report_partially_covered_files() -> None:
    """CoverageReport.get_partially_covered_files should return files below threshold."""
    report = CoverageReport(
        files={
            "high.ts": FileCoverage(
                file_path="high.ts",
                lines=[
                    LineCoverage(line_number=1, execution_count=1),
                    LineCoverage(line_number=2, execution_count=1),
                ],
            ),
            "low.ts": FileCoverage(
                file_path="low.ts",
                lines=[
                    LineCoverage(line_number=1, execution_count=1),
                    LineCoverage(line_number=2, execution_count=0),
                ],
            ),
        }
    )

    partial = report.get_partially_covered_files(threshold=80.0)
    assert len(partial) == 1
    assert partial[0][0] == "low.ts"
    assert abs(partial[0][1] - 50.0) < 0.1


# ── Tests: IstanbulAdapter detection ─────────────────────────────


def test_istanbul_detect_with_vitest_config(tmp_path: Path) -> None:
    """Should detect Istanbul when vitest.config.* exists."""
    _write_file(tmp_path, "vitest.config.ts", "export default {}")

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is True


def test_istanbul_detect_with_jest_config(tmp_path: Path) -> None:
    """Should detect Istanbul when jest.config.* exists."""
    _write_file(tmp_path, "jest.config.js", "module.exports = {}")

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is True


def test_istanbul_detect_with_package_json_vitest(tmp_path: Path) -> None:
    """Should detect Istanbul when vitest is in package.json devDependencies."""
    _write_json(
        tmp_path,
        "package.json",
        {"devDependencies": {"vitest": "^0.34.0"}},
    )

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is True


def test_istanbul_detect_with_package_json_jest(tmp_path: Path) -> None:
    """Should detect Istanbul when jest is in package.json."""
    _write_json(
        tmp_path,
        "package.json",
        {"devDependencies": {"jest": "^29.0.0"}},
    )

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is True


def test_istanbul_detect_with_package_json_c8(tmp_path: Path) -> None:
    """Should detect Istanbul when c8 is in package.json."""
    _write_json(
        tmp_path,
        "package.json",
        {"devDependencies": {"c8": "^8.0.0"}},
    )

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is True


def test_istanbul_detect_with_existing_coverage(tmp_path: Path) -> None:
    """Should detect Istanbul when coverage file exists."""
    _write_json(tmp_path, "coverage/coverage-final.json", {})

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is True


def test_istanbul_detect_no_indicators(tmp_path: Path) -> None:
    """Should not detect Istanbul when no indicators are present."""
    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is False


# ── Tests: IstanbulAdapter parsing ───────────────────────────────


def test_istanbul_parse_coverage_file(tmp_path: Path) -> None:
    """Should parse Istanbul JSON format into CoverageReport."""
    coverage_file = tmp_path / "coverage-final.json"
    _write_json(
        tmp_path, "coverage-final.json", cast("dict[str, object]", _SAMPLE_ISTANBUL_COVERAGE)
    )

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    # Should have 2 files
    assert len(report.files) == 2
    assert "/project/src/math.ts" in report.files
    assert "/project/src/utils.ts" in report.files


def test_istanbul_parse_line_coverage(tmp_path: Path) -> None:
    """Should correctly parse line coverage from statements."""
    coverage_file = tmp_path / "coverage-final.json"
    _write_json(
        tmp_path, "coverage-final.json", cast("dict[str, object]", _SAMPLE_ISTANBUL_COVERAGE)
    )

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    math_file = report.files["/project/src/math.ts"]
    # Should have lines 1, 2, 5, 6 (from statementMap)
    assert len(math_file.lines) == 4

    # Line 1: execution_count = 10
    line1 = next(ln for ln in math_file.lines if ln.line_number == 1)
    assert line1.execution_count == 10
    assert line1.is_covered is True

    # Line 6: execution_count = 0 (uncovered)
    line6 = next(ln for ln in math_file.lines if ln.line_number == 6)
    assert line6.execution_count == 0
    assert line6.is_covered is False


def test_istanbul_parse_function_coverage(tmp_path: Path) -> None:
    """Should correctly parse function coverage."""
    coverage_file = tmp_path / "coverage-final.json"
    _write_json(
        tmp_path, "coverage-final.json", cast("dict[str, object]", _SAMPLE_ISTANBUL_COVERAGE)
    )

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    math_file = report.files["/project/src/math.ts"]
    # Should have 2 functions: add, multiply
    assert len(math_file.functions) == 2

    # Function 'add' should have execution_count = 10
    add_fn = next(fn for fn in math_file.functions if fn.name == "add")
    assert add_fn.execution_count == 10
    assert add_fn.is_covered is True

    # Function 'multiply' should have execution_count = 0 (uncovered)
    multiply_fn = next(fn for fn in math_file.functions if fn.name == "multiply")
    assert multiply_fn.execution_count == 0
    assert multiply_fn.is_covered is False


def test_istanbul_parse_branch_coverage(tmp_path: Path) -> None:
    """Should correctly parse branch coverage."""
    coverage_file = tmp_path / "coverage-final.json"
    _write_json(
        tmp_path, "coverage-final.json", cast("dict[str, object]", _SAMPLE_ISTANBUL_COVERAGE)
    )

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    math_file = report.files["/project/src/math.ts"]
    # Should have 1 branch
    assert len(math_file.branches) == 1

    branch = math_file.branches[0]
    # Branch has 2 locations: [8, 2] -> 2 taken, 2 total
    assert branch.taken_count == 2
    assert branch.total_count == 2
    assert branch.coverage_percentage == 100.0


def test_istanbul_parse_empty_file(tmp_path: Path) -> None:
    """Should handle empty files with no coverage data."""
    coverage_file = tmp_path / "coverage-final.json"
    _write_json(tmp_path, "coverage-final.json", cast("dict[str, object]", _EMPTY_FILE_COVERAGE))

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    empty_file = report.files["/project/src/empty.ts"]
    assert len(empty_file.lines) == 0
    assert len(empty_file.functions) == 0
    assert len(empty_file.branches) == 0
    assert empty_file.line_coverage_percentage == 100.0


def test_istanbul_parse_uncovered_file(tmp_path: Path) -> None:
    """Should correctly identify completely uncovered files."""
    coverage_file = tmp_path / "coverage-final.json"
    _write_json(
        tmp_path, "coverage-final.json", cast("dict[str, object]", _UNCOVERED_FILE_COVERAGE)
    )

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    uncovered_file = report.files["/project/src/uncovered.ts"]
    assert uncovered_file.line_coverage_percentage == 0.0
    assert uncovered_file.function_coverage_percentage == 0.0

    # Should be in uncovered files list
    assert "/project/src/uncovered.ts" in report.get_uncovered_files()


def test_istanbul_parse_invalid_json(tmp_path: Path) -> None:
    """Should return empty report for invalid JSON."""
    coverage_file = tmp_path / "coverage-final.json"
    _write_file(tmp_path, "coverage-final.json", "not valid json {")

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    assert len(report.files) == 0


def test_istanbul_parse_missing_file(tmp_path: Path) -> None:
    """Should return empty report for missing file."""
    coverage_file = tmp_path / "nonexistent.json"

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    assert len(report.files) == 0


# ── Tests: IstanbulAdapter properties ────────────────────────────


def test_istanbul_adapter_name() -> None:
    """IstanbulAdapter.name should return 'istanbul'."""
    adapter = IstanbulAdapter()
    assert adapter.name == "istanbul"


def test_istanbul_adapter_language() -> None:
    """IstanbulAdapter.language should return 'typescript'."""
    adapter = IstanbulAdapter()
    assert adapter.language == "typescript"


# ── Tests: Overall coverage report ───────────────────────────────


def test_coverage_report_overall_metrics(tmp_path: Path) -> None:
    """Should calculate correct overall metrics from sample data."""
    coverage_file = tmp_path / "coverage-final.json"
    _write_json(
        tmp_path, "coverage-final.json", cast("dict[str, object]", _SAMPLE_ISTANBUL_COVERAGE)
    )

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    # Overall metrics should aggregate across both files
    assert report.overall_line_coverage > 0.0
    assert report.overall_function_coverage > 0.0
    assert report.overall_branch_coverage > 0.0

    # Should have 2 files total
    assert len(report.files) == 2


# ── Tests: Additional detection paths ────────────────────────────


def test_istanbul_detect_with_vitest_workspace(tmp_path: Path) -> None:
    """Should detect Istanbul when vitest.workspace.* exists."""
    _write_file(tmp_path, "vitest.workspace.ts", "export default []")

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is True


def test_istanbul_detect_with_vitest_coverage_v8(tmp_path: Path) -> None:
    """Should detect Istanbul when @vitest/coverage-v8 is in devDependencies."""
    _write_json(
        tmp_path,
        "package.json",
        {"devDependencies": {"@vitest/coverage-v8": "^0.34.0"}},
    )

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is True


def test_istanbul_detect_with_deps_in_dependencies(tmp_path: Path) -> None:
    """Should detect Istanbul when vitest is in dependencies (not devDependencies)."""
    _write_json(
        tmp_path,
        "package.json",
        {"dependencies": {"vitest": "^0.34.0"}},
    )

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is True


def test_istanbul_detect_malformed_package_json(tmp_path: Path) -> None:
    """Should not crash on malformed package.json; just returns False."""
    _write_file(tmp_path, "package.json", "{ this is not valid json !!!")

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is False


def test_istanbul_detect_package_json_no_relevant_deps(tmp_path: Path) -> None:
    """Should not detect when package.json has unrelated deps only."""
    _write_json(
        tmp_path,
        "package.json",
        {"devDependencies": {"lodash": "^4.0.0", "express": "^4.18.0"}},
    )

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is False


def test_istanbul_detect_nyc_output(tmp_path: Path) -> None:
    """Should detect Istanbul when .nyc_output/coverage-final.json exists."""
    _write_json(tmp_path, ".nyc_output/coverage-final.json", {})

    adapter = IstanbulAdapter()
    assert adapter.detect(tmp_path) is True


# ── Tests: _find_and_parse_coverage ──────────────────────────────


def test_find_and_parse_coverage_from_coverage_dir(tmp_path: Path) -> None:
    """Should find and parse coverage from coverage/ directory."""
    _write_json(
        tmp_path,
        "coverage/coverage-final.json",
        cast("dict[str, object]", _EMPTY_FILE_COVERAGE),
    )

    adapter = IstanbulAdapter()
    report = adapter._find_and_parse_coverage(tmp_path)

    assert len(report.files) == 1
    assert "/project/src/empty.ts" in report.files


def test_find_and_parse_coverage_from_nyc_output(tmp_path: Path) -> None:
    """Should find coverage from .nyc_output/ when coverage/ is absent."""
    _write_json(
        tmp_path,
        ".nyc_output/coverage-final.json",
        cast("dict[str, object]", _EMPTY_FILE_COVERAGE),
    )

    adapter = IstanbulAdapter()
    report = adapter._find_and_parse_coverage(tmp_path)

    assert len(report.files) == 1


def test_find_and_parse_coverage_no_file(tmp_path: Path) -> None:
    """Should return empty report when no coverage file exists."""
    adapter = IstanbulAdapter()
    report = adapter._find_and_parse_coverage(tmp_path)

    assert len(report.files) == 0


def test_find_and_parse_coverage_prefers_first_path(tmp_path: Path) -> None:
    """Should prefer coverage/ over .nyc_output/ when both exist."""
    # Write different data to each location
    _write_json(
        tmp_path,
        "coverage/coverage-final.json",
        cast("dict[str, object]", _SAMPLE_ISTANBUL_COVERAGE),
    )
    _write_json(
        tmp_path,
        ".nyc_output/coverage-final.json",
        cast("dict[str, object]", _EMPTY_FILE_COVERAGE),
    )

    adapter = IstanbulAdapter()
    report = adapter._find_and_parse_coverage(tmp_path)

    # Should find the 2-file sample, not the 1-file empty one
    assert len(report.files) == 2


# ── Tests: Additional parsing edge cases ─────────────────────────


def test_istanbul_parse_branch_partial_taken(tmp_path: Path) -> None:
    """Should correctly handle branches where only some are taken."""
    data = {
        "/project/src/branch.ts": {
            "statementMap": {},
            "fnMap": {},
            "branchMap": {
                "0": {
                    "loc": {"start": {"line": 10, "column": 0}},
                    "type": "if",
                },
            },
            "s": {},
            "f": {},
            "b": {"0": [5, 0, 3]},
        },
    }
    coverage_file = tmp_path / "cov.json"
    _write_json(tmp_path, "cov.json", cast("dict[str, object]", data))

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    branch_file = report.files["/project/src/branch.ts"]
    assert len(branch_file.branches) == 1

    branch = branch_file.branches[0]
    # [5, 0, 3] -> 2 of 3 taken (5>0 and 3>0, 0 is not > 0)
    assert branch.taken_count == 2
    assert branch.total_count == 3
    assert branch.branch_id == 0


def test_istanbul_parse_branch_non_digit_id(tmp_path: Path) -> None:
    """Should default branch_id to 0 for non-digit branch IDs."""
    data = {
        "/project/src/branch2.ts": {
            "statementMap": {},
            "fnMap": {},
            "branchMap": {
                "abc": {
                    "loc": {"start": {"line": 3, "column": 0}},
                    "type": "cond-expr",
                },
            },
            "s": {},
            "f": {},
            "b": {"abc": [1, 0]},
        },
    }
    coverage_file = tmp_path / "cov.json"
    _write_json(tmp_path, "cov.json", cast("dict[str, object]", data))

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    branch = report.files["/project/src/branch2.ts"].branches[0]
    assert branch.branch_id == 0  # fallback for non-digit
    assert branch.taken_count == 1
    assert branch.total_count == 2


def test_istanbul_parse_branch_non_list_counts_skipped(tmp_path: Path) -> None:
    """Should skip branches where counts is not a list."""
    data = {
        "/project/src/weird.ts": {
            "statementMap": {},
            "fnMap": {},
            "branchMap": {
                "0": {
                    "loc": {"start": {"line": 1, "column": 0}},
                    "type": "if",
                },
            },
            "s": {},
            "f": {},
            "b": {"0": "not-a-list"},
        },
    }
    coverage_file = tmp_path / "cov.json"
    _write_json(tmp_path, "cov.json", cast("dict[str, object]", data))

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    assert len(report.files["/project/src/weird.ts"].branches) == 0


def test_istanbul_parse_function_anonymous_fallback(tmp_path: Path) -> None:
    """Should use anonymous_N fallback when fnMap entry has no name."""
    data = {
        "/project/src/anon.ts": {
            "statementMap": {},
            "fnMap": {
                "0": {
                    "loc": {"start": {"line": 5, "column": 0}},
                },
            },
            "branchMap": {},
            "s": {},
            "f": {"0": 3},
            "b": {},
        },
    }
    coverage_file = tmp_path / "cov.json"
    _write_json(tmp_path, "cov.json", cast("dict[str, object]", data))

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    funcs = report.files["/project/src/anon.ts"].functions
    assert len(funcs) == 1
    assert funcs[0].name == "anonymous_0"
    assert funcs[0].execution_count == 3
    assert funcs[0].line_number == 5


def test_istanbul_parse_function_missing_fnmap_entry(tmp_path: Path) -> None:
    """Should handle fn count with no matching fnMap entry gracefully."""
    data = {
        "/project/src/missing_fn.ts": {
            "statementMap": {},
            "fnMap": {},
            "branchMap": {},
            "s": {},
            "f": {"0": 2},  # fn count exists but no fnMap entry
            "b": {},
        },
    }
    coverage_file = tmp_path / "cov.json"
    _write_json(tmp_path, "cov.json", cast("dict[str, object]", data))

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    funcs = report.files["/project/src/missing_fn.ts"].functions
    assert len(funcs) == 1
    # Falls back to anonymous_0 name and line 0
    assert funcs[0].name == "anonymous_0"
    assert funcs[0].line_number == 0
    assert funcs[0].execution_count == 2


def test_istanbul_parse_line_aggregation_same_line(tmp_path: Path) -> None:
    """Should aggregate statement counts on the same line."""
    data = {
        "/project/src/multi.ts": {
            "statementMap": {
                "0": {"start": {"line": 1, "column": 0}, "end": {"line": 1, "column": 10}},
                "1": {"start": {"line": 1, "column": 12}, "end": {"line": 1, "column": 20}},
                "2": {"start": {"line": 2, "column": 0}, "end": {"line": 2, "column": 10}},
            },
            "fnMap": {},
            "branchMap": {},
            "s": {"0": 3, "1": 5, "2": 1},
            "f": {},
            "b": {},
        },
    }
    coverage_file = tmp_path / "cov.json"
    _write_json(tmp_path, "cov.json", cast("dict[str, object]", data))

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    lines = report.files["/project/src/multi.ts"].lines
    assert len(lines) == 2  # Two distinct line numbers

    line1 = next(ln for ln in lines if ln.line_number == 1)
    # Aggregated from both entries: three plus five equals eight
    assert line1.execution_count == 8

    line2 = next(ln for ln in lines if ln.line_number == 2)
    assert line2.execution_count == 1


def test_istanbul_parse_statement_no_line(tmp_path: Path) -> None:
    """Should skip statements without a start line."""
    data = {
        "/project/src/noline.ts": {
            "statementMap": {
                "0": {"start": {"column": 0}, "end": {"line": 1, "column": 10}},
                "1": {},
            },
            "fnMap": {},
            "branchMap": {},
            "s": {"0": 3, "1": 5},
            "f": {},
            "b": {},
        },
    }
    coverage_file = tmp_path / "cov.json"
    _write_json(tmp_path, "cov.json", cast("dict[str, object]", data))

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    # Both statements lack a valid line, so no lines produced
    assert len(report.files["/project/src/noline.ts"].lines) == 0


def test_istanbul_parse_missing_maps(tmp_path: Path) -> None:
    """Should handle data with entirely missing maps (no keys at all)."""
    data: dict[str, object] = {
        "/project/src/bare.ts": {},
    }
    coverage_file = tmp_path / "cov.json"
    _write_json(tmp_path, "cov.json", data)

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    bare = report.files["/project/src/bare.ts"]
    assert len(bare.lines) == 0
    assert len(bare.functions) == 0
    assert len(bare.branches) == 0


def test_istanbul_parse_empty_json_object(tmp_path: Path) -> None:
    """Should return empty report for empty JSON object."""
    coverage_file = tmp_path / "empty.json"
    _write_json(tmp_path, "empty.json", {})

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    assert len(report.files) == 0


def test_istanbul_parse_lines_sorted(tmp_path: Path) -> None:
    """Line coverage entries should be sorted by line number."""
    data = {
        "/project/src/sorted.ts": {
            "statementMap": {
                "0": {"start": {"line": 10, "column": 0}, "end": {"line": 10, "column": 10}},
                "1": {"start": {"line": 3, "column": 0}, "end": {"line": 3, "column": 10}},
                "2": {"start": {"line": 7, "column": 0}, "end": {"line": 7, "column": 10}},
            },
            "fnMap": {},
            "branchMap": {},
            "s": {"0": 1, "1": 2, "2": 3},
            "f": {},
            "b": {},
        },
    }
    coverage_file = tmp_path / "cov.json"
    _write_json(tmp_path, "cov.json", cast("dict[str, object]", data))

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    lines = report.files["/project/src/sorted.ts"].lines
    line_numbers = [ln.line_number for ln in lines]
    assert line_numbers == [3, 7, 10]


def test_istanbul_parse_branch_all_untaken(tmp_path: Path) -> None:
    """Should correctly report zero taken when all branch arms are untaken."""
    data = {
        "/project/src/nottaken.ts": {
            "statementMap": {},
            "fnMap": {},
            "branchMap": {
                "0": {
                    "loc": {"start": {"line": 5, "column": 0}},
                    "type": "if",
                },
            },
            "s": {},
            "f": {},
            "b": {"0": [0, 0]},
        },
    }
    coverage_file = tmp_path / "cov.json"
    _write_json(tmp_path, "cov.json", cast("dict[str, object]", data))

    adapter = IstanbulAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    branch = report.files["/project/src/nottaken.ts"].branches[0]
    assert branch.taken_count == 0
    assert branch.total_count == 2
    assert branch.coverage_percentage == 0.0


# ── Coverage gap tests: run_coverage, _has_vitest, _has_jest ──────────


def test_has_vitest_true(tmp_path: Path) -> None:
    """_has_vitest returns True when vitest config exists."""
    _write_file(tmp_path, "vitest.config.ts", "export default {}")
    assert _has_vitest(tmp_path) is True


def test_has_vitest_false(tmp_path: Path) -> None:
    """_has_vitest returns False when no vitest config."""
    assert _has_vitest(tmp_path) is False


def test_has_jest_true(tmp_path: Path) -> None:
    """_has_jest returns True when jest config exists."""
    _write_file(tmp_path, "jest.config.js", "module.exports = {}")
    assert _has_jest(tmp_path) is True


def test_has_jest_false(tmp_path: Path) -> None:
    """_has_jest returns False when no jest config."""
    assert _has_jest(tmp_path) is False


@pytest.mark.asyncio
async def test_istanbul_run_coverage_vitest(tmp_path: Path) -> None:
    """run_coverage uses vitest when vitest config exists."""
    _write_file(tmp_path, "vitest.config.ts", "export default {}")
    _write_json(
        tmp_path,
        "coverage/coverage-final.json",
        cast("dict[str, object]", _EMPTY_FILE_COVERAGE),
    )
    adapter = IstanbulAdapter()
    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_proc:
        proc = AsyncMock()
        proc.wait = AsyncMock(return_value=0)
        proc.returncode = 0
        mock_proc.return_value = proc
        report = await adapter.run_coverage(tmp_path)
    assert len(report.files) == 1


@pytest.mark.asyncio
async def test_istanbul_run_coverage_jest(tmp_path: Path) -> None:
    """run_coverage uses jest when jest config exists."""
    _write_file(tmp_path, "jest.config.js", "module.exports = {}")
    _write_json(
        tmp_path,
        "coverage/coverage-final.json",
        cast("dict[str, object]", _EMPTY_FILE_COVERAGE),
    )
    adapter = IstanbulAdapter()
    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_proc:
        proc = AsyncMock()
        proc.wait = AsyncMock(return_value=0)
        proc.returncode = 0
        mock_proc.return_value = proc
        report = await adapter.run_coverage(tmp_path)
    assert len(report.files) == 1


@pytest.mark.asyncio
async def test_istanbul_run_coverage_no_runner(tmp_path: Path) -> None:
    """run_coverage raises when no supported test runner found."""
    adapter = IstanbulAdapter()
    with pytest.raises(RuntimeError, match="No supported test runner"):
        await adapter.run_coverage(tmp_path)


@pytest.mark.asyncio
async def test_istanbul_run_coverage_vitest_timeout(
    tmp_path: Path,
) -> None:
    """run_coverage handles vitest timeout."""
    _write_file(tmp_path, "vitest.config.ts", "export default {}")
    adapter = IstanbulAdapter()
    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_proc:
        proc = AsyncMock()
        # First call (inside wait_for) raises TimeoutError; second (cleanup) returns normally
        proc.wait = AsyncMock(side_effect=[TimeoutError, None])
        proc.returncode = None
        proc.kill = MagicMock()
        mock_proc.return_value = proc
        report = await adapter.run_coverage(tmp_path, timeout=0.01)
    # Returns whatever was found (empty in this case)
    assert isinstance(report, CoverageReport)


@pytest.mark.asyncio
async def test_istanbul_run_coverage_vitest_error(
    tmp_path: Path,
) -> None:
    """run_coverage handles vitest errors."""
    _write_file(tmp_path, "vitest.config.ts", "export default {}")
    adapter = IstanbulAdapter()
    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        side_effect=OSError("npx not found"),
    ):
        report = await adapter.run_coverage(tmp_path)
    assert isinstance(report, CoverageReport)


@pytest.mark.asyncio
async def test_istanbul_run_coverage_jest_timeout(
    tmp_path: Path,
) -> None:
    """run_coverage handles jest timeout."""
    _write_file(tmp_path, "jest.config.js", "module.exports = {}")
    adapter = IstanbulAdapter()
    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_proc:
        proc = AsyncMock()
        # First call (inside wait_for) raises TimeoutError; second (cleanup) returns normally
        proc.wait = AsyncMock(side_effect=[TimeoutError, None])
        proc.returncode = None
        proc.kill = MagicMock()
        mock_proc.return_value = proc
        report = await adapter.run_coverage(tmp_path, timeout=0.01)
    assert isinstance(report, CoverageReport)


@pytest.mark.asyncio
async def test_istanbul_run_coverage_jest_error(
    tmp_path: Path,
) -> None:
    """run_coverage handles jest errors."""
    _write_file(tmp_path, "jest.config.js", "module.exports = {}")
    adapter = IstanbulAdapter()
    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        side_effect=OSError("npx not found"),
    ):
        report = await adapter.run_coverage(tmp_path)
    assert isinstance(report, CoverageReport)


@pytest.mark.asyncio
async def test_istanbul_run_coverage_vitest_with_test_files(
    tmp_path: Path,
) -> None:
    """run_coverage passes test_files to vitest command."""
    _write_file(tmp_path, "vitest.config.ts", "export default {}")
    _write_json(
        tmp_path,
        "coverage/coverage-final.json",
        cast("dict[str, object]", _EMPTY_FILE_COVERAGE),
    )
    adapter = IstanbulAdapter()
    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock_proc:
        proc = AsyncMock()
        proc.wait = AsyncMock(return_value=0)
        proc.returncode = 0
        mock_proc.return_value = proc
        report = await adapter.run_coverage(tmp_path, test_files=[tmp_path / "test_math.ts"])
    assert len(report.files) == 1
