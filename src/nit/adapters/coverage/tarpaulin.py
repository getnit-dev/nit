"""Tarpaulin coverage adapter for Rust projects.

Runs ``cargo tarpaulin --out Lcov`` and parses the LCOV .info format
into the unified CoverageReport.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.adapters.coverage.base import (
    BranchCoverage,
    CoverageAdapter,
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    LineCoverage,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_CARGO_TOML = "Cargo.toml"
_DEFAULT_TIMEOUT = 120.0
_LCOV_OUTPUT_NAME = "lcov.info"

# LCOV record keys
_LCOV_SF = "SF"
_LCOV_FN = "FN"
_LCOV_FNDA = "FNDA"
_LCOV_DA = "DA"
_LCOV_BRDA = "BRDA"
_LCOV_END = "end_of_record"
_LCOV_DA_PARTS = 2
_LCOV_BRDA_PARTS = 4


@dataclass
class _LcovRecordState:
    path: str | None
    fns: list[tuple[int, str]]
    fnda: dict[str, int]
    da: dict[int, int]
    brda: list[tuple[int, int, int, int]]


# ── Adapter ──────────────────────────────────────────────────────


class TarpaulinAdapter(CoverageAdapter):
    """Rust coverage adapter using cargo-tarpaulin with LCOV output."""

    @property
    def name(self) -> str:
        return "tarpaulin"

    @property
    def language(self) -> str:
        return "rust"

    def detect(self, project_path: Path) -> bool:
        """Return True when Cargo.toml exists (Rust project)."""
        return (project_path / _CARGO_TOML).is_file()

    async def run_coverage(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CoverageReport:
        """Run ``cargo tarpaulin --out Lcov`` and parse the generated LCOV file.

        test_files is accepted for API compatibility but not used; tarpaulin
        runs full project coverage.
        """
        _ = test_files
        out_path = project_path / _LCOV_OUTPUT_NAME
        cmd = ["cargo", "tarpaulin", "--out", "Lcov", "-o", str(out_path)]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            logger.warning("cargo tarpaulin timed out after %.1fs", timeout)
            return CoverageReport()
        except FileNotFoundError:
            logger.error("cargo not found — is Rust installed? Is cargo-tarpaulin installed?")
            return CoverageReport()

        if out_path.is_file():
            report = self.parse_coverage_file(out_path)
            with contextlib.suppress(OSError):
                out_path.unlink()
            return report

        return CoverageReport()

    def parse_coverage_file(self, coverage_file: Path) -> CoverageReport:
        """Parse an LCOV-format file (e.g. from tarpaulin --out Lcov) into CoverageReport."""
        try:
            text = coverage_file.read_text(encoding="utf-8")
        except OSError as e:
            logger.error("Failed to read coverage file %s: %s", coverage_file, e)
            return CoverageReport()

        return self._parse_lcov_string(text)

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

    def _flush_lcov_record(
        self,
        files: dict[str, FileCoverage],
        state: _LcovRecordState,
    ) -> None:
        if state.path is None:
            return
        files[state.path] = self._build_file_coverage(
            state.path, state.fns, state.fnda, state.da, state.brda
        )

    def _apply_lcov_key(self, key: str, value: str, state: _LcovRecordState) -> _LcovRecordState:
        next_state = state
        if key == _LCOV_FN:
            match = re.match(r"^(\d+),\s*(.*)$", value)
            if match:
                next_state = _LcovRecordState(
                    state.path,
                    [*state.fns, (int(match.group(1)), match.group(2).strip())],
                    state.fnda,
                    state.da,
                    state.brda,
                )
        elif key == _LCOV_FNDA:
            match = re.match(r"^(\d+),\s*(.*)$", value)
            if match:
                next_state = _LcovRecordState(
                    state.path,
                    state.fns,
                    {**state.fnda, match.group(2).strip(): int(match.group(1))},
                    state.da,
                    state.brda,
                )
        elif key == _LCOV_DA:
            parts = value.split(",")
            if len(parts) >= _LCOV_DA_PARTS:
                try:
                    ln = int(parts[0].strip())
                    cnt = int(parts[1].strip())
                    next_state = _LcovRecordState(
                        state.path, state.fns, state.fnda, {**state.da, ln: cnt}, state.brda
                    )
                except ValueError:
                    pass
        elif key == _LCOV_BRDA:
            parts = value.split(",")
            if len(parts) >= _LCOV_BRDA_PARTS:
                try:
                    ln = int(parts[0].strip())
                    blk = int(parts[1].strip())
                    br = int(parts[2].strip())
                    taken_s = parts[3].strip()
                    taken = 0 if taken_s == "-" else int(taken_s)
                    next_state = _LcovRecordState(
                        state.path,
                        state.fns,
                        state.fnda,
                        state.da,
                        [*state.brda, (ln, blk, br, taken)],
                    )
                except ValueError:
                    pass
        return next_state

    def _build_file_coverage(
        self,
        file_path: str,
        fns: list[tuple[int, str]],
        fnda: dict[str, int],
        da: dict[int, int],
        brda: list[tuple[int, int, int, int]],
    ) -> FileCoverage:
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
