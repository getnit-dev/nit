"""PIT (PITest) mutation testing adapter for Java projects.

PIT is the standard mutation testing tool for Java and JVM languages.  It
integrates with Maven and Gradle via plugins and produces XML reports.  This
adapter detects PIT in ``pom.xml`` or ``build.gradle``, runs the appropriate
build command, and parses the XML output into the unified
``MutationTestReport``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from defusedxml import ElementTree
from defusedxml.ElementTree import ParseError as DefusedParseError

from nit.adapters.mutation.base import (
    MutationTestingAdapter,
    MutationTestReport,
    SurvivingMutant,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 300.0


class PitestAdapter(MutationTestingAdapter):
    """PIT mutation testing adapter for Java projects.

    Detects PIT via ``pom.xml`` or ``build.gradle`` configuration, runs the
    appropriate Maven or Gradle command, and parses the XML report.
    """

    @property
    def name(self) -> str:
        """Return the adapter identifier."""
        return "pitest"

    @property
    def language(self) -> str:
        """Return the primary language."""
        return "java"

    def detect(self, project_root: Path) -> bool:
        """Return True if PIT is configured in *project_root*.

        Checks ``pom.xml`` and ``build.gradle`` for PIT plugin declarations.
        """
        pom = project_root / "pom.xml"
        if pom.is_file():
            try:
                content = pom.read_text(encoding="utf-8")
                if "pitest" in content.lower():
                    return True
            except OSError:
                pass

        for gradle_file in ("build.gradle", "build.gradle.kts"):
            gradle = project_root / gradle_file
            if gradle.is_file():
                try:
                    content = gradle.read_text(encoding="utf-8")
                    if "pitest" in content.lower():
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
        """Run PIT and return a unified mutation test report.

        Detects whether the project uses Maven or Gradle and runs the
        corresponding PIT command.

        Args:
            project_root: Root of the Java project.
            source_files: Optional source file filter (passed via targetClasses).
            timeout: Maximum seconds to wait.

        Returns:
            Parsed ``MutationTestReport``.
        """
        if (project_root / "pom.xml").is_file():
            return await self._run_maven(project_root, source_files=source_files, timeout=timeout)
        if (project_root / "build.gradle").is_file() or (
            project_root / "build.gradle.kts"
        ).is_file():
            return await self._run_gradle(project_root, source_files=source_files, timeout=timeout)

        logger.warning("No Maven or Gradle build file found in %s", project_root)
        return MutationTestReport(tool=self.name)

    async def _run_maven(
        self,
        project_root: Path,
        *,
        source_files: list[str] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> MutationTestReport:
        """Run PIT via Maven.

        Args:
            project_root: Root of the Maven project.
            source_files: Optional target classes filter.
            timeout: Maximum seconds to wait.

        Returns:
            Parsed ``MutationTestReport``.
        """
        cmd = ["mvn", "org.pitest:pitest-maven:mutationCoverage"]
        if source_files:
            target_classes = ",".join(source_files)
            cmd.append(f"-DtargetClasses={target_classes}")

        return await self._execute_and_parse(cmd, project_root, timeout)

    async def _run_gradle(
        self,
        project_root: Path,
        *,
        source_files: list[str] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> MutationTestReport:
        """Run PIT via Gradle.

        Args:
            project_root: Root of the Gradle project.
            source_files: Optional target classes filter.
            timeout: Maximum seconds to wait.

        Returns:
            Parsed ``MutationTestReport``.
        """
        cmd = ["./gradlew", "pitest"]
        if source_files:
            target_classes = ",".join(source_files)
            cmd.append(f"-PtargetClasses={target_classes}")

        return await self._execute_and_parse(cmd, project_root, timeout)

    async def _execute_and_parse(
        self,
        cmd: list[str],
        project_root: Path,
        timeout: float,
    ) -> MutationTestReport:
        """Execute a build command and parse the resulting PIT XML report.

        Args:
            cmd: Command to execute.
            project_root: Root of the project.
            timeout: Maximum seconds to wait.

        Returns:
            Parsed ``MutationTestReport``.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            logger.warning("PIT timed out after %s seconds", timeout)
            return MutationTestReport(tool=self.name)
        except FileNotFoundError:
            logger.warning("Build tool not found for command: %s", cmd[0])
            return MutationTestReport(tool=self.name)

        report_path = self._find_report(project_root)
        if report_path is None:
            logger.warning("PIT XML report not found under %s", project_root)
            return MutationTestReport(tool=self.name)

        return self._parse_report(report_path)

    @staticmethod
    def _find_report(project_root: Path) -> Path | None:
        """Locate the PIT XML report under *project_root*.

        Args:
            project_root: Root of the project.

        Returns:
            Path to the ``mutations.xml`` file, or ``None``.
        """
        # Maven default: target/pit-reports/<timestamp>/mutations.xml
        target_dir = project_root / "target" / "pit-reports"
        if target_dir.is_dir():
            for xml in sorted(target_dir.rglob("mutations.xml"), reverse=True):
                return xml

        # Gradle default: build/reports/pitest/mutations.xml
        build_dir = project_root / "build" / "reports" / "pitest"
        if build_dir.is_dir():
            for xml in sorted(build_dir.rglob("mutations.xml"), reverse=True):
                return xml

        return None

    @staticmethod
    def _parse_report(report_path: Path) -> MutationTestReport:
        """Parse a PIT XML mutations report into unified format.

        Args:
            report_path: Path to the ``mutations.xml`` file.

        Returns:
            Parsed ``MutationTestReport``.
        """
        killed = 0
        survived = 0
        timed_out = 0
        total = 0
        surviving: list[SurvivingMutant] = []

        try:
            tree = ElementTree.parse(report_path)
        except (DefusedParseError, OSError) as exc:
            logger.error("Failed to parse PIT report %s: %s", report_path, exc)
            return MutationTestReport(tool="pitest")

        root = tree.getroot()
        for mutation_elem in root.iter("mutation"):
            total += 1
            detected = mutation_elem.get("detected", "false").lower() == "true"
            status = mutation_elem.get("status", "")

            if detected:
                killed += 1
            elif status == "TIMED_OUT":
                timed_out += 1
            else:
                survived += 1
                file_name = ""
                line_number = 0
                mutator = ""
                description = ""

                src_file_elem = mutation_elem.find("sourceFile")
                if src_file_elem is not None and src_file_elem.text:
                    file_name = src_file_elem.text

                line_elem = mutation_elem.find("lineNumber")
                if line_elem is not None and line_elem.text:
                    with contextlib.suppress(ValueError):
                        line_number = int(line_elem.text)

                mutator_elem = mutation_elem.find("mutator")
                if mutator_elem is not None and mutator_elem.text:
                    mutator = mutator_elem.text

                desc_elem = mutation_elem.find("description")
                if desc_elem is not None and desc_elem.text:
                    description = desc_elem.text

                surviving.append(
                    SurvivingMutant(
                        file_path=file_name,
                        line_number=line_number,
                        original_code="",
                        mutated_code="",
                        mutation_operator=mutator,
                        description=description,
                    )
                )

        score = (killed / total * 100.0) if total > 0 else 0.0

        return MutationTestReport(
            tool="pitest",
            total_mutants=total,
            killed=killed,
            survived=survived,
            timed_out=timed_out,
            mutation_score=score,
            surviving_mutants=surviving,
        )
