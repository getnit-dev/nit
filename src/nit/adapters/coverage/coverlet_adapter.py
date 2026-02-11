"""Coverlet coverage adapter for C#/.NET projects.

Coverlet is the standard coverage tool for .NET. It integrates with
dotnet test via the coverlet.collector and produces Cobertura XML or
JSON reports. This adapter parses Cobertura XML into the unified format.
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
else:
    XmlElement = ElementTree.Element  # runtime: same type as defusedxml

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120.0


def _int_attr(element: XmlElement, key: str, default: int = 0) -> int:
    value = element.get(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _local_name(elem: XmlElement) -> str:
    return elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag


def _process_line_elem(
    line_elem: XmlElement,
    out_lines: list[LineCoverage],
    out_branches: list[BranchCoverage],
) -> None:
    nr = _int_attr(line_elem, "number")
    hits = _int_attr(line_elem, "hits")
    out_lines.append(LineCoverage(line_number=nr, execution_count=hits))
    if line_elem.get("branch", "false").lower() != "true":
        return
    cond_cover = line_elem.get("condition-coverage", "")
    if "/" not in cond_cover:
        return
    try:
        part = cond_cover.split("(")[-1].split(")")[0]
        taken, total = map(int, part.split("/"))
        out_branches.append(
            BranchCoverage(line_number=nr, branch_id=0, taken_count=taken, total_count=total)
        )
    except (ValueError, IndexError):
        pass


def _process_class_element(
    class_elem: XmlElement,
    package_name: str,
    files: dict[str, FileCoverage],
) -> None:
    """Parse one Cobertura <class> element and merge into *files*."""
    class_name = class_elem.get("name", "")
    filename = class_elem.get("filename", "") or class_name.replace(".", "/") + ".cs"
    file_path = filename
    if package_name and not file_path.startswith(("http", "/")):
        pkg_path = package_name.replace(".", "/")
        file_path = f"{pkg_path}/{file_path}" if pkg_path else file_path

    lines_list: list[LineCoverage] = []
    functions_list: list[FunctionCoverage] = []
    branches_list: list[BranchCoverage] = []

    for child in class_elem:
        tag = _local_name(child)
        if tag == "line":
            _process_line_elem(child, lines_list, branches_list)
        elif tag == "lines":
            for sub in child:
                if _local_name(sub) == "line":
                    _process_line_elem(sub, lines_list, branches_list)

    for method_elem in class_elem:
        if _local_name(method_elem) != "method":
            continue
        method_name = method_elem.get("name", "method")
        sig = method_elem.get("signature", "")
        method_lines = [c for c in method_elem if _local_name(c) == "line"]
        line_num = _int_attr(method_lines[0], "number") if method_lines else 0
        exec_count = _int_attr(method_lines[0], "hits") if method_lines else 0
        functions_list.append(
            FunctionCoverage(
                name=f"{method_name}{sig}" if sig else method_name,
                line_number=line_num,
                execution_count=exec_count,
            )
        )

    if not functions_list and lines_list:
        covered_any = any(ln.execution_count > 0 for ln in lines_list)
        functions_list.append(
            FunctionCoverage(
                name=class_name.rsplit("/", maxsplit=1)[-1] if class_name else file_path,
                line_number=lines_list[0].line_number if lines_list else 0,
                execution_count=1 if covered_any else 0,
            )
        )

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


def _parse_cobertura_xml(coverage_file: Path) -> CoverageReport:
    """Parse Cobertura XML report into unified CoverageReport."""
    files: dict[str, FileCoverage] = {}
    try:
        tree = ElementTree.parse(coverage_file)
    except (DefusedParseError, OSError) as e:
        logger.error("Failed to parse Cobertura XML %s: %s", coverage_file, e)
        return CoverageReport()

    root = tree.getroot()
    if _local_name(root) != "coverage":
        logger.warning("Cobertura XML root is not <coverage>: %s", root.tag)
        return CoverageReport()

    # Cobertura: coverage/packages/package/classes/class (or package/class)
    for package in root.iter():
        if _local_name(package) != "package":
            continue
        package_name = package.get("name", "")
        for class_elem in package.iter():
            if _local_name(class_elem) != "class":
                continue
            _process_class_element(class_elem, package_name, files)

    return CoverageReport(files=files)


def _find_cobertura_report(project_path: Path) -> Path | None:
    """Locate a Cobertura XML report under project_path."""
    candidates = [
        project_path / "coverage.cobertura.xml",
        project_path / "cobertura.xml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    test_results = project_path / "TestResults"
    if test_results.is_dir():
        for p in test_results.rglob("coverage.cobertura.xml"):
            return p
        for p in test_results.rglob("coverage.xml"):
            return p
    return None


class CoverletAdapter(CoverageAdapter):
    """Coverlet coverage adapter for C#/.NET projects.

    Supports parsing Cobertura XML reports produced by:
    - dotnet test --collect:"XPlat Code Coverage"
    - Coverlet.MSBuild / coverlet.collector
    """

    @property
    def name(self) -> str:
        return "coverlet"

    @property
    def language(self) -> str:
        return "csharp"

    def detect(self, project_path: Path) -> bool:
        """Return True if Coverlet is configured or a Cobertura report exists."""
        # Check for coverlet in .csproj
        for path in project_path.rglob("*.csproj"):
            if path.name.startswith("."):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                if "coverlet" in content.lower():
                    return True
            except OSError:
                continue
        return _find_cobertura_report(project_path) is not None

    async def run_coverage(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> CoverageReport:
        """Run coverage via dotnet test with Coverlet collector and parse Cobertura XML.

        Uses dotnet test --collect:"XPlat Code Coverage" which produces
        coverage.cobertura.xml in TestResults when coverlet.collector is referenced.
        """
        sln_or_csproj = next(project_path.glob("*.sln"), None) or next(
            project_path.glob("*.csproj"), None
        )
        if sln_or_csproj is None:
            logger.warning("No .sln or .csproj found under %s", project_path)
            return CoverageReport()

        cmd = [
            "dotnet",
            "test",
            str(sln_or_csproj),
            "--collect:XPlat Code Coverage",
        ]
        if test_files:
            filters = [p.stem for p in test_files if p.suffix == ".cs"]
            if filters:
                filter_expr = "|".join(f"FullyQualifiedName~{f}" for f in filters)
                cmd.extend(["--filter", filter_expr])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            logger.warning("Coverage collection timed out after %s s", timeout)
            return CoverageReport()
        except FileNotFoundError:
            logger.warning("dotnet not found")
            return CoverageReport()

        report_path = _find_cobertura_report(project_path)
        if report_path is not None:
            return self.parse_coverage_file(report_path)
        logger.warning("No Cobertura report found under %s", project_path)
        return CoverageReport()

    def parse_coverage_file(self, coverage_file: Path) -> CoverageReport:
        """Parse a Cobertura XML report into unified format."""
        return _parse_cobertura_xml(coverage_file)
