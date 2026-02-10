"""Tests for Istanbul coverage adapter (adapters/coverage/istanbul.py).

Covers detection, coverage parsing from Istanbul JSON format, and
unified CoverageReport generation.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.coverage import (
    BranchCoverage,
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    LineCoverage,
)
from nit.adapters.coverage.istanbul import IstanbulAdapter

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
