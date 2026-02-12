"""Tests for JUnit5Adapter (adapters/unit/junit5_adapter.py).

Covers detection (Gradle/Maven), prompt template, XML parsing,
and tree-sitter validation with sample Java fixtures.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.adapters.base import CaseStatus, TestFrameworkAdapter, ValidationResult
from nit.adapters.unit.junit5_adapter import (
    JUnit5Adapter,
    _find_gradle_test_results,
    _find_surefire_reports,
    _has_junit_gradle,
    _has_junit_import,
    _has_junit_maven,
    _has_test_files,
    _parse_duration_seconds,
    _parse_junit_xml,
    _path_to_class_name,
    _xml_failure_message,
)
from nit.llm.prompts.junit5_prompt import JUnit5Template


def _write_file(root: Path, rel: str, content: str) -> Path:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


def _make_files(root: Path, rel_paths: list[str]) -> None:
    for rel in rel_paths:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()


# ── Sample JUnit/Surefire XML ────────────────────────────────────

_JUNIT_XML_TWO_PASSED = """\
<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="2" failures="0" errors="0" skipped="0">
  <testsuite name="com.example.CalculatorTest" tests="2" failures="0"
    errors="0" skipped="0" time="0.05">
    <testcase classname="com.example.CalculatorTest" name="addReturnsSum" time="0.02" />
    <testcase classname="com.example.CalculatorTest" name="subtractReturnsDifference" time="0.03" />
  </testsuite>
</testsuites>
"""

_JUNIT_XML_WITH_FAILURE = """\
<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="2" failures="1" errors="0" skipped="0">
  <testsuite name="com.example.ParserTest" tests="2" failures="1" errors="0" skipped="0" time="0.1">
    <testcase classname="com.example.ParserTest" name="parsesValid" time="0.03" />
    <testcase classname="com.example.ParserTest" name="rejectsInvalid" time="0.05">
      <failure message="Expected invalid input to fail">AssertionError: expected null</failure>
    </testcase>
  </testsuite>
</testsuites>
"""

_JUNIT_XML_SKIPPED = """\
<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="2" failures="0" errors="0" skipped="1">
  <testsuite name="com.example.FeatureTest" tests="2" failures="0"
    errors="0" skipped="1" time="0.02">
    <testcase classname="com.example.FeatureTest" name="enabledTest" time="0.01" />
    <testcase classname="com.example.FeatureTest" name="disabledTest" time="0.0">
      <skipped />
    </testcase>
  </testsuite>
</testsuites>
"""

_VALID_JAVA = """\
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

class CalculatorTest {
    @Test
    void addReturnsSum() {
        assertEquals(5, 2 + 3);
    }
}
"""

_INVALID_JAVA = """\
import org.junit.jupiter.api.Test;

class BrokenTest {
    @Test
    void missingBrace() {
        assertEquals(1, 1);
"""


# ── Identity ─────────────────────────────────────────────────────


class TestJUnit5AdapterIdentity:
    def test_implements_test_framework_adapter(self) -> None:
        assert isinstance(JUnit5Adapter(), TestFrameworkAdapter)

    def test_name(self) -> None:
        assert JUnit5Adapter().name == "junit5"

    def test_language(self) -> None:
        assert JUnit5Adapter().language == "java"


# ── Detection ─────────────────────────────────────────────────────


class TestJUnit5Detection:
    def test_detect_gradle_junit(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "build.gradle",
            "dependencies { testImplementation 'org.junit.jupiter:junit-jupiter:5.9.0' }\n",
        )
        assert JUnit5Adapter().detect(tmp_path) is True

    def test_detect_gradle_kts_junit(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "build.gradle.kts",
            'dependencies { testImplementation("org.junit.jupiter:junit-jupiter") }\n',
        )
        assert JUnit5Adapter().detect(tmp_path) is True

    def test_detect_maven_junit(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pom.xml",
            "<project><dependencies><dependency><groupId>org.junit.jupiter</groupId>"
            "<artifactId>junit-jupiter</artifactId></dependency></dependencies></project>\n",
        )
        assert JUnit5Adapter().detect(tmp_path) is True

    def test_detect_import_and_test_files(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/test/java/CalculatorTest.java", _VALID_JAVA)
        assert JUnit5Adapter().detect(tmp_path) is True

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert JUnit5Adapter().detect(tmp_path) is False

    def test_no_detection_gradle_without_junit(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "build.gradle", "plugins { id 'java' }\n")
        assert JUnit5Adapter().detect(tmp_path) is False


class TestJUnit5DetectionHelpers:
    def test_has_junit_gradle_true(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path, "build.gradle", "testImplementation 'org.junit.jupiter:junit-jupiter'\n"
        )
        assert _has_junit_gradle(tmp_path) is True

    def test_has_junit_gradle_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "build.gradle", "dependencies {}\n")
        assert _has_junit_gradle(tmp_path) is False

    def test_has_junit_maven_true(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pom.xml",
            "<project><dependencies><dependency><groupId>org.junit.jupiter</groupId></dependency></dependencies></project>\n",
        )
        assert _has_junit_maven(tmp_path) is True

    def test_has_junit_maven_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "pom.xml", "<project></project>\n")
        assert _has_junit_maven(tmp_path) is False

    def test_has_junit_import_true(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/test/java/FooTest.java", "import org.junit.jupiter.api.Test;\n")
        assert _has_junit_import(tmp_path) is True

    def test_has_junit_import_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/Main.java", "public class Main { }\n")
        assert _has_junit_import(tmp_path) is False

    def test_has_test_files_true(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["src/test/java/CalculatorTest.java"])
        assert _has_test_files(tmp_path) is True

    def test_has_test_files_false(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["src/main/java/Main.java"])
        assert _has_test_files(tmp_path) is False


# ── Test patterns ────────────────────────────────────────────────


class TestJUnit5Patterns:
    def test_returns_list_of_patterns(self) -> None:
        patterns = JUnit5Adapter().get_test_pattern()
        assert isinstance(patterns, list)
        assert len(patterns) >= 2

    def test_includes_test_java_pattern(self) -> None:
        patterns = JUnit5Adapter().get_test_pattern()
        assert "**/*Test.java" in patterns

    def test_includes_test_prefix_pattern(self) -> None:
        patterns = JUnit5Adapter().get_test_pattern()
        assert "**/Test*.java" in patterns


# ── Prompt template ──────────────────────────────────────────────


class TestJUnit5PromptTemplate:
    def test_returns_junit5_template(self) -> None:
        template = JUnit5Adapter().get_prompt_template()
        assert isinstance(template, JUnit5Template)

    def test_template_name(self) -> None:
        template = JUnit5Adapter().get_prompt_template()
        assert template.name == "junit5"


# ── XML parsing ──────────────────────────────────────────────────


class TestJUnit5XmlParsing:
    def test_parse_all_pass(self) -> None:
        result = _parse_junit_xml(_JUNIT_XML_TWO_PASSED, _JUNIT_XML_TWO_PASSED)
        assert result.success is True
        assert result.passed == 2
        assert result.failed == 0
        assert result.skipped == 0
        assert result.errors == 0
        assert len(result.test_cases) == 2
        assert all(c.status == CaseStatus.PASSED for c in result.test_cases)

    def test_parse_with_failure(self) -> None:
        result = _parse_junit_xml(_JUNIT_XML_WITH_FAILURE, _JUNIT_XML_WITH_FAILURE)
        assert result.success is False
        assert result.passed == 1
        assert result.failed == 1
        assert len(result.test_cases) == 2
        failed_case = next(c for c in result.test_cases if c.status == CaseStatus.FAILED)
        assert (
            "AssertionError" in failed_case.failure_message
            or "invalid" in failed_case.failure_message.lower()
        )

    def test_parse_with_skipped(self) -> None:
        result = _parse_junit_xml(_JUNIT_XML_SKIPPED, _JUNIT_XML_SKIPPED)
        assert result.passed == 1
        assert result.skipped == 1
        assert len(result.test_cases) == 2
        skipped_case = next(c for c in result.test_cases if c.status == CaseStatus.SKIPPED)
        assert skipped_case.name == "com.example.FeatureTest.disabledTest"


# ── Validation ────────────────────────────────────────────────────


class TestJUnit5Validation:
    def test_validate_valid_java(self) -> None:
        result = JUnit5Adapter().validate_test(_VALID_JAVA)
        assert isinstance(result, ValidationResult)
        assert result.valid is True
        assert result.errors == []

    def test_validate_invalid_java(self) -> None:
        result = JUnit5Adapter().validate_test(_INVALID_JAVA)
        assert result.valid is False
        assert len(result.errors) >= 1


# ── run_tests (integration; may skip if no Gradle/Maven) ───────────


class TestJUnit5RunTests:
    @pytest.mark.asyncio
    async def test_run_tests_no_build_returns_false(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "build.gradle",
            "dependencies { testImplementation 'org.junit.jupiter:junit-jupiter' }\n",
        )
        adapter = JUnit5Adapter()
        result = await adapter.run_tests(tmp_path, timeout=10.0)
        # No gradlew or mvn, so no XML reports; result may be success=False or empty
        assert isinstance(result.passed, int)
        assert isinstance(result.failed, int)
        assert result.raw_output


# ── Additional coverage tests ─────────────────────────────────────


class TestJUnit5DurationParsing:
    """Tests for _parse_duration_seconds covering all branches."""

    def test_parse_int_value(self) -> None:
        assert _parse_duration_seconds(2) == 2.0

    def test_parse_float_value(self) -> None:
        assert _parse_duration_seconds(1.5) == 1.5

    def test_parse_non_str_non_numeric(self) -> None:
        assert _parse_duration_seconds(None) == 0.0
        assert _parse_duration_seconds([]) == 0.0

    def test_parse_string_with_s_suffix(self) -> None:
        assert _parse_duration_seconds("2.5s") == 2.5

    def test_parse_plain_number_string(self) -> None:
        assert _parse_duration_seconds("0.05") == 0.05

    def test_parse_invalid_string(self) -> None:
        assert _parse_duration_seconds("xyz") == 0.0


class TestJUnit5XmlParsingExtended:
    """Extended XML parsing tests for error, skipped-by-status, and edge cases."""

    def test_parse_error_element(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite name="s">
    <testcase classname="com.Foo" name="crashes" time="0.01">
      <error message="OutOfMemoryError">heap space</error>
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_junit_xml(xml, xml)
        assert result.errors == 1
        assert result.test_cases[0].status == CaseStatus.ERROR
        assert "OutOfMemoryError" in result.test_cases[0].failure_message

    def test_parse_skipped_by_status_attribute(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase classname="pkg.Test" name="skippedByAttr" time="0" status="Skipped" />
  </testsuite>
</testsuites>
"""
        result = _parse_junit_xml(xml, xml)
        assert result.skipped == 1
        assert result.test_cases[0].status == CaseStatus.SKIPPED

    def test_parse_no_classname(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase name="standalone" time="0.001" />
  </testsuite>
</testsuites>
"""
        result = _parse_junit_xml(xml, xml)
        assert result.passed == 1
        assert result.test_cases[0].name == "standalone"

    def test_parse_empty_xml(self) -> None:
        xml = '<?xml version="1.0"?><testsuites></testsuites>'
        result = _parse_junit_xml(xml, xml)
        assert result.total == 0
        assert result.success is False

    def test_parse_failure_message_only_body(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase classname="C" name="t" time="0.01">
      <failure message="">body text only</failure>
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_junit_xml(xml, xml)
        assert result.test_cases[0].failure_message == "body text only"

    def test_parse_failure_message_only_attr(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase classname="C" name="t" time="0.01">
      <failure message="attr only"></failure>
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_junit_xml(xml, xml)
        assert result.test_cases[0].failure_message == "attr only"


class TestJUnit5DetectionExtended:
    """Extended detection tests for edge cases."""

    def test_has_junit_maven_no_pom(self, tmp_path: Path) -> None:
        assert _has_junit_maven(tmp_path) is False

    def test_has_junit_import_no_java_files(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/main.txt", "import org.junit.jupiter.api.Test;\n")
        assert _has_junit_import(tmp_path) is False

    def test_has_test_files_prefix_pattern(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["src/test/java/TestFoo.java"])
        assert _has_test_files(tmp_path) is True


class TestJUnit5PathToClassName:
    """Tests for _path_to_class_name helper."""

    def test_standard_maven_layout(self, tmp_path: Path) -> None:
        test_file = tmp_path / "src" / "test" / "java" / "com" / "example" / "FooTest.java"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.touch()
        result = _path_to_class_name(test_file, tmp_path)
        assert result == "com.example.FooTest"

    def test_non_relative_path(self, tmp_path: Path) -> None:
        result = _path_to_class_name(Path("/completely/different/FooTest.java"), tmp_path)
        assert result == ""

    def test_simple_path(self, tmp_path: Path) -> None:
        test_file = tmp_path / "FooTest.java"
        test_file.touch()
        result = _path_to_class_name(test_file, tmp_path)
        assert result == "FooTest"


class TestJUnit5RequiredCommands:
    """Tests for get_required_packages and get_required_commands."""

    def test_required_packages_empty(self) -> None:
        assert JUnit5Adapter().get_required_packages() == []

    def test_required_commands_java(self) -> None:
        assert "java" in JUnit5Adapter().get_required_commands()


class TestJUnit5RunTestsExtended:
    """Extended run_tests tests for Gradle/Maven branches."""

    @pytest.mark.asyncio
    async def test_run_tests_maven_no_reports(self, tmp_path: Path) -> None:
        # No gradlew => falls back to maven; no surefire reports => failure
        _write_file(tmp_path, "pom.xml", "<project/>")
        adapter = JUnit5Adapter()
        result = await adapter.run_tests(tmp_path, timeout=5.0)
        assert result.success is False


# ── Additional coverage: missing lines ────────────────────────────


class TestJUnit5FindSurefireReports:
    """Cover _find_surefire_reports."""

    def test_returns_empty_when_no_dir(self, tmp_path: Path) -> None:
        assert _find_surefire_reports(tmp_path) == []

    def test_returns_matching_xml_files(self, tmp_path: Path) -> None:
        reports_dir = tmp_path / "target" / "surefire-reports"
        reports_dir.mkdir(parents=True)
        (reports_dir / "TEST-FooTest.xml").write_text(_JUNIT_XML_TWO_PASSED)
        (reports_dir / "TEST-BarTest.xml").write_text(_JUNIT_XML_TWO_PASSED)
        (reports_dir / "other.txt").touch()
        result = _find_surefire_reports(tmp_path)
        assert len(result) == 2
        assert all(p.name.startswith("TEST-") for p in result)


class TestJUnit5FindGradleTestResults:
    """Cover _find_gradle_test_results."""

    def test_returns_empty_when_no_dir(self, tmp_path: Path) -> None:
        assert _find_gradle_test_results(tmp_path) == []

    def test_returns_xml_files_recursively(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "build" / "test-results" / "test"
        results_dir.mkdir(parents=True)
        (results_dir / "TEST-FooTest.xml").write_text(_JUNIT_XML_TWO_PASSED)
        result = _find_gradle_test_results(tmp_path)
        assert len(result) == 1


class TestJUnit5XmlFailureMessage:
    """Cover _xml_failure_message branches."""

    def test_message_with_both_attr_and_body(self) -> None:
        xml = '<failure message="msg">body text</failure>'
        match = re.search(
            r"<failure\b(?P<attrs>[^>]*)>(?P<body>.*?)</failure>",
            xml,
            flags=re.DOTALL,
        )
        assert match is not None
        result = _xml_failure_message(match)
        assert "msg" in result
        assert "body text" in result

    def test_message_only_attr(self) -> None:
        xml = '<failure message="only attr"></failure>'
        match = re.search(
            r"<failure\b(?P<attrs>[^>]*)>(?P<body>.*?)</failure>",
            xml,
            flags=re.DOTALL,
        )
        assert match is not None
        result = _xml_failure_message(match)
        assert result == "only attr"

    def test_message_only_body(self) -> None:
        xml = '<failure message="">only body</failure>'
        match = re.search(
            r"<failure\b(?P<attrs>[^>]*)>(?P<body>.*?)</failure>",
            xml,
            flags=re.DOTALL,
        )
        assert match is not None
        result = _xml_failure_message(match)
        assert result == "only body"


class TestJUnit5PathToClassNameExtended:
    """More edge cases for _path_to_class_name."""

    def test_src_without_test_subdir(self, tmp_path: Path) -> None:
        test_file = tmp_path / "src" / "main" / "java" / "FooTest.java"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.touch()
        result = _path_to_class_name(test_file, tmp_path)
        assert "FooTest" in result

    def test_path_with_java_in_parts(self, tmp_path: Path) -> None:
        test_file = tmp_path / "src" / "test" / "java" / "FooTest.java"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.touch()
        result = _path_to_class_name(test_file, tmp_path)
        assert result == "FooTest"

    def test_empty_parts_after_stripping(self, tmp_path: Path) -> None:
        test_file = tmp_path / "src" / "test" / "java" / "FooTest.java"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.touch()
        result = _path_to_class_name(test_file, tmp_path)
        assert result != ""


class TestJUnit5RunTestsGradle:
    """Cover Gradle run path."""

    @pytest.mark.asyncio
    async def test_run_tests_with_gradlew(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(tmp_path, "gradlew", "#!/bin/sh\nexit 0\n")
        (tmp_path / "gradlew").chmod(0o755)

        # Create XML reports
        xml_dir = tmp_path / "build" / "test-results" / "test"
        xml_dir.mkdir(parents=True)
        (xml_dir / "TEST-Calc.xml").write_text(_JUNIT_XML_TWO_PASSED)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        monkeypatch.setattr(
            "nit.adapters.unit.junit5_adapter.asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        adapter = JUnit5Adapter()
        result = await adapter.run_tests(tmp_path, timeout=5.0, collect_coverage=False)
        assert result.passed == 2
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_run_tests_gradle_with_test_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(tmp_path, "gradlew", "#!/bin/sh\nexit 0\n")
        (tmp_path / "gradlew").chmod(0o755)

        xml_dir = tmp_path / "build" / "test-results" / "test"
        xml_dir.mkdir(parents=True)
        (xml_dir / "TEST-Calc.xml").write_text(_JUNIT_XML_TWO_PASSED)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"out", b"err"))

        monkeypatch.setattr(
            "nit.adapters.unit.junit5_adapter.asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        test_file = tmp_path / "src" / "test" / "java" / "com" / "CalculatorTest.java"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.touch()
        adapter = JUnit5Adapter()
        result = await adapter.run_tests(
            tmp_path,
            test_files=[test_file],
            timeout=5.0,
            collect_coverage=False,
        )
        assert result.passed == 2

    @pytest.mark.asyncio
    async def test_run_tests_maven_with_test_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # No gradlew => Maven path
        reports_dir = tmp_path / "target" / "surefire-reports"
        reports_dir.mkdir(parents=True)
        (reports_dir / "TEST-FooTest.xml").write_text(_JUNIT_XML_TWO_PASSED)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        monkeypatch.setattr(
            "nit.adapters.unit.junit5_adapter.asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        test_file = tmp_path / "FooTest.java"
        adapter = JUnit5Adapter()
        result = await adapter.run_tests(
            tmp_path,
            test_files=[test_file],
            timeout=5.0,
            collect_coverage=False,
        )
        assert result.passed == 2
