"""Go coverage adapter — run ``go test -cover`` and parse cover profile.

Parses the standard Go cover profile format (mode + file:line.column,line.column
numStmts count) into the unified CoverageReport.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from typing import TYPE_CHECKING

from nit.adapters.coverage.base import (
    CoverageAdapter,
    CoverageReport,
    FileCoverage,
    LineCoverage,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_GO_MOD = "go.mod"
_DEFAULT_TIMEOUT = 120.0

# Cover profile: "file:startLine.startCol,endLine.endCol numStmts count"
_COVER_LINE_REGEX = re.compile(r"^(.+?):(\d+)\.\d+,(\d+)\.\d+\s+(\d+)\s+(\d+)\s*$")


# ── Adapter ──────────────────────────────────────────────────────


class GoCoverAdapter(CoverageAdapter):
    """Go coverage adapter using ``go test -coverprofile``."""

    @property
    def name(self) -> str:
        return "go_cover"

    @property
    def language(self) -> str:
        return "go"

    def detect(self, project_path: Path) -> bool:
        """Return True when go.mod exists (Go project)."""
        return (project_path / _GO_MOD).is_file()

    async def run_coverage(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CoverageReport:
        """Run ``go test -coverprofile=... ./...`` and parse the profile."""
        profile_path = project_path / "coverage.out"
        if test_files:
            pkgs = set()
            for f in test_files:
                if f.suffix != ".go":
                    continue
                try:
                    rel = f.parent.relative_to(project_path)
                    pkgs.add("." if not rel.parts else f"./{rel}")
                except ValueError, TypeError:
                    continue
            pkg_list = sorted(pkgs) if pkgs else ["./..."]
        else:
            pkg_list = ["./..."]
        cmd = ["go", "test", "-coverprofile=coverage.out", *pkg_list]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            logger.warning("go test -cover timed out after %.1fs", timeout)
            return CoverageReport()
        except FileNotFoundError:
            logger.error("go not found")
            return CoverageReport()

        if profile_path.is_file():
            report = self.parse_coverage_file(profile_path)
            with contextlib.suppress(OSError):
                profile_path.unlink()
            return report

        return CoverageReport()

    def parse_coverage_file(self, coverage_file: Path) -> CoverageReport:
        """Parse a Go cover profile file into CoverageReport.

        Format: first line "mode: set" or "mode: count", then one line per block:
        file:startLine.startCol,endLine.endCol numStmts count
        """
        try:
            text = coverage_file.read_text(encoding="utf-8")
        except OSError as e:
            logger.error("Failed to read coverage file %s: %s", coverage_file, e)
            return CoverageReport()

        files: dict[str, FileCoverage] = {}
        # file path -> line number -> execution count (max over blocks)
        file_lines: dict[str, dict[int, int]] = {}

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("mode:"):
                continue
            match = _COVER_LINE_REGEX.match(line)
            if not match:
                continue
            file_path, start_line_s, end_line_s, _num_stmts, count_s = match.groups()
            start_line = int(start_line_s)
            end_line = int(end_line_s)
            count = int(count_s)

            if file_path not in file_lines:
                file_lines[file_path] = {}
            for ln in range(start_line, end_line + 1):
                file_lines[file_path][ln] = max(file_lines[file_path].get(ln, 0), count)

        for file_path, line_counts in file_lines.items():
            lines = [
                LineCoverage(line_number=ln, execution_count=line_counts[ln])
                for ln in sorted(line_counts.keys())
            ]
            files[file_path] = FileCoverage(file_path=file_path, lines=lines)

        return CoverageReport(files=files)
