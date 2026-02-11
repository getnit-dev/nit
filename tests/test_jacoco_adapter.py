"""Tests for JaCoCo adapter (adapters/coverage/jacoco.py).

Covers detection (Gradle/Maven), coverage parsing from JaCoCo XML,
and unified CoverageReport generation.
"""

from __future__ import annotations

from pathlib import Path

from nit.adapters.coverage.jacoco import JaCoCoAdapter, _parse_jacoco_xml


def _write_file(root: Path, rel: str, content: str) -> Path:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


# ── Sample JaCoCo XML ────────────────────────────────────────────

_JACOCO_XML_SAMPLE = """\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<report name="jacoco">
  <package name="com/example">
    <class name="com/example/Calculator" sourcefilename="Calculator.java">
      <method name="add" desc="(II)I" line="10"/>
      <method name="subtract" desc="(II)I" line="14"/>
      <counter type="INSTRUCTION" missed="2" covered="8"/>
      <counter type="BRANCH" missed="0" covered="2"/>
      <counter type="LINE" missed="1" covered="5"/>
      <counter type="METHOD" missed="0" covered="2"/>
      <line nr="10" mi="0" ci="2" mb="0" cb="0"/>
      <line nr="11" mi="0" ci="1" mb="0" cb="0"/>
      <line nr="12" mi="0" ci="1" mb="0" cb="0"/>
      <line nr="14" mi="0" ci="2" mb="0" cb="1"/>
      <line nr="15" mi="1" ci="0" mb="0" cb="0"/>
    </class>
  </package>
</report>
"""

_JACOCO_XML_MINIMAL = """\
<?xml version="1.0" encoding="UTF-8"?>
<report name="jacoco">
  <package name="foo">
    <class name="foo/Bar" sourcefilename="Bar.java">
      <counter type="LINE" missed="1" covered="2"/>
      <line nr="1" mi="0" ci="1" mb="0" cb="0"/>
      <line nr="2" mi="0" ci="1" mb="0" cb="0"/>
      <line nr="3" mi="1" ci="0" mb="0" cb="0"/>
    </class>
  </package>
</report>
"""

_JACOCO_XML_EMPTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<report name="jacoco">
</report>
"""


# ── Identity ─────────────────────────────────────────────────────


class TestJaCoCoAdapterIdentity:
    def test_name(self) -> None:
        assert JaCoCoAdapter().name == "jacoco"

    def test_language(self) -> None:
        assert JaCoCoAdapter().language == "java"


# ── Detection ────────────────────────────────────────────────────


class TestJaCoCoDetection:
    def test_detect_gradle_jacoco(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "build.gradle", "plugins { id 'jacoco' }\n")
        assert JaCoCoAdapter().detect(tmp_path) is True

    def test_detect_gradle_kts_jacoco(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "build.gradle.kts", "plugins { jacoco }\n")
        assert JaCoCoAdapter().detect(tmp_path) is True

    def test_detect_maven_jacoco(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pom.xml",
            "<project><build><plugins><plugin><artifactId>jacoco-maven-plugin</artifactId></plugin></plugins></build></project>\n",
        )
        assert JaCoCoAdapter().detect(tmp_path) is True

    def test_detect_existing_report(self, tmp_path: Path) -> None:
        report_dir = tmp_path / "target" / "site" / "jacoco"
        report_dir.mkdir(parents=True)
        (report_dir / "jacoco.xml").write_text(_JACOCO_XML_MINIMAL)
        assert JaCoCoAdapter().detect(tmp_path) is True

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert JaCoCoAdapter().detect(tmp_path) is False

    def test_no_detection_gradle_without_jacoco(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "build.gradle", "plugins { id 'java' }\n")
        assert JaCoCoAdapter().detect(tmp_path) is False


# ── Parsing ──────────────────────────────────────────────────────


class TestJaCoCoParsing:
    def test_parse_sample_xml(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "jacoco.xml"
        xml_path.write_text(_JACOCO_XML_SAMPLE)
        report = JaCoCoAdapter().parse_coverage_file(xml_path)
        assert report.files
        file_paths = list(report.files.keys())
        assert any("Calculator" in p for p in file_paths)
        file_cov = next(f for f in report.files.values() if "Calculator" in f.file_path)
        assert file_cov.lines
        assert len(file_cov.lines) >= 5
        covered = sum(1 for ln in file_cov.lines if ln.execution_count > 0)
        assert covered >= 4
        assert report.overall_line_coverage >= 0.0
        assert report.overall_line_coverage <= 100.0

    def test_parse_minimal_xml(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "jacoco.xml"
        xml_path.write_text(_JACOCO_XML_MINIMAL)
        report = _parse_jacoco_xml(xml_path)
        assert report.files
        assert len(report.files) >= 1
        file_cov = next(iter(report.files.values()))
        assert len(file_cov.lines) == 3
        assert file_cov.line_coverage_percentage >= 0.0
        assert file_cov.line_coverage_percentage <= 100.0

    def test_parse_empty_report(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "jacoco.xml"
        xml_path.write_text(_JACOCO_XML_EMPTY)
        report = JaCoCoAdapter().parse_coverage_file(xml_path)
        assert report.files == {}
        assert report.overall_line_coverage == 100.0

    def test_parse_nonexistent_file_returns_empty(self) -> None:
        report = JaCoCoAdapter().parse_coverage_file(Path("/nonexistent/jacoco.xml"))
        assert report.files == {}
