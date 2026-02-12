"""JUnit 5 adapter — detection, prompt generation, execution, and validation.

Implements ``TestFrameworkAdapter`` for Java projects using JUnit 5 (Jupiter)
with Gradle or Maven.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.base import (
    CaseResult,
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)
from nit.adapters.coverage.jacoco import JaCoCoAdapter
from nit.llm.prompts.junit5_prompt import JUnit5Template
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)

logger = logging.getLogger(__name__)

_JAVA_LANGUAGE = "java"

# Test file patterns (JUnit convention)
_TEST_PATTERNS = [
    "**/*Test.java",
    "**/Test*.java",
]

_DEFAULT_TIMEOUT = 180.0

# Detection: Gradle/Maven + JUnit dependency or import
_GRADLE_FILES = ("build.gradle", "build.gradle.kts")
_MAVEN_FILE = "pom.xml"
_JUNIT_PATTERN = re.compile(
    r"junit-jupiter|org\.junit\.jupiter|junit:junit",
    re.IGNORECASE,
)
_JUNIT_IMPORT = re.compile(r"import\s+org\.junit\.jupiter")

# JUnit/Surefire XML (same structure as GTest-style)
_XML_ATTR_REGEX = re.compile(r'(?P<name>[A-Za-z0-9_:-]+)="(?P<value>[^"]*)"')
_XML_TESTCASE_REGEX = re.compile(
    r"<testcase\b(?P<attrs>.*?)(?:(?P<self>\s*/>)|>(?P<body>.*?)</testcase>)",
    flags=re.DOTALL,
)
_XML_FAILURE_REGEX = re.compile(
    r"<failure\b(?P<attrs>[^>]*)>(?P<body>.*?)</failure>",
    flags=re.DOTALL,
)
_XML_ERROR_REGEX = re.compile(
    r"<error\b(?P<attrs>[^>]*)>(?P<body>.*?)</error>",
    flags=re.DOTALL,
)


@dataclass
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    not_found: bool = False


def _parse_xml_attrs(attrs_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _XML_ATTR_REGEX.finditer(attrs_text):
        attrs[match.group("name")] = match.group("value")
    return attrs


def _xml_failure_message(match: re.Match[str]) -> str:
    message_attr = _parse_xml_attrs(match.group("attrs")).get("message", "")
    text = match.group("body").strip()
    if message_attr and text:
        return f"{message_attr}\n{text}"
    if message_attr:
        return message_attr
    return text


def _parse_duration_seconds(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return 0.0
    text = value.strip().lower()
    try:
        if text.endswith("s"):
            return float(text[:-1])
        return float(text)
    except ValueError:
        return 0.0


def _parse_junit_xml(xml_text: str, raw_output: str) -> RunResult:
    """Parse JUnit/Surefire XML into RunResult."""
    result = RunResult(raw_output=raw_output)
    for testcase_match in _XML_TESTCASE_REGEX.finditer(xml_text):
        attrs = _parse_xml_attrs(testcase_match.group("attrs"))
        body = testcase_match.group("body") or ""

        classname = attrs.get("classname", "")
        name = attrs.get("name", "unknown")
        full_name = f"{classname}.{name}" if classname else name

        time_sec = _parse_duration_seconds(attrs.get("time", 0.0))
        duration_ms = time_sec * 1000.0

        failure_match = _XML_FAILURE_REGEX.search(body)
        error_match = _XML_ERROR_REGEX.search(body)
        skipped = "<skipped" in body or "skipped" in attrs.get("status", "").lower()

        if failure_match is not None:
            status = CaseStatus.FAILED
            failure_message = _xml_failure_message(failure_match)
            result.failed += 1
        elif error_match is not None:
            status = CaseStatus.ERROR
            failure_message = _xml_failure_message(error_match)
            result.errors += 1
        elif skipped:
            status = CaseStatus.SKIPPED
            failure_message = ""
            result.skipped += 1
        else:
            status = CaseStatus.PASSED
            failure_message = ""
            result.passed += 1

        result.test_cases.append(
            CaseResult(
                name=full_name,
                status=status,
                duration_ms=duration_ms,
                failure_message=failure_message,
                file_path=attrs.get("file", ""),
            )
        )
        result.duration_ms += duration_ms

    result.success = result.failed == 0 and result.errors == 0 and result.total > 0
    return result


def _has_junit_gradle(project_path: Path) -> bool:
    for name in _GRADLE_FILES:
        path = project_path / name
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                if _JUNIT_PATTERN.search(content):
                    return True
            except OSError:
                pass
    return False


def _has_junit_maven(project_path: Path) -> bool:
    pom = project_path / _MAVEN_FILE
    if not pom.is_file():
        return False
    try:
        content = pom.read_text(encoding="utf-8", errors="replace")
        return bool(_JUNIT_PATTERN.search(content))
    except OSError:
        return False


def _has_junit_import(project_path: Path) -> bool:
    for path in project_path.rglob("*.java"):
        if path.name.startswith("."):
            continue
        try:
            snippet = path.read_text(encoding="utf-8", errors="replace")[:8192]
            if _JUNIT_IMPORT.search(snippet):
                return True
        except OSError:
            continue
    return False


def _has_test_files(project_path: Path) -> bool:
    return any(any(project_path.glob(p)) for p in _TEST_PATTERNS)


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


def _find_surefire_reports(project_path: Path) -> list[Path]:
    """Maven: target/surefire-reports/TEST-*.xml."""
    reports_dir = project_path / "target" / "surefire-reports"
    if not reports_dir.is_dir():
        return []
    return sorted(reports_dir.glob("TEST-*.xml"))


def _find_gradle_test_results(project_path: Path) -> list[Path]:
    """Gradle: build/test-results/test/*.xml (or test/*/TEST-*.xml)."""
    base = project_path / "build" / "test-results"
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.xml") if p.is_file())


async def _run_gradle_tests(
    project_path: Path,
    test_files: list[Path] | None,
    timeout: float,
) -> tuple[str, list[Path]]:
    gradlew = project_path / "gradlew"
    if gradlew.is_file():
        cmd = ["./gradlew", "test"]
    elif (project_path / "gradlew.bat").is_file():
        cmd = ["gradlew.bat", "test"]
    else:
        cmd = ["gradle", "test"]
    if test_files:
        classes = [_path_to_class_name(p, project_path) for p in test_files]
        classes = [c for c in classes if c]
        if classes:
            cmd.extend(["--tests", "|".join(classes)])
    result = await _run_command(cmd, cwd=project_path, timeout=timeout)
    parts = [f"$ {' '.join(cmd)}\nexit_code={result.returncode}"]
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(result.stderr)
    raw_output = "\n".join(parts)
    xml_files = _find_gradle_test_results(project_path) if not result.timed_out else []
    return (raw_output, xml_files)


async def _run_maven_tests(
    project_path: Path,
    test_files: list[Path] | None,
    timeout: float,
) -> tuple[str, list[Path]]:
    cmd = ["mvn", "test", "-q"]
    if test_files:
        names = [p.stem for p in test_files if p.suffix == ".java"]
        if names:
            cmd.extend(["-Dtest=" + ",".join(names)])
    result = await _run_command(cmd, cwd=project_path, timeout=timeout)
    parts = [f"$ {' '.join(cmd)}\nexit_code={result.returncode}"]
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(result.stderr)
    raw_output = "\n".join(parts)
    xml_files = _find_surefire_reports(project_path) if not result.timed_out else []
    return (raw_output, xml_files)


class JUnit5Adapter(TestFrameworkAdapter):
    """JUnit 5 (Jupiter) adapter for Java projects with Gradle or Maven."""

    @property
    def name(self) -> str:
        return "junit5"

    @property
    def language(self) -> str:
        return _JAVA_LANGUAGE

    def detect(self, project_path: Path) -> bool:
        """Return True when the project uses JUnit 5 (Gradle or Maven)."""
        return (
            _has_junit_gradle(project_path)
            or _has_junit_maven(project_path)
            or (_has_junit_import(project_path) and _has_test_files(project_path))
        )

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    def get_prompt_template(self) -> JUnit5Template:
        return JUnit5Template()

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        collect_coverage: bool = True,
    ) -> RunResult:
        """Execute tests via Gradle or Maven and parse XML reports.

        Optionally collects coverage using JaCoCoAdapter.
        """
        if _has_junit_gradle(project_path):
            raw_output, xml_files = await _run_gradle_tests(project_path, test_files, timeout)
        else:
            raw_output, xml_files = await _run_maven_tests(project_path, test_files, timeout)

        if not xml_files:
            return RunResult(raw_output=raw_output, success=False)

        aggregate = RunResult(raw_output=raw_output)
        for xml_path in xml_files:
            try:
                xml_text = xml_path.read_text(encoding="utf-8", errors="replace")
                parsed = _parse_junit_xml(xml_text, raw_output)
                aggregate.passed += parsed.passed
                aggregate.failed += parsed.failed
                aggregate.skipped += parsed.skipped
                aggregate.errors += parsed.errors
                aggregate.duration_ms += parsed.duration_ms
                aggregate.test_cases.extend(parsed.test_cases)
            except OSError:
                continue

        aggregate.success = aggregate.failed == 0 and aggregate.errors == 0 and aggregate.total > 0

        # Collect coverage if requested
        if collect_coverage:
            try:
                coverage_adapter = JaCoCoAdapter()
                coverage_report = await coverage_adapter.run_coverage(
                    project_path, test_files=test_files, timeout=timeout
                )
                aggregate.coverage = coverage_report
                logger.info(
                    "Coverage collected: %.1f%% line coverage",
                    coverage_report.overall_line_coverage,
                )
            except Exception as e:
                logger.warning("Failed to collect coverage: %s", e)

        return aggregate

    def validate_test(self, test_code: str) -> ValidationResult:
        """Parse test_code as Java with tree-sitter and report syntax errors."""
        source = test_code.encode("utf-8")
        tree = parse_code(source, _JAVA_LANGUAGE)
        root = tree.root_node

        if not has_parse_errors(root):
            return ValidationResult(valid=True)

        error_ranges = collect_error_ranges(root)
        errors = [f"Syntax error at line {start}-{end}" for start, end in error_ranges]
        return ValidationResult(valid=False, errors=errors)

    def get_required_packages(self) -> list[str]:
        """Return required packages for JUnit 5."""
        return []  # JUnit is typically managed by Maven/Gradle

    def get_required_commands(self) -> list[str]:
        """Return required commands for JUnit 5."""
        return ["java"]


def _path_to_class_name(path: Path, project_path: Path) -> str:
    """Convert src/test/java/com/example/FooTest.java -> com.example.FooTest."""
    try:
        rel = path.resolve().relative_to(project_path.resolve())
    except ValueError:
        return ""
    parts = list(rel.parts)
    # Remove src/test/java or similar prefix
    if "src" in parts:
        idx = parts.index("src")
        if idx + 1 < len(parts) and parts[idx + 1] == "test":
            parts = parts[idx + 2 :]
        else:
            parts = parts[idx + 1 :]
    if "java" in parts:
        idx = parts.index("java")
        parts = parts[idx + 1 :]
    if not parts:
        return ""
    return ".".join((*parts[:-1], path.stem)) if parts else ""
