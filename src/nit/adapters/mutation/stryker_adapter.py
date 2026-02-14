"""Stryker mutation testing adapter for JavaScript/TypeScript projects.

Stryker Mutator is the standard mutation testing framework for JavaScript and
TypeScript.  It integrates via ``npx stryker run`` and produces JSON reports.
This adapter detects a Stryker configuration, runs the tool, and parses the
JSON output into the unified ``MutationTestReport``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from nit.adapters.mutation.base import (
    MutationTestingAdapter,
    MutationTestReport,
    SurvivingMutant,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 300.0


class StrykerAdapter(MutationTestingAdapter):
    """Stryker Mutator adapter for JavaScript/TypeScript projects.

    Detects Stryker via configuration files or the ``@stryker-mutator/core``
    dependency in ``package.json``, runs ``npx stryker run --reporters json``,
    and parses the resulting JSON report.
    """

    @property
    def name(self) -> str:
        """Return the adapter identifier."""
        return "stryker"

    @property
    def language(self) -> str:
        """Return the primary language."""
        return "javascript"

    def detect(self, project_root: Path) -> bool:
        """Return True if Stryker is configured in *project_root*.

        Checks for ``stryker.conf.*`` files or ``@stryker-mutator/core`` in
        ``package.json``.
        """
        config_patterns = [
            "stryker.conf.js",
            "stryker.conf.mjs",
            "stryker.conf.cjs",
            "stryker.conf.json",
        ]
        for pattern in config_patterns:
            if (project_root / pattern).is_file():
                return True

        package_json = project_root / "package.json"
        if package_json.is_file():
            try:
                content = package_json.read_text(encoding="utf-8")
                if "@stryker-mutator/core" in content:
                    return True
            except OSError:
                pass

        return False

    async def run_mutation_tests(
        self,
        project_root: Path,
        *,
        source_files: list[str] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> MutationTestReport:
        """Run Stryker and return a unified mutation test report.

        Executes ``npx stryker run --reporters json`` and parses the JSON
        output from ``reports/mutation/mutation.json``.

        Args:
            project_root: Root of the JavaScript/TypeScript project.
            source_files: Optional source file filter (passed via --mutate).
            timeout: Maximum seconds to wait.

        Returns:
            Parsed ``MutationTestReport``.
        """
        cmd = ["npx", "stryker", "run", "--reporters", "json"]
        if source_files:
            mutate_glob = ",".join(source_files)
            cmd.extend(["--mutate", mutate_glob])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            logger.warning("Stryker timed out after %s seconds", timeout)
            return MutationTestReport(tool=self.name)
        except FileNotFoundError:
            logger.warning("npx not found — cannot run Stryker")
            return MutationTestReport(tool=self.name)

        # Parse the JSON report
        report_path = project_root / "reports" / "mutation" / "mutation.json"
        if not report_path.is_file():
            logger.warning("Stryker JSON report not found at %s", report_path)
            return MutationTestReport(tool=self.name)

        return self._parse_report(report_path)

    def _parse_report(self, report_path: Path) -> MutationTestReport:
        """Parse a Stryker JSON report into unified format.

        Args:
            report_path: Path to the ``mutation.json`` file.

        Returns:
            Parsed ``MutationTestReport``.
        """
        try:
            content = report_path.read_text(encoding="utf-8")
            data = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to parse Stryker report %s: %s", report_path, exc)
            return MutationTestReport(tool=self.name)

        killed = 0
        survived = 0
        timed_out = 0
        total = 0
        surviving: list[SurvivingMutant] = []

        files = data.get("files", {})
        for file_path, file_data in files.items():
            for mutant in file_data.get("mutants", []):
                total += 1
                status = mutant.get("status", "")
                if status == "Killed":
                    killed += 1
                elif status == "Survived":
                    survived += 1
                    surviving.append(
                        SurvivingMutant(
                            file_path=file_path,
                            line_number=mutant.get("location", {}).get("start", {}).get("line", 0),
                            original_code=mutant.get("originalLines", ""),
                            mutated_code=mutant.get("mutatedLines", ""),
                            mutation_operator=mutant.get("mutatorName", "Unknown"),
                            description=mutant.get("description", ""),
                        )
                    )
                elif status == "Timeout":
                    timed_out += 1

        score = (killed / total * 100.0) if total > 0 else 0.0

        return MutationTestReport(
            tool=self.name,
            total_mutants=total,
            killed=killed,
            survived=survived,
            timed_out=timed_out,
            mutation_score=score,
            surviving_mutants=surviving,
        )
