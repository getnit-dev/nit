"""Tests for the KotestAdapter (adapters/unit/kotest_adapter.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.base import CaseStatus, TestFrameworkAdapter, ValidationResult
from nit.adapters.unit.kotest_adapter import (
    KotestAdapter,
    _collect_junit_xml,
    _has_gradle,
    _has_kotest_import_in_kt_files,
    _has_kotest_in_gradle,
    _has_kotest_in_maven,
    _has_maven,
    _parse_junit_xml,
)
from nit.llm.prompts.kotest_prompt import KotestTemplate


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


_JUNIT_XML_SUCCESS = """\
<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="CalculatorTest" tests="2" failures="0" errors="0" skipped="0" time="0.05">
    <testcase classname="CalculatorTest" name="divide returns correct result" time="0.02" />
    <testcase classname="CalculatorTest" name="throws when divisor is zero" time="0.03" />
  </testsuite>
</testsuites>
"""

_JUNIT_XML_WITH_FAILURE = """\
<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="CalculatorTest" tests="2" failures="1" errors="0" skipped="0" time="0.06">
    <testcase classname="CalculatorTest" name="divide returns correct result" time="0.02" />
    <testcase classname="CalculatorTest" name="throws when divisor is zero" time="0.04"
               file="src/test/kotlin/CalculatorTest.kt">
      <failure message="Expected ArithmeticException">divide(1, 0) did not throw</failure>
    </testcase>
  </testsuite>
</testsuites>
"""


class TestKotestAdapterIdentity:
    def test_implements_test_framework_adapter(self) -> None:
        assert isinstance(KotestAdapter(), TestFrameworkAdapter)

    def test_name(self) -> None:
        assert KotestAdapter().name == "kotest"

    def test_language(self) -> None:
        assert KotestAdapter().language == "kotlin"


class TestKotestDetection:
    def test_detect_gradle_build_with_io_kotest(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "build.gradle.kts",
            'dependencies { testImplementation("io.kotest:kotest-runner-junit5:5.0.0") }\n',
        )
        assert KotestAdapter().detect(tmp_path) is True

    def test_detect_gradle_groovy_with_io_kotest(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "build.gradle",
            "dependencies { testImplementation 'io.kotest:kotest-runner-junit5:5.0.0' }\n",
        )
        assert KotestAdapter().detect(tmp_path) is True

    def test_detect_maven_pom_with_kotest(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pom.xml",
            "<project><dependencies><dependency><groupId>io.kotest</groupId></dependency></dependencies></project>\n",
        )
        assert KotestAdapter().detect(tmp_path) is True

    def test_detect_kt_file_with_import_io_kotest(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "src/test/kotlin/CalculatorTest.kt",
            "import io.kotest.core.spec.style.FunSpec\nimport io.kotest.matchers.shouldBe\n",
        )
        assert KotestAdapter().detect(tmp_path) is True

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert KotestAdapter().detect(tmp_path) is False

    def test_no_detection_gradle_without_kotest(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "build.gradle.kts",
            'dependencies { testImplementation("junit:junit:4.13") }\n',
        )
        assert KotestAdapter().detect(tmp_path) is False

    def test_no_detection_kt_without_kotest_import(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/main/kotlin/Main.kt", "fun main() { }\n")
        assert KotestAdapter().detect(tmp_path) is False


class TestDetectionHelpers:
    def test_has_kotest_in_gradle_true(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "build.gradle.kts", "io.kotest\n")
        assert _has_kotest_in_gradle(tmp_path) is True

    def test_has_kotest_in_gradle_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "build.gradle.kts", "junit only\n")
        assert _has_kotest_in_gradle(tmp_path) is False

    def test_has_kotest_in_maven_true(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "pom.xml", "<groupId>io.kotest</groupId>\n")
        assert _has_kotest_in_maven(tmp_path) is True

    def test_has_kotest_in_maven_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "pom.xml", "<groupId>org.junit</groupId>\n")
        assert _has_kotest_in_maven(tmp_path) is False

    def test_has_kotest_import_in_kt_files_true(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path, "app/CalculatorSpec.kt", "import io.kotest.core.spec.style.StringSpec\n"
        )
        assert _has_kotest_import_in_kt_files(tmp_path) is True

    def test_has_kotest_import_in_kt_files_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "app/Main.kt", "import java.util.List\n")
        assert _has_kotest_import_in_kt_files(tmp_path) is False

    def test_has_gradle_true_wrapper(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "gradlew", "#!/bin/sh\n")
        assert _has_gradle(tmp_path) is True

    def test_has_gradle_true_build_file(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "build.gradle.kts", "")
        assert _has_gradle(tmp_path) is True

    def test_has_gradle_false(self, tmp_path: Path) -> None:
        assert _has_gradle(tmp_path) is False

    def test_has_maven_true(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "pom.xml", "")
        assert _has_maven(tmp_path) is True

    def test_has_maven_false(self, tmp_path: Path) -> None:
        assert _has_maven(tmp_path) is False


class TestKotestPatterns:
    def test_returns_list_of_patterns(self) -> None:
        patterns = KotestAdapter().get_test_pattern()
        assert isinstance(patterns, list)
        assert len(patterns) == 3

    def test_includes_test_kt_pattern(self) -> None:
        patterns = KotestAdapter().get_test_pattern()
        assert "**/*Test.kt" in patterns
        assert "**/*Spec.kt" in patterns
        assert "**/*Tests.kt" in patterns


class TestKotestPromptTemplate:
    def test_returns_kotest_template(self) -> None:
        template = KotestAdapter().get_prompt_template()
        assert isinstance(template, KotestTemplate)

    def test_template_name(self) -> None:
        template = KotestAdapter().get_prompt_template()
        assert template.name == "kotest"


class TestKotestValidation:
    def test_validate_test_returns_valid_true(self) -> None:
        result = KotestAdapter().validate_test("class X : FunSpec({ })")
        assert isinstance(result, ValidationResult)
        assert result.valid is True


class TestJunitXmlParsing:
    def test_parse_all_passing(self) -> None:
        result = _parse_junit_xml(_JUNIT_XML_SUCCESS, "")
        assert result.success is True
        assert result.passed == 2
        assert result.failed == 0
        assert result.skipped == 0
        assert result.total == 2
        names = [c.name for c in result.test_cases]
        assert "CalculatorTest.divide returns correct result" in names
        assert "CalculatorTest.throws when divisor is zero" in names

    def test_parse_with_failure(self) -> None:
        result = _parse_junit_xml(_JUNIT_XML_WITH_FAILURE, "")
        assert result.success is False
        assert result.passed == 1
        assert result.failed == 1
        assert result.total == 2
        failed_case = next(c for c in result.test_cases if c.status == CaseStatus.FAILED)
        assert "throws when divisor is zero" in failed_case.name
        assert (
            "Expected ArithmeticException" in failed_case.failure_message
            or "divide" in failed_case.failure_message
        )


class TestCollectJunitXml:
    def test_collects_xml_from_dir(self, tmp_path: Path) -> None:
        xml_dir = tmp_path / "build" / "test-results" / "test"
        xml_dir.mkdir(parents=True)
        (xml_dir / "TEST-CalculatorTest.xml").write_text(_JUNIT_XML_SUCCESS, encoding="utf-8")
        result = _collect_junit_xml(tmp_path / "build" / "test-results", "raw")
        assert result.passed == 2
        assert result.total == 2
        assert result.raw_output == "raw"

    def test_empty_dir_returns_zero_tests(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        result = _collect_junit_xml(tmp_path / "empty", "raw")
        assert result.total == 0
        assert result.raw_output == "raw"

    def test_nonexistent_dir_returns_zero_tests(self, tmp_path: Path) -> None:
        result = _collect_junit_xml(tmp_path / "nonexistent", "raw")
        assert result.total == 0


class TestKotestRunTests:
    @pytest.mark.asyncio
    async def test_run_tests_no_gradle_or_maven_returns_failure(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "build.gradle.kts", "io.kotest\n")  # detect passes
        adapter = KotestAdapter()
        result = await adapter.run_tests(tmp_path)
        assert result.success is False
        assert "No Gradle or Maven" in result.raw_output or "gradlew" in result.raw_output

    @pytest.mark.asyncio
    async def test_run_tests_with_gradle_calls_gradlew(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "gradlew", "#!/bin/sh\nexit 0\n")
        (tmp_path / "gradlew").chmod(0o755)
        _write_file(tmp_path, "build.gradle.kts", 'plugins { id("java") }\n')
        xml_dir = tmp_path / "build" / "test-results" / "test"
        xml_dir.mkdir(parents=True)
        (xml_dir / "TEST-Sample.xml").write_text(_JUNIT_XML_SUCCESS, encoding="utf-8")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch(
            "nit.adapters.unit.kotest_adapter.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as m:
            m.return_value = mock_proc
            adapter = KotestAdapter()
            result = await adapter.run_tests(tmp_path, timeout=5.0)
        assert m.called
        assert result.raw_output
        assert result.passed == 2
        assert result.total == 2
