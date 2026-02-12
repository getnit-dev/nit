"""Tests for XUnitAdapter (adapters/unit/xunit_adapter.py).

Covers detection (.csproj + using Xunit), prompt template, TRX parsing,
and tree-sitter validation with sample C# fixtures.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from defusedxml.ElementTree import fromstring

from nit.adapters.base import CaseStatus, TestFrameworkAdapter, ValidationResult
from nit.adapters.unit.xunit_adapter import (
    XUnitAdapter,
    _CommandResult,
    _extract_failure_message,
    _find_sln_or_csproj,
    _has_test_files,
    _has_xunit_csproj,
    _has_xunit_import,
    _outcome_to_status,
    _parse_duration,
    _parse_trx,
    _run_command,
)
from nit.llm.prompts.xunit_prompt import XUnitTemplate


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


# ── Sample TRX XML ────────────────────────────────────────────────

_TRX_TWO_PASSED = """\
<?xml version="1.0" encoding="utf-8"?>
<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <Results>
    <UnitTestResult testName="Calc.Add" outcome="Passed" duration="0:00:00.012" />
    <UnitTestResult testName="Calc.Divide" outcome="Passed" duration="0:00:00.008" />
  </Results>
</TestRun>
"""

_TRX_WITH_FAILURE = """\
<?xml version="1.0" encoding="utf-8"?>
<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <Results>
    <UnitTestResult testName="ParserTests.ParsesValid" outcome="Passed" duration="0:00:00.005" />
    <UnitTestResult testName="ParserTests.RejectsInvalid" outcome="Failed" duration="0:00:00.010">
      <Output>
        <ErrorInfo>
          <Message>Assert.Equal() Failure: Expected invalid input to fail</Message>
        </ErrorInfo>
      </Output>
    </UnitTestResult>
  </Results>
</TestRun>
"""

_TRX_SKIPPED = """\
<?xml version="1.0" encoding="utf-8"?>
<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <Results>
    <UnitTestResult testName="FeatureTests.EnabledTest" outcome="Passed" duration="0:00:00.001" />
    <UnitTestResult testName="FeatureTests.SkippedTest" outcome="Skipped" duration="0:00:00.000" />
  </Results>
</TestRun>
"""

_VALID_CSHARP = """\
using Xunit;

public class CalculatorTests
{
    [Fact]
    public void Add_ReturnsSum_WhenGivenTwoNumbers()
    {
        Assert.Equal(5, 2 + 3);
    }
}
"""

_INVALID_CSHARP = """\
using Xunit;

public class BrokenTest
{
    [Fact]
    public void MissingBrace()
    {
        Assert.Equal(1, 1);
"""


# ── Identity ─────────────────────────────────────────────────────


class TestXUnitAdapterIdentity:
    def test_implements_test_framework_adapter(self) -> None:
        assert isinstance(XUnitAdapter(), TestFrameworkAdapter)

    def test_name(self) -> None:
        assert XUnitAdapter().name == "xunit"

    def test_language(self) -> None:
        assert XUnitAdapter().language == "csharp"


# ── Detection ────────────────────────────────────────────────────


class TestXUnitDetection:
    def test_detect_csproj_xunit(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "MyTests.csproj",
            '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="xunit" '
            'Version="2.6.0" /></ItemGroup></Project>',
        )
        assert XUnitAdapter().detect(tmp_path) is True

    def test_detect_import_and_test_files(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "tests/CalculatorTests.cs", _VALID_CSHARP)
        assert XUnitAdapter().detect(tmp_path) is True

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert XUnitAdapter().detect(tmp_path) is False

    def test_no_detection_csproj_without_xunit(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "App.csproj",
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            "<TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>",
        )
        assert XUnitAdapter().detect(tmp_path) is False


class TestXUnitDetectionHelpers:
    def test_has_xunit_csproj_true(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "Tests.csproj",
            '<ItemGroup><PackageReference Include="xunit" Version="2.6.0" /></ItemGroup>',
        )
        assert _has_xunit_csproj(tmp_path) is True

    def test_has_xunit_csproj_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "App.csproj", "<Project></Project>")
        assert _has_xunit_csproj(tmp_path) is False

    def test_has_xunit_import_true(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "FooTests.cs", "using Xunit;\npublic class Foo { }\n")
        assert _has_xunit_import(tmp_path) is True

    def test_has_xunit_import_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "Program.cs", "public class Program { }\n")
        assert _has_xunit_import(tmp_path) is False

    def test_has_test_files_true(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["CalculatorTests.cs"])
        assert _has_test_files(tmp_path) is True

    def test_has_test_files_false(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["Program.cs"])
        assert _has_test_files(tmp_path) is False


# ── Test patterns ────────────────────────────────────────────────


class TestXUnitPatterns:
    def test_returns_list_of_patterns(self) -> None:
        patterns = XUnitAdapter().get_test_pattern()
        assert isinstance(patterns, list)
        assert len(patterns) >= 2

    def test_includes_tests_cs_pattern(self) -> None:
        patterns = XUnitAdapter().get_test_pattern()
        assert "**/*Tests.cs" in patterns

    def test_includes_test_cs_pattern(self) -> None:
        patterns = XUnitAdapter().get_test_pattern()
        assert "**/*Test.cs" in patterns


# ── Prompt template ──────────────────────────────────────────────


class TestXUnitPromptTemplate:
    def test_returns_xunit_template(self) -> None:
        template = XUnitAdapter().get_prompt_template()
        assert isinstance(template, XUnitTemplate)

    def test_template_name(self) -> None:
        template = XUnitAdapter().get_prompt_template()
        assert template.name == "xunit"


# ── TRX parsing ──────────────────────────────────────────────────


class TestXUnitTrxParsing:
    def test_parse_all_pass(self, tmp_path: Path) -> None:
        trx_path = tmp_path / "results.trx"
        trx_path.write_text(_TRX_TWO_PASSED)
        result = _parse_trx(trx_path, _TRX_TWO_PASSED)
        assert result.success is True
        assert result.passed == 2
        assert result.failed == 0
        assert result.skipped == 0
        assert result.errors == 0
        assert len(result.test_cases) == 2
        assert all(c.status == CaseStatus.PASSED for c in result.test_cases)

    def test_parse_with_failure(self, tmp_path: Path) -> None:
        trx_path = tmp_path / "results.trx"
        trx_path.write_text(_TRX_WITH_FAILURE)
        result = _parse_trx(trx_path, _TRX_WITH_FAILURE)
        assert result.success is False
        assert result.passed == 1
        assert result.failed == 1
        assert len(result.test_cases) == 2
        failed_case = next(c for c in result.test_cases if c.status == CaseStatus.FAILED)
        assert (
            "Assert.Equal" in failed_case.failure_message
            or "invalid" in failed_case.failure_message.lower()
        )

    def test_parse_with_skipped(self, tmp_path: Path) -> None:
        trx_path = tmp_path / "results.trx"
        trx_path.write_text(_TRX_SKIPPED)
        result = _parse_trx(trx_path, _TRX_SKIPPED)
        assert result.passed == 1
        assert result.skipped == 1
        assert len(result.test_cases) == 2
        skipped_case = next(c for c in result.test_cases if c.status == CaseStatus.SKIPPED)
        assert skipped_case.name == "FeatureTests.SkippedTest"


# ── Validation ────────────────────────────────────────────────────


class TestXUnitValidation:
    def test_validate_valid_csharp(self) -> None:
        result = XUnitAdapter().validate_test(_VALID_CSHARP)
        assert isinstance(result, ValidationResult)
        assert result.valid is True
        assert result.errors == []

    def test_validate_invalid_csharp(self) -> None:
        result = XUnitAdapter().validate_test(_INVALID_CSHARP)
        assert result.valid is False
        assert len(result.errors) >= 1


# ── run_tests (no dotnet; expect no TRX) ─────────────────────────


class TestXUnitRunTests:
    @pytest.mark.asyncio
    async def test_run_tests_no_sln_or_csproj_returns_false(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "FooTests.cs", _VALID_CSHARP)
        adapter = XUnitAdapter()
        result = await adapter.run_tests(tmp_path, timeout=5.0)
        assert result.success is False
        assert "No .sln or .csproj" in result.raw_output or result.raw_output


# ── Additional coverage tests ─────────────────────────────────────


class TestXUnitDurationParsing:
    """Tests for _parse_duration covering all branches."""

    def test_parse_int_small(self) -> None:
        # Small int => multiply by 1000
        assert _parse_duration(2) == 2000.0

    def test_parse_int_large(self) -> None:
        # Larger than 1000 => already ms
        assert _parse_duration(5000) == 5000.0

    def test_parse_float_small(self) -> None:
        assert _parse_duration(0.5) == 500.0

    def test_parse_non_str_non_numeric(self) -> None:
        assert _parse_duration(None) == 0.0
        assert _parse_duration([]) == 0.0

    def test_parse_trx_format(self) -> None:
        result = _parse_duration("0:01:02.5")
        assert result == 62500.0  # 62.5 seconds in ms

    def test_parse_non_trx_format(self) -> None:
        assert _parse_duration("1.5") == 1500.0

    def test_parse_invalid_string(self) -> None:
        assert _parse_duration("abc") == 0.0

    def test_parse_invalid_trx_parts(self) -> None:
        assert _parse_duration("x:y:z") == 0.0


class TestXUnitOutcomeToStatus:
    """Tests for _outcome_to_status covering all branches."""

    def test_passed(self) -> None:
        assert _outcome_to_status("Passed") == CaseStatus.PASSED

    def test_failed(self) -> None:
        assert _outcome_to_status("Failed") == CaseStatus.FAILED

    def test_error(self) -> None:
        assert _outcome_to_status("Error") == CaseStatus.FAILED

    def test_not_executed(self) -> None:
        assert _outcome_to_status("NotExecuted") == CaseStatus.SKIPPED

    def test_skipped(self) -> None:
        assert _outcome_to_status("Skipped") == CaseStatus.SKIPPED

    def test_ignored(self) -> None:
        assert _outcome_to_status("Ignored") == CaseStatus.SKIPPED

    def test_unknown_outcome(self) -> None:
        assert _outcome_to_status("SomethingElse") == CaseStatus.ERROR


class TestXUnitTrxParsingExtended:
    """Extended TRX parsing tests."""

    def test_parse_invalid_xml(self, tmp_path: Path) -> None:
        trx_path = tmp_path / "bad.trx"
        trx_path.write_text("this is not xml at all")
        result = _parse_trx(trx_path, "raw")
        assert result.total == 0

    def test_parse_missing_file(self, tmp_path: Path) -> None:
        result = _parse_trx(tmp_path / "nonexistent.trx", "raw")
        assert result.total == 0

    def test_parse_unknown_outcome(self, tmp_path: Path) -> None:
        trx_xml = """\
<?xml version="1.0" encoding="utf-8"?>
<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <Results>
    <UnitTestResult testName="Test.Unknown" outcome="WeirdOutcome" duration="0:00:00.001" />
  </Results>
</TestRun>
"""
        trx_path = tmp_path / "results.trx"
        trx_path.write_text(trx_xml)
        result = _parse_trx(trx_path, trx_xml)
        assert result.errors == 1
        assert result.test_cases[0].status == CaseStatus.ERROR

    def test_parse_failure_with_stack_trace(self, tmp_path: Path) -> None:
        trx_xml = """\
<?xml version="1.0" encoding="utf-8"?>
<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <Results>
    <UnitTestResult testName="Test.Fail" outcome="Failed" duration="0:00:00.010">
      <Output>
        <ErrorInfo>
          <StackTrace>at Foo.Bar() in Bar.cs:line 42</StackTrace>
        </ErrorInfo>
      </Output>
    </UnitTestResult>
  </Results>
</TestRun>
"""
        trx_path = tmp_path / "results.trx"
        trx_path.write_text(trx_xml)
        result = _parse_trx(trx_path, trx_xml)
        assert result.failed == 1
        failed = result.test_cases[0]
        assert "Bar.cs" in failed.failure_message


class TestXUnitDetectionExtended:
    """Extended detection tests."""

    def test_has_xunit_csproj_hidden_file_skipped(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".hidden.csproj",
            '<PackageReference Include="xunit" />',
        )
        assert _has_xunit_csproj(tmp_path) is False

    def test_has_xunit_import_hidden_file_skipped(self, tmp_path: Path) -> None:
        _write_file(tmp_path, ".hidden.cs", "using Xunit;\n")
        assert _has_xunit_import(tmp_path) is False


class TestXUnitFindSlnOrCsproj:
    """Tests for _find_sln_or_csproj."""

    def test_find_sln(self, tmp_path: Path) -> None:
        sln = tmp_path / "App.sln"
        sln.touch()
        result = _find_sln_or_csproj(tmp_path)
        assert result == sln

    def test_find_test_csproj(self, tmp_path: Path) -> None:
        csproj = _write_file(
            tmp_path,
            "Tests.csproj",
            '<PackageReference Include="xunit" Version="2.6" />',
        )
        result = _find_sln_or_csproj(tmp_path)
        assert result == csproj

    def test_find_fallback_csproj(self, tmp_path: Path) -> None:
        csproj = tmp_path / "App.csproj"
        csproj.write_text("<Project/>")
        result = _find_sln_or_csproj(tmp_path)
        assert result == csproj

    def test_find_nothing(self, tmp_path: Path) -> None:
        assert _find_sln_or_csproj(tmp_path) is None


class TestXUnitExtractFailureMessage:
    """Tests for _extract_failure_message covering branches."""

    def test_extract_from_message_child(self) -> None:
        xml_str = "<Result><Message>direct message</Message></Result>"
        elem = fromstring(xml_str)
        assert _extract_failure_message(elem) == "direct message"

    def test_extract_empty_for_no_match(self) -> None:
        xml_str = "<Result><SomethingElse>data</SomethingElse></Result>"
        elem = fromstring(xml_str)
        assert _extract_failure_message(elem) == ""

    def test_extract_from_output_errorinfo_non_error_child(self) -> None:
        """Cover the branch where Output child is not ErrorInfo."""
        xml_str = "<Result><Output><NotErrorInfo>data</NotErrorInfo></Output></Result>"
        elem = fromstring(xml_str)
        assert _extract_failure_message(elem) == ""

    def test_extract_from_errorinfo_empty(self) -> None:
        """ErrorInfo with no Message or StackTrace returns empty string."""
        xml_str = "<Result><Output><ErrorInfo></ErrorInfo></Output></Result>"
        elem = fromstring(xml_str)
        assert _extract_failure_message(elem) == ""


# ── Additional coverage: missing lines ────────────────────────────


class TestXUnitRunCommand:
    """Cover _run_command helper."""

    @pytest.mark.asyncio
    async def test_run_command_success(self, tmp_path: Path) -> None:
        result = await _run_command(["echo", "hello"], cwd=tmp_path, timeout=10.0)
        assert result.returncode == 0
        assert "hello" in result.stdout

    @pytest.mark.asyncio
    async def test_run_command_file_not_found(self, tmp_path: Path) -> None:
        result = await _run_command(["nonexistent_binary_xyz"], cwd=tmp_path, timeout=10.0)
        assert result.not_found is True
        assert result.returncode == 127


class TestXUnitDetectionExtendedMore:
    """Cover more detection branches."""

    def test_has_xunit_import_hidden_cs_file(self, tmp_path: Path) -> None:
        _write_file(tmp_path, ".hidden.cs", "using Xunit;\n")
        assert _has_xunit_import(tmp_path) is False

    def test_has_xunit_csproj_no_match(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "App.csproj", "<Project></Project>")
        assert _has_xunit_csproj(tmp_path) is False

    def test_has_test_files_mixed(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["FooTest.cs"])
        assert _has_test_files(tmp_path) is True


class TestXUnitFindSlnOrCsprojExtended:
    """Cover more _find_sln_or_csproj branches."""

    def test_find_nothing_in_empty_dir(self, tmp_path: Path) -> None:
        result = _find_sln_or_csproj(tmp_path)
        assert result is None

    def test_prefers_sln_over_csproj(self, tmp_path: Path) -> None:
        sln = tmp_path / "App.sln"
        sln.touch()
        _write_file(tmp_path, "Tests.csproj", '<PackageReference Include="xunit" />')
        result = _find_sln_or_csproj(tmp_path)
        assert result == sln


class TestXUnitRunTestsExtended:
    """Cover more run_tests branches."""

    @pytest.mark.asyncio
    async def test_run_tests_with_trx_and_test_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(
            tmp_path,
            "Tests.csproj",
            '<PackageReference Include="xunit" Version="2.6" />',
        )
        trx_dir = tmp_path / "TestResults"
        trx_dir.mkdir()
        trx_path = trx_dir / "nit_results.trx"
        trx_path.write_text(_TRX_TWO_PASSED)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"out", b"err"))

        monkeypatch.setattr(
            "nit.adapters.unit.xunit_adapter.asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        )
        test_file = tmp_path / "FooTests.cs"
        test_file.write_text(_VALID_CSHARP)
        adapter = XUnitAdapter()
        result = await adapter.run_tests(
            tmp_path,
            test_files=[test_file],
            timeout=5.0,
            collect_coverage=False,
        )
        assert result.passed == 2
        assert result.total == 2

    @pytest.mark.asyncio
    async def test_run_tests_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(
            tmp_path,
            "Tests.csproj",
            '<PackageReference Include="xunit" Version="2.6" />',
        )

        async def _fake_run_command(cmd: list[str], *, cwd: Path, timeout: float) -> _CommandResult:
            return _CommandResult(returncode=1, stdout="", stderr="timed out", timed_out=True)

        monkeypatch.setattr("nit.adapters.unit.xunit_adapter._run_command", _fake_run_command)
        adapter = XUnitAdapter()
        result = await adapter.run_tests(tmp_path, timeout=5.0, collect_coverage=False)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_run_tests_not_found(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(
            tmp_path,
            "Tests.csproj",
            '<PackageReference Include="xunit" Version="2.6" />',
        )

        async def _fake_run_command(cmd: list[str], *, cwd: Path, timeout: float) -> _CommandResult:
            return _CommandResult(returncode=127, stdout="", stderr="not found", not_found=True)

        monkeypatch.setattr("nit.adapters.unit.xunit_adapter._run_command", _fake_run_command)
        adapter = XUnitAdapter()
        result = await adapter.run_tests(tmp_path, timeout=5.0, collect_coverage=False)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_run_tests_no_trx_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_file(
            tmp_path,
            "Tests.csproj",
            '<PackageReference Include="xunit" Version="2.6" />',
        )

        async def _fake_run_command(cmd: list[str], *, cwd: Path, timeout: float) -> _CommandResult:
            return _CommandResult(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr("nit.adapters.unit.xunit_adapter._run_command", _fake_run_command)
        adapter = XUnitAdapter()
        result = await adapter.run_tests(tmp_path, timeout=5.0, collect_coverage=False)
        assert result.success is False
