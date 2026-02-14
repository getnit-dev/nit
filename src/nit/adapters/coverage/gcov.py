"""Gcov/lcov/llvm-cov adapter for C/C++ projects.

Supports parsing lcov .info format (from gcov/lcov/geninfo) and llvm-cov
export JSON format into the unified CoverageReport.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nit.adapters.coverage.base import (
    BranchCoverage,
    CoverageAdapter,
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    LineCoverage,
)
from nit.utils.subprocess_runner import run_subprocess

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class _LcovRecordState:
    path: str | None
    fns: list[tuple[int, str]]
    fnda: dict[str, int]
    da: dict[int, int]
    brda: list[tuple[int, int, int, int]]


# ── Constants ────────────────────────────────────────────────────

# Detection: CMake with coverage, gcov/lcov, or existing coverage files
_CMAKE_COVERAGE_PATTERNS = [
    "coverage",
    "Coverage",
    "COVERAGE",
    "gcov",
    "GCOV",
    "lcov",
    "LCOV",
    "code_coverage",
    "CODE_COVERAGE",
]
_COVERAGE_FILE_GLOBS = ["*.info", "*.lcov", "coverage.info", "lcov.info"]
_LLVM_COV_JSON_NAMES = ["coverage.json", "coverage-export.json"]

_DEFAULT_TIMEOUT = 120.0

# LCOV record keys
_LCOV_SF = "SF"
_LCOV_FN = "FN"
_LCOV_FNDA = "FNDA"
_LCOV_DA = "DA"
_LCOV_BRDA = "BRDA"
_LCOV_END = "end_of_record"
_LCOV_DA_PARTS = 2
_LCOV_BRDA_PARTS = 4

# llvm-cov JSON segment/branch indices
_LLVM_SEGMENT_LINE = 0
_LLVM_SEGMENT_COUNT = 2
_LLVM_SEGMENT_MIN_LEN = 3
_LLVM_REGION_COUNT_INDEX = 3
_LLVM_BRANCH_MIN_LEN = 4
_LLVM_BRANCH_TAKEN_INDEX = 3


# ── Adapter ──────────────────────────────────────────────────────


class GcovAdapter(CoverageAdapter):
    """Gcov/lcov/llvm-cov adapter for C/C++ projects.

    Supports:
    - lcov .info format (from gcov + geninfo, or gcovr --lcov)
    - llvm-cov export JSON format

    Parses both into unified CoverageReport.
    """

    # ── Identity ─────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "gcov"

    @property
    def language(self) -> str:
        return "cpp"

    # ── Detection ────────────────────────────────────────────────

    def _detect_cmake_coverage(self, project_path: Path) -> bool:
        for cmake_name in ("CMakeLists.txt", "CMakeLists"):
            cmake_path = project_path / cmake_name
            if cmake_path.exists():
                try:
                    content = cmake_path.read_text()
                    if any(p in content for p in _CMAKE_COVERAGE_PATTERNS):
                        return True
                except OSError:
                    pass
        return False

    def _detect_gcov_or_lcov_files(self, project_path: Path) -> bool:
        if next(project_path.rglob("*.gcno"), None) or next(project_path.rglob("*.gcda"), None):
            return True
        for pattern in _COVERAGE_FILE_GLOBS:
            if pattern.startswith("*"):
                if next(project_path.rglob(pattern), None):
                    return True
            elif (project_path / pattern).exists():
                return True
        return False

    def _detect_llvm_cov_json(self, project_path: Path) -> bool:
        for name in _LLVM_COV_JSON_NAMES:
            if (project_path / name).exists():
                return True
        return any(
            path.name.endswith("coverage.json") or "llvm-cov" in path.name
            for path in project_path.rglob("*.json")
        )

    def detect(self, project_path: Path) -> bool:
        """Return True if gcov/lcov or llvm-cov coverage is available."""
        return (
            self._detect_cmake_coverage(project_path)
            or self._detect_gcov_or_lcov_files(project_path)
            or self._detect_llvm_cov_json(project_path)
        )

    # ── Coverage execution ───────────────────────────────────────

    async def run_coverage(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CoverageReport:
        """Run coverage collection via lcov or llvm-cov when available.

        Tries in order:
        1. lcov --capture -o coverage.info, then parse coverage.info
        2. llvm-cov export (if .profdata/.profraw present)
        3. Parse any existing coverage.info / coverage.json in project_path

        Returns:
            Unified CoverageReport.
        """
        if test_files is not None:
            logger.debug("Filtering by test files not supported for gcov; running all")
        # Try lcov capture (requires lcov installed and .gcda files)
        report = await self._run_lcov_capture(project_path, timeout)
        if report.files:
            return report

        # Try llvm-cov export (requires llvm-cov and profdata)
        report = await self._run_llvm_cov_export(project_path, timeout)
        if report.files:
            return report

        # Fallback: look for existing coverage files
        report = self._find_and_parse_existing(project_path)
        if report.files:
            return report

        logger.warning("No gcov/lcov/llvm-cov coverage file found in %s", project_path)
        return CoverageReport()

    async def _run_lcov_capture(self, project_path: Path, timeout: float) -> CoverageReport:
        """Run lcov --capture and parse output .info file."""
        out_info = project_path / "coverage.info"
        try:
            result = await run_subprocess(
                ["lcov", "--capture", "--directory", ".", "--output-file", str(out_info)],
                cwd=project_path,
                timeout=timeout,
            )
            if result.success and out_info.exists():
                return self.parse_coverage_file(out_info)
        except (FileNotFoundError, ValueError) as e:
            logger.debug("lcov capture not available: %s", e)
        return CoverageReport()

    async def _run_llvm_cov_export(self, project_path: Path, timeout: float) -> CoverageReport:
        """Run llvm-cov export and parse JSON if profdata/profraw exist."""
        profdata = next(project_path.rglob("*.profdata"), None)
        if not profdata:
            return CoverageReport()
        # Search common build directories for binaries instead of scanning everything
        build_dirs = ["build", "cmake-build-debug", "cmake-build-release", "out", "target", "bin"]
        search_roots = [project_path / d for d in build_dirs if (project_path / d).is_dir()]
        if not search_roots:
            search_roots = [project_path]
        for search_root in search_roots:
            for binary in search_root.rglob("*"):
                if not binary.is_file() or binary.suffix not in ("", ".exe"):
                    continue
                try:
                    result = await run_subprocess(
                        [
                            "llvm-cov",
                            "export",
                            str(binary),
                            f"--instr-profile={profdata}",
                        ],
                        cwd=project_path,
                        timeout=timeout,
                    )
                    if result.success and result.stdout.strip():
                        return self._parse_llvm_cov_json_string(result.stdout)
                except (FileNotFoundError, ValueError, json.JSONDecodeError):
                    continue
        return CoverageReport()

    def _find_and_parse_existing(self, project_path: Path) -> CoverageReport:
        """Find and parse existing coverage.info or coverage JSON."""
        for name in ["coverage.info", "lcov.info", "coverage.lcov"]:
            p = project_path / name
            if p.exists():
                return self.parse_coverage_file(p)
        for name in _LLVM_COV_JSON_NAMES:
            p = project_path / name
            if p.exists():
                return self.parse_coverage_file(p)
        for path in project_path.rglob("*.info"):
            return self.parse_coverage_file(path)
        return CoverageReport()

    # ── Coverage parsing ─────────────────────────────────────────

    def parse_coverage_file(self, coverage_file: Path) -> CoverageReport:
        """Parse a coverage file into unified CoverageReport.

        Supports:
        - LCOV .info / .lcov (text): SF, FN, FNDA, DA, BRDA, end_of_record
        - llvm-cov export JSON (Data[].Files[].Segments, etc.)
        """
        if not coverage_file.exists():
            logger.warning("Coverage file does not exist: %s", coverage_file)
            return CoverageReport()

        suffix = coverage_file.suffix.lower()
        if suffix == ".json":
            return self._parse_llvm_cov_file(coverage_file)
        if suffix in (".info", ".lcov") or coverage_file.name.endswith(".info"):
            return self._parse_lcov_file(coverage_file)
        # Try content: JSON vs LCOV text
        try:
            raw = coverage_file.read_text()
            if raw.strip().startswith("{"):
                return self._parse_llvm_cov_json_string(raw)
            return self._parse_lcov_string(raw)
        except OSError as e:
            logger.error("Failed to read coverage file %s: %s", coverage_file, e)
            return CoverageReport()

    def _parse_lcov_file(self, path: Path) -> CoverageReport:
        """Parse LCOV-format file."""
        try:
            return self._parse_lcov_string(path.read_text())
        except OSError as e:
            logger.error("Failed to read LCOV file %s: %s", path, e)
            return CoverageReport()

    def _flush_lcov_record(self, files: dict[str, FileCoverage], state: _LcovRecordState) -> None:
        if state.path is None:
            return
        files[state.path] = self._build_file_coverage_lcov(
            state.path, state.fns, state.fnda, state.da, state.brda
        )

    def _parse_lcov_string(self, content: str) -> CoverageReport:
        """Parse LCOV format text into CoverageReport."""
        files: dict[str, FileCoverage] = {}
        state = _LcovRecordState(None, [], {}, {}, [])

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if ":" not in line:
                if line == _LCOV_END and state.path is not None:
                    self._flush_lcov_record(files, state)
                    state = _LcovRecordState(None, [], {}, {}, [])
                continue
            key, _, value = line.partition(":")
            value = value.strip()
            if key == _LCOV_SF:
                self._flush_lcov_record(files, state)
                state = _LcovRecordState(value, [], {}, {}, [])
            else:
                state = self._apply_lcov_key(key, value, state)

        if state.path is not None:
            self._flush_lcov_record(files, state)
        return CoverageReport(files=files)

    def _apply_lcov_key(self, key: str, value: str, state: _LcovRecordState) -> _LcovRecordState:
        if key == _LCOV_FN:
            match = re.match(r"^(\d+),\s*(.*)$", value)
            if match:
                state = _LcovRecordState(
                    state.path,
                    [*state.fns, (int(match.group(1)), match.group(2).strip())],
                    state.fnda,
                    state.da,
                    state.brda,
                )
            return state
        if key == _LCOV_FNDA:
            match = re.match(r"^(\d+),\s*(.*)$", value)
            if match:
                state = _LcovRecordState(
                    state.path,
                    state.fns,
                    {**state.fnda, match.group(2).strip(): int(match.group(1))},
                    state.da,
                    state.brda,
                )
            return state
        if key == _LCOV_DA:
            parts = value.split(",")
            if len(parts) >= _LCOV_DA_PARTS:
                try:
                    ln = int(parts[0].strip())
                    cnt = int(parts[1].strip())
                    state = _LcovRecordState(
                        state.path, state.fns, state.fnda, {**state.da, ln: cnt}, state.brda
                    )
                except ValueError:
                    pass
            return state
        if key == _LCOV_BRDA:
            parts = value.split(",")
            if len(parts) >= _LCOV_BRDA_PARTS:
                try:
                    ln = int(parts[0].strip())
                    blk = int(parts[1].strip())
                    br = int(parts[2].strip())
                    taken_s = parts[3].strip()
                    taken = 0 if taken_s == "-" else int(taken_s)
                    state = _LcovRecordState(
                        state.path,
                        state.fns,
                        state.fnda,
                        state.da,
                        [*state.brda, (ln, blk, br, taken)],
                    )
                except ValueError:
                    pass
            return state
        return state

    def _build_file_coverage_lcov(
        self,
        file_path: str,
        fns: list[tuple[int, str]],
        fnda: dict[str, int],
        da: dict[int, int],
        brda: list[tuple[int, int, int, int]],
    ) -> FileCoverage:
        """Build FileCoverage from LCOV record data."""
        lines = [
            LineCoverage(line_number=ln, execution_count=cnt) for ln, cnt in sorted(da.items())
        ]
        functions = [
            FunctionCoverage(
                name=name,
                line_number=line,
                execution_count=fnda.get(name, 0),
            )
            for line, name in fns
        ]
        # BranchCoverage: one per BRDA; taken_count 0 or 1, total_count 1
        branches = [
            BranchCoverage(
                line_number=ln,
                branch_id=block * 1000 + branch,
                taken_count=min(1, taken),
                total_count=1,
            )
            for ln, block, branch, taken in brda
        ]
        return FileCoverage(
            file_path=file_path,
            lines=lines,
            functions=functions,
            branches=branches,
        )

    def _parse_llvm_cov_file(self, path: Path) -> CoverageReport:
        """Parse llvm-cov export JSON file."""
        try:
            return self._parse_llvm_cov_json_string(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            logger.error("Failed to parse llvm-cov JSON %s: %s", path, e)
            return CoverageReport()

    def _parse_llvm_cov_json_string(self, content: str) -> CoverageReport:
        """Parse llvm-cov export JSON string into CoverageReport."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON for llvm-cov: %s", e)
            return CoverageReport()
        files: dict[str, FileCoverage] = {}
        # Structure: Data[] -> Files[] with filename, segments, branches, etc.
        data_list = data.get("data", []) if isinstance(data, dict) else []
        if not data_list and isinstance(data, dict) and "data" not in data:
            data_list = [data]
        for export_block in data_list:
            if not isinstance(export_block, dict):
                continue
            for file_info in export_block.get("files", []):
                if not isinstance(file_info, dict):
                    continue
                path = file_info.get("filename")
                if not path:
                    continue
                fc = self._file_coverage_from_llvm_cov(file_info)
                if fc:
                    files[path] = fc
        return CoverageReport(files=files)

    def _file_coverage_from_llvm_cov(self, file_info: dict[str, Any]) -> FileCoverage | None:
        """Build FileCoverage from one file entry in llvm-cov export."""
        path = file_info.get("filename")
        if not path:
            return None
        segments = file_info.get("segments", [])
        # Segment: [line, column, count, hasCount, isRegionEntry] (or similar)
        line_counts: dict[int, int] = {}
        for seg in segments:
            if not isinstance(seg, (list, tuple)) or len(seg) < _LLVM_SEGMENT_MIN_LEN:
                continue
            line_num = int(seg[_LLVM_SEGMENT_LINE])
            count = int(seg[_LLVM_SEGMENT_COUNT]) if len(seg) > _LLVM_SEGMENT_COUNT else 0
            line_counts[line_num] = line_counts.get(line_num, 0) + count
        lines = [
            LineCoverage(line_number=ln, execution_count=cnt)
            for ln, cnt in sorted(line_counts.items())
        ]
        # Functions: expansions or summary; llvm-cov JSON may have "functions" array
        functions = []
        for func in file_info.get("functions", []):
            if not isinstance(func, dict):
                continue
            name = func.get("name", "")
            regions = func.get("regions", [])
            count = 0
            if (
                regions
                and isinstance(regions[0], (list, tuple))
                and len(regions[0]) > _LLVM_REGION_COUNT_INDEX
            ):
                count = int(regions[0][_LLVM_REGION_COUNT_INDEX])
            line_num = int(regions[0][0]) if regions else 0
            functions.append(
                FunctionCoverage(name=name, line_number=line_num, execution_count=count)
            )
        branches = []
        for br in file_info.get("branches", []):
            if not isinstance(br, (list, tuple)) or len(br) < _LLVM_BRANCH_MIN_LEN:
                continue
            line_num = int(br[0])
            taken = int(br[_LLVM_BRANCH_TAKEN_INDEX]) if len(br) > _LLVM_BRANCH_TAKEN_INDEX else 0
            total = 1
            branches.append(
                BranchCoverage(
                    line_number=line_num,
                    branch_id=0,
                    taken_count=taken,
                    total_count=total,
                )
            )
        return FileCoverage(
            file_path=path,
            lines=lines,
            functions=functions,
            branches=branches,
        )
