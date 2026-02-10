"""Tests for the Catch2Adapter (adapters/unit/catch2_adapter.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nit.adapters.base import (
    CaseStatus,
    TestFrameworkAdapter,
)
from nit.adapters.unit.catch2_adapter import (
    Catch2Adapter,
    _CommandResult,
    _has_catch2_cmake_patterns,
    _has_catch2_include,
    _has_catch2_test_files,
    _parse_catch2_junit,
    _parse_catch2_text,
)
from nit.llm.prompts.catch2_prompt import Catch2Template

if TYPE_CHECKING:
    from pathlib import Path


def _make_files(root: Path, rel_paths: list[str]) -> None:
    """Create empty files (with parent directories) under *root*."""
    for rel in rel_paths:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()


def _write_file(root: Path, rel: str, content: str) -> None:
    """Write *content* to a file under *root*."""
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


_CATCH2_JUNIT_XML_OK = """\
<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="math" tests="2" failures="0" errors="0" skipped="0" time="0.003">
    <testcase classname="Math" name="adds numbers" time="0.001" file="tests/math.catch2.cpp" />
    <testcase classname="Math" name="subtracts numbers" time="0.002" file="tests/math.catch2.cpp" />
  </testsuite>
</testsuites>
"""

_CATCH2_JUNIT_XML_WITH_FAILURE = """\
<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="math" tests="2" failures="1" errors="0" skipped="0" time="0.005">
    <testcase classname="Math" name="adds numbers" time="0.001" file="tests/math.catch2.cpp" />
    <testcase classname="Math" name="divide by zero" time="0.004" file="tests/math.catch2.cpp">
      <failure message="CHECK failed">expected exception</failure>
    </testcase>
  </testsuite>
</testsuites>
"""

_VALID_CPP = """\
#include <catch2/catch_test_macros.hpp>

TEST_CASE("math works", "[math]") {
  SECTION("addition") {
    REQUIRE(1 + 1 == 2);
    CHECK(2 + 2 == 4);
  }
}
"""

_INVALID_CPP = """\
#include <catch2/catch_test_macros.hpp>

TEST_CASE("broken", "[math]") {
  REQUIRE((1 + );
}
"""


class TestCatch2AdapterIdentity:
    def test_implements_test_framework_adapter(self) -> None:
        assert isinstance(Catch2Adapter(), TestFrameworkAdapter)

    def test_name(self) -> None:
        assert Catch2Adapter().name == "catch2"

    def test_language(self) -> None:
        assert Catch2Adapter().language == "cpp"


class TestCatch2Detection:
    def test_detect_cmake_find_package(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "cmake_minimum_required(VERSION 3.20)\nfind_package(Catch2 REQUIRED)\n",
        )
        assert Catch2Adapter().detect(tmp_path) is True

    def test_detect_cmake_target_link(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "target_link_libraries(unit_tests PRIVATE Catch2::Catch2WithMain)\n",
        )
        assert Catch2Adapter().detect(tmp_path) is True

    def test_detect_include_modern_header(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "tests/math.catch2.cpp",
            "#include <catch2/catch_test_macros.hpp>\n",
        )
        assert Catch2Adapter().detect(tmp_path) is True

    def test_detect_include_legacy_header(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "tests/math_test.cpp",
            '#include "catch.hpp"\n',
        )
        assert Catch2Adapter().detect(tmp_path) is True

    def test_detect_test_file_pattern(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["tests/math.catch2.cpp"])
        assert Catch2Adapter().detect(tmp_path) is True

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert Catch2Adapter().detect(tmp_path) is False


class TestCatch2DetectionHelpers:
    def test_has_cmake_patterns_true(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "CMakeLists.txt", "find_package(Catch2 REQUIRED)\n")
        assert _has_catch2_cmake_patterns(tmp_path) is True

    def test_has_cmake_patterns_false_without_file(self, tmp_path: Path) -> None:
        assert _has_catch2_cmake_patterns(tmp_path) is False

    def test_has_cmake_patterns_false_without_catch2(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "CMakeLists.txt", "project(example)\n")
        assert _has_catch2_cmake_patterns(tmp_path) is False

    def test_has_include_true(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/test.cpp", "#include <catch2/catch_test_macros.hpp>\n")
        assert _has_catch2_include(tmp_path) is True

    def test_has_include_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/test.cpp", "#include <vector>\n")
        assert _has_catch2_include(tmp_path) is False

    def test_has_test_files_true(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["tests/example.catch2.cpp"])
        assert _has_catch2_test_files(tmp_path) is True

    def test_has_test_files_false(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["src/example.cpp"])
        assert _has_catch2_test_files(tmp_path) is False


class TestCatch2TestPatterns:
    def test_returns_list_of_patterns(self) -> None:
        patterns = Catch2Adapter().get_test_pattern()
        assert isinstance(patterns, list)
        assert "**/*_test.cpp" in patterns
        assert "**/*.catch2.cpp" in patterns


class TestCatch2PromptTemplate:
    def test_returns_catch2_template(self) -> None:
        template = Catch2Adapter().get_prompt_template()
        assert isinstance(template, Catch2Template)
        assert template.name == "catch2"


class TestCatch2JunitParsing:
    def test_parse_all_passing(self) -> None:
        result = _parse_catch2_junit(_CATCH2_JUNIT_XML_OK, _CATCH2_JUNIT_XML_OK)
        assert result.success is True
        assert result.passed == 2
        assert result.failed == 0
        assert result.total == 2
        assert result.duration_ms > 0

    def test_parse_with_failure(self) -> None:
        result = _parse_catch2_junit(_CATCH2_JUNIT_XML_WITH_FAILURE, _CATCH2_JUNIT_XML_WITH_FAILURE)
        assert result.success is False
        assert result.passed == 1
        assert result.failed == 1
        assert result.total == 2

    def test_failure_message_captured(self) -> None:
        result = _parse_catch2_junit(_CATCH2_JUNIT_XML_WITH_FAILURE, _CATCH2_JUNIT_XML_WITH_FAILURE)
        failed_cases = [tc for tc in result.test_cases if tc.status == CaseStatus.FAILED]
        assert len(failed_cases) == 1
        assert "CHECK failed" in failed_cases[0].failure_message
        assert "expected exception" in failed_cases[0].failure_message

    def test_case_name_contains_classname(self) -> None:
        result = _parse_catch2_junit(_CATCH2_JUNIT_XML_OK, _CATCH2_JUNIT_XML_OK)
        assert "Math.adds numbers" in [tc.name for tc in result.test_cases]

    def test_parse_invalid_xml(self) -> None:
        result = _parse_catch2_junit("<not xml", "<not xml")
        assert result.success is False
        assert result.total == 0


class TestCatch2TextParsing:
    def test_parse_all_tests_passed_summary(self) -> None:
        output = "All tests passed (12 assertions in 4 test cases)"
        result = _parse_catch2_text(output, output)
        assert result.success is True
        assert result.passed == 4
        assert result.failed == 0

    def test_parse_failure_summary(self) -> None:
        output = "test cases: 5 | 3 passed | 1 failed | 1 skipped"
        result = _parse_catch2_text(output, output)
        assert result.success is False
        assert result.passed == 3
        assert result.failed == 1
        assert result.skipped == 1
        assert result.total == 5

    def test_parse_unknown_text(self) -> None:
        result = _parse_catch2_text("no summary", "no summary")
        assert result.success is False
        assert result.total == 0


class TestCatch2Validation:
    def test_valid_cpp(self) -> None:
        result = Catch2Adapter().validate_test(_VALID_CPP)
        assert result.valid is True
        assert result.errors == []

    def test_invalid_cpp(self) -> None:
        result = Catch2Adapter().validate_test(_INVALID_CPP)
        assert result.valid is False
        assert len(result.errors) > 0


class TestCatch2RunTests:
    @pytest.mark.asyncio
    async def test_run_tests_parses_text_summary_when_junit_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        binary = tmp_path / "build" / "math_tests"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.touch()

        async def _fake_run_command(
            cmd: list[str],
            *,
            cwd: Path,
            timeout: float,
        ) -> _CommandResult:
            del cwd, timeout
            if cmd[0].endswith("math_tests"):
                return _CommandResult(
                    returncode=0,
                    stdout="All tests passed (4 assertions in 2 test cases)",
                    stderr="",
                )
            return _CommandResult(returncode=127, stdout="", stderr="", not_found=True)

        monkeypatch.setattr(
            "nit.adapters.unit.catch2_adapter._find_cmake_build_dir", lambda _p: None
        )
        monkeypatch.setattr(
            "nit.adapters.unit.catch2_adapter._discover_catch2_binaries",
            lambda _p, _b: [binary],
        )
        monkeypatch.setattr("nit.adapters.unit.catch2_adapter._run_command", _fake_run_command)

        result = await Catch2Adapter().run_tests(tmp_path)
        assert result.success is True
        assert result.passed == 2
        assert result.failed == 0
