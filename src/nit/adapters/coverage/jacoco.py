"""JaCoCo coverage adapter for Java projects.

JaCoCo is the standard coverage tool for JVM projects. It integrates with
Gradle (jacoco plugin) and Maven (jacoco-maven-plugin) and produces XML reports.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from defusedxml import ElementTree
from defusedxml.ElementTree import ParseError as DefusedParseError

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
    from xml.etree.ElementTree import Element as XmlElement

logger = logging.getLogger(__name__)

# JaCoCo report paths (Gradle: build/reports/jacoco/...; Maven: target/site/jacoco/jacoco.xml)
_JACOCO_PATHS = [
    "build/reports/jacoco/test/jacocoTestReport.xml",
    "build/reports/jacoco/test/jacoco.xml",
    "build/jacoco/test/jacocoTestReport.xml",
    "target/site/jacoco/jacoco.xml",
    "target/jacoco.xml",
]

_DEFAULT_TIMEOUT = 120.0


def _int_attr(element: XmlElement, key: str, default: int = 0) -> int:
    value = element.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _file_path_from_class(package_name: str, class_name: str, source_filename: str) -> str:
    if source_filename:
        return package_name.replace(".", "/") + "/" + source_filename
    return class_name + ".java" if not class_name.endswith(".java") else class_name


def _parse_class_counters(
    class_elem: XmlElement,
) -> tuple[list[FunctionCoverage], list[LineCoverage], list[BranchCoverage]]:
    functions_list: list[FunctionCoverage] = []
    lines_list: list[LineCoverage] = []
    branches_list: list[BranchCoverage] = []
    line_counter_missed = 0
    line_counter_covered = 0

    for counter in class_elem.findall("counter"):
        ctype = counter.get("type", "")
        missed = _int_attr(counter, "missed")
        covered = _int_attr(counter, "covered")
        if ctype == "METHOD":
            functions_list.extend(
                FunctionCoverage(
                    name=f"method_{idx}",
                    line_number=0,
                    execution_count=1 if idx < covered else 0,
                )
                for idx in range(covered + missed)
            )
        elif ctype == "LINE":
            line_counter_missed = missed
            line_counter_covered = covered

    for line_elem in class_elem.findall("line"):
        nr = _int_attr(line_elem, "nr")
        mi = _int_attr(line_elem, "mi")
        ci = _int_attr(line_elem, "ci")
        mb = _int_attr(line_elem, "mb")
        cb = _int_attr(line_elem, "cb")
        execution_count = ci if (mi + ci) > 0 else (0 if mi > 0 else 1)
        lines_list.append(LineCoverage(line_number=nr, execution_count=execution_count))
        if mb + cb > 0:
            branches_list.append(
                BranchCoverage(line_number=nr, branch_id=0, taken_count=cb, total_count=mb + cb)
            )

    if not lines_list and line_counter_missed + line_counter_covered > 0:
        total = line_counter_missed + line_counter_covered
        lines_list.extend(
            LineCoverage(line_number=i + 1, execution_count=1 if i < line_counter_covered else 0)
            for i in range(total)
        )

    return (functions_list, lines_list, branches_list)


def _ensure_functions(
    functions_list: list[FunctionCoverage],
    lines_list: list[LineCoverage],
    class_name: str,
    file_path: str,
) -> None:
    if functions_list or not lines_list:
        return
    covered_any = any(ln.execution_count > 0 for ln in lines_list)
    functions_list.append(
        FunctionCoverage(
            name=class_name.rsplit("/", maxsplit=1)[-1] if class_name else file_path,
            line_number=lines_list[0].line_number if lines_list else 0,
            execution_count=1 if covered_any else 0,
        )
    )


def _parse_jacoco_xml(coverage_file: Path) -> CoverageReport:
    """Parse JaCoCo XML report into unified CoverageReport."""
    files: dict[str, FileCoverage] = {}
    try:
        tree = ElementTree.parse(coverage_file)
    except (DefusedParseError, OSError) as e:
        logger.error("Failed to parse JaCoCo XML %s: %s", coverage_file, e)
        return CoverageReport()

    root = tree.getroot()
    if root.tag != "report":
        logger.warning("JaCoCo XML root is not <report>: %s", root.tag)
        return CoverageReport()

    for package in root.findall(".//package"):
        package_name = package.get("name", "")
        for class_elem in package.findall("class"):
            class_name = class_elem.get("name", "")
            source_filename = class_elem.get("sourcefilename", "")
            file_path = _file_path_from_class(package_name, class_name, source_filename)

            functions_list, lines_list, branches_list = _parse_class_counters(class_elem)
            _ensure_functions(functions_list, lines_list, class_name, file_path)

            if file_path in files:
                existing = files[file_path]
                existing.lines.extend(lines_list)
                existing.functions.extend(functions_list)
                existing.branches.extend(branches_list)
            else:
                files[file_path] = FileCoverage(
                    file_path=file_path,
                    lines=lines_list,
                    functions=functions_list,
                    branches=branches_list,
                )

    return CoverageReport(files=files)


class JaCoCoAdapter(CoverageAdapter):
    """JaCoCo coverage adapter for Java projects.

    Supports parsing JaCoCo XML reports produced by:
    - Gradle JaCoCo plugin
    - Maven jacoco-maven-plugin
    """

    @property
    def name(self) -> str:
        return "jacoco"

    @property
    def language(self) -> str:
        return "java"

    def detect(self, project_path: Path) -> bool:
        """Return True if JaCoCo is configured (Gradle/Maven) or report exists."""
        for name in ("build.gradle", "build.gradle.kts"):
            path = project_path / name
            if path.is_file():
                try:
                    if "jacoco" in path.read_text(encoding="utf-8", errors="replace").lower():
                        return True
                except OSError:
                    pass
        pom = project_path / "pom.xml"
        if pom.is_file():
            try:
                if "jacoco" in pom.read_text(encoding="utf-8", errors="replace").lower():
                    return True
            except OSError:
                pass
        return any((project_path / p).is_file() for p in _JACOCO_PATHS)

    async def run_coverage(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CoverageReport:
        """Run coverage via Gradle or Maven and parse JaCoCo XML."""
        output_path: Path | None = None
        gradlew = project_path / "gradlew"
        if gradlew.is_file():
            cmd = ["./gradlew", "test", "jacocoTestReport"]
            if test_files:
                class_names = [p.stem for p in test_files if p.suffix == ".java"]
                if class_names:
                    cmd.extend(["--tests", "|".join(class_names)])
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
            for candidate in _JACOCO_PATHS:
                p = project_path / candidate
                if p.is_file():
                    output_path = p
                    break
        else:
            cmd = ["mvn", "test", "jacoco:report", "-q"]
            if test_files:
                class_names = [p.stem for p in test_files if p.suffix == ".java"]
                if class_names:
                    cmd.extend(["-Dtest=" + ",".join(class_names)])
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
            for candidate in _JACOCO_PATHS:
                p = project_path / candidate
                if p.is_file():
                    output_path = p
                    break

        if output_path is not None:
            return self.parse_coverage_file(output_path)
        logger.warning("No JaCoCo report found under %s", project_path)
        return CoverageReport()

    def parse_coverage_file(self, coverage_file: Path) -> CoverageReport:
        """Parse JaCoCo XML report into unified CoverageReport."""
        return _parse_jacoco_xml(coverage_file)
