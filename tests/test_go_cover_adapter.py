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

    def test_parse_mode_count(self, tmp_path: Path) -> None:
        """Should parse 'mode: count' profile identically to 'mode: set'."""
        content = (
            "mode: count\n"
            "example.com/pkg/main.go:1.1,3.2 2 5\n"
            "example.com/pkg/main.go:5.1,7.2 2 0\n"
        )
        profile = _write_file(tmp_path, "count.out", content)
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(profile)

        assert len(report.files) == 1
        main = report.files["example.com/pkg/main.go"]
        # Lines 1-3 covered with count 5, lines 5-7 with count 0
        covered = [ln for ln in main.lines if ln.execution_count > 0]
        uncovered = [ln for ln in main.lines if ln.execution_count == 0]
        assert len(covered) == 3
        assert all(ln.execution_count == 5 for ln in covered)
        assert len(uncovered) == 3

    def test_parse_overlapping_blocks_takes_max(self, tmp_path: Path) -> None:
        """When two blocks cover the same line, max count should be kept."""
        content = (
            "mode: set\n"
            "example.com/pkg/overlap.go:5.1,10.2 3 1\n"
            "example.com/pkg/overlap.go:8.1,12.2 3 5\n"
        )
        profile = _write_file(tmp_path, "overlap.out", content)
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(profile)

        overlap = report.files["example.com/pkg/overlap.go"]
        # Lines 8-10 appear in both blocks; should take max
        line8 = next(ln for ln in overlap.lines if ln.line_number == 8)
        assert line8.execution_count == 5  # max(1, 5)
        line9 = next(ln for ln in overlap.lines if ln.line_number == 9)
        assert line9.execution_count == 5
        line10 = next(ln for ln in overlap.lines if ln.line_number == 10)
        assert line10.execution_count == 5
        # Line 5 only in first block
        line5 = next(ln for ln in overlap.lines if ln.line_number == 5)
        assert line5.execution_count == 1
        # Line 12 only in second block
        line12 = next(ln for ln in overlap.lines if ln.line_number == 12)
        assert line12.execution_count == 5

    def test_parse_multiple_files(self, tmp_path: Path) -> None:
        """Should handle many files in a single profile."""
        content = (
            "mode: set\n"
            "example.com/a/a.go:1.1,2.2 1 1\n"
            "example.com/b/b.go:1.1,2.2 1 0\n"
            "example.com/c/c.go:1.1,3.2 2 3\n"
        )
        profile = _write_file(tmp_path, "multi.out", content)
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(profile)

        assert len(report.files) == 3
        assert "example.com/a/a.go" in report.files
        assert "example.com/b/b.go" in report.files
        assert "example.com/c/c.go" in report.files

    def test_parse_skips_malformed_lines(self, tmp_path: Path) -> None:
        """Malformed lines should be silently skipped."""
        content = (
            "mode: set\n"
            "this-is-not-a-valid-coverage-line\n"
            "example.com/pkg/ok.go:1.1,3.2 2 1\n"
            "also invalid\n"
        )
        profile = _write_file(tmp_path, "bad.out", content)
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(profile)

        assert len(report.files) == 1
        assert "example.com/pkg/ok.go" in report.files

    def test_parse_blank_and_whitespace_lines(self, tmp_path: Path) -> None:
        """Blank and whitespace-only lines in the profile should be skipped."""
        content = "mode: set\n\n   \nexample.com/pkg/ws.go:1.1,2.2 1 1\n\n"
        profile = _write_file(tmp_path, "ws.out", content)
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(profile)

        assert len(report.files) == 1
        ws = report.files["example.com/pkg/ws.go"]
        assert len(ws.lines) == 2

    def test_parse_lines_sorted_by_number(self, tmp_path: Path) -> None:
        """LineCoverage entries should be sorted by line number."""
        content = (
            "mode: set\n"
            "example.com/pkg/sorted.go:20.1,22.2 2 1\n"
            "example.com/pkg/sorted.go:5.1,7.2 2 1\n"
            "example.com/pkg/sorted.go:10.1,12.2 2 1\n"
        )
        profile = _write_file(tmp_path, "sorted.out", content)
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(profile)

        lines = report.files["example.com/pkg/sorted.go"].lines
        line_nums = [ln.line_number for ln in lines]
        assert line_nums == sorted(line_nums)

    def test_parse_single_line_block(self, tmp_path: Path) -> None:
        """A block spanning a single line should produce one LineCoverage."""
        content = "mode: set\nexample.com/pkg/single.go:42.1,42.30 1 7\n"
        profile = _write_file(tmp_path, "single.out", content)
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(profile)

        single = report.files["example.com/pkg/single.go"]
        assert len(single.lines) == 1
        assert single.lines[0].line_number == 42
        assert single.lines[0].execution_count == 7

    def test_file_coverage_has_no_functions_or_branches(self, tmp_path: Path) -> None:
        """Go cover adapter does not produce function or branch coverage."""
        content = "mode: set\nexample.com/pkg/nofn.go:1.1,3.2 2 1\n"
        profile = _write_file(tmp_path, "nofn.out", content)
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(profile)

        nofn = report.files["example.com/pkg/nofn.go"]
        assert len(nofn.functions) == 0
        assert len(nofn.branches) == 0

    def test_overall_coverage_percentage(self, tmp_path: Path) -> None:
        """Overall line coverage should be calculated across all files."""
        content = (
            "mode: set\n"
            "example.com/a/a.go:1.1,2.2 1 1\n"
            "example.com/a/a.go:3.1,4.2 1 0\n"
            "example.com/b/b.go:1.1,2.2 1 1\n"
        )
        profile = _write_file(tmp_path, "overall.out", content)
        adapter = GoCoverAdapter()
        report = adapter.parse_coverage_file(profile)

        # a.go: lines 1,2 covered, 3,4 not -> 2/4
        # b.go: lines 1,2 covered -> 2/2
        # Total: 4/6 = 66.67%
        assert abs(report.overall_line_coverage - 66.67) < 0.1
