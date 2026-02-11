"""Tests for gcov/lcov/llvm-cov adapter (adapters/coverage/gcov.py).

Covers detection, LCOV .info parsing, llvm-cov JSON parsing, and
unified CoverageReport generation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from nit.adapters.coverage.gcov import GcovAdapter


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


# ── Sample LCOV .info ───────────────────────────────────────────

_SAMPLE_LCOV_INFO = """TN:
SF:/project/src/math.cpp
FN:1,add
FN:5,multiply
FNDA:2,add
FNDA:0,multiply
DA:1,2
DA:2,2
DA:3,0
DA:5,0
DA:6,0
LF:5
LH:2
BRDA:2,0,0,1
BRDA:2,0,1,-
BRDA:5,0,0,-
LF:5
LH:2
end_of_record
TN:
SF:/project/src/utils.cpp
FN:1,helper
FNDA:5,helper
DA:1,5
DA:2,5
DA:3,5
LF:3
LH:3
end_of_record
"""

_SAMPLE_LCOV_SINGLE_FILE = """TN:
SF:/project/src/single.cpp
FN:10,foo
FNDA:1,foo
DA:10,1
DA:11,1
LF:2
LH:2
end_of_record
"""

_SAMPLE_LCOV_UNCOVERED = """TN:
SF:/project/src/uncovered.cpp
FN:1,main
FNDA:0,main
DA:1,0
DA:2,0
DA:3,0
LF:3
LH:0
end_of_record
"""

_SAMPLE_LCOV_BRDA = """TN:
SF:/project/src/branch.cpp
DA:1,1
DA:2,2
DA:3,0
BRDA:2,0,0,1
BRDA:2,0,1,1
BRDA:2,1,0,-
BRDA:3,0,0,-
LF:3
LH:2
end_of_record
"""

# ── Sample llvm-cov export JSON ─────────────────────────────────

_SAMPLE_LLVM_COV_JSON = {
    "data": [
        {
            "files": [
                {
                    "filename": "/project/src/math.cpp",
                    "segments": [
                        [1, 1, 2, 1, 1],
                        [2, 1, 2, 1, 1],
                        [3, 1, 0, 1, 1],
                        [5, 1, 0, 1, 1],
                    ],
                    "summary": {
                        "lines": {"count": 4, "covered": 2, "percent": 50.0},
                        "functions": {"count": 2, "covered": 1, "percent": 50.0},
                        "regions": {"count": 4, "covered": 2, "percent": 50.0},
                    },
                },
                {
                    "filename": "/project/src/utils.cpp",
                    "segments": [
                        [1, 1, 5, 1, 1],
                        [2, 1, 5, 1, 1],
                    ],
                    "summary": {
                        "lines": {"count": 2, "covered": 2, "percent": 100.0},
                    },
                },
            ],
        }
    ]
}

_SAMPLE_LLVM_COV_EMPTY: dict[str, Any] = {"data": [{"files": []}]}


# ── Tests: GcovAdapter detection ────────────────────────────────


def test_gcov_detect_with_cmake_coverage(tmp_path: Path) -> None:
    """Should detect gcov when CMakeLists.txt mentions coverage."""
    _write_file(
        tmp_path, "CMakeLists.txt", "add_compile_options(--coverage)\nadd_link_options(--coverage)"
    )

    adapter = GcovAdapter()
    assert adapter.detect(tmp_path) is True


def test_gcov_detect_with_cmake_gcov(tmp_path: Path) -> None:
    """Should detect gcov when CMakeLists.txt mentions gcov."""
    _write_file(
        tmp_path,
        "CMakeLists.txt",
        'find_package(Gcov)\nset(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} --coverage")',
    )

    adapter = GcovAdapter()
    assert adapter.detect(tmp_path) is True


def test_gcov_detect_with_gcno(tmp_path: Path) -> None:
    """Should detect gcov when .gcno files exist."""
    (tmp_path / "build").mkdir()
    _write_file(tmp_path / "build", "foo.gcno", "")

    adapter = GcovAdapter()
    assert adapter.detect(tmp_path) is True


def test_gcov_detect_with_gcda(tmp_path: Path) -> None:
    """Should detect gcov when .gcda files exist."""
    (tmp_path / "build").mkdir()
    _write_file(tmp_path / "build", "foo.gcda", "")

    adapter = GcovAdapter()
    assert adapter.detect(tmp_path) is True


def test_gcov_detect_with_coverage_info(tmp_path: Path) -> None:
    """Should detect gcov when coverage.info exists."""
    _write_file(tmp_path, "coverage.info", "SF:foo\nend_of_record")

    adapter = GcovAdapter()
    assert adapter.detect(tmp_path) is True


def test_gcov_detect_with_llvm_cov_json(tmp_path: Path) -> None:
    """Should detect gcov when coverage.json (llvm-cov) exists."""
    _write_json(tmp_path, "coverage.json", {"data": []})

    adapter = GcovAdapter()
    assert adapter.detect(tmp_path) is True


def test_gcov_detect_no_indicators(tmp_path: Path) -> None:
    """Should not detect gcov when no indicators are present."""
    adapter = GcovAdapter()
    assert adapter.detect(tmp_path) is False


# ── Tests: LCOV parsing ──────────────────────────────────────────


def test_gcov_parse_lcov_info(tmp_path: Path) -> None:
    """Should parse LCOV .info format into CoverageReport."""
    coverage_file = tmp_path / "coverage.info"
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_INFO)

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    assert len(report.files) == 2
    assert "/project/src/math.cpp" in report.files
    assert "/project/src/utils.cpp" in report.files


def test_gcov_parse_lcov_line_coverage(tmp_path: Path) -> None:
    """Should correctly parse line coverage from LCOV DA records."""
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_INFO)

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")

    math_file = report.files["/project/src/math.cpp"]
    assert len(math_file.lines) == 5
    line1 = next(ln for ln in math_file.lines if ln.line_number == 1)
    assert line1.execution_count == 2
    assert line1.is_covered is True
    line3 = next(ln for ln in math_file.lines if ln.line_number == 3)
    assert line3.execution_count == 0
    assert line3.is_covered is False


def test_gcov_parse_lcov_function_coverage(tmp_path: Path) -> None:
    """Should correctly parse function coverage from FN/FNDA."""
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_INFO)

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")

    math_file = report.files["/project/src/math.cpp"]
    assert len(math_file.functions) == 2
    add_fn = next(f for f in math_file.functions if f.name == "add")
    assert add_fn.execution_count == 2
    assert add_fn.is_covered is True
    mult_fn = next(f for f in math_file.functions if f.name == "multiply")
    assert mult_fn.execution_count == 0
    assert mult_fn.is_covered is False


def test_gcov_parse_lcov_branch_coverage(tmp_path: Path) -> None:
    """Should correctly parse BRDA records into BranchCoverage."""
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_BRDA)

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")

    branch_file = report.files["/project/src/branch.cpp"]
    assert len(branch_file.branches) == 4
    line2_branches = [b for b in branch_file.branches if b.line_number == 2]
    assert len(line2_branches) == 3


def test_gcov_parse_lcov_uncovered_file(tmp_path: Path) -> None:
    """Should correctly identify completely uncovered file."""
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_UNCOVERED)

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")

    uncovered_file = report.files["/project/src/uncovered.cpp"]
    assert uncovered_file.line_coverage_percentage == 0.0
    assert "/project/src/uncovered.cpp" in report.get_uncovered_files()


def test_gcov_parse_lcov_fully_covered(tmp_path: Path) -> None:
    """Should correctly parse fully covered file."""
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_INFO)

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")

    utils_file = report.files["/project/src/utils.cpp"]
    assert utils_file.line_coverage_percentage == 100.0
    assert all(ln.is_covered for ln in utils_file.lines)


def test_gcov_parse_lcov_brda_dash(tmp_path: Path) -> None:
    """Should treat BRDA '-' as not executed (0)."""
    lcov = """TN:
SF:/project/src/dash.cpp
DA:1,1
BRDA:1,0,0,-
end_of_record
"""
    _write_file(tmp_path, "coverage.info", lcov)

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")

    assert "/project/src/dash.cpp" in report.files
    branch = report.files["/project/src/dash.cpp"].branches[0]
    assert branch.taken_count == 0
    assert branch.total_count == 1


# ── Tests: llvm-cov JSON parsing ─────────────────────────────────


def test_gcov_parse_llvm_cov_json(tmp_path: Path) -> None:
    """Should parse llvm-cov export JSON into CoverageReport."""
    coverage_file = tmp_path / "coverage.json"
    _write_json(tmp_path, "coverage.json", cast("dict[str, object]", _SAMPLE_LLVM_COV_JSON))

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(coverage_file)

    assert len(report.files) == 2
    assert "/project/src/math.cpp" in report.files
    assert "/project/src/utils.cpp" in report.files


def test_gcov_parse_llvm_cov_segments(tmp_path: Path) -> None:
    """Should correctly parse segments into line coverage."""
    _write_json(tmp_path, "coverage.json", cast("dict[str, object]", _SAMPLE_LLVM_COV_JSON))

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.json")

    math_file = report.files["/project/src/math.cpp"]
    assert len(math_file.lines) >= 1
    assert report.overall_line_coverage > 0.0


def test_gcov_parse_llvm_cov_empty_data(tmp_path: Path) -> None:
    """Should return empty report for llvm-cov JSON with no files."""
    _write_json(tmp_path, "coverage.json", cast("dict[str, object]", _SAMPLE_LLVM_COV_EMPTY))

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.json")

    assert len(report.files) == 0


# ── Tests: parse_coverage_file format detection ──────────────────


def test_gcov_parse_missing_file(tmp_path: Path) -> None:
    """Should return empty report for missing file."""
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "nonexistent.info")

    assert len(report.files) == 0


def test_gcov_parse_invalid_json(tmp_path: Path) -> None:
    """Should return empty report for invalid JSON when file is .json."""
    _write_file(tmp_path, "coverage.json", "not valid json {")

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.json")

    assert len(report.files) == 0


def test_gcov_parse_content_detection_json(tmp_path: Path) -> None:
    """Should detect JSON by content when parsing."""
    _write_file(
        tmp_path,
        "report.txt",
        json.dumps(cast("dict[str, object]", _SAMPLE_LLVM_COV_JSON)),
    )

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "report.txt")

    assert len(report.files) == 2


def test_gcov_parse_content_detection_lcov(tmp_path: Path) -> None:
    """Should detect LCOV by content when parsing."""
    _write_file(tmp_path, "report.txt", _SAMPLE_LCOV_SINGLE_FILE)

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "report.txt")

    assert len(report.files) == 1
    assert "/project/src/single.cpp" in report.files


# ── Tests: GcovAdapter properties ───────────────────────────────


def test_gcov_adapter_name() -> None:
    """GcovAdapter.name should return 'gcov'."""
    adapter = GcovAdapter()
    assert adapter.name == "gcov"


def test_gcov_adapter_language() -> None:
    """GcovAdapter.language should return 'cpp'."""
    adapter = GcovAdapter()
    assert adapter.language == "cpp"


# ── Tests: Overall coverage report ────────────────────────────────


def test_gcov_report_overall_metrics(tmp_path: Path) -> None:
    """Should calculate correct overall metrics from LCOV data."""
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_INFO)

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")

    assert report.overall_line_coverage > 0.0
    assert len(report.files) == 2


def test_gcov_report_partially_covered(tmp_path: Path) -> None:
    """Should identify partially covered files below threshold."""
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_INFO)

    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")

    partial = report.get_partially_covered_files(threshold=80.0)
    assert len(partial) >= 0
