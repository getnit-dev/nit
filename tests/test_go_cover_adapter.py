"""Tests for GoCoverAdapter (adapters/coverage/go_cover_adapter.py).

Covers detection, cover profile parsing, and unified CoverageReport.
"""

from __future__ import annotations

from pathlib import Path

from nit.adapters.coverage.go_cover_adapter import GoCoverAdapter


def _write_file(root: Path, rel: str, content: str) -> Path:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


# ── Sample cover profile ────────────────────────────────────────

_GO_COVER_PROFILE = """\
mode: set
example.com/mypkg/foo.go:5.2,7.4 2 1
example.com/mypkg/foo.go:10.1,12.3 3 0
example.com/mypkg/bar.go:1.1,3.2 2 2
"""


class TestGoCoverAdapterIdentity:
    def test_name(self) -> None:
        assert GoCoverAdapter().name == "go_cover"

    def test_language(self) -> None:
        assert GoCoverAdapter().language == "go"


class TestGoCoverDetection:
    def test_detect_go_mod(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "go.mod", "module example.com/mypkg\n")
        assert GoCoverAdapter().detect(tmp_path) is True

    def test_no_detection_without_go_mod(self, tmp_path: Path) -> None:
        assert GoCoverAdapter().detect(tmp_path) is False


class TestGoCoverParseCoverageFile:
    def test_parse_cover_profile(self, tmp_path: Path) -> None:
        profile = tmp_path / "coverage.out"
        profile.write_text(_GO_COVER_PROFILE, encoding="utf-8")
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(profile)
        assert len(report.files) == 2
        assert "example.com/mypkg/foo.go" in report.files
        assert "example.com/mypkg/bar.go" in report.files

        foo = report.files["example.com/mypkg/foo.go"]
        # Lines 5-7 from first block (count 1), lines 10-12 from second (count 0)
        line_nums = [ln.line_number for ln in foo.lines]
        assert 5 in line_nums
        assert 6 in line_nums
        assert 7 in line_nums
        assert 10 in line_nums
        assert 11 in line_nums
        assert 12 in line_nums
        covered = [ln for ln in foo.lines if ln.execution_count > 0]
        assert len(covered) == 3  # lines 5, 6, 7

        bar = report.files["example.com/mypkg/bar.go"]
        assert len(bar.lines) == 3  # 1, 2, 3
        assert all(ln.execution_count == 2 for ln in bar.lines)

    def test_parse_empty_file(self, tmp_path: Path) -> None:
        profile = tmp_path / "empty.out"
        profile.write_text("mode: set\n", encoding="utf-8")
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(profile)
        assert len(report.files) == 0

    def test_parse_missing_file_returns_empty_report(self) -> None:
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(Path("/nonexistent/coverage.out"))
        assert len(report.files) == 0
