"""Kotest adapter — detection, prompt generation, execution, and validation.

Implements ``TestFrameworkAdapter`` for Kotlin projects using Kotest.
Kotlin compiles to the JVM; tests run via Gradle or Maven (same execution
path as JUnit 5).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.adapters.base import (
    CaseResult,
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)
from nit.llm.prompts.kotest_prompt import KotestTemplate

if TYPE_CHECKING:
    from pathlib import Path

# ── Constants ────────────────────────────────────────────────────

_TEST_PATTERNS = [
    "**/*Test.kt",
    "**/*Spec.kt",
    "**/*Tests.kt",
]

_DEFAULT_TIMEOUT = 180.0

_KOTLIN_LANGUAGE = "kotlin"

# Gradle/Maven build file names
_GRADLE_BUILD_NAMES = ("build.gradle", "build.gradle.kts")
_GRADLE_SETTINGS_NAMES = ("settings.gradle", "settings.gradle.kts")
_GRADLE_WRAPPER_NAMES = ("gradlew", "gradlew.bat")
_MAVEN_POM = "pom.xml"

# JUnit XML parsing (same format as GTest / Gradle / Maven output)
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


# ── Adapter ──────────────────────────────────────────────────────


class KotestAdapter(TestFrameworkAdapter):
    """Kotest framework adapter for Kotlin projects.

    Detection is via io.kotest in Gradle/Maven deps or ``import io.kotest``
    in .kt files. Execution uses Gradle (``./gradlew test``) or Maven
    (``mvn test``); Kotest runs on JUnit 5 on the JVM.
    """

    @property
    def name(self) -> str:
        return "kotest"

    @property
    def language(self) -> str:
        return _KOTLIN_LANGUAGE

    def detect(self, project_path: Path) -> bool:
        """Return ``True`` when the project uses Kotest.

        Checks Gradle/Maven build files for io.kotest, or .kt source files
        for ``import io.kotest``.
        """
        if _has_kotest_in_gradle(project_path):
            return True
        if _has_kotest_in_maven(project_path):
            return True
        return _has_kotest_import_in_kt_files(project_path)

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    def get_prompt_template(self) -> KotestTemplate:
        return KotestTemplate()

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> RunResult:
        """Execute Kotest via Gradle or Maven and parse JUnit XML output."""
        if _has_gradle(project_path):
            return await _run_gradle_tests(project_path, test_files, timeout)
        if _has_maven(project_path):
            return await _run_maven_tests(project_path, test_files, timeout)
        return RunResult(
            raw_output="No Gradle or Maven build found; cannot run Kotest.",
            success=False,
        )

    def validate_test(self, _test_code: str) -> ValidationResult:
        """Kotlin is not in tree-sitter supported languages; skip syntax check.

        Returns valid=True so generation can proceed. Full validation happens
        at run time when tests are executed via Gradle/Maven.
        """
        return ValidationResult(valid=True)


# ── Detection helpers ────────────────────────────────────────────


def _has_kotest_in_gradle(project_path: Path) -> bool:
    for name in _GRADLE_BUILD_NAMES:
        path = project_path / name
        if path.is_file():
            try:
                if "io.kotest" in path.read_text(encoding="utf-8", errors="replace"):
                    return True
            except OSError:
                continue
    for name in _GRADLE_SETTINGS_NAMES:
        path = project_path / name
        if path.is_file():
            try:
                if "io.kotest" in path.read_text(encoding="utf-8", errors="replace"):
                    return True
            except OSError:
                continue
    return False


def _has_kotest_in_maven(project_path: Path) -> bool:
    pom = project_path / _MAVEN_POM
    if not pom.is_file():
        return False
    try:
        return "kotest" in pom.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False


def _has_kotest_import_in_kt_files(project_path: Path) -> bool:
    for path in project_path.rglob("*.kt"):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.parts):
            continue
        try:
            if "import io.kotest" in path.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def _has_gradle(project_path: Path) -> bool:
    return any((project_path / name).is_file() for name in _GRADLE_WRAPPER_NAMES) or any(
        (project_path / name).is_file() for name in _GRADLE_BUILD_NAMES
    )


def _has_maven(project_path: Path) -> bool:
    return (project_path / _MAVEN_POM).is_file()


# ── Execution helpers ────────────────────────────────────────────


async def _run_gradle_tests(
    project_path: Path,
    test_files: list[Path] | None,
    timeout: float,
) -> RunResult:
    gradlew = project_path / "gradlew"
    if not gradlew.is_file():
        gradlew = project_path / "gradlew.bat"
    if not gradlew.is_file():
        return RunResult(
            raw_output="gradlew not found; run from project root or add Gradle wrapper.",
            success=False,
        )
    cmd = [str(gradlew), "test", "-q", "--no-daemon"]
    if test_files:
        # Gradle: filter by test class/file; approximate with test name pattern
        for p in test_files:
            stem = p.stem
            if stem:
                cmd.extend(["--tests", f"*{stem}*"])
    result = await _run_command(cmd, cwd=project_path, timeout=timeout)
    raw = _format_output(cmd, result)
    xml_dir = project_path / "build" / "test-results"
    parsed = _collect_junit_xml(xml_dir, raw)
    parsed.raw_output = raw
    parsed.success = (
        parsed.failed == 0 and parsed.errors == 0 and (parsed.total > 0 or result.returncode == 0)
    )
    return parsed


async def _run_maven_tests(
    project_path: Path,
    test_files: list[Path] | None,
    timeout: float,
) -> RunResult:
    cmd = ["mvn", "test", "-q"]
    if test_files:
        # Maven: -Dtest=ClassName for each; approximate with file stem
        test_arg = ",".join(p.stem for p in test_files if p.stem)
        if test_arg:
            cmd.extend(["-Dtest", test_arg])
    result = await _run_command(cmd, cwd=project_path, timeout=timeout)
    raw = _format_output(cmd, result)
    xml_dir = project_path / "target" / "surefire-reports"
    parsed = _collect_junit_xml(xml_dir, raw)
    parsed.raw_output = raw
    parsed.success = (
        parsed.failed == 0 and parsed.errors == 0 and (parsed.total > 0 or result.returncode == 0)
    )
    return parsed


def _collect_junit_xml(xml_dir: Path, raw_output: str) -> RunResult:
    """Glob JUnit XML under *xml_dir* and merge into one RunResult."""
    aggregate = RunResult(raw_output=raw_output)
    if not xml_dir.is_dir():
        return aggregate
    xml_files = list(xml_dir.rglob("*.xml"))
    for xml_path in xml_files:
        try:
            text = xml_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parsed = _parse_junit_xml(text, raw_output)
        aggregate.passed += parsed.passed
        aggregate.failed += parsed.failed
        aggregate.skipped += parsed.skipped
        aggregate.errors += parsed.errors
        aggregate.duration_ms += parsed.duration_ms
        aggregate.test_cases.extend(parsed.test_cases)
    if aggregate.test_cases:
        aggregate.success = aggregate.failed == 0 and aggregate.errors == 0
    return aggregate


def _parse_junit_xml(xml_text: str, raw_output: str) -> RunResult:
    """Parse JUnit-style XML (Gradle/Maven) into RunResult."""
    result = RunResult(raw_output=raw_output)
    for testcase_match in _XML_TESTCASE_REGEX.finditer(xml_text):
        attrs = _parse_xml_attrs(testcase_match.group("attrs"))
        body = testcase_match.group("body") or ""
        classname = attrs.get("classname", "")
        name = attrs.get("name", "unknown")
        full_name = f"{classname}.{name}" if classname else name
        duration_ms = _parse_duration_ms(attrs.get("time", 0.0))
        failure_match = _XML_FAILURE_REGEX.search(body)
        error_match = _XML_ERROR_REGEX.search(body)
        has_skipped = "<skipped" in body
        status_attr = (attrs.get("status") or "").lower()
        if failure_match is not None:
            status = CaseStatus.FAILED
            failure_message = _xml_failure_message(failure_match)
            result.failed += 1
        elif error_match is not None:
            status = CaseStatus.ERROR
            failure_message = _xml_failure_message(error_match)
            result.errors += 1
        elif has_skipped or status_attr in {"notrun", "disabled", "skipped"}:
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


def _parse_xml_attrs(attrs_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _XML_ATTR_REGEX.finditer(attrs_text):
        out[m.group("name")] = m.group("value")
    return out


def _xml_failure_message(match: re.Match[str]) -> str:
    attrs = _parse_xml_attrs(match.group("attrs"))
    msg = attrs.get("message", "")
    body = match.group("body").strip()
    if msg and body:
        return f"{msg}\n{body}"
    return msg or body


def _parse_duration_ms(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value) * 1000.0
    if not isinstance(value, str):
        return 0.0
    text = value.strip().lower()
    try:
        if text.endswith("ms"):
            return float(text[:-2])
        if text.endswith("s"):
            return float(text[:-1]) * 1000.0
        return float(text) * 1000.0
    except ValueError:
        return 0.0


async def _run_command(
    cmd: list[str],
    *,
    cwd: Path,
    timeout: float,
) -> _CommandResult:
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


def _format_output(cmd: list[str], result: _CommandResult) -> str:
    parts = [f"$ {' '.join(cmd)}", f"exit_code={result.returncode}"]
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(result.stderr)
    return "\n".join(parts)


@dataclass
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    not_found: bool = False
