"""Tests for Coverlet adapter (adapters/coverage/coverlet_adapter.py).

Covers detection (.csproj with coverlet or existing Cobertura report),
coverage parsing from Cobertura XML, and unified CoverageReport generation.
"""

from __future__ import annotations

from pathlib import Path

from nit.adapters.coverage.coverlet_adapter import (
    CoverletAdapter,
    _parse_cobertura_xml,
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
