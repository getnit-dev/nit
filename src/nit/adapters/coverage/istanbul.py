"""Istanbul/c8 coverage adapter for JavaScript/TypeScript projects.

Istanbul is the de facto standard coverage tool for JS/TS. It's built into
Vitest and Jest, and can also be used standalone via c8.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.coverage.base import (
    BranchCoverage,
    CoverageAdapter,
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    LineCoverage,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_CONFIG_GLOBS = ("vitest.config.*", "vitest.workspace.*", "jest.config.*")

# Coverage file locations (Istanbul standard paths)
_COVERAGE_PATHS = [
    "coverage/coverage-final.json",
    ".nyc_output/coverage-final.json",
]

_DEFAULT_TIMEOUT = 120.0


# ── Adapter ──────────────────────────────────────────────────────


class IstanbulAdapter(CoverageAdapter):
    """Istanbul coverage adapter for JavaScript/TypeScript.

    Supports running coverage via:
    - Vitest's built-in coverage (uses c8/Istanbul under the hood)
    - Jest with Istanbul reporter
    - Standalone c8

    Parses Istanbul's JSON coverage format into unified CoverageReport.
    """

    # ── Identity ─────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "istanbul"

    @property
    def language(self) -> str:
        return "typescript"

    # ── Detection ────────────────────────────────────────────────

    def detect(self, project_path: Path) -> bool:
        """Return True if Istanbul/c8 coverage is available.

        Checks for:
        - Vitest or Jest config files
        - package.json with vitest/jest/c8 in devDependencies
        - Existing coverage output files
        """
        # Check for test framework config files
        for glob_pattern in _CONFIG_GLOBS:
            if list(project_path.glob(glob_pattern)):
                return True

        # Check package.json for coverage-capable test frameworks
        package_json_path = project_path / "package.json"
        if package_json_path.exists():
            try:
                with package_json_path.open() as f:
                    pkg = json.load(f)
                    dev_deps = pkg.get("devDependencies", {})
                    deps = pkg.get("dependencies", {})
                    all_deps = {**dev_deps, **deps}
                    # Look for test frameworks or standalone coverage tools
                    coverage_tools = {"vitest", "jest", "c8", "@vitest/coverage-v8"}
                    if any(tool in all_deps for tool in coverage_tools):
                        return True
            except json.JSONDecodeError, OSError:
                pass

        # Check for existing coverage files
        return any((project_path / coverage_path).exists() for coverage_path in _COVERAGE_PATHS)

    # ── Coverage execution ───────────────────────────────────────

    async def run_coverage(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CoverageReport:
        """Run coverage collection via Vitest or Jest.

        Args:
            project_path: Root of the project.
            test_files: Specific test files to run (not all tools support this).
            timeout: Maximum seconds to wait.

        Returns:
            Unified CoverageReport.
        """
        # Determine which test runner to use
        if _has_vitest(project_path):
            return await self._run_vitest_coverage(project_path, test_files, timeout)
        if _has_jest(project_path):
            return await self._run_jest_coverage(project_path, test_files, timeout)
        msg = f"No supported test runner found in {project_path}"
        raise RuntimeError(msg)

    async def _run_vitest_coverage(
        self,
        project_path: Path,
        test_files: list[Path] | None,
        timeout: float,
    ) -> CoverageReport:
        """Run Vitest with coverage enabled."""
        cmd = ["npx", "vitest", "run", "--coverage"]
        if test_files:
            # Add specific test files to the command
            cmd.extend(str(f) for f in test_files)

        logger.info("Running Vitest coverage: %s", " ".join(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except TimeoutError:
            logger.warning("Vitest coverage timed out after %.1fs", timeout)
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        except Exception as e:
            logger.error("Failed to run Vitest coverage: %s", e)

        # Parse the generated coverage file
        return self._find_and_parse_coverage(project_path)

    async def _run_jest_coverage(
        self,
        project_path: Path,
        test_files: list[Path] | None,
        timeout: float,
    ) -> CoverageReport:
        """Run Jest with coverage enabled."""
        cmd = ["npx", "jest", "--coverage"]
        if test_files:
            cmd.extend(str(f) for f in test_files)

        logger.info("Running Jest coverage: %s", " ".join(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except TimeoutError:
            logger.warning("Jest coverage timed out after %.1fs", timeout)
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        except Exception as e:
            logger.error("Failed to run Jest coverage: %s", e)

        return self._find_and_parse_coverage(project_path)

    def _find_and_parse_coverage(self, project_path: Path) -> CoverageReport:
        """Find and parse the coverage JSON file."""
        for coverage_path in _COVERAGE_PATHS:
            full_path = project_path / coverage_path
            if full_path.exists():
                return self.parse_coverage_file(full_path)

        # No coverage file found - return empty report
        logger.warning("No coverage file found in %s", project_path)
        return CoverageReport()

    # ── Coverage parsing ─────────────────────────────────────────

    def parse_coverage_file(self, coverage_file: Path) -> CoverageReport:
        """Parse Istanbul JSON coverage format into unified report.

        Istanbul format:
        {
          "/path/to/file.ts": {
            "path": "/path/to/file.ts",
            "statementMap": { "0": {...}, "1": {...} },
            "fnMap": { "0": {...}, "1": {...} },
            "branchMap": { "0": {...}, "1": {...} },
            "s": { "0": 1, "1": 0, ... },  // statement hit counts
            "f": { "0": 1, "1": 0, ... },  // function hit counts
            "b": { "0": [1, 0], ... }       // branch hit counts [taken, not taken]
          }
        }
        """
        try:
            with coverage_file.open() as f:
                istanbul_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to parse coverage file %s: %s", coverage_file, e)
            return CoverageReport()

        files: dict[str, FileCoverage] = {}

        for file_path, file_data in istanbul_data.items():
            files[file_path] = self._parse_file_coverage(file_path, file_data)

        return CoverageReport(files=files)

    def _parse_file_coverage(self, file_path: str, data: dict[str, Any]) -> FileCoverage:
        """Parse coverage data for a single file."""
        lines = self._parse_line_coverage(data)
        functions = self._parse_function_coverage(data)
        branches = self._parse_branch_coverage(data)

        return FileCoverage(
            file_path=file_path,
            lines=lines,
            functions=functions,
            branches=branches,
        )

    def _parse_line_coverage(self, data: dict[str, Any]) -> list[LineCoverage]:
        """Extract line coverage from Istanbul statement data."""
        statement_map = data.get("statementMap", {})
        statement_counts = data.get("s", {})

        lines: dict[int, int] = {}

        # Aggregate statement hits by line number
        for stmt_id, count in statement_counts.items():
            stmt_info = statement_map.get(stmt_id, {})
            start = stmt_info.get("start", {})
            line = start.get("line")
            if line is not None:
                lines[line] = lines.get(line, 0) + count

        return [
            LineCoverage(line_number=line_num, execution_count=count)
            for line_num, count in sorted(lines.items())
        ]

    def _parse_function_coverage(self, data: dict[str, Any]) -> list[FunctionCoverage]:
        """Extract function coverage from Istanbul function data."""
        fn_map = data.get("fnMap", {})
        fn_counts = data.get("f", {})

        functions = []
        for fn_id, count in fn_counts.items():
            fn_info = fn_map.get(fn_id, {})
            name = fn_info.get("name", f"anonymous_{fn_id}")
            loc = fn_info.get("loc", {})
            start = loc.get("start", {})
            line = start.get("line", 0)

            functions.append(
                FunctionCoverage(
                    name=name,
                    line_number=line,
                    execution_count=count,
                )
            )

        return functions

    def _parse_branch_coverage(self, data: dict[str, Any]) -> list[BranchCoverage]:
        """Extract branch coverage from Istanbul branch data."""
        branch_map = data.get("branchMap", {})
        branch_counts = data.get("b", {})

        branches = []
        for branch_id, counts in branch_counts.items():
            branch_info = branch_map.get(branch_id, {})
            loc = branch_info.get("loc", {})
            start = loc.get("start", {})
            line = start.get("line", 0)

            # Istanbul branch format: [taken_count1, taken_count2, ...]
            # We track total branches and how many were taken
            if isinstance(counts, list):
                taken = sum(1 for c in counts if c > 0)
                total = len(counts)
                branches.append(
                    BranchCoverage(
                        line_number=line,
                        branch_id=int(branch_id) if branch_id.isdigit() else 0,
                        taken_count=taken,
                        total_count=total,
                    )
                )

        return branches


# ── Helper functions ─────────────────────────────────────────────


def _has_vitest(project_path: Path) -> bool:
    """Check if project uses Vitest."""
    return any(project_path.glob("vitest.config.*"))


def _has_jest(project_path: Path) -> bool:
    """Check if project uses Jest."""
    return any(project_path.glob("jest.config.*"))
