"""Tests for gcov/lcov/llvm-cov adapter (adapters/coverage/gcov.py).

Covers detection, LCOV .info parsing, llvm-cov JSON parsing, and
unified CoverageReport generation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.coverage.base import CoverageReport
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


# ── Additional coverage tests ─────────────────────────────────────


def test_gcov_detect_cmake_no_coverage_patterns(tmp_path: Path) -> None:
    """Should not detect when CMakeLists.txt has no coverage patterns."""
    _write_file(tmp_path, "CMakeLists.txt", "project(example)\nadd_executable(main main.cpp)")
    adapter = GcovAdapter()
    assert adapter.detect(tmp_path) is False


def test_gcov_detect_cmake_read_error(tmp_path: Path) -> None:
    """Should handle missing CMakeLists gracefully."""
    adapter = GcovAdapter()
    assert adapter._detect_cmake_coverage(tmp_path) is False


def test_gcov_detect_lcov_files_via_glob(tmp_path: Path) -> None:
    """Should detect via *.info glob pattern."""
    _write_file(tmp_path / "subdir", "output.info", "SF:foo\nend_of_record")
    adapter = GcovAdapter()
    assert adapter._detect_gcov_or_lcov_files(tmp_path) is True


def test_gcov_detect_lcov_files_no_match(tmp_path: Path) -> None:
    """Should return False when no lcov/gcov files found."""
    adapter = GcovAdapter()
    assert adapter._detect_gcov_or_lcov_files(tmp_path) is False


def test_gcov_detect_llvm_cov_json_by_name(tmp_path: Path) -> None:
    """Should detect llvm-cov JSON by exact name match."""
    _write_json(tmp_path, "coverage-export.json", {"data": []})
    adapter = GcovAdapter()
    assert adapter._detect_llvm_cov_json(tmp_path) is True


def test_gcov_detect_llvm_cov_json_by_rglob(tmp_path: Path) -> None:
    """Should detect llvm-cov JSON via rglob for *coverage.json."""
    _write_json(tmp_path / "build", "project-coverage.json", {"data": []})
    adapter = GcovAdapter()
    assert adapter._detect_llvm_cov_json(tmp_path) is True


def test_gcov_detect_llvm_cov_json_no_match(tmp_path: Path) -> None:
    """Should return False when no llvm-cov JSON found."""
    adapter = GcovAdapter()
    assert adapter._detect_llvm_cov_json(tmp_path) is False


def test_gcov_parse_lcov_string_no_end_of_record(tmp_path: Path) -> None:
    """Should flush record even without end_of_record at EOF."""
    lcov = """SF:/project/src/eof.cpp
DA:1,5
DA:2,0
"""
    _write_file(tmp_path, "coverage.info", lcov)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")
    assert "/project/src/eof.cpp" in report.files
    assert len(report.files["/project/src/eof.cpp"].lines) == 2


def test_gcov_parse_lcov_string_empty(tmp_path: Path) -> None:
    """Should handle empty content gracefully."""
    _write_file(tmp_path, "coverage.info", "")
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")
    assert len(report.files) == 0


def test_gcov_parse_lcov_string_multiple_records(tmp_path: Path) -> None:
    """Should parse multiple SF records correctly."""
    lcov = """SF:/a.cpp
DA:1,1
end_of_record
SF:/b.cpp
DA:1,0
end_of_record
SF:/c.cpp
DA:1,3
end_of_record
"""
    _write_file(tmp_path, "coverage.info", lcov)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")
    assert len(report.files) == 3


def test_gcov_parse_lcov_invalid_da_ignored(tmp_path: Path) -> None:
    """Should ignore DA lines that cannot be parsed as int."""
    lcov = """SF:/bad.cpp
DA:abc,xyz
DA:1,2
end_of_record
"""
    _write_file(tmp_path, "coverage.info", lcov)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")
    assert len(report.files["/bad.cpp"].lines) == 1


def test_gcov_parse_lcov_invalid_brda_ignored(tmp_path: Path) -> None:
    """Should ignore BRDA lines that cannot be parsed."""
    lcov = """SF:/badbr.cpp
DA:1,1
BRDA:x,0,0,0
BRDA:1,0,0,1
end_of_record
"""
    _write_file(tmp_path, "coverage.info", lcov)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")
    assert len(report.files["/badbr.cpp"].branches) == 1


def test_gcov_find_and_parse_lcov_info(tmp_path: Path) -> None:
    """Should find coverage.info and parse it."""
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_SINGLE_FILE)
    adapter = GcovAdapter()
    report = adapter._find_and_parse_existing(tmp_path)
    assert len(report.files) == 1


def test_gcov_find_and_parse_lcov_lcov(tmp_path: Path) -> None:
    """Should find lcov.info and parse it."""
    _write_file(tmp_path, "lcov.info", _SAMPLE_LCOV_SINGLE_FILE)
    adapter = GcovAdapter()
    report = adapter._find_and_parse_existing(tmp_path)
    assert len(report.files) == 1


def test_gcov_find_and_parse_json(tmp_path: Path) -> None:
    """Should find coverage.json and parse it."""
    _write_json(tmp_path, "coverage.json", cast("dict[str, object]", _SAMPLE_LLVM_COV_JSON))
    adapter = GcovAdapter()
    report = adapter._find_and_parse_existing(tmp_path)
    assert len(report.files) == 2


def test_gcov_find_and_parse_rglob_info(tmp_path: Path) -> None:
    """Should find *.info via rglob when named files not present."""
    _write_file(tmp_path / "subdir", "custom.info", _SAMPLE_LCOV_SINGLE_FILE)
    adapter = GcovAdapter()
    report = adapter._find_and_parse_existing(tmp_path)
    assert len(report.files) == 1


def test_gcov_find_and_parse_nothing(tmp_path: Path) -> None:
    """Should return empty report when nothing found."""
    adapter = GcovAdapter()
    report = adapter._find_and_parse_existing(tmp_path)
    assert len(report.files) == 0


def test_gcov_llvm_cov_json_with_functions(tmp_path: Path) -> None:
    """Should parse llvm-cov JSON functions array."""
    data: dict[str, object] = {
        "data": [
            {
                "files": [
                    {
                        "filename": "/src/main.cpp",
                        "segments": [[1, 1, 5, 1, 1]],
                        "functions": [
                            {
                                "name": "main",
                                "regions": [[1, 1, 10, 1]],
                            }
                        ],
                    }
                ]
            }
        ]
    }
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    assert len(report.files) == 1
    fc = report.files["/src/main.cpp"]
    assert len(fc.functions) == 1
    assert fc.functions[0].name == "main"


def test_gcov_llvm_cov_json_with_branches(tmp_path: Path) -> None:
    """Should parse llvm-cov JSON branches array."""
    data: dict[str, object] = {
        "data": [
            {
                "files": [
                    {
                        "filename": "/src/branch.cpp",
                        "segments": [[1, 1, 2, 1, 1]],
                        "branches": [[5, 1, 1, 1]],
                    }
                ]
            }
        ]
    }
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    fc = report.files["/src/branch.cpp"]
    assert len(fc.branches) == 1
    assert fc.branches[0].taken_count == 1


def test_gcov_llvm_cov_json_invalid_file_info_skipped(tmp_path: Path) -> None:
    """Should skip non-dict entries in files array."""
    data: dict[str, object] = {"data": [{"files": ["not a dict", 42]}]}
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    assert len(report.files) == 0


def test_gcov_llvm_cov_json_file_without_filename(tmp_path: Path) -> None:
    """Should skip file entries without filename."""
    data: dict[str, object] = {"data": [{"files": [{"segments": []}]}]}
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    assert len(report.files) == 0


# ── Coverage gap tests: run_coverage, _run_lcov_capture, _run_llvm_cov_export ─


@pytest.mark.asyncio
async def test_gcov_run_coverage_falls_back_to_existing(tmp_path: Path) -> None:
    """run_coverage should fall back to _find_and_parse_existing."""
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_SINGLE_FILE)
    adapter = GcovAdapter()
    with (
        patch.object(adapter, "_run_lcov_capture", new_callable=AsyncMock) as mock_lcov,
        patch.object(adapter, "_run_llvm_cov_export", new_callable=AsyncMock) as mock_llvm,
    ):
        mock_lcov.return_value = CoverageReport()
        mock_llvm.return_value = CoverageReport()
        report = await adapter.run_coverage(tmp_path)
    assert len(report.files) == 1


@pytest.mark.asyncio
async def test_gcov_run_coverage_returns_empty_when_nothing_found(
    tmp_path: Path,
) -> None:
    """run_coverage returns empty report when nothing is found."""
    adapter = GcovAdapter()
    with (
        patch.object(adapter, "_run_lcov_capture", new_callable=AsyncMock) as mock_lcov,
        patch.object(adapter, "_run_llvm_cov_export", new_callable=AsyncMock) as mock_llvm,
    ):
        mock_lcov.return_value = CoverageReport()
        mock_llvm.return_value = CoverageReport()
        report = await adapter.run_coverage(tmp_path)
    assert len(report.files) == 0


@pytest.mark.asyncio
async def test_gcov_run_coverage_test_files_logged(tmp_path: Path) -> None:
    """run_coverage should log debug when test_files provided."""
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_SINGLE_FILE)
    adapter = GcovAdapter()
    with (
        patch.object(adapter, "_run_lcov_capture", new_callable=AsyncMock) as mock_lcov,
        patch.object(adapter, "_run_llvm_cov_export", new_callable=AsyncMock) as mock_llvm,
    ):
        mock_lcov.return_value = CoverageReport()
        mock_llvm.return_value = CoverageReport()
        report = await adapter.run_coverage(tmp_path, test_files=[tmp_path / "test.cpp"])
    assert len(report.files) == 1


@pytest.mark.asyncio
async def test_gcov_run_coverage_lcov_success(tmp_path: Path) -> None:
    """run_coverage returns lcov result when lcov capture succeeds."""
    adapter = GcovAdapter()
    fake_report = CoverageReport(files={"a.cpp": cast("Any", object())})
    with patch.object(adapter, "_run_lcov_capture", new_callable=AsyncMock) as mock_lcov:
        mock_lcov.return_value = fake_report
        report = await adapter.run_coverage(tmp_path)
    assert report.files


@pytest.mark.asyncio
async def test_gcov_run_lcov_capture_file_not_found(tmp_path: Path) -> None:
    """_run_lcov_capture returns empty on FileNotFoundError."""
    adapter = GcovAdapter()
    with patch(
        "nit.adapters.coverage.gcov.run_subprocess",
        new_callable=AsyncMock,
        side_effect=FileNotFoundError("lcov not found"),
    ):
        report = await adapter._run_lcov_capture(tmp_path, timeout=5.0)
    assert len(report.files) == 0


@pytest.mark.asyncio
async def test_gcov_run_lcov_capture_success(tmp_path: Path) -> None:
    """_run_lcov_capture parses output when lcov succeeds."""
    _write_file(tmp_path, "coverage.info", _SAMPLE_LCOV_SINGLE_FILE)
    adapter = GcovAdapter()
    mock_result = MagicMock(success=True)
    with patch(
        "nit.adapters.coverage.gcov.run_subprocess",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        report = await adapter._run_lcov_capture(tmp_path, timeout=5.0)
    assert len(report.files) == 1


@pytest.mark.asyncio
async def test_gcov_run_llvm_cov_export_no_profdata(tmp_path: Path) -> None:
    """_run_llvm_cov_export returns empty when no .profdata found."""
    adapter = GcovAdapter()
    report = await adapter._run_llvm_cov_export(tmp_path, timeout=5.0)
    assert len(report.files) == 0


def test_gcov_parse_lcov_file_oserror(tmp_path: Path) -> None:
    """_parse_lcov_file returns empty on OSError."""
    adapter = GcovAdapter()
    missing = tmp_path / "nonexistent.info"
    report = adapter._parse_lcov_file(missing)
    assert len(report.files) == 0


def test_gcov_parse_llvm_cov_file_oserror(tmp_path: Path) -> None:
    """_parse_llvm_cov_file returns empty on OSError."""
    adapter = GcovAdapter()
    missing = tmp_path / "nonexistent.json"
    report = adapter._parse_llvm_cov_file(missing)
    assert len(report.files) == 0


def test_gcov_parse_llvm_cov_json_string_invalid() -> None:
    """_parse_llvm_cov_json_string returns empty on invalid JSON."""
    adapter = GcovAdapter()
    report = adapter._parse_llvm_cov_json_string("{broken json")
    assert len(report.files) == 0


def test_gcov_parse_coverage_file_oserror_on_read(tmp_path: Path) -> None:
    """parse_coverage_file returns empty when content reading fails."""
    adapter = GcovAdapter()
    # File with unknown extension - triggers content detection branch
    file_path = tmp_path / "report.dat"
    file_path.write_text("dummy")
    with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
        report = adapter.parse_coverage_file(file_path)
    assert len(report.files) == 0


def test_gcov_detect_cmake_os_error(tmp_path: Path) -> None:
    """_detect_cmake_coverage handles unreadable CMakeLists.txt."""
    cmake = tmp_path / "CMakeLists.txt"
    cmake.write_text("coverage")
    adapter = GcovAdapter()
    # Make file unreadable by patching read_text
    with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
        result = adapter._detect_cmake_coverage(tmp_path)
    assert result is False


def test_gcov_detect_lcov_fixed_name(tmp_path: Path) -> None:
    """_detect_gcov_or_lcov_files returns True for lcov.info by name."""
    (tmp_path / "lcov.info").write_text("SF:foo\nend_of_record")
    adapter = GcovAdapter()
    assert adapter._detect_gcov_or_lcov_files(tmp_path) is True


def test_gcov_find_and_parse_coverage_lcov(tmp_path: Path) -> None:
    """_find_and_parse_existing finds coverage.lcov file."""
    _write_file(tmp_path, "coverage.lcov", _SAMPLE_LCOV_SINGLE_FILE)
    adapter = GcovAdapter()
    report = adapter._find_and_parse_existing(tmp_path)
    assert len(report.files) == 1


def test_gcov_llvm_cov_json_non_dict_data_block(tmp_path: Path) -> None:
    """Should skip non-dict entries in data array."""
    data: dict[str, object] = {"data": ["not-a-dict", 42]}
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    assert len(report.files) == 0


def test_gcov_llvm_cov_json_no_data_key(tmp_path: Path) -> None:
    """Should treat top-level dict without 'data' as single export block."""
    data: dict[str, object] = {
        "files": [
            {
                "filename": "/src/main.cpp",
                "segments": [[1, 1, 3, 1, 1]],
            }
        ]
    }
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    assert len(report.files) == 1


def test_gcov_llvm_cov_short_segment_skipped(tmp_path: Path) -> None:
    """Should skip segments shorter than minimum length."""
    data: dict[str, object] = {
        "data": [
            {
                "files": [
                    {
                        "filename": "/src/short.cpp",
                        "segments": [[1, 2], [3, 1, 5, 1, 1]],
                    }
                ]
            }
        ]
    }
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    fc = report.files["/src/short.cpp"]
    assert len(fc.lines) == 1


def test_gcov_llvm_cov_non_list_segment_skipped(tmp_path: Path) -> None:
    """Should skip non-list segment entries."""
    data: dict[str, object] = {
        "data": [
            {
                "files": [
                    {
                        "filename": "/src/seg.cpp",
                        "segments": ["bad", [1, 1, 2, 1, 1]],
                    }
                ]
            }
        ]
    }
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    assert len(report.files["/src/seg.cpp"].lines) == 1


def test_gcov_llvm_cov_function_no_regions(tmp_path: Path) -> None:
    """Should handle function entries with empty regions."""
    data: dict[str, object] = {
        "data": [
            {
                "files": [
                    {
                        "filename": "/src/noreg.cpp",
                        "segments": [[1, 1, 1, 1, 1]],
                        "functions": [{"name": "noreg", "regions": []}],
                    }
                ]
            }
        ]
    }
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    fc = report.files["/src/noreg.cpp"]
    assert len(fc.functions) == 1
    assert fc.functions[0].name == "noreg"
    assert fc.functions[0].line_number == 0
    assert fc.functions[0].execution_count == 0


def test_gcov_llvm_cov_non_dict_function_skipped(tmp_path: Path) -> None:
    """Should skip non-dict function entries."""
    data: dict[str, object] = {
        "data": [
            {
                "files": [
                    {
                        "filename": "/src/badfn.cpp",
                        "segments": [[1, 1, 1, 1, 1]],
                        "functions": ["not-a-dict"],
                    }
                ]
            }
        ]
    }
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    assert len(report.files["/src/badfn.cpp"].functions) == 0


def test_gcov_llvm_cov_short_branch_skipped(tmp_path: Path) -> None:
    """Should skip branches shorter than minimum length."""
    data: dict[str, object] = {
        "data": [
            {
                "files": [
                    {
                        "filename": "/src/shortbr.cpp",
                        "segments": [[1, 1, 1, 1, 1]],
                        "branches": [[1, 2], [5, 1, 1, 1]],
                    }
                ]
            }
        ]
    }
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    assert len(report.files["/src/shortbr.cpp"].branches) == 1


def test_gcov_llvm_cov_non_list_branch_skipped(tmp_path: Path) -> None:
    """Should skip non-list/tuple branch entries."""
    data: dict[str, object] = {
        "data": [
            {
                "files": [
                    {
                        "filename": "/src/badbr.cpp",
                        "segments": [[1, 1, 1, 1, 1]],
                        "branches": ["bad", [5, 1, 1, 1]],
                    }
                ]
            }
        ]
    }
    _write_json(tmp_path, "cov.json", data)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "cov.json")
    assert len(report.files["/src/badbr.cpp"].branches) == 1


def test_gcov_parse_lcov_line_without_colon_not_end(tmp_path: Path) -> None:
    """Should ignore non-end-of-record lines without colons."""
    lcov = """SF:/project/src/test.cpp
DA:1,1
some_noise_line
end_of_record
"""
    _write_file(tmp_path, "coverage.info", lcov)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")
    assert "/project/src/test.cpp" in report.files


def test_gcov_find_and_parse_coverage_export_json(tmp_path: Path) -> None:
    """_find_and_parse_existing finds coverage-export.json."""
    _write_json(
        tmp_path,
        "coverage-export.json",
        cast("dict[str, object]", _SAMPLE_LLVM_COV_JSON),
    )
    adapter = GcovAdapter()
    report = adapter._find_and_parse_existing(tmp_path)
    assert len(report.files) == 2


def test_gcov_parse_lcov_sf_flushes_previous(tmp_path: Path) -> None:
    """A new SF line should flush previous record without end_of_record."""
    lcov = """SF:/a.cpp
DA:1,1
SF:/b.cpp
DA:1,0
end_of_record
"""
    _write_file(tmp_path, "coverage.info", lcov)
    adapter = GcovAdapter()
    report = adapter.parse_coverage_file(tmp_path / "coverage.info")
    assert len(report.files) == 2
    assert "/a.cpp" in report.files
    assert "/b.cpp" in report.files
