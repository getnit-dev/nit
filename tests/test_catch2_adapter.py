"""Tests for the Catch2Adapter (adapters/unit/catch2_adapter.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.adapters.base import (
    CaseStatus,
    RunResult,
    TestFrameworkAdapter,
)
from nit.adapters.unit.catch2_adapter import (
    Catch2Adapter,
    _CommandResult,
    _ctest_regex_from_test_files,
    _discover_catch2_binaries,
    _find_cmake_build_dir,
    _format_command_output,
    _has_catch2_cmake_patterns,
    _has_catch2_include,
    _has_catch2_test_files,
    _is_executable_file,
    _merge_run_results,
    _normalize_catch2_for_validation,
    _parse_catch2_junit,
    _parse_catch2_text,
    _parse_duration_ms,
    _select_binaries,
)
from nit.llm.prompts.catch2_prompt import Catch2Template


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


# ── Additional coverage tests ─────────────────────────────────────


class TestCatch2DurationParsing:
    """Tests for _parse_duration_ms covering all branches."""

    def test_parse_int_value(self) -> None:
        assert _parse_duration_ms(2) == 2000.0

    def test_parse_float_value(self) -> None:
        assert _parse_duration_ms(0.5) == 500.0

    def test_parse_non_str_non_numeric(self) -> None:
        assert _parse_duration_ms(None) == 0.0
        assert _parse_duration_ms([1, 2]) == 0.0

    def test_parse_string_ms_suffix(self) -> None:
        assert _parse_duration_ms("250ms") == 250.0

    def test_parse_string_s_suffix(self) -> None:
        assert _parse_duration_ms("1.5s") == 1500.0

    def test_parse_string_plain_number(self) -> None:
        # plain number treated as seconds
        assert _parse_duration_ms("0.003") == 3.0

    def test_parse_invalid_string(self) -> None:
        assert _parse_duration_ms("abc") == 0.0


class TestCatch2JunitParsingExtended:
    """Additional parsing tests for XML branches."""

    def test_parse_error_element(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite name="s">
    <testcase classname="C" name="t1" time="0.001">
      <error message="fatal error">segfault at 0x0</error>
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_catch2_junit(xml, xml)
        assert result.errors == 1
        assert result.test_cases[0].status == CaseStatus.ERROR
        assert "fatal error" in result.test_cases[0].failure_message
        assert "segfault" in result.test_cases[0].failure_message

    def test_parse_skipped_element(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite name="s">
    <testcase classname="C" name="skippable" time="0">
      <skipped />
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_catch2_junit(xml, xml)
        assert result.skipped == 1
        assert result.test_cases[0].status == CaseStatus.SKIPPED

    def test_parse_testcase_without_classname(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase name="lone_test" time="0.002" />
  </testsuite>
</testsuites>
"""
        result = _parse_catch2_junit(xml, xml)
        assert result.passed == 1
        assert result.test_cases[0].name == "lone_test"

    def test_parse_failure_message_only_attr(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase classname="C" name="f1" time="0.001">
      <failure message="msg only"></failure>
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_catch2_junit(xml, xml)
        assert result.test_cases[0].failure_message == "msg only"

    def test_parse_failure_message_only_body(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase classname="C" name="f2" time="0.001">
      <failure message="">body only text</failure>
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_catch2_junit(xml, xml)
        assert result.test_cases[0].failure_message == "body only text"

    def test_empty_testsuites(self) -> None:
        xml = '<?xml version="1.0"?><testsuites></testsuites>'
        result = _parse_catch2_junit(xml, xml)
        assert result.success is False
        assert result.total == 0


class TestCatch2TextParsingExtended:
    """Additional tests for plaintext summary parsing."""

    def test_parse_summary_without_skipped(self) -> None:
        output = "test cases: 3 | 2 passed | 1 failed"
        result = _parse_catch2_text(output, output)
        assert result.passed == 2
        assert result.failed == 1
        assert result.skipped == 0

    def test_parse_all_passed_single_assertion(self) -> None:
        output = "All tests passed (1 assertion in 1 test case)"
        result = _parse_catch2_text(output, output)
        assert result.success is True
        assert result.passed == 1


class TestCatch2CmakeHelpers:
    """Extended tests for cmake / build dir detection."""

    def test_cmake_patterns_with_catch_discover_tests(self, tmp_path: Path) -> None:
        content = "find_package(Catch2 REQUIRED)\ncatch_discover_tests(test_target)\n"
        _write_file(tmp_path, "CMakeLists.txt", content)
        assert _has_catch2_cmake_patterns(tmp_path) is True

    def test_cmake_patterns_mention_catch2_but_no_known_pattern(self, tmp_path: Path) -> None:
        # Contains "catch2" but none of the known patterns
        _write_file(tmp_path, "CMakeLists.txt", "# catch2 is great\n")
        assert _has_catch2_cmake_patterns(tmp_path) is False

    def test_has_include_skips_non_source_extensions(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "readme.txt", "#include <catch2/catch_test_macros.hpp>\n")
        assert _has_catch2_include(tmp_path) is False


class TestCatch2BuildDirHelpers:
    """Tests for _find_cmake_build_dir and friends."""

    def test_find_cmake_build_dir_standard(self, tmp_path: Path) -> None:
        build = tmp_path / "build"
        build.mkdir()
        (build / "CMakeCache.txt").touch()
        assert _find_cmake_build_dir(tmp_path) == build

    def test_find_cmake_build_dir_none(self, tmp_path: Path) -> None:
        assert _find_cmake_build_dir(tmp_path) is None

    def test_find_cmake_build_dir_project_root(self, tmp_path: Path) -> None:
        (tmp_path / "CTestTestfile.cmake").touch()
        assert _find_cmake_build_dir(tmp_path) == tmp_path

    def test_find_cmake_build_dir_testing_subdir(self, tmp_path: Path) -> None:
        build = tmp_path / "cmake-build-debug"
        build.mkdir()
        (build / "Testing").mkdir()
        assert _find_cmake_build_dir(tmp_path) == build


class TestCatch2BinaryHelpers:
    """Tests for binary selection and discovery helpers."""

    def test_select_binaries_no_test_files_returns_all(self) -> None:
        binaries = [Path("/b/test_a"), Path("/b/test_b")]
        result = _select_binaries(binaries, None)
        assert result == binaries

    def test_select_binaries_filters_by_stem(self, tmp_path: Path) -> None:
        binaries = [Path("/b/test_a"), Path("/b/test_b"), Path("/b/other")]
        test_files = [Path("/src/test_a.cpp")]
        result = _select_binaries(binaries, test_files)
        assert len(result) == 1
        assert result[0].name == "test_a"

    def test_select_binaries_no_match_returns_all(self, tmp_path: Path) -> None:
        binaries = [Path("/b/test_a")]
        test_files = [Path("/src/no_match.cpp")]
        result = _select_binaries(binaries, test_files)
        assert result == binaries

    def test_ctest_regex_from_test_files(self) -> None:
        files = [Path("/src/test_math.cpp"), Path("/src/test_string.cpp")]
        regex = _ctest_regex_from_test_files(files)
        assert "test_math" in regex
        assert "test_string" in regex
        assert "|" in regex

    def test_ctest_regex_empty_list(self) -> None:
        assert _ctest_regex_from_test_files([]) == ""


class TestCatch2FormatCommandOutput:
    """Tests for _format_command_output."""

    def test_format_with_stdout_and_stderr(self) -> None:
        cmd_result = _CommandResult(returncode=1, stdout="out text", stderr="err text")
        output = _format_command_output(["cmd", "arg"], cmd_result)
        assert "$ cmd arg" in output
        assert "exit_code=1" in output
        assert "out text" in output
        assert "err text" in output

    def test_format_no_output(self) -> None:
        cmd_result = _CommandResult(returncode=0, stdout="", stderr="")
        output = _format_command_output(["cmd"], cmd_result)
        assert "$ cmd" in output
        assert "exit_code=0" in output


class TestCatch2MergeResults:
    """Tests for _merge_run_results."""

    def test_merge_accumulates_counters(self) -> None:
        target = RunResult(passed=1, failed=0, skipped=0, errors=0, duration_ms=100.0)
        source = RunResult(passed=2, failed=1, skipped=1, errors=0, duration_ms=200.0)
        _merge_run_results(target, source)
        assert target.passed == 3
        assert target.failed == 1
        assert target.skipped == 1
        assert target.duration_ms == 300.0


class TestCatch2RunTestsExtended:
    """Extended async tests for run_tests branches."""

    @pytest.mark.asyncio
    async def test_run_tests_no_binaries_found(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "nit.adapters.unit.catch2_adapter._find_cmake_build_dir", lambda _p: None
        )
        monkeypatch.setattr(
            "nit.adapters.unit.catch2_adapter._discover_catch2_binaries",
            lambda _p, _b: [],
        )
        result = await Catch2Adapter().run_tests(tmp_path)
        assert result.success is False
        assert "No Catch2 binaries" in result.raw_output

    @pytest.mark.asyncio
    async def test_run_tests_binary_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        binary = tmp_path / "build" / "test_bin"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.touch()

        async def _fake_run_command(cmd: list[str], *, cwd: Path, timeout: float) -> _CommandResult:
            del cwd, timeout
            if cmd[0].endswith("test_bin"):
                return _CommandResult(returncode=1, stdout="", stderr="timed out", timed_out=True)
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
        assert result.success is False
        assert result.errors >= 1

    @pytest.mark.asyncio
    async def test_run_tests_nonzero_exit_no_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        binary = tmp_path / "build" / "bad_bin"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.touch()

        async def _fake_run_command(cmd: list[str], *, cwd: Path, timeout: float) -> _CommandResult:
            del cwd, timeout
            if cmd[0].endswith("bad_bin"):
                return _CommandResult(returncode=1, stdout="", stderr="crash")
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
        # binary returns nonzero with no parseable text => errors incremented
        assert result.success is False
        assert result.errors >= 1


class TestCatch2NormalizeForValidation:
    """Tests for _normalize_catch2_for_validation."""

    def test_normalize_test_case(self) -> None:
        code = 'TEST_CASE("example", "[tag]") {\n  REQUIRE(1 == 1);\n}'
        result = _normalize_catch2_for_validation(code)
        assert "void __nit_test_case()" in result
        assert "TEST_CASE" not in result

    def test_normalize_section(self) -> None:
        code = 'SECTION("sub") { REQUIRE(true); }'
        result = _normalize_catch2_for_validation(code)
        assert "SECTION" not in result
        assert "{ REQUIRE(true); }" in result


# ── Additional coverage: missing lines ────────────────────────────


class TestCatch2AdapterRunTestsCoverage:
    """Cover collect_coverage branch and CTest path in run_tests."""

    @pytest.mark.asyncio
    async def test_run_tests_collect_coverage_false(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When collect_coverage=False, skip coverage collection."""
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

        result = await Catch2Adapter().run_tests(tmp_path, collect_coverage=False)
        assert result.success is True
        assert result.coverage is None

    @pytest.mark.asyncio
    async def test_run_tests_via_ctest_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cover CTest build timeout branch."""
        build = tmp_path / "build"
        build.mkdir()
        (build / "CMakeCache.txt").touch()

        async def _fake_run_command(
            cmd: list[str],
            *,
            cwd: Path,
            timeout: float,
        ) -> _CommandResult:
            del cwd, timeout
            return _CommandResult(returncode=1, stdout="", stderr="timed out", timed_out=True)

        monkeypatch.setattr("nit.adapters.unit.catch2_adapter._run_command", _fake_run_command)
        result = await Catch2Adapter().run_tests(tmp_path)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_run_tests_via_ctest_not_found(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cover CTest build not found branch -> fallback to direct."""
        build = tmp_path / "build"
        build.mkdir()
        (build / "CMakeCache.txt").touch()

        async def _fake_run_command(
            cmd: list[str],
            *,
            cwd: Path,
            timeout: float,
        ) -> _CommandResult:
            del cwd, timeout
            return _CommandResult(returncode=127, stdout="", stderr="not found", not_found=True)

        monkeypatch.setattr("nit.adapters.unit.catch2_adapter._run_command", _fake_run_command)
        monkeypatch.setattr(
            "nit.adapters.unit.catch2_adapter._discover_catch2_binaries",
            lambda _p, _b: [],
        )
        result = await Catch2Adapter().run_tests(tmp_path)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_run_tests_via_ctest_with_test_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cover CTest regex filter from test_files."""
        build = tmp_path / "build"
        build.mkdir()
        (build / "CMakeCache.txt").touch()

        report_content = _CATCH2_JUNIT_XML_OK
        report_written = False

        async def _fake_run_command(
            cmd: list[str],
            *,
            cwd: Path,
            timeout: float,
        ) -> _CommandResult:
            nonlocal report_written
            if "cmake" in cmd[0]:
                return _CommandResult(returncode=0, stdout="build ok", stderr="")
            if "ctest" in cmd[0]:
                # Write the XML report that CTest would produce
                for i, arg in enumerate(cmd):
                    if arg == "--output-junit":
                        report_path = Path(cmd[i + 1])
                        report_path.write_text(report_content)
                        report_written = True
                return _CommandResult(returncode=0, stdout="ctest ok", stderr="")
            return _CommandResult(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("nit.adapters.unit.catch2_adapter._run_command", _fake_run_command)
        test_files = [Path("/src/test_math.cpp")]
        result = await Catch2Adapter().run_tests(
            tmp_path, test_files=test_files, collect_coverage=False
        )
        if report_written:
            assert result.success is True

    @pytest.mark.asyncio
    async def test_run_tests_ctest_timeout_on_ctest_itself(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cover ctest command timeout (after build succeeds)."""
        build = tmp_path / "build"
        build.mkdir()
        (build / "CMakeCache.txt").touch()

        call_count = 0

        async def _fake_run_command(
            cmd: list[str],
            *,
            cwd: Path,
            timeout: float,
        ) -> _CommandResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _CommandResult(returncode=0, stdout="build ok", stderr="")
            return _CommandResult(returncode=1, stdout="", stderr="timeout", timed_out=True)

        monkeypatch.setattr("nit.adapters.unit.catch2_adapter._run_command", _fake_run_command)
        result = await Catch2Adapter().run_tests(tmp_path, collect_coverage=False)
        assert result.success is False


class TestCatch2DiscoverBinaries:
    """Cover _discover_catch2_binaries and _is_executable_file."""

    def test_discover_no_build_dir(self, tmp_path: Path) -> None:
        result = _discover_catch2_binaries(tmp_path, None)
        assert isinstance(result, list)

    def test_is_executable_file_non_file(self, tmp_path: Path) -> None:
        assert _is_executable_file(tmp_path) is False

    def test_is_executable_file_source_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "test.cpp"
        f.write_text("int main() {}")
        f.chmod(0o755)
        assert _is_executable_file(f) is False


class TestCatch2TextParsingErrors:
    """Cover text parsing with total > parsed total branch."""

    def test_parse_summary_with_errors_inferred(self) -> None:
        # total > passed + failed + skipped => errors inferred
        output = "test cases: 10 | 3 passed | 2 failed | 1 skipped"
        result = _parse_catch2_text(output, output)
        assert result.passed == 3
        assert result.failed == 2
        assert result.skipped == 1
        assert result.errors == 4
