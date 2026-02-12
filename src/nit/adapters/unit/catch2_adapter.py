"""Catch2 adapter — detection, prompt generation, execution, and validation.

Implements ``TestFrameworkAdapter`` for projects using Catch2
(C/C++ unit test framework).
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from nit.adapters.base import (
    CaseResult,
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)
from nit.adapters.coverage.gcov import GcovAdapter
from nit.llm.prompts.catch2_prompt import Catch2Template
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)

logger = logging.getLogger(__name__)

_CMAKE_FILE = "CMakeLists.txt"

_CATCH2_CMAKE_PATTERNS = (
    "find_package(catch2",
    "catch_discover_tests",
    "catch2::catch2",
    "catch2::catch2withmain",
)

_CATCH2_INCLUDE_REGEX = re.compile(r"""#include\s*[<"](catch2/catch[^">]*|catch\.hpp)[>"]""")

_TEST_PATTERNS = [
    "**/*_test.cpp",
    "**/*_test.cc",
    "**/*.catch2.cpp",
    "**/*_tests.cpp",
]

_DEFAULT_TIMEOUT = 180.0
_CPP_LANGUAGE = "cpp"

_SCAN_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".cpp",
        ".cc",
        ".cxx",
        ".h",
        ".hh",
        ".hpp",
        ".hxx",
    }
)

_BUILD_DIR_CANDIDATES = (
    "build",
    "cmake-build-debug",
    "cmake-build-release",
)

_CATCH2_BINARY_PATTERNS = (
    "*test*",
    "*_tests",
    "*catch2*",
)

_ALL_TESTS_PASSED_RE = re.compile(
    r"All tests passed \(\d+ assertions? in (?P<cases>\d+) test cases?\)",
    flags=re.IGNORECASE,
)

_TEST_SUMMARY_RE = re.compile(
    r"test cases:\s*(?P<total>\d+)\s*\|\s*(?P<passed>\d+)\s*passed\s*\|\s*"
    r"(?P<failed>\d+)\s*failed(?:\s*\|\s*(?P<skipped>\d+)\s*skipped)?",
    flags=re.IGNORECASE,
)

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


class Catch2Adapter(TestFrameworkAdapter):
    """Catch2 framework adapter for C/C++ projects."""

    @property
    def name(self) -> str:
        return "catch2"

    @property
    def language(self) -> str:
        return "cpp"

    def detect(self, project_path: Path) -> bool:
        """Return ``True`` when the project likely uses Catch2."""
        if _has_catch2_cmake_patterns(project_path):
            return True
        if _has_catch2_include(project_path):
            return True
        return _has_catch2_test_files(project_path)

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    def get_prompt_template(self) -> Catch2Template:
        return Catch2Template()

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        collect_coverage: bool = True,
    ) -> RunResult:
        """Execute Catch2 via CMake/CTest, with direct binary fallback.

        Optionally collects coverage using GcovAdapter.
        """
        output_parts: list[str] = []

        with tempfile.TemporaryDirectory(prefix="nit_catch2_") as temp_dir:
            report_dir = Path(temp_dir)
            build_dir = _find_cmake_build_dir(project_path)

            ctest_result = await _run_via_ctest(
                build_dir=build_dir,
                report_dir=report_dir,
                test_files=test_files,
                timeout=timeout,
                output_parts=output_parts,
            )
            if ctest_result is not None:
                return ctest_result

            discovered = _discover_catch2_binaries(project_path, build_dir)
            binaries = _select_binaries(discovered, test_files)
            result = await _run_direct_binaries(
                binaries=binaries,
                report_dir=report_dir,
                timeout=timeout,
                output_parts=output_parts,
            )

            # Collect coverage if requested
            if collect_coverage and result.success:
                try:
                    coverage_adapter = GcovAdapter()
                    coverage_report = await coverage_adapter.run_coverage(
                        project_path, test_files=test_files, timeout=timeout
                    )
                    result.coverage = coverage_report
                except Exception as e:
                    logger.warning("Failed to collect coverage: %s", e)

            return result

    def validate_test(self, test_code: str) -> ValidationResult:
        """Parse *test_code* as C++ with tree-sitter and report syntax errors."""
        source = _normalize_catch2_for_validation(test_code).encode("utf-8")
        tree = parse_code(source, _CPP_LANGUAGE)
        root = tree.root_node

        if not has_parse_errors(root):
            return ValidationResult(valid=True)

        error_ranges = collect_error_ranges(root)
        errors = [f"Syntax error at line {start}-{end}" for start, end in error_ranges]
        return ValidationResult(valid=False, errors=errors)


def _normalize_catch2_for_validation(test_code: str) -> str:
    """Normalize Catch2 macro blocks into parser-friendly C++ for validation."""
    normalized = re.sub(
        r"\bTEST_CASE\s*\([^)]*\)\s*\{",
        "void __nit_test_case() {",
        test_code,
    )
    return re.sub(
        r"\bSECTION\s*\([^)]*\)\s*\{",
        "{",
        normalized,
    )


def _has_catch2_cmake_patterns(project_path: Path) -> bool:
    cmake = project_path / _CMAKE_FILE
    if not cmake.is_file():
        return False

    try:
        content = cmake.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    normalized = content.lower()
    if "catch2" not in normalized:
        return False

    return any(pattern in normalized for pattern in _CATCH2_CMAKE_PATTERNS)


def _has_catch2_include(project_path: Path) -> bool:
    for path in _walk_source_files(project_path):
        if path.suffix.lower() not in _SCAN_EXTENSIONS:
            continue
        try:
            snippet = path.read_text(encoding="utf-8", errors="replace")[:8192]
        except OSError:
            continue
        if _CATCH2_INCLUDE_REGEX.search(snippet):
            return True
    return False


def _has_catch2_test_files(project_path: Path) -> bool:
    return any(any(project_path.glob(pattern)) for pattern in _TEST_PATTERNS)


def _walk_source_files(project_path: Path) -> list[Path]:
    files: list[Path] = []
    for path in project_path.rglob("*"):
        if not path.is_file():
            continue
        if any(part.startswith(".") and part != "." for part in path.parts):
            continue
        files.append(path)
    return files


async def _run_via_ctest(
    *,
    build_dir: Path | None,
    report_dir: Path,
    test_files: list[Path] | None,
    timeout: float,
    output_parts: list[str],
) -> RunResult | None:
    if build_dir is None:
        return None

    ctest_report = report_dir / "ctest-results.xml"

    build_cmd = ["cmake", "--build", ".", "--target", "test"]
    build_result = await _run_command(build_cmd, cwd=build_dir, timeout=timeout)
    output_parts.append(_format_command_output(build_cmd, build_result))
    if build_result.timed_out:
        return RunResult(raw_output="\n\n".join(output_parts), success=False)
    if build_result.not_found:
        return None

    ctest_cmd = [
        "ctest",
        "--output-on-failure",
        "--output-junit",
        str(ctest_report),
    ]
    if test_files:
        regex = _ctest_regex_from_test_files(test_files)
        if regex:
            ctest_cmd.extend(["-R", regex])

    ctest_result = await _run_command(ctest_cmd, cwd=build_dir, timeout=timeout)
    output_parts.append(_format_command_output(ctest_cmd, ctest_result))
    if ctest_result.timed_out:
        return RunResult(raw_output="\n\n".join(output_parts), success=False)

    if not ctest_report.is_file():
        return None

    parsed = _parse_catch2_junit(
        ctest_report.read_text(encoding="utf-8", errors="replace"),
        "\n\n".join(output_parts),
    )
    parsed.success = parsed.failed == 0 and parsed.errors == 0 and ctest_result.returncode == 0
    return parsed


async def _run_direct_binaries(
    binaries: list[Path],
    report_dir: Path,
    timeout: float,
    output_parts: list[str],
) -> RunResult:
    if not binaries:
        output_parts.append("No Catch2 binaries found for direct execution.")
        return RunResult(raw_output="\n\n".join(output_parts), success=False)

    aggregate = RunResult(raw_output="")
    for idx, binary in enumerate(binaries):
        junit_report = report_dir / f"catch2-{idx}.xml"
        cmd = [str(binary), "--reporter", "junit", "--out", str(junit_report)]
        cmd_result = await _run_command(cmd, cwd=binary.parent, timeout=timeout)
        output_parts.append(_format_command_output(cmd, cmd_result))

        if cmd_result.timed_out:
            aggregate.errors += 1
            continue

        if junit_report.is_file():
            parsed = _parse_catch2_junit(
                junit_report.read_text(encoding="utf-8", errors="replace"),
                "\n\n".join(output_parts),
            )
            _merge_run_results(aggregate, parsed)
            continue

        parsed = _parse_catch2_text(
            f"{cmd_result.stdout}\n{cmd_result.stderr}",
            "\n\n".join(output_parts),
        )
        if parsed.total > 0:
            _merge_run_results(aggregate, parsed)
        elif cmd_result.returncode != 0:
            aggregate.errors += 1

    aggregate.raw_output = "\n\n".join(output_parts)
    aggregate.success = aggregate.failed == 0 and aggregate.errors == 0 and aggregate.total > 0

    return aggregate


def _find_cmake_build_dir(project_path: Path) -> Path | None:
    for dirname in _BUILD_DIR_CANDIDATES:
        candidate = project_path / dirname
        if _looks_like_cmake_build_dir(candidate):
            return candidate

    if _looks_like_cmake_build_dir(project_path):
        return project_path

    return None


def _looks_like_cmake_build_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "CMakeCache.txt").is_file():
        return True
    if (path / "CTestTestfile.cmake").is_file():
        return True
    return (path / "Testing").is_dir()


def _discover_catch2_binaries(project_path: Path, build_dir: Path | None) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []

    search_roots: list[Path] = []
    if build_dir is not None:
        search_roots.append(build_dir)
    search_roots.append(project_path)

    for root in search_roots:
        for pattern in _CATCH2_BINARY_PATTERNS:
            for candidate in root.rglob(pattern):
                if not _is_executable_file(candidate):
                    continue
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                ordered.append(resolved)

    return ordered


def _is_executable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() in {".cpp", ".cc", ".cxx", ".h", ".hpp", ".txt", ".cmake"}:
        return False
    return (path.stat().st_mode & 0o111) != 0


def _select_binaries(binaries: list[Path], test_files: list[Path] | None) -> list[Path]:
    if not test_files:
        return binaries

    wanted_names = {test_file.stem.lower() for test_file in test_files}
    filtered = [binary for binary in binaries if binary.stem.lower() in wanted_names]
    return filtered if filtered else binaries


def _ctest_regex_from_test_files(test_files: list[Path]) -> str:
    names = [path.stem for path in test_files if path.stem]
    if not names:
        return ""
    escaped = [re.escape(name) for name in names]
    return "|".join(escaped)


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


def _format_command_output(cmd: list[str], result: _CommandResult) -> str:
    command = " ".join(cmd)
    parts = [f"$ {command}", f"exit_code={result.returncode}"]
    if result.stdout:
        parts.append(result.stdout)
    if result.stderr:
        parts.append(result.stderr)
    return "\n".join(parts)


def _merge_run_results(target: RunResult, source: RunResult) -> None:
    target.passed += source.passed
    target.failed += source.failed
    target.skipped += source.skipped
    target.errors += source.errors
    target.duration_ms += source.duration_ms
    target.test_cases.extend(source.test_cases)


def _parse_catch2_junit(xml_text: str, raw_output: str) -> RunResult:
    """Parse Catch2 JUnit XML output into a ``RunResult``."""
    result = RunResult(raw_output=raw_output)
    matches = list(_XML_TESTCASE_REGEX.finditer(xml_text))
    if not matches:
        return RunResult(raw_output=raw_output, success=False)

    for testcase_match in matches:
        attrs = _parse_xml_attrs(testcase_match.group("attrs"))
        body = testcase_match.group("body") or ""

        classname = attrs.get("classname", "")
        name = attrs.get("name", "unknown")
        full_name = f"{classname}.{name}" if classname else name

        duration_ms = _parse_duration_ms(attrs.get("time", 0.0))

        failure_match = _XML_FAILURE_REGEX.search(body)
        error_match = _XML_ERROR_REGEX.search(body)
        has_skipped = "<skipped" in body

        if failure_match is not None:
            status = CaseStatus.FAILED
            failure_message = _xml_failure_message_from_match(failure_match)
            result.failed += 1
        elif error_match is not None:
            status = CaseStatus.ERROR
            failure_message = _xml_failure_message_from_match(error_match)
            result.errors += 1
        elif has_skipped:
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
    attrs: dict[str, str] = {}
    for match in _XML_ATTR_REGEX.finditer(attrs_text):
        attrs[match.group("name")] = match.group("value")
    return attrs


def _xml_failure_message_from_match(match: re.Match[str]) -> str:
    message_attr = _parse_xml_attrs(match.group("attrs")).get("message", "")
    text = match.group("body").strip()
    if message_attr and text:
        return f"{message_attr}\n{text}"
    if message_attr:
        return message_attr
    return text


def _parse_catch2_text(output: str, raw_output: str) -> RunResult:
    """Parse Catch2 plaintext summary output into a ``RunResult``."""
    result = RunResult(raw_output=raw_output, success=False)

    all_passed = _ALL_TESTS_PASSED_RE.search(output)
    if all_passed is not None:
        result.passed = int(all_passed.group("cases"))
        result.success = result.passed > 0
        return result

    summary = _TEST_SUMMARY_RE.search(output)
    if summary is None:
        return result

    result.passed = int(summary.group("passed"))
    result.failed = int(summary.group("failed"))
    skipped_group = summary.group("skipped")
    result.skipped = int(skipped_group) if skipped_group is not None else 0
    total = int(summary.group("total"))
    if total > result.total:
        result.errors = total - result.total
    result.success = result.failed == 0 and result.errors == 0 and result.total > 0
    return result


def _parse_duration_ms(value: object) -> float:
    if isinstance(value, int | float):
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
