"""Tests for coverage.py adapter (adapters/coverage/coverage_py_adapter.py).

Covers detection, coverage parsing from coverage.py JSON format, and
unified CoverageReport generation.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.coverage.coverage_py_adapter import CoveragePyAdapter

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


# ── Sample coverage.py JSON ──────────────────────────────────────

_SAMPLE_COVERAGE_PY_JSON = {
    "meta": {
        "version": "7.3.0",
        "timestamp": "2024-01-15T10:30:00",
        "branch_coverage": True,
        "show_contexts": False,
    },
    "files": {
        "/project/src/math.py": {
            "executed_lines": [1, 2, 3, 5, 6],
            "missing_lines": [8, 9],
            "excluded_lines": [],
            "summary": {
                "covered_lines": 5,
                "num_statements": 7,
                "percent_covered": 71.43,
                "percent_covered_display": "71",
                "missing_lines": 2,
                "excluded_lines": 0,
            },
        },
        "/project/src/utils.py": {
            "executed_lines": [1, 2, 3],
            "missing_lines": [],
            "excluded_lines": [],
            "summary": {
                "covered_lines": 3,
                "num_statements": 3,
                "percent_covered": 100.0,
                "percent_covered_display": "100",
                "missing_lines": 0,
                "excluded_lines": 0,
            },
        },
    },
    "totals": {
        "covered_lines": 8,
        "num_statements": 10,
        "percent_covered": 80.0,
        "percent_covered_display": "80",
        "missing_lines": 2,
        "excluded_lines": 0,
    },
}

_EMPTY_FILE_COVERAGE = {
    "meta": {
        "version": "7.3.0",
        "timestamp": "2024-01-15T10:30:00",
        "branch_coverage": False,
        "show_contexts": False,
    },
    "files": {
        "/project/src/empty.py": {
            "executed_lines": [],
            "missing_lines": [],
            "excluded_lines": [],
            "summary": {
                "covered_lines": 0,
                "num_statements": 0,
                "percent_covered": 100.0,
                "missing_lines": 0,
                "excluded_lines": 0,
            },
        }
    },
    "totals": {
        "covered_lines": 0,
        "num_statements": 0,
        "percent_covered": 100.0,
        "missing_lines": 0,
        "excluded_lines": 0,
    },
}

_UNCOVERED_FILE_COVERAGE = {
    "meta": {
        "version": "7.3.0",
        "timestamp": "2024-01-15T10:30:00",
        "branch_coverage": False,
        "show_contexts": False,
    },
    "files": {
        "/project/src/uncovered.py": {
            "executed_lines": [],
            "missing_lines": [1, 2, 3, 4, 5],
            "excluded_lines": [],
            "summary": {
                "covered_lines": 0,
                "num_statements": 5,
                "percent_covered": 0.0,
                "missing_lines": 5,
                "excluded_lines": 0,
            },
        }
    },
    "totals": {
        "covered_lines": 0,
        "num_statements": 5,
        "percent_covered": 0.0,
        "missing_lines": 5,
        "excluded_lines": 0,
    },
}

_BRANCH_COVERAGE_JSON = {
    "meta": {
        "version": "7.3.0",
        "timestamp": "2024-01-15T10:30:00",
        "branch_coverage": True,
        "show_contexts": False,
    },
    "files": {
        "/project/src/branching.py": {
            "executed_lines": [1, 2, 3, 5],
            "missing_lines": [6],
            "excluded_lines": [],
            "missing_branches": [
                [2, 3],  # Line 2, branch to line 3 not taken
                [5, 6],  # Line 5, branch to line 6 not taken
            ],
            "summary": {
                "covered_lines": 4,
                "num_statements": 5,
                "percent_covered": 80.0,
                "missing_lines": 1,
                "excluded_lines": 0,
            },
        }
    },
    "totals": {
        "covered_lines": 4,
        "num_statements": 5,
        "percent_covered": 80.0,
        "missing_lines": 1,
        "excluded_lines": 0,
    },
}


# ── Tests: CoveragePyAdapter detection ───────────────────────────


def test_coverage_py_detect_with_pytest_ini(tmp_path: Path) -> None:
    """Should detect coverage.py when pytest.ini exists."""
    _write_file(tmp_path, "pytest.ini", "[pytest]\ntestpaths = tests")

    adapter = CoveragePyAdapter()
    assert adapter.detect(tmp_path) is True


def test_coverage_py_detect_with_pyproject_toml(tmp_path: Path) -> None:
    """Should detect coverage.py when pyproject.toml exists."""
    _write_file(
        tmp_path,
        "pyproject.toml",
        "[tool.pytest.ini_options]\ntestpaths = ['tests']",
    )

    adapter = CoveragePyAdapter()
    assert adapter.detect(tmp_path) is True


def test_coverage_py_detect_with_requirements(tmp_path: Path) -> None:
    """Should detect coverage.py when pytest-cov is in requirements."""
    _write_file(tmp_path, "requirements.txt", "pytest-cov>=4.0.0\npytest>=7.0.0")

    adapter = CoveragePyAdapter()
    assert adapter.detect(tmp_path) is True


def test_coverage_py_detect_with_dev_requirements(tmp_path: Path) -> None:
    """Should detect coverage.py when coverage is in dev requirements."""
    _write_file(tmp_path, "requirements-dev.txt", "coverage>=7.0.0\npytest>=7.0.0")

    adapter = CoveragePyAdapter()
    assert adapter.detect(tmp_path) is True


def test_coverage_py_detect_with_existing_coverage_file(tmp_path: Path) -> None:
    """Should detect coverage.py when .coverage file exists."""
    _write_file(tmp_path, ".coverage", "")

    adapter = CoveragePyAdapter()
    assert adapter.detect(tmp_path) is True


def test_coverage_py_detect_with_coverage_json(tmp_path: Path) -> None:
    """Should detect coverage.py when coverage.json exists."""
    _write_json(tmp_path, "coverage.json", {})

    adapter = CoveragePyAdapter()
    assert adapter.detect(tmp_path) is True


def test_coverage_py_detect_no_indicators(tmp_path: Path) -> None:
    """Should not detect coverage.py when no indicators are present."""
    adapter = CoveragePyAdapter()
    assert adapter.detect(tmp_path) is False


# ── Tests: CoveragePyAdapter parsing ─────────────────────────────


def test_coverage_py_parse_coverage_file(tmp_path: Path) -> None:
    """Should parse coverage.py JSON format into CoverageReport."""
    coverage_file = tmp_path / "coverage.json"
    _write_json(tmp_path, "coverage.json", _SAMPLE_COVERAGE_PY_JSON)

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    # Should have 2 files
    assert len(report.files) == 2
    assert "/project/src/math.py" in report.files
    assert "/project/src/utils.py" in report.files


def test_coverage_py_parse_line_coverage(tmp_path: Path) -> None:
    """Should correctly parse line coverage from executed/missing lines."""
    coverage_file = tmp_path / "coverage.json"
    _write_json(tmp_path, "coverage.json", _SAMPLE_COVERAGE_PY_JSON)

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    math_file = report.files["/project/src/math.py"]
    # Should have 7 total lines (5 executed + 2 missing)
    assert len(math_file.lines) == 7

    # Line 1 should be executed
    line1 = next(ln for ln in math_file.lines if ln.line_number == 1)
    assert line1.execution_count == 1
    assert line1.is_covered is True

    # Line 8 should be missing (not executed)
    line8 = next(ln for ln in math_file.lines if ln.line_number == 8)
    assert line8.execution_count == 0
    assert line8.is_covered is False


def test_coverage_py_parse_fully_covered_file(tmp_path: Path) -> None:
    """Should correctly parse a file with 100% coverage."""
    coverage_file = tmp_path / "coverage.json"
    _write_json(tmp_path, "coverage.json", _SAMPLE_COVERAGE_PY_JSON)

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    utils_file = report.files["/project/src/utils.py"]
    # Should have 3 lines, all executed
    assert len(utils_file.lines) == 3
    assert all(ln.is_covered for ln in utils_file.lines)
    assert utils_file.line_coverage_percentage == 100.0


def test_coverage_py_parse_empty_file(tmp_path: Path) -> None:
    """Should handle empty files with no coverage data."""
    coverage_file = tmp_path / "coverage.json"
    _write_json(tmp_path, "coverage.json", _EMPTY_FILE_COVERAGE)

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    empty_file = report.files["/project/src/empty.py"]
    assert len(empty_file.lines) == 0
    assert len(empty_file.functions) == 0
    assert len(empty_file.branches) == 0
    assert empty_file.line_coverage_percentage == 100.0


def test_coverage_py_parse_uncovered_file(tmp_path: Path) -> None:
    """Should correctly identify completely uncovered files."""
    coverage_file = tmp_path / "coverage.json"
    _write_json(tmp_path, "coverage.json", _UNCOVERED_FILE_COVERAGE)

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    uncovered_file = report.files["/project/src/uncovered.py"]
    assert uncovered_file.line_coverage_percentage == 0.0

    # Should be in uncovered files list
    assert "/project/src/uncovered.py" in report.get_uncovered_files()


def test_coverage_py_parse_branch_coverage(tmp_path: Path) -> None:
    """Should correctly parse branch coverage when available."""
    coverage_file = tmp_path / "coverage.json"
    _write_json(tmp_path, "coverage.json", _BRANCH_COVERAGE_JSON)

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    branching_file = report.files["/project/src/branching.py"]
    # Should have 2 branches (both missing)
    assert len(branching_file.branches) == 2

    # Check that branches are tracked by line number
    branch_lines = {branch.line_number for branch in branching_file.branches}
    assert 2 in branch_lines
    assert 5 in branch_lines


def test_coverage_py_parse_invalid_json(tmp_path: Path) -> None:
    """Should return empty report for invalid JSON."""
    coverage_file = tmp_path / "coverage.json"
    _write_file(tmp_path, "coverage.json", "not valid json {")

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    assert len(report.files) == 0


def test_coverage_py_parse_missing_file(tmp_path: Path) -> None:
    """Should return empty report for missing file."""
    coverage_file = tmp_path / "nonexistent.json"

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    assert len(report.files) == 0


# ── Tests: CoveragePyAdapter properties ──────────────────────────


def test_coverage_py_adapter_name() -> None:
    """CoveragePyAdapter.name should return 'coverage.py'."""
    adapter = CoveragePyAdapter()
    assert adapter.name == "coverage.py"


def test_coverage_py_adapter_language() -> None:
    """CoveragePyAdapter.language should return 'python'."""
    adapter = CoveragePyAdapter()
    assert adapter.language == "python"


# ── Tests: Overall coverage report ───────────────────────────────


def test_coverage_py_report_overall_metrics(tmp_path: Path) -> None:
    """Should calculate correct overall metrics from sample data."""
    coverage_file = tmp_path / "coverage.json"
    _write_json(tmp_path, "coverage.json", _SAMPLE_COVERAGE_PY_JSON)

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    # Overall metrics should aggregate across both files
    # 8 covered / 10 total = 80%
    assert abs(report.overall_line_coverage - 80.0) < 0.1

    # Should have 2 files total
    assert len(report.files) == 2


def test_coverage_py_report_uncovered_files(tmp_path: Path) -> None:
    """Should correctly identify uncovered files."""
    coverage_file = tmp_path / "coverage.json"
    _write_json(tmp_path, "coverage.json", _UNCOVERED_FILE_COVERAGE)

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    uncovered = report.get_uncovered_files()
    assert len(uncovered) == 1
    assert "/project/src/uncovered.py" in uncovered


def test_coverage_py_report_partially_covered_files(tmp_path: Path) -> None:
    """Should identify partially covered files below threshold."""
    coverage_file = tmp_path / "coverage.json"
    _write_json(tmp_path, "coverage.json", _SAMPLE_COVERAGE_PY_JSON)

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    # math.py has 71.43% coverage, which is below 80% threshold
    partial = report.get_partially_covered_files(threshold=80.0)
    assert len(partial) == 1
    assert partial[0][0] == "/project/src/math.py"
    assert abs(partial[0][1] - 71.43) < 0.1


def test_coverage_py_parse_with_missing_meta(tmp_path: Path) -> None:
    """Should handle coverage JSON without meta field."""
    coverage_file = tmp_path / "coverage.json"
    minimal_coverage = {
        "files": {
            "/project/src/simple.py": {
                "executed_lines": [1, 2],
                "missing_lines": [3],
                "excluded_lines": [],
            }
        }
    }
    _write_json(tmp_path, "coverage.json", cast("dict[str, object]", minimal_coverage))

    adapter = CoveragePyAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    # Should still parse the file successfully
    assert len(report.files) == 1
    simple_file = report.files["/project/src/simple.py"]
    assert len(simple_file.lines) == 3
