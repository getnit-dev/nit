"""mutmut mutation testing adapter for Python projects.

mutmut is a popular mutation testing tool for Python.  It runs mutations
against the test suite and reports surviving mutants.  This adapter detects
mutmut in project dependencies, runs ``mutmut run`` followed by
``mutmut results``, and parses the output into the unified
``MutationTestReport``.
"""

from __future__ import annotations

import asyncio
import logging
import re
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


class MutmutAdapter(MutationTestingAdapter):
    """mutmut adapter for Python projects.

    Detects mutmut in ``requirements*.txt``, ``setup.cfg``, or
    ``pyproject.toml``, runs ``mutmut run`` then ``mutmut results``, and
    parses the text output.
    """

    @property
    def name(self) -> str:
        """Return the adapter identifier."""
        return "mutmut"

    @property
    def language(self) -> str:
        """Return the primary language."""
        return "python"

    def detect(self, project_root: Path) -> bool:
        """Return True if mutmut is configured in *project_root*.

        Checks ``requirements*.txt``, ``setup.cfg``, and ``pyproject.toml``
        for a ``mutmut`` dependency.
        """
        for req_file in project_root.glob("requirements*.txt"):
            try:
                content = req_file.read_text(encoding="utf-8")
                if "mutmut" in content:
                    return True
            except OSError:
                continue

        setup_cfg = project_root / "setup.cfg"
        if setup_cfg.is_file():
            try:
                content = setup_cfg.read_text(encoding="utf-8")
                if "mutmut" in content:
                    return True
            except OSError:
                pass

        pyproject = project_root / "pyproject.toml"
        if pyproject.is_file():
            try:
                content = pyproject.read_text(encoding="utf-8")
                if "mutmut" in content:
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
        """Run mutmut and return a unified mutation test report.

        Executes ``mutmut run`` then ``mutmut results`` and parses the
        text output.

        Args:
            project_root: Root of the Python project.
            source_files: Optional source file filter (passed via --paths-to-mutate).
            timeout: Maximum seconds to wait.

        Returns:
            Parsed ``MutationTestReport``.
        """
        cmd = ["mutmut", "run", "--no-progress"]
        if source_files:
            cmd.extend(["--paths-to-mutate", ",".join(source_files)])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            logger.warning("mutmut timed out after %s seconds", timeout)
            return MutationTestReport(tool=self.name)
        except FileNotFoundError:
            logger.warning("mutmut not found — cannot run mutation tests")
            return MutationTestReport(tool=self.name)

        return await self._collect_results(project_root, timeout)

    async def _collect_results(self, project_root: Path, timeout: float) -> MutationTestReport:
        """Run ``mutmut results`` and parse the output.

        Args:
            project_root: Root of the Python project.
            timeout: Maximum seconds to wait.

        Returns:
            Parsed ``MutationTestReport``.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "mutmut",
                "results",
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except (TimeoutError, FileNotFoundError) as exc:
            logger.warning("Failed to collect mutmut results: %s", exc)
            return MutationTestReport(tool=self.name)

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        return self._parse_results_output(stdout)

    def _parse_results_output(self, output: str) -> MutationTestReport:
        """Parse the text output of ``mutmut results``.

        Args:
            output: Raw stdout from ``mutmut results``.

        Returns:
            Parsed ``MutationTestReport``.
        """
        killed = 0
        survived = 0
        timed_out = 0
        surviving: list[SurvivingMutant] = []

        killed_match = re.search(r"Killed\s+(\d+)", output, re.IGNORECASE)
        survived_match = re.search(r"Survived\s+(\d+)", output, re.IGNORECASE)
        timeout_match = re.search(r"Timeout\s+(\d+)", output, re.IGNORECASE)

        if killed_match:
            killed = int(killed_match.group(1))
        if survived_match:
            survived = int(survived_match.group(1))
        if timeout_match:
            timed_out = int(timeout_match.group(1))

        total = killed + survived + timed_out

        # Parse individual surviving mutants
        # mutmut results format: "--- file_path ---\n<line>: mutant description"
        current_file = ""
        for line in output.splitlines():
            file_match = re.match(r"^---\s+(.+?)\s+---$", line)
            if file_match:
                current_file = file_match.group(1)
                continue

            mutant_match = re.match(r"^(\d+):\s+(.+)$", line.strip())
            if mutant_match and current_file:
                surviving.append(
                    SurvivingMutant(
                        file_path=current_file,
                        line_number=int(mutant_match.group(1)),
                        original_code="",
                        mutated_code="",
                        mutation_operator="mutmut",
                        description=mutant_match.group(2),
                    )
                )

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
