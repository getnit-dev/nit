"""Tests for the GTestAdapter (adapters/unit/gtest_adapter.py).

Covers detection, prompt template, XML/JSON parsing, execution fallback,
and tree-sitter validation with sample C++ fixtures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from nit.adapters.base import (
    CaseResult,
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
    ValidationResult,
)
from nit.adapters.unit.gtest_adapter import (
    GTestAdapter,
    _CommandResult,
    _ctest_regex_from_test_files,
    _discover_gtest_binaries,
    _find_cmake_build_dir,
    _format_command_output,
    _format_json_failures,
    _has_gtest_cmake_patterns,
    _has_gtest_include,
    _has_gtest_test_files,
    _is_executable_file,
    _json_status_and_failure,
    _looks_like_json_test_case,
    _merge_run_results,
    _parse_duration_ms,
    _parse_gtest_json,
    _parse_gtest_xml,
    _select_binaries,
    _to_str,
)
from nit.llm.prompts.gtest_prompt import GTestTemplate

# ── Helpers ──────────────────────────────────────────────────────


def _make_files(root: Path, rel_paths: list[str]) -> None:
    """Create empty files (with parent directories) under *root*."""
    for rel in rel_paths:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()


def _write_file(root: Path, rel: str, content: str) -> Path:
    """Write *content* to a file under *root* and return its path."""
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


# ── Sample Google Test XML/JSON output ───────────────────────────

_GTEST_XML_ALL_SUCCESS = """\
<testsuites tests="2" failures="0" disabled="0" errors="0" time="0.003">
  <testsuite
    name="MathTest"
    tests="2"
    failures="0"
    disabled="0"
    skipped="0"
    errors="0"
    time="0.003"
  >
    <testcase classname="MathTest" name="AddsNumbers" status="run" time="0.001" />
    <testcase classname="MathTest" name="SubtractsNumbers" status="run" time="0.002" />
  </testsuite>
</testsuites>
"""

_GTEST_XML_WITH_ISSUES = """\
<testsuites tests="3" failures="1" disabled="0" errors="0" time="0.011">
  <testsuite
    name="ParserTest"
    tests="3"
    failures="1"
    disabled="0"
    skipped="1"
    errors="0"
    time="0.011"
  >
    <testcase classname="ParserTest" name="ParsesValid" status="run" time="0.003" />
    <testcase classname="ParserTest" name="RejectsInvalid" status="run" time="0.005">
      <failure message="Expected invalid input to fail">Assertion failed</failure>
    </testcase>
    <testcase classname="ParserTest" name="FeatureFlagged" status="notrun" time="0.000">
      <skipped />
    </testcase>
  </testsuite>
</testsuites>
"""

_GTEST_JSON_MIXED = """\
{
  "name": "AllTests",
  "testsuites": [
    {
      "name": "MathTest",
      "testsuite": [
        {
          "name": "AddsNumbers",
          "status": "RUN",
          "time": "1ms",
          "failures": []
        },
        {
          "name": "RejectsInvalid",
          "status": "RUN",
          "time": "0.002s",
          "failures": [{"failure": "Expected true to be false"}]
        },
        {
          "name": "DisabledCase",
          "status": "DISABLED",
          "time": "0ms",
          "failures": []
        }
      ]
    }
  ]
}
"""

# ── Valid / Invalid C++ samples ──────────────────────────────────

_VALID_CPP = """\
#include <gtest/gtest.h>

int add(int a, int b) {
  return a + b;
}

TEST(MathTest, AddsNumbers) {
  EXPECT_EQ(add(2, 3), 5);
}
"""

_INVALID_CPP = """\
#include <gtest/gtest.h>

TEST(BrokenTest, MissingBrace) {
  EXPECT_EQ(1 + 1, 2);
"""


# ═══════════════════════════════════════════════════════════════════
# Test classes
# ═══════════════════════════════════════════════════════════════════


class TestGTestAdapterIdentity:
    """Basic identity and interface conformance."""

    def test_implements_test_framework_adapter(self) -> None:
        assert isinstance(GTestAdapter(), TestFrameworkAdapter)

    def test_name(self) -> None:
        assert GTestAdapter().name == "gtest"

    def test_language(self) -> None:
        assert GTestAdapter().language == "cpp"


# ── Detection ─────────────────────────────────────────────────────


class TestGTestDetection:
    def test_detect_cmake_find_package(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "find_package(GTest REQUIRED)\n",
        )
        assert GTestAdapter().detect(tmp_path) is True

    def test_detect_cmake_discover_tests(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "gtest_discover_tests(math_test)\n",
        )
        assert GTestAdapter().detect(tmp_path) is True

    def test_detect_include_pattern(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "tests/math_test.cpp", _VALID_CPP)
        assert GTestAdapter().detect(tmp_path) is True

    def test_detect_test_file_pattern(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "tests/logic_test.cc", "int main() { return 0; }\n")
        assert GTestAdapter().detect(tmp_path) is True

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert GTestAdapter().detect(tmp_path) is False


class TestDetectionHelpers:
    def test_has_gtest_cmake_patterns_true(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "target_link_libraries(unit_test PRIVATE GTest::gtest_main)\n",
        )
        assert _has_gtest_cmake_patterns(tmp_path) is True

    def test_has_gtest_cmake_patterns_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "CMakeLists.txt", "project(sample)\n")
        assert _has_gtest_cmake_patterns(tmp_path) is False

    def test_has_gtest_include_true(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "tests/sample_test.cpp", "#include <gtest/gtest.h>\n")
        assert _has_gtest_include(tmp_path) is True

    def test_has_gtest_include_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/main.cpp", "#include <vector>\n")
        assert _has_gtest_include(tmp_path) is False

    def test_has_gtest_test_files_true(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["tests/math_test.cpp"])
        assert _has_gtest_test_files(tmp_path) is True

    def test_has_gtest_test_files_false(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["src/math.cpp"])
        assert _has_gtest_test_files(tmp_path) is False


# ── Test patterns ────────────────────────────────────────────────


class TestGTestPatterns:
    def test_returns_list_of_patterns(self) -> None:
        patterns = GTestAdapter().get_test_pattern()
        assert isinstance(patterns, list)
        assert len(patterns) >= 2

    def test_includes_cpp_pattern(self) -> None:
        patterns = GTestAdapter().get_test_pattern()
        assert "**/*_test.cpp" in patterns

    def test_includes_cc_pattern(self) -> None:
        patterns = GTestAdapter().get_test_pattern()
        assert "**/*_test.cc" in patterns


# ── Prompt template ──────────────────────────────────────────────


class TestGTestPromptTemplate:
    def test_returns_gtest_template(self) -> None:
        template = GTestAdapter().get_prompt_template()
        assert isinstance(template, GTestTemplate)

    def test_template_name(self) -> None:
        template = GTestAdapter().get_prompt_template()
        assert template.name == "gtest"


# ── XML / JSON parsing ───────────────────────────────────────────


class TestGTestXmlParsing:
    def test_parse_all_passing(self) -> None:
        result = _parse_gtest_xml(_GTEST_XML_ALL_SUCCESS, _GTEST_XML_ALL_SUCCESS)
        assert result.success is True
        assert result.passed == 2
        assert result.failed == 0
        assert result.skipped == 0
        assert result.total == 2

    def test_parse_with_failures(self) -> None:
        result = _parse_gtest_xml(_GTEST_XML_WITH_ISSUES, _GTEST_XML_WITH_ISSUES)
        assert result.success is False
        assert result.passed == 1
        assert result.failed == 1
        assert result.skipped == 1
        assert result.total == 3

    def test_failure_message_captured(self) -> None:
        result = _parse_gtest_xml(_GTEST_XML_WITH_ISSUES, _GTEST_XML_WITH_ISSUES)
        failed_cases = [tc for tc in result.test_cases if tc.status == CaseStatus.FAILED]
        assert len(failed_cases) == 1
        assert "Expected invalid input to fail" in failed_cases[0].failure_message

    def test_parse_invalid_xml(self) -> None:
        result = _parse_gtest_xml("<testsuite>", "bad")
        assert result.success is False
        assert result.total == 0


class TestGTestJsonParsing:
    def test_parse_json_mixed_results(self) -> None:
        result = _parse_gtest_json(_GTEST_JSON_MIXED, _GTEST_JSON_MIXED)
        assert result.success is False
        assert result.passed == 1
        assert result.failed == 1
        assert result.skipped == 1
        assert result.total == 3

    def test_parse_json_failure_message(self) -> None:
        result = _parse_gtest_json(_GTEST_JSON_MIXED, _GTEST_JSON_MIXED)
        failed = [tc for tc in result.test_cases if tc.status == CaseStatus.FAILED]
        assert len(failed) == 1
        assert "Expected true to be false" in failed[0].failure_message

    def test_parse_invalid_json(self) -> None:
        result = _parse_gtest_json("not-json", "bad")
        assert result.success is False
        assert result.total == 0


class TestHelpers:
    def test_find_cmake_build_dir(self, tmp_path: Path) -> None:
        build_dir = tmp_path / "build"
        build_dir.mkdir(parents=True)
        _make_files(build_dir, ["CMakeCache.txt"])

        detected = _find_cmake_build_dir(tmp_path)
        assert detected == build_dir

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-only test (shell scripts)")
    def test_discover_gtest_binaries(self, tmp_path: Path) -> None:
        build_dir = tmp_path / "build"
        binary = _write_file(build_dir, "math_test", "#!/bin/sh\nexit 0\n")
        binary.chmod(0o700)

        discovered = _discover_gtest_binaries(tmp_path, build_dir)
        assert binary.resolve() in discovered

    def test_ctest_regex_from_test_files(self, tmp_path: Path) -> None:
        test_file = _write_file(tmp_path, "tests/math_test.cpp", "")
        regex = _ctest_regex_from_test_files([test_file])
        assert "math_test" in regex

    def test_parse_duration_ms_seconds(self) -> None:
        assert _parse_duration_ms("0.5s") == 500.0

    def test_parse_duration_ms_milliseconds(self) -> None:
        assert _parse_duration_ms("12ms") == 12.0


# ── Validation ───────────────────────────────────────────────────


class TestGTestValidation:
    def test_adapter_validate_valid_code(self) -> None:
        result = GTestAdapter().validate_test(_VALID_CPP)
        assert result.valid is True

    def test_adapter_validate_invalid_code(self) -> None:
        result = GTestAdapter().validate_test(_INVALID_CPP)
        assert result.valid is False

    def test_validation_result_type(self) -> None:
        result = GTestAdapter().validate_test(_VALID_CPP)
        assert isinstance(result, ValidationResult)


# ── Run tests fallback ───────────────────────────────────────────


class TestRunTestsFallback:
    @pytest.mark.asyncio
    async def test_run_tests_no_binaries_returns_failure(self, tmp_path: Path) -> None:
        result = await GTestAdapter().run_tests(tmp_path)
        assert result.success is False
        assert "No Google Test binaries found" in result.raw_output


# ── Integration-style sample project ─────────────────────────────


class TestSampleCppProject:
    @pytest.fixture()
    def sample_cpp_project(self, tmp_path: Path) -> Path:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            """\
cmake_minimum_required(VERSION 3.20)
project(sample_cpp)
enable_testing()
find_package(GTest REQUIRED)
add_executable(math_test tests/math_test.cpp)
target_link_libraries(math_test PRIVATE GTest::gtest_main)
gtest_discover_tests(math_test)
""",
        )
        _write_file(tmp_path, "src/math.cpp", "int add(int a, int b) { return a + b; }\n")
        _write_file(tmp_path, "tests/math_test.cpp", _VALID_CPP)
        return tmp_path

    def test_detect_sample_project(self, sample_cpp_project: Path) -> None:
        assert GTestAdapter().detect(sample_cpp_project) is True

    def test_validate_sample_test(self, sample_cpp_project: Path) -> None:
        test_code = (sample_cpp_project / "tests/math_test.cpp").read_text(encoding="utf-8")
        result = GTestAdapter().validate_test(test_code)
        assert result.valid is True

    def test_prompt_template_for_sample(self, sample_cpp_project: Path) -> None:
        template = GTestAdapter().get_prompt_template()
        assert template.name == "gtest"


# ── Additional coverage: missing lines ────────────────────────────


class TestGTestRequiredPackagesAndCommands:
    """Cover get_required_packages and get_required_commands."""

    def test_required_packages_empty(self) -> None:
        assert GTestAdapter().get_required_packages() == []

    def test_required_commands_contains_cmake(self) -> None:
        assert "cmake" in GTestAdapter().get_required_commands()


class TestGTestCmakeDetectionOSError:
    """Cover OSError branch in _has_gtest_cmake_patterns."""

    def test_cmake_no_gtest_keyword(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "CMakeLists.txt", "project(example)\nadd_library(foo)\n")
        assert _has_gtest_cmake_patterns(tmp_path) is False


class TestGTestIncludeEdgeCases:
    """Cover branches in _has_gtest_include."""

    def test_skips_non_source_extensions(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "readme.txt", "#include <gtest/gtest.h>\n")
        assert _has_gtest_include(tmp_path) is False

    def test_skips_hidden_dirs(self, tmp_path: Path) -> None:
        _write_file(tmp_path, ".hidden/test.cpp", "#include <gtest/gtest.h>\n")
        assert _has_gtest_include(tmp_path) is False


class TestGTestFindCmakeBuildDirExtended:
    """Cover more branches of _find_cmake_build_dir."""

    def test_find_cmake_build_debug_dir(self, tmp_path: Path) -> None:
        build = tmp_path / "cmake-build-debug"
        build.mkdir()
        (build / "CTestTestfile.cmake").touch()
        assert _find_cmake_build_dir(tmp_path) == build

    def test_find_cmake_build_release_dir(self, tmp_path: Path) -> None:
        build = tmp_path / "cmake-build-release"
        build.mkdir()
        (build / "Testing").mkdir()
        assert _find_cmake_build_dir(tmp_path) == build

    def test_project_root_as_build_dir(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeCache.txt").touch()
        assert _find_cmake_build_dir(tmp_path) == tmp_path

    def test_returns_none_when_no_build_dir(self, tmp_path: Path) -> None:
        assert _find_cmake_build_dir(tmp_path) is None


class TestGTestIsExecutableFile:
    """Cover _is_executable_file branches."""

    def test_non_file(self, tmp_path: Path) -> None:
        assert _is_executable_file(tmp_path) is False

    def test_source_file_not_executable(self, tmp_path: Path) -> None:
        f = tmp_path / "test.cpp"
        f.write_text("int main() {}")
        f.chmod(0o755)
        assert _is_executable_file(f) is False

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions")
    def test_executable_binary(self, tmp_path: Path) -> None:
        f = tmp_path / "math_test"
        f.write_text("#!/bin/sh\nexit 0\n")
        f.chmod(0o755)
        assert _is_executable_file(f) is True

    def test_non_executable_binary(self, tmp_path: Path) -> None:
        f = tmp_path / "math_test"
        f.write_text("data")
        f.chmod(0o644)
        assert _is_executable_file(f) is False


class TestGTestSelectBinaries:
    """Cover _select_binaries branches."""

    def test_no_test_files_returns_all(self) -> None:
        binaries = [Path("/b/test_a"), Path("/b/test_b")]
        assert _select_binaries(binaries, None) == binaries

    def test_filter_by_stem(self) -> None:
        binaries = [Path("/b/test_a"), Path("/b/test_b")]
        test_files = [Path("/src/test_a.cpp")]
        result = _select_binaries(binaries, test_files)
        assert len(result) == 1
        assert result[0].name == "test_a"

    def test_no_match_returns_all(self) -> None:
        binaries = [Path("/b/test_a")]
        test_files = [Path("/src/no_match.cpp")]
        assert _select_binaries(binaries, test_files) == binaries


class TestGTestCTestRegex:
    """Cover _ctest_regex_from_test_files."""

    def test_empty_list(self) -> None:
        assert _ctest_regex_from_test_files([]) == ""

    def test_multiple_files(self) -> None:
        files = [Path("/a/test_math.cpp"), Path("/b/test_str.cpp")]
        regex = _ctest_regex_from_test_files(files)
        assert "test_math" in regex
        assert "test_str" in regex
        assert "|" in regex


class TestGTestFormatCommandOutput:
    """Cover _format_command_output."""

    def test_format_with_all_parts(self) -> None:
        cr = _CommandResult(returncode=1, stdout="out", stderr="err")
        output = _format_command_output(["cmake", "--build", "."], cr)
        assert "$ cmake --build ." in output
        assert "exit_code=1" in output
        assert "out" in output
        assert "err" in output

    def test_format_without_output(self) -> None:
        cr = _CommandResult(returncode=0, stdout="", stderr="")
        output = _format_command_output(["cmd"], cr)
        assert "exit_code=0" in output


class TestGTestMergeResults:
    """Cover _merge_run_results."""

    def test_merge_accumulates(self) -> None:
        target = RunResult(passed=1, failed=0, skipped=0, errors=0, duration_ms=10)
        source = RunResult(
            passed=2,
            failed=1,
            skipped=1,
            errors=0,
            duration_ms=20,
            test_cases=[
                CaseResult(name="t", status=CaseStatus.PASSED),
            ],
        )
        _merge_run_results(target, source)
        assert target.passed == 3
        assert target.failed == 1
        assert target.skipped == 1
        assert target.duration_ms == 30
        assert len(target.test_cases) == 1


class TestGTestXmlParsingExtended:
    """Cover more XML parsing branches."""

    def test_parse_error_element(self) -> None:
        xml = """\
<testsuites>
  <testsuite>
    <testcase classname="C" name="t1" time="0.001">
      <error message="segfault">core dumped</error>
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_gtest_xml(xml, xml)
        assert result.errors == 1
        assert result.test_cases[0].status == CaseStatus.ERROR
        assert "segfault" in result.test_cases[0].failure_message

    def test_parse_skipped_by_status_attr(self) -> None:
        xml = """\
<testsuites>
  <testsuite>
    <testcase classname="C" name="disabled" status="notrun" time="0">
      <skipped />
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_gtest_xml(xml, xml)
        assert result.skipped == 1
        assert result.test_cases[0].status == CaseStatus.SKIPPED

    def test_parse_no_classname(self) -> None:
        xml = """\
<testsuites>
  <testsuite>
    <testcase name="standalone" time="0.001" status="run" />
  </testsuite>
</testsuites>
"""
        result = _parse_gtest_xml(xml, xml)
        assert result.test_cases[0].name == "standalone"

    def test_parse_failure_only_message_attr(self) -> None:
        xml = """\
<testsuites>
  <testsuite>
    <testcase classname="C" name="f" time="0.001">
      <failure message="only attr"></failure>
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_gtest_xml(xml, xml)
        assert result.test_cases[0].failure_message == "only attr"

    def test_parse_failure_only_body(self) -> None:
        xml = """\
<testsuites>
  <testsuite>
    <testcase classname="C" name="f" time="0.001">
      <failure message="">body text</failure>
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_gtest_xml(xml, xml)
        assert result.test_cases[0].failure_message == "body text"


class TestGTestJsonParsingExtended:
    """Cover more JSON parsing branches."""

    def test_parse_json_non_dict(self) -> None:
        result = _parse_gtest_json("[1, 2, 3]", "raw")
        assert result.success is False

    def test_parse_json_error_status(self) -> None:
        data = json.dumps(
            {
                "testsuites": [
                    {
                        "name": "Suite",
                        "testsuite": [
                            {
                                "name": "crash",
                                "status": "UNKNOWN_STATUS",
                                "time": "0ms",
                            }
                        ],
                    }
                ],
            }
        )
        result = _parse_gtest_json(data, data)
        assert result.errors == 1

    def test_parse_json_passed_status(self) -> None:
        data = json.dumps(
            {
                "testsuites": [
                    {
                        "name": "S",
                        "testsuite": [
                            {"name": "ok", "status": "RUN", "time": "1ms"},
                        ],
                    }
                ],
            }
        )
        result = _parse_gtest_json(data, data)
        assert result.passed == 1
        assert result.success is True

    def test_parse_json_skipped_status(self) -> None:
        data = json.dumps(
            {
                "testsuites": [
                    {
                        "name": "S",
                        "testsuite": [
                            {"name": "skip", "status": "NOTRUN", "time": "0ms"},
                        ],
                    }
                ],
            }
        )
        result = _parse_gtest_json(data, data)
        assert result.skipped == 1

    def test_format_json_failures_string_entries(self) -> None:

        result = _format_json_failures(["error1", "error2"])
        assert "error1" in result
        assert "error2" in result

    def test_format_json_failures_dict_entries(self) -> None:

        result = _format_json_failures([{"failure": "msg1"}, {"message": "msg2"}])
        assert "msg1" in result
        assert "msg2" in result

    def test_format_json_failures_non_list(self) -> None:

        assert _format_json_failures("not a list") == ""
        assert _format_json_failures(None) == ""

    def test_format_json_failures_dict_with_value_key(self) -> None:

        result = _format_json_failures([{"value": "val"}])
        assert result == "val"


class TestGTestDurationParsingExtended:
    """Cover more _parse_duration_ms branches."""

    def test_int_value(self) -> None:
        assert _parse_duration_ms(2) == 2000.0

    def test_float_value(self) -> None:
        assert _parse_duration_ms(0.5) == 500.0

    def test_non_numeric_non_str(self) -> None:
        assert _parse_duration_ms(None) == 0.0
        assert _parse_duration_ms([]) == 0.0

    def test_plain_number_string(self) -> None:
        assert _parse_duration_ms("0.003") == 3.0

    def test_invalid_string(self) -> None:
        assert _parse_duration_ms("abc") == 0.0


class TestGTestToStr:
    """Cover _to_str branches."""

    def test_str_value(self) -> None:

        assert _to_str("hello") == "hello"

    def test_non_str_value(self) -> None:

        assert _to_str(42) == ""
        assert _to_str(None) == ""


class TestGTestDiscoverBinariesExtended:
    """Cover _discover_gtest_binaries branches."""

    def test_no_build_dir(self, tmp_path: Path) -> None:
        result = _discover_gtest_binaries(tmp_path, None)
        assert isinstance(result, list)

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix permissions")
    def test_deduplication(self, tmp_path: Path) -> None:
        # Same binary under project_path and build_dir
        build = tmp_path / "build"
        build.mkdir()
        binary = build / "math_test"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        result = _discover_gtest_binaries(tmp_path, build)
        # Should not duplicate the same resolved path
        resolved = [p for p in result if p == binary.resolve()]
        assert len(resolved) <= 1


class TestGTestJsonLooksLikeTestCase:
    """Cover _looks_like_json_test_case branches."""

    def test_with_status_key(self) -> None:

        assert _looks_like_json_test_case({"status": "RUN"}) is True

    def test_with_result_key(self) -> None:

        assert _looks_like_json_test_case({"result": "passed"}) is True

    def test_with_failures_list(self) -> None:

        assert _looks_like_json_test_case({"failures": []}) is True

    def test_without_relevant_keys(self) -> None:

        assert _looks_like_json_test_case({"name": "only"}) is False


class TestGTestJsonStatusAndFailure:
    """Cover _json_status_and_failure branches."""

    def test_failed_with_failure_message(self) -> None:

        status, msg = _json_status_and_failure({"status": "RUN", "failures": [{"failure": "err"}]})
        assert status == CaseStatus.FAILED
        assert "err" in msg

    def test_skipped_status(self) -> None:

        status, _ = _json_status_and_failure({"status": "DISABLED"})
        assert status == CaseStatus.SKIPPED

    def test_passed_status(self) -> None:

        status, _ = _json_status_and_failure({"status": "RUN"})
        assert status == CaseStatus.PASSED

    def test_error_unknown_status(self) -> None:

        status, _ = _json_status_and_failure({"status": "UNKNOWN"})
        assert status == CaseStatus.ERROR
