"""Coverage.py adapter for Python projects.

Coverage.py is the de facto standard coverage tool for Python. It's typically
used via pytest-cov plugin, which integrates seamlessly with pytest.
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

_CONFIG_FILES = ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini")

# Coverage file locations (coverage.py standard paths)
_COVERAGE_PATHS = [
    "coverage.json",
    ".coverage.json",
    "htmlcov/coverage.json",
]

_DEFAULT_TIMEOUT = 120.0

# Branch data minimum length
_MIN_BRANCH_DATA_LENGTH = 2


# ── Adapter ──────────────────────────────────────────────────────


class CoveragePyAdapter(CoverageAdapter):
    """Coverage.py adapter for Python projects.

    Supports running coverage via:
    - pytest-cov plugin (recommended)
    - Standalone coverage.py run

    Parses coverage.py's JSON coverage format into unified CoverageReport.
    """

    # ── Identity ─────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "coverage.py"

    @property
    def language(self) -> str:
        return "python"

    # ── Detection ────────────────────────────────────────────────

    def detect(self, project_path: Path) -> bool:
        """Return True if coverage.py is available.

        Checks for:
        - pytest.ini or pyproject.toml with pytest config
        - requirements.txt or pyproject.toml with pytest-cov/coverage
        - Existing .coverage or coverage.json files
        """
        # Check for pytest config files
        for config_file in _CONFIG_FILES:
            if (project_path / config_file).exists():
                return True

        # Check for pytest or coverage in requirements/pyproject.toml
        requirements_files = [
            "requirements.txt",
            "requirements-dev.txt",
            "dev-requirements.txt",
            "pyproject.toml",
        ]
        for req_file in requirements_files:
            req_path = project_path / req_file
            if req_path.exists():
                try:
                    content = req_path.read_text()
                    if any(tool in content for tool in ["pytest-cov", "coverage", "pytest"]):
                        return True
                except OSError:
                    pass

        # Check for existing coverage files
        if (project_path / ".coverage").exists():
            return True

        return any((project_path / coverage_path).exists() for coverage_path in _COVERAGE_PATHS)

    # ── Coverage execution ───────────────────────────────────────

    async def run_coverage(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CoverageReport:
        """Run coverage collection via pytest-cov.

        Args:
            project_path: Root of the project.
            test_files: Specific test files to run.
            timeout: Maximum seconds to wait.

        Returns:
            Unified CoverageReport.
        """
        # Use pytest-cov to run coverage
        return await self._run_pytest_coverage(project_path, test_files, timeout)

    async def _run_pytest_coverage(
        self,
        project_path: Path,
        test_files: list[Path] | None,
        timeout: float,
    ) -> CoverageReport:
        """Run pytest with coverage enabled via pytest-cov."""
        # Generate JSON report for easier parsing
        coverage_json = project_path / "coverage.json"

        cmd = [
            ".venv/bin/python",
            "-m",
            "pytest",
            "--cov=.",
            "--cov-report=json:coverage.json",
            "--cov-report=term",
        ]

        if test_files:
            # Add specific test files to the command
            cmd.extend(str(f) for f in test_files)

        logger.info("Running pytest coverage: %s", " ".join(cmd))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except TimeoutError:
            logger.warning("pytest coverage timed out after %.1fs", timeout)
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        except Exception as e:
            logger.error("Failed to run pytest coverage: %s", e)

        # Parse the generated coverage file
        if coverage_json.exists():
            return self.parse_coverage_file(coverage_json)

        # Fallback to other locations
        for coverage_path in _COVERAGE_PATHS:
            full_path = project_path / coverage_path
            if full_path.exists():
                return self.parse_coverage_file(full_path)

        # No coverage file found - return empty report
        logger.warning("No coverage file found in %s", project_path)
        return CoverageReport()

    # ── Coverage parsing ─────────────────────────────────────────

    def parse_coverage_file(self, coverage_file: Path) -> CoverageReport:
        """Parse coverage.py JSON format into unified report.

        Coverage.py JSON format:
        {
          "meta": {
            "version": "7.x.x",
            "timestamp": "...",
            "branch_coverage": true
          },
          "files": {
            "src/example.py": {
              "executed_lines": [1, 2, 5, 6],
              "missing_lines": [3, 4],
              "excluded_lines": [],
              "summary": {
                "covered_lines": 4,
                "num_statements": 6,
                "percent_covered": 66.67
              }
            }
          },
          "totals": {...}
        }
        """
        try:
            with coverage_file.open() as f:
                coverage_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to parse coverage file %s: %s", coverage_file, e)
            return CoverageReport()

        files: dict[str, FileCoverage] = {}

        # Parse each file's coverage data
        files_data = coverage_data.get("files", {})
        for file_path, file_data in files_data.items():
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
        """Extract line coverage from coverage.py data."""
        executed_lines = set(data.get("executed_lines", []))
        missing_lines = set(data.get("missing_lines", []))

        # Combine executed and missing lines to get all executable lines
        all_lines = executed_lines | missing_lines

        # Create LineCoverage entries
        lines = []
        for line_num in sorted(all_lines):
            execution_count = 1 if line_num in executed_lines else 0
            lines.append(LineCoverage(line_number=line_num, execution_count=execution_count))

        return lines

    def _parse_function_coverage(self, data: dict[str, Any]) -> list[FunctionCoverage]:
        """Extract function coverage from coverage.py data.

        Note: Standard coverage.py JSON doesn't include function-level data.
        We return an empty list for now. Future enhancement could parse
        from coverage.py's detailed XML or use AST analysis.
        """
        # Coverage.py's JSON format doesn't include function-level coverage
        # This would require additional analysis or using XML format
        functions_data = data.get("functions", {})

        functions = []
        for func_name, func_info in functions_data.items():
            line_number = func_info.get("line_number", 0)
            executed = func_info.get("executed_lines", [])
            execution_count = 1 if executed else 0

            functions.append(
                FunctionCoverage(
                    name=func_name,
                    line_number=line_number,
                    execution_count=execution_count,
                )
            )

        return functions

    def _parse_branch_coverage(self, data: dict[str, Any]) -> list[BranchCoverage]:
        """Extract branch coverage from coverage.py data.

        Coverage.py tracks branches when --cov-branch is used.
        Branch data is in the format:
        "missing_branches": [[line, branch_id], ...]
        """
        # Get executed and missing branches
        missing_branches_data = data.get("missing_branches", [])

        # Build a map of line -> branch counts
        branch_map: dict[int, dict[str, int]] = {}

        for branch_entry in missing_branches_data:
            if isinstance(branch_entry, list) and len(branch_entry) >= _MIN_BRANCH_DATA_LENGTH:
                line_num = branch_entry[0]
                if line_num not in branch_map:
                    branch_map[line_num] = {"total": 0, "taken": 0}
                branch_map[line_num]["total"] += 1

        # Note: Standard JSON format doesn't provide executed branches separately
        # We only know about missing branches, so branch coverage may be incomplete

        branches = []
        for line_num, counts in sorted(branch_map.items()):
            branches.append(
                BranchCoverage(
                    line_number=line_num,
                    branch_id=0,  # coverage.py doesn't provide branch IDs in JSON
                    taken_count=counts["taken"],
                    total_count=counts["total"],
                )
            )

        return branches
