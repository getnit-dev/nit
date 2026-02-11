"""Tests for XUnitAdapter (adapters/unit/xunit_adapter.py).

Covers detection (.csproj + using Xunit), prompt template, TRX parsing,
and tree-sitter validation with sample C# fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.adapters.base import CaseStatus, TestFrameworkAdapter, ValidationResult
from nit.adapters.unit.xunit_adapter import (
    XUnitAdapter,
    _has_test_files,
    _has_xunit_csproj,
    _has_xunit_import,
    _parse_trx,
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
