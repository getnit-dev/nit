"""Tests for TarpaulinAdapter (adapters/coverage/tarpaulin.py).

Covers detection and LCOV parsing into unified CoverageReport.
"""

from __future__ import annotations

from pathlib import Path

from nit.adapters.coverage.tarpaulin import TarpaulinAdapter


def _write_file(root: Path, rel: str, content: str) -> Path:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


# ── Sample LCOV content ───────────────────────────────────────────

_LCOV_SAMPLE = """\
SF:src/lib.rs
FN:1,my_crate::add
FNDA:2,my_crate::add
DA:5,2
DA:6,1
DA:7,2
end_of_record
SF:src/main.rs
FN:10,main
FNDA:1,main
DA:12,1
DA:13,1
end_of_record
"""


class TestTarpaulinAdapterIdentity:
    def test_name(self) -> None:
        assert TarpaulinAdapter().name == "tarpaulin"

    def test_language(self) -> None:
        assert TarpaulinAdapter().language == "rust"


class TestTarpaulinDetection:
    def test_detect_cargo_toml(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "Cargo.toml", '[package]\nname = "mylib"\n')
        assert TarpaulinAdapter().detect(tmp_path) is True

    def test_no_detection_without_cargo_toml(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "src/lib.rs", "fn main() {}\n")
        assert TarpaulinAdapter().detect(tmp_path) is False

    def test_no_detection_empty_dir(self, tmp_path: Path) -> None:
        assert TarpaulinAdapter().detect(tmp_path) is False


class TestTarpaulinParseCoverageFile:
    def test_parse_lcov_file(self, tmp_path: Path) -> None:
        lcov_file = tmp_path / "lcov.info"
        lcov_file.write_text(_LCOV_SAMPLE, encoding="utf-8")
        adapter = TarpaulinAdapter()
        report = adapter.parse_coverage_file(lcov_file)
        assert len(report.files) == 2
        assert "src/lib.rs" in report.files
        assert "src/main.rs" in report.files

        lib_rs = report.files["src/lib.rs"]
        assert len(lib_rs.lines) == 3
        line_nums = [ln.line_number for ln in lib_rs.lines]
        assert 5 in line_nums
        assert 6 in line_nums
        assert 7 in line_nums
        assert lib_rs.lines[0].execution_count == 2

        main_rs = report.files["src/main.rs"]
        assert len(main_rs.lines) == 2
        assert all(ln.execution_count == 1 for ln in main_rs.lines)

    def test_parse_empty_file(self, tmp_path: Path) -> None:
        lcov_file = tmp_path / "empty.info"
        lcov_file.write_text("", encoding="utf-8")
        adapter = TarpaulinAdapter()
        report = adapter.parse_coverage_file(lcov_file)
        assert len(report.files) == 0

    def test_parse_single_sf_no_da(self, tmp_path: Path) -> None:
        lcov_file = tmp_path / "minimal.info"
        lcov_file.write_text(
            "SF:src/foo.rs\nend_of_record\n",
            encoding="utf-8",
        )
        adapter = TarpaulinAdapter()
        report = adapter.parse_coverage_file(lcov_file)
        assert len(report.files) == 1
        assert "src/foo.rs" in report.files
        assert report.files["src/foo.rs"].lines == []
