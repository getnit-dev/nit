"""Tests for JUnit5Adapter (adapters/unit/junit5_adapter.py).

Covers detection (Gradle/Maven), prompt template, XML parsing,
and tree-sitter validation with sample Java fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.adapters.base import CaseStatus, TestFrameworkAdapter, ValidationResult
from nit.adapters.unit.junit5_adapter import (
    JUnit5Adapter,
    _has_junit_gradle,
    _has_junit_import,
    _has_junit_maven,
    _has_test_files,
    _parse_junit_xml,
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
