"""Tests for the GTestAdapter (adapters/unit/gtest_adapter.py).

Covers detection, prompt template, XML/JSON parsing, execution fallback,
and tree-sitter validation with sample C++ fixtures.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.base import CaseStatus, TestFrameworkAdapter, ValidationResult
from nit.adapters.unit.gtest_adapter import (
    GTestAdapter,
    _ctest_regex_from_test_files,
    _discover_gtest_binaries,
    _find_cmake_build_dir,
    _has_gtest_cmake_patterns,
    _has_gtest_include,
    _has_gtest_test_files,
    _parse_duration_ms,
    _parse_gtest_json,
    _parse_gtest_xml,
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
