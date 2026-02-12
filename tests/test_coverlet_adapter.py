"""Tests for Coverlet adapter (adapters/coverage/coverlet_adapter.py).

Covers detection (.csproj with coverlet or existing Cobertura report),
coverage parsing from Cobertura XML, and unified CoverageReport generation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from defusedxml.ElementTree import fromstring

from nit.adapters.coverage.coverlet_adapter import (
    CoverletAdapter,
    _find_cobertura_report,
    _int_attr,
    _parse_cobertura_xml,
    _process_line_elem,
)


def _write_file(root: Path, rel: str, content: str) -> Path:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


# ── Sample Cobertura XML ─────────────────────────────────────────

_COBERTURA_XML_SAMPLE = """\
<?xml version="1.0" encoding="utf-8"?>
<coverage line-rate="0.8" branch-rate="0.5" lines-covered="4" lines-valid="5">
  <packages>
    <package name="MyApp" line-rate="0.8" branch-rate="0.5">
      <classes>
        <class name="MyApp.Calculator" filename="Calculator.cs" line-rate="0.8" branch-rate="0.5">
          <lines>
            <line number="10" hits="2"/>
            <line number="11" hits="1"/>
            <line number="12" hits="1"/>
            <line number="14" hits="2" branch="true" condition-coverage="50% (1/2)"/>
            <line number="15" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""

_COBERTURA_XML_MINIMAL = """\
<?xml version="1.0" encoding="utf-8"?>
<coverage line-rate="0.66" branch-rate="0" lines-covered="2" lines-valid="3">
  <packages>
    <package name="foo">
      <classes>
        <class name="foo.Bar" filename="Bar.cs">
          <lines>
            <line number="1" hits="1"/>
            <line number="2" hits="1"/>
            <line number="3" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""

_COBERTURA_XML_EMPTY = """\
<?xml version="1.0" encoding="utf-8"?>
<coverage line-rate="0" branch-rate="0">
</coverage>
"""


# ── Identity ─────────────────────────────────────────────────────


class TestCoverletAdapterIdentity:
    def test_name(self) -> None:
        assert CoverletAdapter().name == "coverlet"

    def test_language(self) -> None:
        assert CoverletAdapter().language == "csharp"


# ── Detection ────────────────────────────────────────────────────


class TestCoverletDetection:
    def test_detect_csproj_coverlet(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "MyTests.csproj",
            '<Project><ItemGroup><PackageReference Include="coverlet.collector" />'
            "</ItemGroup></Project>",
        )
        assert CoverletAdapter().detect(tmp_path) is True

    def test_detect_existing_report(self, tmp_path: Path) -> None:
        (tmp_path / "coverage.cobertura.xml").write_text(_COBERTURA_XML_MINIMAL)
        assert CoverletAdapter().detect(tmp_path) is True

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert CoverletAdapter().detect(tmp_path) is False

    def test_no_detection_csproj_without_coverlet(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "App.csproj",
            '<Project Sdk="Microsoft.NET.Sdk"></Project>',
        )
        assert CoverletAdapter().detect(tmp_path) is False


# ── Parsing ──────────────────────────────────────────────────────


class TestCoverletParsing:
    def test_parse_sample_xml(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "coverage.cobertura.xml"
        xml_path.write_text(_COBERTURA_XML_SAMPLE)
        report = CoverletAdapter().parse_coverage_file(xml_path)
        assert report.files
        file_paths = list(report.files.keys())
        assert any("Calculator" in p for p in file_paths)
        for fc in report.files.values():
            assert fc.lines
            assert report.overall_line_coverage >= 0.0

    def test_parse_minimal_xml(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "cobertura.xml"
        xml_path.write_text(_COBERTURA_XML_MINIMAL)
        report = _parse_cobertura_xml(xml_path)
        assert report.files
        assert len(report.files) >= 1
        fc = next(iter(report.files.values()))
        assert len(fc.lines) == 3
        covered = sum(1 for ln in fc.lines if ln.execution_count > 0)
        assert covered == 2

    def test_parse_empty_coverage_returns_empty_report(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "empty.xml"
        xml_path.write_text(_COBERTURA_XML_EMPTY)
        report = _parse_cobertura_xml(xml_path)
        assert report.files == {}
        assert report.overall_line_coverage == 100.0


# ── Additional coverage tests ─────────────────────────────────────

_COBERTURA_XML_WITH_METHOD = """\
<?xml version="1.0" encoding="utf-8"?>
<coverage line-rate="1.0" branch-rate="0">
  <packages>
    <package name="App">
      <classes>
        <class name="App.Calculator" filename="Calculator.cs">
          <method name="Add" signature="(int,int)">
            <line number="5" hits="3"/>
          </method>
          <lines>
            <line number="5" hits="3"/>
            <line number="6" hits="2"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""

_COBERTURA_XML_BRANCH_LINE = """\
<?xml version="1.0" encoding="utf-8"?>
<coverage line-rate="0.5" branch-rate="0.5">
  <packages>
    <package name="App">
      <classes>
        <class name="App.Logic" filename="Logic.cs">
          <lines>
            <line number="10" hits="2" branch="true" condition-coverage="50% (1/2)"/>
            <line number="11" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""

_COBERTURA_XML_NO_FILENAME = """\
<?xml version="1.0" encoding="utf-8"?>
<coverage line-rate="0.5">
  <packages>
    <package name="MyPkg">
      <classes>
        <class name="MyPkg.Util">
          <lines>
            <line number="1" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


class TestCoverletParsingExtended:
    """Extended parsing tests for branches and edge cases."""

    def test_parse_with_method_elements(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "cov.xml"
        xml_path.write_text(_COBERTURA_XML_WITH_METHOD)
        report = _parse_cobertura_xml(xml_path)
        assert len(report.files) >= 1
        fc = next(iter(report.files.values()))
        # Should have at least the method function
        assert any(f.name.startswith("Add") for f in fc.functions)

    def test_parse_branch_lines(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "cov.xml"
        xml_path.write_text(_COBERTURA_XML_BRANCH_LINE)
        report = _parse_cobertura_xml(xml_path)
        fc = next(iter(report.files.values()))
        assert len(fc.branches) == 1
        assert fc.branches[0].taken_count == 1
        assert fc.branches[0].total_count == 2

    def test_parse_class_without_filename(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "cov.xml"
        xml_path.write_text(_COBERTURA_XML_NO_FILENAME)
        report = _parse_cobertura_xml(xml_path)
        assert len(report.files) >= 1

    def test_parse_invalid_xml(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "bad.xml"
        xml_path.write_text("this is not xml at all")
        report = _parse_cobertura_xml(xml_path)
        assert report.files == {}

    def test_parse_non_coverage_root(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "wrong.xml"
        xml_path.write_text('<?xml version="1.0"?><notcoverage/>')
        report = _parse_cobertura_xml(xml_path)
        assert report.files == {}

    def test_parse_missing_file(self, tmp_path: Path) -> None:
        report = _parse_cobertura_xml(tmp_path / "missing.xml")
        assert report.files == {}


class TestCoverletFindReport:
    """Tests for _find_cobertura_report."""

    def test_find_standard_name(self, tmp_path: Path) -> None:
        (tmp_path / "coverage.cobertura.xml").write_text(_COBERTURA_XML_MINIMAL)
        result = _find_cobertura_report(tmp_path)
        assert result is not None
        assert result.name == "coverage.cobertura.xml"

    def test_find_cobertura_name(self, tmp_path: Path) -> None:
        (tmp_path / "cobertura.xml").write_text(_COBERTURA_XML_MINIMAL)
        result = _find_cobertura_report(tmp_path)
        assert result is not None
        assert result.name == "cobertura.xml"

    def test_find_in_test_results(self, tmp_path: Path) -> None:
        tr_dir = tmp_path / "TestResults" / "guid"
        tr_dir.mkdir(parents=True)
        (tr_dir / "coverage.cobertura.xml").write_text(_COBERTURA_XML_MINIMAL)
        result = _find_cobertura_report(tmp_path)
        assert result is not None

    def test_find_coverage_xml_in_test_results(self, tmp_path: Path) -> None:
        tr_dir = tmp_path / "TestResults"
        tr_dir.mkdir()
        (tr_dir / "coverage.xml").write_text(_COBERTURA_XML_MINIMAL)
        result = _find_cobertura_report(tmp_path)
        assert result is not None

    def test_find_nothing(self, tmp_path: Path) -> None:
        assert _find_cobertura_report(tmp_path) is None


class TestCoverletDetectionExtended:
    """Extended detection tests."""

    def test_detect_hidden_csproj_skipped(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".hidden.csproj",
            '<PackageReference Include="coverlet.collector" />',
        )
        assert CoverletAdapter().detect(tmp_path) is False

    def test_detect_coverlet_in_nested_csproj(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path / "tests",
            "Tests.csproj",
            '<Project><ItemGroup><PackageReference Include="coverlet.msbuild" />'
            "</ItemGroup></Project>",
        )
        assert CoverletAdapter().detect(tmp_path) is True


class TestCoverletIntAttr:
    """Tests for _int_attr helper."""

    def test_valid_int(self) -> None:
        elem = fromstring('<line number="42"/>')
        assert _int_attr(elem, "number") == 42

    def test_missing_attr(self) -> None:
        elem = fromstring("<line/>")
        assert _int_attr(elem, "number") == 0

    def test_invalid_value(self) -> None:
        elem = fromstring('<line number="abc"/>')
        assert _int_attr(elem, "number") == 0

    def test_custom_default(self) -> None:
        elem = fromstring("<line/>")
        assert _int_attr(elem, "number", default=99) == 99


class TestCoverletProcessLineElem:
    """Tests for _process_line_elem branch coverage parsing."""

    def test_non_branch_line(self) -> None:
        elem = fromstring('<line number="1" hits="5"/>')
        lines: list[object] = []
        branches: list[object] = []
        _process_line_elem(elem, lines, branches)  # type: ignore[arg-type]
        assert len(lines) == 1
        assert len(branches) == 0

    def test_branch_line_without_condition_coverage(self) -> None:
        elem = fromstring('<line number="2" hits="1" branch="true"/>')
        lines: list[object] = []
        branches: list[object] = []
        _process_line_elem(elem, lines, branches)  # type: ignore[arg-type]
        assert len(lines) == 1
        assert len(branches) == 0

    def test_branch_line_with_condition_coverage(self) -> None:
        elem = fromstring(
            '<line number="3" hits="2" branch="true" condition-coverage="75% (3/4)"/>'
        )
        lines: list[object] = []
        branches: list[object] = []
        _process_line_elem(elem, lines, branches)  # type: ignore[arg-type]
        assert len(branches) == 1

    def test_branch_line_invalid_condition_coverage(self) -> None:
        """Should not crash on malformed condition-coverage value."""
        elem = fromstring(
            '<line number="4" hits="1" branch="true" condition-coverage="bad(data)"/>'
        )
        lines: list[object] = []
        branches: list[object] = []
        _process_line_elem(elem, lines, branches)  # type: ignore[arg-type]
        assert len(lines) == 1
        # Malformed, so no branch parsed
        assert len(branches) == 0


# ── Coverage gap tests: run_coverage, merging, edge cases ─────────────

_COBERTURA_XML_MERGE = """\
<?xml version="1.0" encoding="utf-8"?>
<coverage line-rate="0.5">
  <packages>
    <package name="App">
      <classes>
        <class name="App.Svc" filename="Svc.cs">
          <lines>
            <line number="1" hits="1"/>
          </lines>
        </class>
        <class name="App.Svc" filename="Svc.cs">
          <lines>
            <line number="2" hits="2"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""

_COBERTURA_XML_LINE_DIRECT = """\
<?xml version="1.0" encoding="utf-8"?>
<coverage line-rate="1.0">
  <packages>
    <package name="App">
      <classes>
        <class name="App.Direct" filename="Direct.cs">
          <line number="1" hits="3"/>
          <lines>
            <line number="2" hits="5"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""

_COBERTURA_XML_ABS_PATH = """\
<?xml version="1.0" encoding="utf-8"?>
<coverage line-rate="1.0">
  <packages>
    <package name="App">
      <classes>
        <class name="App.Abs" filename="/absolute/path/Abs.cs">
          <lines>
            <line number="1" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


class TestCoverletParsingGaps:
    """Tests that close remaining coverage gaps."""

    def test_parse_merges_same_filename(self, tmp_path: Path) -> None:
        """Two class elements with same filename should merge lines."""
        xml_path = tmp_path / "merge.xml"
        xml_path.write_text(_COBERTURA_XML_MERGE)
        report = _parse_cobertura_xml(xml_path)
        assert len(report.files) == 1
        fc = next(iter(report.files.values()))
        assert len(fc.lines) == 2

    def test_parse_line_direct_child(self, tmp_path: Path) -> None:
        """<line> as direct child of <class> should be parsed."""
        xml_path = tmp_path / "direct.xml"
        xml_path.write_text(_COBERTURA_XML_LINE_DIRECT)
        report = _parse_cobertura_xml(xml_path)
        fc = next(iter(report.files.values()))
        assert len(fc.lines) == 2

    def test_parse_absolute_path_not_prefixed(self, tmp_path: Path) -> None:
        """Filename starting with / should not be prefixed with pkg."""
        xml_path = tmp_path / "abs.xml"
        xml_path.write_text(_COBERTURA_XML_ABS_PATH)
        report = _parse_cobertura_xml(xml_path)
        assert "/absolute/path/Abs.cs" in report.files

    def test_find_cobertura_no_test_results(self, tmp_path: Path) -> None:
        """_find_cobertura_report returns None if TestResults is not a dir."""
        # No TestResults dir at all
        assert _find_cobertura_report(tmp_path) is None


class TestCoverletRunCoverage:
    """Tests for run_coverage async method."""

    @pytest.mark.asyncio
    async def test_run_coverage_no_sln_or_csproj(self, tmp_path: Path) -> None:
        """Returns empty report when no .sln or .csproj found."""
        adapter = CoverletAdapter()
        report = await adapter.run_coverage(tmp_path)
        assert len(report.files) == 0

    @pytest.mark.asyncio
    async def test_run_coverage_timeout(self, tmp_path: Path) -> None:
        """Returns empty report on timeout."""
        (tmp_path / "App.sln").write_text("sln content")
        adapter = CoverletAdapter()
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as mock_proc:
            proc = AsyncMock()
            proc.communicate = AsyncMock(side_effect=TimeoutError)
            mock_proc.return_value = proc
            report = await adapter.run_coverage(tmp_path, timeout=0.01)
        assert len(report.files) == 0

    @pytest.mark.asyncio
    async def test_run_coverage_dotnet_not_found(self, tmp_path: Path) -> None:
        """Returns empty report when dotnet not found."""
        (tmp_path / "App.csproj").write_text("<Project/>")
        adapter = CoverletAdapter()
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("dotnet"),
        ):
            report = await adapter.run_coverage(tmp_path)
        assert len(report.files) == 0

    @pytest.mark.asyncio
    async def test_run_coverage_success_with_report(self, tmp_path: Path) -> None:
        """Parses Cobertura report when found after dotnet test."""
        (tmp_path / "App.csproj").write_text("<Project/>")
        (tmp_path / "coverage.cobertura.xml").write_text(_COBERTURA_XML_MINIMAL)
        adapter = CoverletAdapter()
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as mock_proc:
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.returncode = 0
            mock_proc.return_value = proc
            report = await adapter.run_coverage(tmp_path)
        assert len(report.files) >= 1

    @pytest.mark.asyncio
    async def test_run_coverage_with_test_files(self, tmp_path: Path) -> None:
        """run_coverage adds filter when test_files provided."""
        (tmp_path / "App.sln").write_text("sln")
        (tmp_path / "coverage.cobertura.xml").write_text(_COBERTURA_XML_MINIMAL)
        adapter = CoverletAdapter()
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as mock_proc:
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.returncode = 0
            mock_proc.return_value = proc
            report = await adapter.run_coverage(
                tmp_path,
                test_files=[tmp_path / "TestCalc.cs"],
            )
        assert len(report.files) >= 1

    @pytest.mark.asyncio
    async def test_run_coverage_no_report_after_run(self, tmp_path: Path) -> None:
        """Returns empty report when dotnet test produces no report."""
        (tmp_path / "App.csproj").write_text("<Project/>")
        adapter = CoverletAdapter()
        with patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as mock_proc:
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.returncode = 0
            mock_proc.return_value = proc
            report = await adapter.run_coverage(tmp_path)
        assert len(report.files) == 0


class TestCoverletDetectOSError:
    """Test detect() when csproj read fails."""

    def test_detect_csproj_oserror(self, tmp_path: Path) -> None:
        """Handles OSError reading csproj files."""
        _write_file(tmp_path, "Bad.csproj", "coverlet inside")
        adapter = CoverletAdapter()
        with patch.object(Path, "read_text", side_effect=OSError("perm denied")):
            # Falls back to _find_cobertura_report
            result = adapter.detect(tmp_path)
        assert result is False
