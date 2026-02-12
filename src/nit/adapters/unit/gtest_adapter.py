"""Google Test adapter — detection, prompt generation, execution, and validation.

Implements ``TestFrameworkAdapter`` for projects using Google Test
(C/C++ unit test framework).
"""

from __future__ import annotations

import asyncio
import json
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
from nit.llm.prompts.gtest_prompt import GTestTemplate
from nit.parsing.treesitter import (
    collect_error_ranges,
    has_parse_errors,
    parse_code,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

_CMAKE_FILE = "CMakeLists.txt"

_GTEST_CMAKE_PATTERNS = (
    "find_package(GTest",
    "gtest_discover_tests",
    "target_link_libraries",
)

_GTEST_INCLUDE_REGEX = re.compile(r'#include\s*[<"]gtest/gtest\.h[>"]')

_TEST_PATTERNS = [
    "**/*_test.cpp",
    "**/*_test.cc",
]

_DEFAULT_TIMEOUT = 180.0

_CPP_LANGUAGE = "cpp"

# Keep the scan targeted to source files where gtest includes may appear.
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

_GTEST_BINARY_PATTERNS = (
    "*test*",
    "*_tests",
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


# ── Adapter ──────────────────────────────────────────────────────


class GTestAdapter(TestFrameworkAdapter):
    """Google Test framework adapter for C/C++ projects."""

    @property
    def name(self) -> str:
        return "gtest"

    @property
    def language(self) -> str:
        return "cpp"

    def detect(self, project_path: Path) -> bool:
        """Return ``True`` when the project likely uses Google Test."""
        if _has_gtest_cmake_patterns(project_path):
            return True
        if _has_gtest_include(project_path):
            return True
        return _has_gtest_test_files(project_path)

    def get_test_pattern(self) -> list[str]:
        return list(_TEST_PATTERNS)

    def get_prompt_template(self) -> GTestTemplate:
        return GTestTemplate()

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        collect_coverage: bool = True,
    ) -> RunResult:
        """Execute Google Test via CMake/CTest, with direct binary fallback."""
        output_parts: list[str] = []

        with tempfile.TemporaryDirectory(prefix="nit_gtest_") as temp_dir:
            report_dir = Path(temp_dir)
            build_dir = _find_cmake_build_dir(project_path)

            # Try CTest first
            ctest_result = await _try_run_via_ctest(
                build_dir, report_dir, test_files, timeout, output_parts
            )
            if ctest_result is not None:
                return ctest_result

            # Fall back to direct binary execution
            discovered = _discover_gtest_binaries(project_path, build_dir)
            binaries = _select_binaries(discovered, test_files)
            aggregate = await _run_direct_gtest_binaries(
                binaries, report_dir, timeout, output_parts
            )

            # Collect coverage if requested
            if collect_coverage:
                await _collect_gtest_coverage(aggregate, project_path, test_files, timeout)

            return aggregate

    def validate_test(self, test_code: str) -> ValidationResult:
        """Parse *test_code* as C++ with tree-sitter and report syntax errors."""
        source = test_code.encode("utf-8")
        tree = parse_code(source, _CPP_LANGUAGE)
        root = tree.root_node

        if not has_parse_errors(root):
            return ValidationResult(valid=True)

        error_ranges = collect_error_ranges(root)
        errors = [f"Syntax error at line {start}-{end}" for start, end in error_ranges]
        return ValidationResult(valid=False, errors=errors)

    def get_required_packages(self) -> list[str]:
        """Return required packages for Google Test."""
        return []  # GTest is typically built and linked via CMake

    def get_required_commands(self) -> list[str]:
        """Return required commands for Google Test."""
        return ["cmake"]


# ── Detection helpers ────────────────────────────────────────────


def _has_gtest_cmake_patterns(project_path: Path) -> bool:
    cmake = project_path / _CMAKE_FILE
    if not cmake.is_file():
        return False

    try:
        content = cmake.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    normalized = content.lower()
    if "gtest" not in normalized:
        return False

    return any(pattern.lower() in normalized for pattern in _GTEST_CMAKE_PATTERNS)


def _has_gtest_include(project_path: Path) -> bool:
    for path in _walk_source_files(project_path):
        if path.suffix.lower() not in _SCAN_EXTENSIONS:
            continue
        try:
            snippet = path.read_text(encoding="utf-8", errors="replace")[:8192]
        except OSError:
            continue
        if _GTEST_INCLUDE_REGEX.search(snippet):
            return True
    return False


def _has_gtest_test_files(project_path: Path) -> bool:
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


# ── Execution helpers ────────────────────────────────────────────


async def _try_run_via_ctest(
    build_dir: Path | None,
    report_dir: Path,
    test_files: list[Path] | None,
    timeout: float,
    output_parts: list[str],
) -> RunResult | None:
    """Try to run tests via CTest. Returns None if CTest is not available."""
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

    parsed = _parse_gtest_xml(
        ctest_report.read_text(encoding="utf-8", errors="replace"),
        "\n\n".join(output_parts),
    )
    parsed.success = parsed.failed == 0 and parsed.errors == 0 and ctest_result.returncode == 0
    return parsed


async def _run_direct_gtest_binaries(
    binaries: list[Path],
    report_dir: Path,
    timeout: float,
    output_parts: list[str],
) -> RunResult:
    """Run Google Test binaries directly."""

    if not binaries:
        output_parts.append("No Google Test binaries found for direct execution.")
        return RunResult(raw_output="\n\n".join(output_parts), success=False)

    aggregate = RunResult(raw_output="")
    for idx, binary in enumerate(binaries):
        xml_report = report_dir / f"gtest-{idx}.xml"
        cmd = [str(binary), f"--gtest_output=xml:{xml_report}"]
        cmd_result = await _run_command(cmd, cwd=binary.parent, timeout=timeout)
        output_parts.append(_format_command_output(cmd, cmd_result))

        if cmd_result.timed_out:
            aggregate.errors += 1
            continue

        if xml_report.is_file():
            parsed = _parse_gtest_xml(
                xml_report.read_text(encoding="utf-8", errors="replace"),
                "\n\n".join(output_parts),
            )
            _merge_run_results(aggregate, parsed)

    aggregate.raw_output = "\n\n".join(output_parts)
    aggregate.success = aggregate.failed == 0 and aggregate.errors == 0 and aggregate.total > 0
    return aggregate


async def _collect_gtest_coverage(
    aggregate: RunResult,
    project_path: Path,
    test_files: list[Path] | None,
    timeout: float,
) -> None:
    """Collect coverage for Google Test execution."""
    try:
        coverage_adapter = GcovAdapter()
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


def _find_cmake_build_dir(project_path: Path) -> Path | None:
    # Prefer explicit build directories.
    for dirname in _BUILD_DIR_CANDIDATES:
        candidate = project_path / dirname
        if _looks_like_cmake_build_dir(candidate):
            return candidate

    # If root already contains CMake cache artifacts, treat it as build dir.
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


def _discover_gtest_binaries(project_path: Path, build_dir: Path | None) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []

    search_roots: list[Path] = []
    if build_dir is not None:
        search_roots.append(build_dir)
    search_roots.append(project_path)

    for root in search_roots:
        for pattern in _GTEST_BINARY_PATTERNS:
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
    return path.stat().st_mode & 0o111 != 0


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


# ── Output parsing (XML / JSON) ──────────────────────────────────


def _parse_gtest_xml(xml_text: str, raw_output: str) -> RunResult:
    """Parse Google Test XML/JUnit output into a ``RunResult``."""
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

        status_attr = attrs.get("status", "run").lower()
        if failure_match is not None:
            status = CaseStatus.FAILED
            failure_message = _xml_failure_message_from_match(failure_match)
            result.failed += 1
        elif error_match is not None:
            status = CaseStatus.ERROR
            failure_message = _xml_failure_message_from_match(error_match)
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


def _parse_gtest_json(json_text: str, raw_output: str) -> RunResult:
    """Parse Google Test JSON output into a ``RunResult``."""
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        return RunResult(raw_output=raw_output, success=False)

    if not isinstance(payload, dict):
        return RunResult(raw_output=raw_output, success=False)

    result = RunResult(raw_output=raw_output)
    test_cases = _collect_json_test_cases(payload)
    for test_case in test_cases:
        result.test_cases.append(test_case)
        result.duration_ms += test_case.duration_ms

        if test_case.status == CaseStatus.PASSED:
            result.passed += 1
        elif test_case.status == CaseStatus.FAILED:
            result.failed += 1
        elif test_case.status == CaseStatus.SKIPPED:
            result.skipped += 1
        else:
            result.errors += 1

    result.success = result.failed == 0 and result.errors == 0 and result.total > 0
    return result


def _collect_json_test_cases(payload: dict[str, object]) -> list[CaseResult]:
    """Collect test cases recursively from Google Test JSON structures."""
    results: list[CaseResult] = []

    def _walk(node: object, *, parents: list[str]) -> None:
        if isinstance(node, list):
            for item in node:
                _walk(item, parents=parents)
            return

        if not isinstance(node, dict):
            return

        current_name = _to_str(node.get("name"))
        next_parents = parents + ([current_name] if current_name else [])

        is_leaf = _looks_like_json_test_case(node)
        if is_leaf:
            status, failure = _json_status_and_failure(node)
            duration = _parse_duration_ms(node.get("time", node.get("duration", 0.0)))
            file_path = _to_str(node.get("file"))
            case_name = ".".join(next_parents) if next_parents else "unknown"
            results.append(
                CaseResult(
                    name=case_name,
                    status=status,
                    duration_ms=duration,
                    failure_message=failure,
                    file_path=file_path,
                )
            )

        for key in ("testsuites", "testsuite", "testcases", "tests", "children"):
            child = node.get(key)
            if child is not None:
                _walk(child, parents=next_parents)

    _walk(payload, parents=[])
    return results


def _looks_like_json_test_case(node: dict[str, object]) -> bool:
    if "status" in node or "result" in node:
        return True
    failures = node.get("failures")
    return bool(isinstance(failures, list))


def _json_status_and_failure(node: dict[str, object]) -> tuple[CaseStatus, str]:
    failures = node.get("failures")
    failure_message = _format_json_failures(failures)

    raw_status = _to_str(node.get("status") or node.get("result")).lower()
    if failure_message or raw_status in {"failed", "failure", "fail"}:
        return (CaseStatus.FAILED, failure_message)
    if raw_status in {"skipped", "notrun", "disabled", "pending"}:
        return (CaseStatus.SKIPPED, "")
    if raw_status in {"passed", "run", "ok", "success"}:
        return (CaseStatus.PASSED, "")
    return (CaseStatus.ERROR, failure_message)


def _format_json_failures(failures: object) -> str:
    if not isinstance(failures, list):
        return ""

    messages: list[str] = []
    for entry in failures:
        if isinstance(entry, str):
            messages.append(entry)
        elif isinstance(entry, dict):
            for key in ("failure", "message", "value"):
                value = entry.get(key)
                if isinstance(value, str) and value:
                    messages.append(value)
                    break
    return "\n".join(messages)


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


def _to_str(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""
