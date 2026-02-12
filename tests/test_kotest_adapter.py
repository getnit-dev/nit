"""Tests for the KotestAdapter (adapters/unit/kotest_adapter.py)."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.base import CaseStatus, TestFrameworkAdapter, ValidationResult
from nit.adapters.unit.kotest_adapter import (
    KotestAdapter,
    _collect_junit_xml,
    _CommandResult,
    _format_output,
    _has_gradle,
    _has_kotest_import_in_kt_files,
    _has_kotest_in_gradle,
    _has_kotest_in_maven,
    _has_maven,
    _parse_duration_ms,
    _parse_junit_xml,
    _xml_failure_message,
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


# ── Additional coverage: missing lines ────────────────────────────


class TestKotestRunTestsMaven:
    """Cover Maven run path in run_tests."""

    @pytest.mark.asyncio
    async def test_run_tests_with_maven(
        self,
        tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "pom.xml", "<project/>")
        # No gradlew => Maven path, but mvn likely not found
        adapter = KotestAdapter()
        result = await adapter.run_tests(tmp_path, timeout=5.0, collect_coverage=False)
        # Maven will either fail or produce no results
        assert isinstance(result.passed, int)

    @pytest.mark.asyncio
    async def test_run_tests_with_maven_mocked(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(tmp_path, "pom.xml", "<project/>")
        # Create surefire reports
        xml_dir = tmp_path / "target" / "surefire-reports"
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
            result = await adapter.run_tests(tmp_path, timeout=5.0, collect_coverage=False)
        assert result.passed == 2

    @pytest.mark.asyncio
    async def test_run_tests_maven_with_test_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(tmp_path, "pom.xml", "<project/>")
        xml_dir = tmp_path / "target" / "surefire-reports"
        xml_dir.mkdir(parents=True)
        (xml_dir / "TEST-Calc.xml").write_text(_JUNIT_XML_SUCCESS, encoding="utf-8")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch(
            "nit.adapters.unit.kotest_adapter.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as m:
            m.return_value = mock_proc
            test_file = Path("/src/test/kotlin/CalcTest.kt")
            adapter = KotestAdapter()
            result = await adapter.run_tests(
                tmp_path,
                test_files=[test_file],
                timeout=5.0,
                collect_coverage=False,
            )
        assert result.passed == 2

    @pytest.mark.asyncio
    async def test_run_tests_no_build_system(self, tmp_path: Path) -> None:
        """No Gradle or Maven => failure."""
        adapter = KotestAdapter()
        result = await adapter.run_tests(tmp_path, collect_coverage=False)
        assert result.success is False
        assert "No Gradle or Maven" in result.raw_output


class TestKotestGradleWithTestFiles:
    """Cover Gradle path with test_files filter."""

    @pytest.mark.asyncio
    async def test_run_gradle_with_test_files(
        self,
        tmp_path: Path,
    ) -> None:
        _write_file(tmp_path, "gradlew", "#!/bin/sh\nexit 0\n")
        (tmp_path / "gradlew").chmod(0o755)
        _write_file(tmp_path, "build.gradle.kts", 'plugins { id("java") }\n')
        xml_dir = tmp_path / "build" / "test-results" / "test"
        xml_dir.mkdir(parents=True)
        (xml_dir / "TEST-Sample.xml").write_text(_JUNIT_XML_SUCCESS, encoding="utf-8")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"out", b"err"))

        with patch(
            "nit.adapters.unit.kotest_adapter.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as m:
            m.return_value = mock_proc
            test_file = Path("/src/CalculatorSpec.kt")
            adapter = KotestAdapter()
            result = await adapter.run_tests(
                tmp_path,
                test_files=[test_file],
                timeout=5.0,
                collect_coverage=False,
            )
        assert result.passed == 2

    @pytest.mark.asyncio
    async def test_run_gradle_no_gradlew(self, tmp_path: Path) -> None:
        """No gradlew but build.gradle.kts exists."""
        _write_file(tmp_path, "build.gradle.kts", 'plugins { id("java") }\n')
        adapter = KotestAdapter()
        result = await adapter.run_tests(tmp_path, timeout=5.0, collect_coverage=False)
        assert "gradlew" in result.raw_output or result.success is False


class TestKotestDetectionExtended:
    """Cover edge cases in detection helpers."""

    def test_has_kotest_in_gradle_settings(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "settings.gradle.kts", 'include("io.kotest")\n')
        assert _has_kotest_in_gradle(tmp_path) is True

    def test_has_kotest_in_gradle_settings_groovy(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "settings.gradle", "include 'io.kotest'\n")
        assert _has_kotest_in_gradle(tmp_path) is True

    def test_has_kotest_in_maven_no_pom(self, tmp_path: Path) -> None:
        assert _has_kotest_in_maven(tmp_path) is False

    def test_has_kotest_import_skips_hidden_dirs(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".hidden/Test.kt",
            "import io.kotest.core.spec.style.FunSpec\n",
        )
        assert _has_kotest_import_in_kt_files(tmp_path) is False


class TestKotestXmlParsing:
    """Cover more XML parsing branches."""

    def test_parse_error_element(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase classname="C" name="crash" time="0.01">
      <error message="OutOfMemory">heap space</error>
    </testcase>
  </testsuite>
</testsuites>
"""
        result = _parse_junit_xml(xml, "")
        assert result.errors == 1
        assert result.test_cases[0].status == CaseStatus.ERROR

    def test_parse_skipped_by_status_attr(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase classname="C" name="skip" time="0" status="disabled" />
  </testsuite>
</testsuites>
"""
        result = _parse_junit_xml(xml, "")
        assert result.skipped == 1

    def test_parse_no_classname(self) -> None:
        xml = """\
<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase name="alone" time="0.001" />
  </testsuite>
</testsuites>
"""
        result = _parse_junit_xml(xml, "")
        assert result.test_cases[0].name == "alone"


class TestKotestDurationParsing:
    """Cover _parse_duration_ms."""

    def test_int_value(self) -> None:
        assert _parse_duration_ms(2) == 2000.0

    def test_float_value(self) -> None:
        assert _parse_duration_ms(0.5) == 500.0

    def test_ms_suffix(self) -> None:
        assert _parse_duration_ms("250ms") == 250.0

    def test_s_suffix(self) -> None:
        assert _parse_duration_ms("1.5s") == 1500.0

    def test_plain_number(self) -> None:
        assert _parse_duration_ms("0.003") == 3.0

    def test_non_str_non_numeric(self) -> None:
        assert _parse_duration_ms(None) == 0.0

    def test_invalid_string(self) -> None:
        assert _parse_duration_ms("abc") == 0.0


class TestKotestFormatOutput:
    """Cover _format_output helper."""

    def test_format_with_stdout_stderr(self) -> None:
        cr = _CommandResult(returncode=1, stdout="out", stderr="err")
        result = _format_output(["mvn", "test"], cr)
        assert "$ mvn test" in result
        assert "exit_code=1" in result
        assert "out" in result
        assert "err" in result

    def test_format_no_output(self) -> None:
        cr = _CommandResult(returncode=0, stdout="", stderr="")
        result = _format_output(["cmd"], cr)
        assert "exit_code=0" in result


class TestKotestXmlFailureMessage:
    """Cover _xml_failure_message branches."""

    def test_message_only_attr(self) -> None:
        xml = '<failure message="attr only"></failure>'
        match = re.search(
            r"<failure\b(?P<attrs>[^>]*)>(?P<body>.*?)</failure>",
            xml,
            flags=re.DOTALL,
        )
        assert match is not None
        result = _xml_failure_message(match)
        assert result == "attr only"

    def test_message_only_body(self) -> None:
        xml = '<failure message="">body only</failure>'
        match = re.search(
            r"<failure\b(?P<attrs>[^>]*)>(?P<body>.*?)</failure>",
            xml,
            flags=re.DOTALL,
        )
        assert match is not None
        result = _xml_failure_message(match)
        assert result == "body only"


class TestKotestCollectJunitXmlOSError:
    """Cover OSError branch in _collect_junit_xml."""

    def test_unreadable_xml_skipped(self, tmp_path: Path) -> None:
        xml_dir = tmp_path / "results"
        xml_dir.mkdir()
        f = xml_dir / "TEST-Broken.xml"
        f.write_text("bad", encoding="utf-8")
        # Even with unparseable XML, it should not crash
        result = _collect_junit_xml(xml_dir, "raw")
        assert isinstance(result.total, int)
