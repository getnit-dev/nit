"""xUnit adapter — detection, prompt generation, execution, and validation.

Implements ``TestFrameworkAdapter`` for C#/.NET projects using xUnit with
dotnet test and TRX result format.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from defusedxml import ElementTree
from defusedxml.ElementTree import ParseError as DefusedParseError

from nit.adapters.base import (
    CaseResult,
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)
from nit.adapters.coverage.coverlet_adapter import CoverletAdapter
from nit.llm.prompts.xunit_prompt import XUnitTemplate
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)

if TYPE_CHECKING:
    from pathlib import Path
    from xml.etree.ElementTree import Element as XmlElement


logger = logging.getLogger(__name__)
_CSHARP_LANGUAGE = "csharp"
_DURATION_MS_SCALE = 1000.0
_TRX_TIME_PARTS = 3

# Test file patterns (xUnit convention)
_TEST_PATTERNS = [
    "**/*Tests.cs",
    "**/*Test.cs",
]

_DEFAULT_TIMEOUT = 180.0

# TRX logger output path (relative to project_path)
_TRX_LOG_DIR = "TestResults"
_TRX_LOG_FILE = "nit_results.trx"

# Detection: .csproj with xunit PackageReference or using Xunit in .cs
_CSPROJ_XUNIT_PATTERN = re.compile(
    r'PackageReference\s+Include\s*=\s*["\']([^"\']*xunit[^"\']*)["\']',
    re.IGNORECASE,
)
_XUNIT_IMPORT = re.compile(r"using\s+Xunit\s*;")


@dataclass
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    not_found: bool = False


def _parse_duration(value: object) -> float:
    """Parse TRX duration (e.g. 0:00:01.234) to milliseconds."""
    if isinstance(value, (int, float)):
        return float(value) * _DURATION_MS_SCALE if value < _DURATION_MS_SCALE else float(value)
    if not isinstance(value, str):
        return 0.0
    # TRX duration format: "0:00:00.123456" (hours:minutes:seconds.fraction)
    parts = value.strip().split(":")
    if len(parts) != _TRX_TIME_PARTS:
        try:
            return float(value.strip()) * _DURATION_MS_SCALE
        except ValueError:
            return 0.0
    try:
        hours = float(parts[0])
        minutes = float(parts[1])
        sec_frac = parts[2]
        seconds = float(sec_frac)
        total_sec = hours * 3600 + minutes * 60 + seconds
        return total_sec * _DURATION_MS_SCALE
    except ValueError:
        return 0.0


def _outcome_to_status(outcome: str) -> CaseStatus:
    """Map TRX outcome string to CaseStatus."""
    if outcome == "Passed":
        return CaseStatus.PASSED
    if outcome in ("Failed", "Error"):
        return CaseStatus.FAILED
    if outcome in ("NotExecuted", "Skipped", "Ignored"):
        return CaseStatus.SKIPPED
    return CaseStatus.ERROR


def _extract_failure_message(elem: XmlElement) -> str:
    """Extract failure message from UnitTestResult Output/ErrorInfo or Message."""

    def local_tag(e: XmlElement) -> str:
        return e.tag.split("}")[-1] if "}" in e.tag else e.tag

    for child in elem:
        if local_tag(child) == "Output":
            for out_child in child:
                if local_tag(out_child) != "ErrorInfo":
                    continue
                for sub in out_child.iter():
                    if local_tag(sub) == "Message" and sub.text:
                        return sub.text.strip()
                for sub in out_child.iter():
                    if local_tag(sub) == "StackTrace" and sub.text:
                        return sub.text.strip()
                return ""
        if local_tag(child) == "Message" and child.text:
            return child.text.strip()
    return ""


def _parse_trx(trx_path: Path, raw_output: str) -> RunResult:
    """Parse TRX XML into RunResult."""
    result = RunResult(raw_output=raw_output)
    try:
        tree = ElementTree.parse(trx_path)
    except (DefusedParseError, OSError):
        return result

    root = tree.getroot()
    for elem in root.iter():
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local != "UnitTestResult":
            continue

        test_name = elem.get("testName", "unknown")
        outcome = (elem.get("outcome") or "").strip()
        duration_ms = _parse_duration(elem.get("duration", "0"))
        failure_message = _extract_failure_message(elem)
        status = _outcome_to_status(outcome)

        result.passed += 1 if status == CaseStatus.PASSED else 0
        result.failed += 1 if status == CaseStatus.FAILED else 0
        result.skipped += 1 if status == CaseStatus.SKIPPED else 0
        result.errors += 1 if status == CaseStatus.ERROR else 0
        result.test_cases.append(
            CaseResult(
                name=test_name,
                status=status,
                duration_ms=duration_ms,
                failure_message=failure_message,
                file_path=elem.get("computerName", ""),
            )
        )
        result.duration_ms += duration_ms

    result.success = result.failed == 0 and result.errors == 0 and result.total > 0
    return result


async def _run_command(cmd: list[str], *, cwd: Path, timeout: float) -> _CommandResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        return _CommandResult(
            returncode=1,
            stdout="",
            stderr=f"Command timed out after {timeout:.1f}s",
            timed_out=True,
        )
    except FileNotFoundError:
        return _CommandResult(
            returncode=127,
            stdout="",
            stderr=f"Command not found: {cmd[0]}",
            not_found=True,
        )

    return _CommandResult(
        returncode=proc.returncode if proc.returncode is not None else 1,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
    )


def _has_xunit_csproj(project_path: Path) -> bool:
    for path in project_path.rglob("*.csproj"):
        if path.name.startswith("."):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            if _CSPROJ_XUNIT_PATTERN.search(content):
                return True
        except OSError:
            continue
    return False


def _has_xunit_import(project_path: Path) -> bool:
    for path in project_path.rglob("*.cs"):
        if path.name.startswith("."):
            continue
        try:
            snippet = path.read_text(encoding="utf-8", errors="replace")[:8192]
            if _XUNIT_IMPORT.search(snippet):
                return True
        except OSError:
            continue
    return False


def _has_test_files(project_path: Path) -> bool:
    return any(any(project_path.glob(p)) for p in _TEST_PATTERNS)


def _find_sln_or_csproj(project_path: Path) -> Path | None:
    """Return path to a .sln or test .csproj to run dotnet test from."""
    sln = next(project_path.glob("*.sln"), None)
    if sln is not None:
        return sln
    # Prefer test project
    for path in project_path.rglob("*.csproj"):
        if path.name.startswith("."):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            if _CSPROJ_XUNIT_PATTERN.search(content):
                return path
        except OSError:
            continue
    return next(project_path.glob("*.csproj"), None)


class XUnitAdapter(TestFrameworkAdapter):
    """xUnit adapter for C#/.NET projects using dotnet test and TRX output."""

    @property
    def name(self) -> str:
        return "xunit"

    @property
    def language(self) -> str:
        return _CSHARP_LANGUAGE

    def detect(self, project_path: Path) -> bool:
        """Return True when the project uses xUnit (.csproj or using Xunit)."""
        return _has_xunit_csproj(project_path) or (
            _has_xunit_import(project_path) and _has_test_files(project_path)
        )

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    def get_prompt_template(self) -> XUnitTemplate:
        return XUnitTemplate()

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        collect_coverage: bool = True,
    ) -> RunResult:
        """Execute tests via dotnet test and parse TRX report.

        Optionally collects coverage using CoverletAdapter.
        """
        target = _find_sln_or_csproj(project_path)
        if target is None:
            return RunResult(
                raw_output="No .sln or .csproj found",
                success=False,
            )

        log_dir = project_path / _TRX_LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        trx_path = log_dir / _TRX_LOG_FILE
        logger_arg = f"trx;LogFileName={_TRX_LOG_DIR}/{_TRX_LOG_FILE}"

        cmd = ["dotnet", "test", str(target), "--logger", logger_arg]
        if test_files:
            filters = [p.stem for p in test_files if p.suffix == ".cs"]
            if filters:
                # Filter by fully qualified name: dotnet test --filter "FullyQualifiedName~FooTests"
                filter_expr = "|".join(f"FullyQualifiedName~{f}" for f in filters)
                cmd.extend(["--filter", filter_expr])

        cmd_result = await _run_command(cmd, cwd=project_path, timeout=timeout)
        output_parts = [f"$ {' '.join(cmd)}\nexit_code={cmd_result.returncode}"]
        if cmd_result.stdout:
            output_parts.append(cmd_result.stdout)
        if cmd_result.stderr:
            output_parts.append(cmd_result.stderr)
        raw_output = "\n".join(output_parts)

        if cmd_result.timed_out or cmd_result.not_found:
            return RunResult(raw_output=raw_output, success=False)

        if not trx_path.is_file():
            return RunResult(raw_output=raw_output, success=False)

        result = _parse_trx(trx_path, raw_output)

        # Collect coverage if requested
        if collect_coverage:
            try:
                coverage_adapter = CoverletAdapter()
                coverage_report = await coverage_adapter.run_coverage(
                    project_path, test_files=test_files, timeout=timeout
                )
                result.coverage = coverage_report
                logger.info(
                    "Coverage collected: %.1f%% line coverage",
                    coverage_report.overall_line_coverage,
                )
            except Exception as e:
                logger.warning("Failed to collect coverage: %s", e)

        return result

    def validate_test(self, test_code: str) -> ValidationResult:
        """Parse test_code as C# with tree-sitter and report syntax errors."""
        source = test_code.encode("utf-8")
        tree = parse_code(source, _CSHARP_LANGUAGE)
        root = tree.root_node

        if not has_parse_errors(root):
            return ValidationResult(valid=True)

        error_ranges = collect_error_ranges(root)
        errors = [f"Syntax error at line {start}-{end}" for start, end in error_ranges]
        return ValidationResult(valid=False, errors=errors)
