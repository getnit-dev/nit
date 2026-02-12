"""Tests for the terminal (Rich) reporter."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call

import pytest
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress
from rich.table import Table

from nit.agents.analyzers.coverage import (
    CoverageGapReport,
    FunctionGap,
    GapPriority,
    StaleTest,
)
from nit.agents.reporters.terminal import (
    CLIReporter,
    _format_duration,
    _pass_rate_color,
    reporter,
)
from nit.models.coverage import CoverageReport, PackageCoverage
from nit.models.test_result import TestResult

# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def mock_console() -> MagicMock:
    """Return a MagicMock that replaces the console."""
    return MagicMock()


@pytest.fixture
def cli_reporter(mock_console: MagicMock) -> CLIReporter:
    """Return a CLIReporter with a mocked console."""
    r = CLIReporter()
    r.console = mock_console  # type narrowing handled via mock_console fixture
    return r


# ── Helper function tests ───────────────────────────────────────


class TestPassRateColor:
    """Tests for the _pass_rate_color helper."""

    def test_perfect_rate(self) -> None:
        assert _pass_rate_color(100.0) == "green"

    def test_above_perfect_returns_green(self) -> None:
        # Edge: above 100 shouldn't happen but still green
        assert _pass_rate_color(105.0) == "green"

    def test_good_rate_returns_yellow(self) -> None:
        assert _pass_rate_color(80.0) == "yellow"

    def test_between_good_and_perfect_returns_yellow(self) -> None:
        assert _pass_rate_color(95.0) == "yellow"

    def test_below_good_returns_red(self) -> None:
        assert _pass_rate_color(79.9) == "red"

    def test_zero_returns_red(self) -> None:
        assert _pass_rate_color(0.0) == "red"


class TestFormatDuration:
    """Tests for the _format_duration helper."""

    def test_seconds(self) -> None:
        assert _format_duration(5.0) == "5.0s"

    def test_zero(self) -> None:
        assert _format_duration(0.0) == "0.0s"

    def test_exactly_sixty_seconds(self) -> None:
        assert _format_duration(60.0) == "1.0m"

    def test_above_sixty_seconds(self) -> None:
        assert _format_duration(90.0) == "1.5m"

    def test_sub_second(self) -> None:
        assert _format_duration(0.3) == "0.3s"

    def test_just_below_sixty(self) -> None:
        assert _format_duration(59.9) == "59.9s"


# ── CLIReporter basic print methods ────────────────────────────


class TestCLIReporterBasicPrints:
    """Tests for basic print_* helper methods."""

    def test_print_header(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_header("My Header")
        mock_console.print.assert_called_once_with("\n[bold cyan]My Header[/bold cyan]\n")

    def test_print_success(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_success("All good")
        mock_console.print.assert_called_once_with("[green]\u2713[/green] All good")

    def test_print_error(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_error("Something broke")
        mock_console.print.assert_called_once_with("[red]\u2717[/red] Something broke")

    def test_print_warning(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_warning("Be careful")
        mock_console.print.assert_called_once_with("[yellow]\u26a0[/yellow] Be careful")

    def test_print_info(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_info("FYI")
        mock_console.print.assert_called_once_with("[dim]FYI[/dim]")


# ── Pipeline progress display ──────────────────────────────────


class TestPipelineProgress:
    """Tests for pipeline progress display methods."""

    def test_print_pipeline_header(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        cli_reporter.print_pipeline_header("My Pipeline")
        calls = mock_console.print.call_args_list
        assert len(calls) == 2
        # First call is just a blank print()
        assert calls[0] == call()
        # Second is a Panel
        panel_arg = calls[1].args[0]
        assert isinstance(panel_arg, Panel)

    def test_print_step_header(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_step_header(1, 5, "Analyzing code")
        mock_console.print.assert_called_once_with(
            "\n[bold cyan]\u25b8 Step 1/5[/bold cyan]  Analyzing code"
        )

    def test_print_step_done_seconds(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        cli_reporter.print_step_done("Analysis complete", 3.2)
        mock_console.print.assert_called_once_with(
            "  [green]\u2713[/green] Analysis complete [dim](3.2s)[/dim]"
        )

    def test_print_step_done_minutes(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        cli_reporter.print_step_done("Long task", 120.0)
        mock_console.print.assert_called_once_with(
            "  [green]\u2713[/green] Long task [dim](2.0m)[/dim]"
        )

    def test_print_step_skip(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_step_skip("Optional step")
        mock_console.print.assert_called_once_with(
            "  [yellow]\u2298[/yellow] Optional step [dim](skipped)[/dim]"
        )

    def test_create_status(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.create_status("Loading...")
        mock_console.status.assert_called_once_with("Loading...")

    def test_print_analysis_progress(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        cli_reporter.print_analysis_progress(3, 10, "File scan")
        mock_console.print.assert_called_once_with("  [dim](3/10)[/dim] File scan")


# ── Test summary bar ───────────────────────────────────────────


class TestTestSummaryBar:
    """Tests for print_test_summary_bar."""

    def test_no_tests(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_test_summary_bar(0, 0, 0, 0, 0.0)
        mock_console.print.assert_called_once_with("  [dim]No tests executed[/dim]")

    def test_all_passed(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_test_summary_bar(10, 0, 0, 0, 5000.0)
        calls = mock_console.print.call_args_list
        # Should have 4 calls: blank, summary line, breakdown line, blank
        assert len(calls) == 4
        summary_text = calls[1].args[0]
        assert "10" in summary_text
        assert "100%" in summary_text
        breakdown_text = calls[2].args[0]
        assert "10 passed" in breakdown_text

    def test_mixed_results(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_test_summary_bar(7, 2, 1, 0, 3000.0)
        calls = mock_console.print.call_args_list
        assert len(calls) == 4
        summary_text = calls[1].args[0]
        assert "10" in summary_text
        assert "70%" in summary_text
        breakdown_text = calls[2].args[0]
        assert "7 passed" in breakdown_text
        assert "2 failed" in breakdown_text
        assert "1 skipped" in breakdown_text

    def test_all_categories(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_test_summary_bar(5, 2, 1, 2, 10000.0)
        calls = mock_console.print.call_args_list
        breakdown_text = calls[2].args[0]
        assert "5 passed" in breakdown_text
        assert "2 failed" in breakdown_text
        assert "1 skipped" in breakdown_text
        assert "2 errors" in breakdown_text

    def test_duration_in_minutes(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        # 120000 ms = 120s = 2.0m
        cli_reporter.print_test_summary_bar(1, 0, 0, 0, 120000.0)
        calls = mock_console.print.call_args_list
        summary_text = calls[1].args[0]
        assert "2.0m" in summary_text

    def test_only_failed(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_test_summary_bar(0, 5, 0, 0, 1000.0)
        calls = mock_console.print.call_args_list
        summary_text = calls[1].args[0]
        assert "0%" in summary_text


# ── Build result bar ───────────────────────────────────────────


class TestBuildResultBar:
    """Tests for _build_result_bar."""

    def test_empty(self, cli_reporter: CLIReporter) -> None:
        bar = cli_reporter._build_result_bar(0, 0, 0, 0)
        assert "[dim]" in bar
        assert "\u2591" in bar

    def test_all_passed_no_dim_padding(self, cli_reporter: CLIReporter) -> None:
        bar = cli_reporter._build_result_bar(10, 0, 0, 0, width=10)
        assert "[green]" in bar
        assert "\u2588" in bar

    def test_mixed(self, cli_reporter: CLIReporter) -> None:
        bar = cli_reporter._build_result_bar(5, 5, 0, 0, width=10)
        assert "[green]" in bar
        assert "[red]" in bar

    def test_custom_width(self, cli_reporter: CLIReporter) -> None:
        bar = cli_reporter._build_result_bar(1, 0, 0, 0, width=20)
        # The bar string should contain block characters
        assert "\u2588" in bar


# ── Coverage summary ───────────────────────────────────────────


class TestPrintCoverageSummary:
    """Tests for print_coverage_summary."""

    def test_single_package(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        report = CoverageReport(
            packages={
                "core": PackageCoverage(
                    name="core",
                    line_coverage=0.85,
                    function_coverage=0.90,
                    branch_coverage=0.70,
                ),
            },
            overall_line_coverage=0.85,
            overall_function_coverage=0.90,
            overall_branch_coverage=0.70,
        )
        cli_reporter.print_coverage_summary(report)
        mock_console.print.assert_called_once()
        # The argument should be a Table
        table = mock_console.print.call_args.args[0]
        assert isinstance(table, Table)

    def test_multiple_packages(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        report = CoverageReport(
            packages={
                "core": PackageCoverage(
                    name="core",
                    line_coverage=0.85,
                    function_coverage=0.90,
                    branch_coverage=0.70,
                ),
                "web": PackageCoverage(
                    name="web",
                    line_coverage=0.40,
                    function_coverage=0.50,
                    branch_coverage=0.30,
                ),
            },
            overall_line_coverage=0.62,
            overall_function_coverage=0.70,
            overall_branch_coverage=0.50,
        )
        cli_reporter.print_coverage_summary(report)
        mock_console.print.assert_called_once()


# ── Test results ───────────────────────────────────────────────


class TestPrintTestResults:
    """Tests for print_test_results."""

    def test_all_passing(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        results = [
            TestResult(name="test_a", passed=True, duration=0.5),
            TestResult(name="test_b", passed=True, duration=1.2),
        ]
        cli_reporter.print_test_results(results)
        calls = mock_console.print.call_args_list
        # Table + summary
        assert len(calls) == 2
        summary = calls[1].args[0]
        assert "Passed: 2" in summary
        assert "Failed: 0" in summary

    def test_with_failures(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        results = [
            TestResult(name="test_ok", passed=True, duration=0.1),
            TestResult(
                name="test_fail",
                passed=False,
                duration=0.2,
                error_message="AssertionError: expected 1 got 2",
            ),
        ]
        cli_reporter.print_test_results(results)
        calls = mock_console.print.call_args_list
        summary = calls[1].args[0]
        assert "Passed: 1" in summary
        assert "Failed: 1" in summary

    def test_empty_results(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_test_results([])
        calls = mock_console.print.call_args_list
        summary = calls[1].args[0]
        assert "Total: 0" in summary

    def test_no_duration(self, cli_reporter: CLIReporter) -> None:
        results = [TestResult(name="test_x", passed=True, duration=None)]
        cli_reporter.print_test_results(results)
        # Should not raise — the "-" is rendered in table

    def test_no_error_message(self, cli_reporter: CLIReporter) -> None:
        results = [TestResult(name="test_x", passed=False)]
        cli_reporter.print_test_results(results)
        # Should not raise — empty error_message handled


# ── create_progress ────────────────────────────────────────────


class TestCreateProgress:
    """Tests for create_progress."""

    def test_with_total(self, cli_reporter: CLIReporter) -> None:
        progress = cli_reporter.create_progress(total=10)
        assert isinstance(progress, Progress)
        # Should contain a BarColumn when total is given
        assert any(isinstance(c, BarColumn) for c in progress.columns)

    def test_without_total(self, cli_reporter: CLIReporter) -> None:
        progress = cli_reporter.create_progress(total=None)
        assert isinstance(progress, Progress)
        # Should NOT contain BarColumn when total is None
        assert not any(isinstance(c, BarColumn) for c in progress.columns)


# ── Coverage color helper ──────────────────────────────────────


class TestGetCoverageColor:
    """Tests for _get_coverage_color."""

    def test_high(self, cli_reporter: CLIReporter) -> None:
        assert cli_reporter._get_coverage_color(80.0) == "green"
        assert cli_reporter._get_coverage_color(100.0) == "green"

    def test_medium(self, cli_reporter: CLIReporter) -> None:
        assert cli_reporter._get_coverage_color(50.0) == "yellow"
        assert cli_reporter._get_coverage_color(79.9) == "yellow"

    def test_low(self, cli_reporter: CLIReporter) -> None:
        assert cli_reporter._get_coverage_color(0.0) == "red"
        assert cli_reporter._get_coverage_color(49.9) == "red"


# ── Strip workdir ──────────────────────────────────────────────


class TestStripWorkdir:
    """Tests for _strip_workdir."""

    def test_relative_path_under_cwd(self, cli_reporter: CLIReporter) -> None:
        cwd = Path.cwd()
        full_path = str(cwd / "src" / "nit" / "cli.py")
        result = cli_reporter._strip_workdir(full_path)
        assert result == str(Path("src") / "nit" / "cli.py")

    def test_path_not_under_cwd(self, cli_reporter: CLIReporter) -> None:
        result = cli_reporter._strip_workdir("/completely/different/path.py")
        assert result == "/completely/different/path.py"

    def test_plain_relative(self, cli_reporter: CLIReporter) -> None:
        # If already relative, ValueError from relative_to -> returned as-is
        result = cli_reporter._strip_workdir("just_a_file.py")
        # Path("just_a_file.py").relative_to(cwd) will raise ValueError
        assert result == "just_a_file.py"


# ── Bug analysis ───────────────────────────────────────────────


class TestPrintBugAnalysis:
    """Tests for print_bug_analysis."""

    def test_no_bugs(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_bug_analysis([])
        mock_console.print.assert_called_once_with("[dim]No bugs found in test failures[/dim]")

    def test_with_bugs(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        bug1 = MagicMock()
        bug1.file_path = "src/app.py"
        bug1.line_number = 42
        bug1.bug_type = "NullReference"
        bug1.severity = "HIGH"

        bug2 = MagicMock()
        bug2.file_path = "src/util.py"
        bug2.bug_type = "TypeError"
        bug2.severity = "LOW"
        # No line_number attribute
        del bug2.line_number

        cli_reporter.print_bug_analysis([bug1, bug2])
        mock_console.print.assert_called_once()
        table = mock_console.print.call_args.args[0]
        assert isinstance(table, Table)

    def test_unknown_severity(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        bug = MagicMock()
        bug.file_path = "src/x.py"
        bug.line_number = 1
        bug.bug_type = "Logic"
        bug.severity = "UNKNOWN"

        cli_reporter.print_bug_analysis([bug])
        mock_console.print.assert_called_once()

    def test_medium_severity(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        bug = MagicMock()
        bug.file_path = "src/x.py"
        bug.line_number = 5
        bug.bug_type = "Concurrency"
        bug.severity = "MEDIUM"

        cli_reporter.print_bug_analysis([bug])
        mock_console.print.assert_called_once()

    def test_missing_severity_attr(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        """Bug without severity or bug_type attributes uses defaults."""
        bug = MagicMock(spec=[])
        bug.file_path = "src/x.py"
        cli_reporter.print_bug_analysis([bug])
        mock_console.print.assert_called_once()


# ── Coverage gaps ──────────────────────────────────────────────


class TestPrintCoverageGaps:
    """Tests for print_coverage_gaps."""

    def test_no_gaps(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_coverage_gaps({})
        mock_console.print.assert_called_once_with("[green]\u2713[/green] No coverage gaps found")

    def test_with_gaps(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        gaps: dict[str, Any] = {
            "src/api.py": {
                "coverage": 0.3,
                "risk_level": "HIGH",
                "uncovered_functions": 5,
            },
            "src/db.py": {
                "coverage": 0.7,
                "risk_level": "LOW",
                "uncovered_functions": 1,
            },
        }
        cli_reporter.print_coverage_gaps(gaps)
        mock_console.print.assert_called_once()
        table = mock_console.print.call_args.args[0]
        assert isinstance(table, Table)

    def test_medium_risk(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        gaps: dict[str, Any] = {
            "src/service.py": {
                "coverage": 0.55,
                "risk_level": "MEDIUM",
                "uncovered_functions": 2,
            },
        }
        cli_reporter.print_coverage_gaps(gaps)
        mock_console.print.assert_called_once()

    def test_missing_fields_use_defaults(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gaps: dict[str, Any] = {
            "src/minimal.py": {},
        }
        cli_reporter.print_coverage_gaps(gaps)
        mock_console.print.assert_called_once()


# ── Semantic gap analysis ──────────────────────────────────────


class TestPrintSemanticGapAnalysis:
    """Tests for print_semantic_gap_analysis."""

    def test_no_gaps_no_untested(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        gap_report = CoverageGapReport()
        cli_reporter.print_semantic_gap_analysis(gap_report)
        mock_console.print.assert_called_once_with(
            "[green]\u2713[/green] No significant coverage gaps found"
        )

    def test_with_untested_files_below_limit(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap_report = CoverageGapReport(
            untested_files=["src/a.py", "src/b.py"],
            overall_coverage=40.0,
            target_coverage=80.0,
        )
        cli_reporter.print_semantic_gap_analysis(gap_report)
        texts = [c.args[0] if c.args else "" for c in mock_console.print.call_args_list]
        joined = " ".join(str(t) for t in texts)
        assert "Untested Files (2)" in joined

    def test_untested_files_above_limit(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap_report = CoverageGapReport(
            untested_files=[f"src/file_{i}.py" for i in range(10)],
            overall_coverage=20.0,
            target_coverage=80.0,
        )
        cli_reporter.print_semantic_gap_analysis(gap_report)
        texts = [str(c.args[0]) if c.args else "" for c in mock_console.print.call_args_list]
        joined = " ".join(texts)
        assert "and 5 more" in joined

    def test_with_function_gaps(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        gap_report = CoverageGapReport(
            function_gaps=[
                FunctionGap(
                    file_path="src/module.py",
                    function_name="do_work",
                    line_number=10,
                    end_line=30,
                    coverage_percentage=0.0,
                    complexity=15,
                    is_public=True,
                    priority=GapPriority.CRITICAL,
                ),
            ],
            overall_coverage=50.0,
            target_coverage=80.0,
        )
        cli_reporter.print_semantic_gap_analysis(gap_report)
        # At least the table gets printed
        assert mock_console.print.call_count >= 4

    def test_has_llm_gaps_flag(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        gap_report = CoverageGapReport(
            untested_files=["src/x.py"],
            overall_coverage=60.0,
            target_coverage=80.0,
        )
        cli_reporter.print_semantic_gap_analysis(gap_report, has_llm_gaps=True)
        texts = [str(c.args[0]) if c.args else "" for c in mock_console.print.call_args_list]
        joined = " ".join(texts)
        assert "heuristics + LLM" in joined

    def test_without_llm_gaps_flag(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap_report = CoverageGapReport(
            untested_files=["src/x.py"],
            overall_coverage=60.0,
            target_coverage=80.0,
        )
        cli_reporter.print_semantic_gap_analysis(gap_report, has_llm_gaps=False)
        texts = [str(c.args[0]) if c.args else "" for c in mock_console.print.call_args_list]
        joined = " ".join(texts)
        assert "configure LLM for deeper" in joined

    def test_with_stale_tests(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cwd = str(Path.cwd())
        gap_report = CoverageGapReport(
            function_gaps=[
                FunctionGap(
                    file_path="src/mod.py",
                    function_name="f",
                    line_number=1,
                    end_line=5,
                    coverage_percentage=0.0,
                    complexity=1,
                    is_public=True,
                    priority=GapPriority.HIGH,
                ),
            ],
            stale_tests=[
                StaleTest(
                    test_file=f"{cwd}/tests/test_old.py",
                    missing_imports=["old_module"],
                    reason="Module removed",
                ),
            ],
            overall_coverage=55.0,
            target_coverage=80.0,
        )
        cli_reporter.print_semantic_gap_analysis(gap_report)
        # Stale tests table and recommendations should be printed
        assert mock_console.print.call_count >= 5


# ── Function gaps table ────────────────────────────────────────


class TestPrintFunctionGapsTable:
    """Tests for _print_function_gaps_table."""

    def _make_gap(
        self,
        priority: GapPriority,
        *,
        name: str = "func",
        complexity: int = 5,
        coverage: float = 0.0,
        is_public: bool = True,
    ) -> FunctionGap:
        return FunctionGap(
            file_path="src/m.py",
            function_name=name,
            line_number=1,
            end_line=10,
            coverage_percentage=coverage,
            complexity=complexity,
            is_public=is_public,
            priority=priority,
        )

    def test_all_priority_levels(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        gaps = [
            self._make_gap(GapPriority.CRITICAL),
            self._make_gap(GapPriority.HIGH),
            self._make_gap(GapPriority.MEDIUM),
            self._make_gap(GapPriority.LOW),
        ]
        cli_reporter._print_function_gaps_table(gaps)
        mock_console.print.assert_called_once()
        table = mock_console.print.call_args.args[0]
        assert isinstance(table, Table)

    def test_long_function_name_truncated(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap = self._make_gap(GapPriority.HIGH, name="a" * 50)
        cli_reporter._print_function_gaps_table([gap])
        mock_console.print.assert_called_once()

    def test_long_file_path_truncated(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap = FunctionGap(
            file_path="/a/very/deeply/nested/directory/structure/here/module.py",
            function_name="fn",
            line_number=1,
            end_line=5,
            coverage_percentage=10.0,
            complexity=2,
            is_public=False,
            priority=GapPriority.MEDIUM,
        )
        cli_reporter._print_function_gaps_table([gap])
        mock_console.print.assert_called_once()


# ── Stale tests table ──────────────────────────────────────────


class TestPrintStaleTestsTable:
    """Tests for _print_stale_tests_table."""

    def test_basic(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cwd = str(Path.cwd())
        stales = [
            StaleTest(
                test_file=f"{cwd}/tests/test_old.py",
                missing_imports=["gone_module"],
                reason="Module was deleted",
            ),
        ]
        cli_reporter._print_stale_tests_table(stales)
        # blank line + table
        assert mock_console.print.call_count == 2

    def test_long_missing_imports_truncated(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        cwd = str(Path.cwd())
        stales = [
            StaleTest(
                test_file=f"{cwd}/tests/test_x.py",
                missing_imports=[
                    "very_long_module_name_one",
                    "very_long_module_name_two",
                ],
                reason="Modules removed during refactor",
            ),
        ]
        cli_reporter._print_stale_tests_table(stales)
        assert mock_console.print.call_count == 2

    def test_long_reason_truncated(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        cwd = str(Path.cwd())
        stales = [
            StaleTest(
                test_file=f"{cwd}/tests/test_y.py",
                missing_imports=[],
                reason="A" * 60,
            ),
        ]
        cli_reporter._print_stale_tests_table(stales)
        assert mock_console.print.call_count == 2

    def test_no_missing_imports(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cwd = str(Path.cwd())
        stales = [
            StaleTest(
                test_file=f"{cwd}/tests/test_z.py",
                missing_imports=[],
                reason="No source target",
            ),
        ]
        cli_reporter._print_stale_tests_table(stales)
        assert mock_console.print.call_count == 2


# ── Add gap row ────────────────────────────────────────────────


class TestAddGapRow:
    """Tests for _add_gap_row."""

    def test_public_function(self, cli_reporter: CLIReporter) -> None:
        table = Table()
        for _ in range(6):
            table.add_column("col")
        gap = FunctionGap(
            file_path="src/pub.py",
            function_name="public_func",
            line_number=1,
            end_line=10,
            coverage_percentage=30.0,
            complexity=3,
            is_public=True,
            priority=GapPriority.HIGH,
        )
        cli_reporter._add_gap_row(table, gap, "yellow")
        assert table.row_count == 1

    def test_private_function(self, cli_reporter: CLIReporter) -> None:
        table = Table()
        for _ in range(6):
            table.add_column("col")
        gap = FunctionGap(
            file_path="src/priv.py",
            function_name="_helper",
            line_number=1,
            end_line=5,
            coverage_percentage=0.0,
            complexity=1,
            is_public=False,
            priority=GapPriority.LOW,
        )
        cli_reporter._add_gap_row(table, gap, "dim")
        assert table.row_count == 1


# ── Gap recommendations ───────────────────────────────────────


class TestPrintGapRecommendations:
    """Tests for _print_gap_recommendations."""

    def test_no_recommendations(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        gap_report = CoverageGapReport(
            overall_coverage=90.0,
            target_coverage=80.0,
        )
        cli_reporter._print_gap_recommendations(gap_report)
        # No console.print calls since no recommendations
        mock_console.print.assert_not_called()

    def test_critical_and_high_gaps(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap_report = CoverageGapReport(
            function_gaps=[
                FunctionGap(
                    file_path="a.py",
                    function_name="f",
                    line_number=1,
                    end_line=5,
                    coverage_percentage=0.0,
                    complexity=10,
                    is_public=True,
                    priority=GapPriority.CRITICAL,
                ),
                FunctionGap(
                    file_path="b.py",
                    function_name="g",
                    line_number=1,
                    end_line=5,
                    coverage_percentage=20.0,
                    complexity=5,
                    is_public=True,
                    priority=GapPriority.HIGH,
                ),
            ],
            overall_coverage=50.0,
            target_coverage=80.0,
        )
        cli_reporter._print_gap_recommendations(gap_report)
        texts = [str(c.args[0]) if c.args else "" for c in mock_console.print.call_args_list]
        joined = " ".join(texts)
        assert "CRITICAL" in joined
        assert "HIGH" in joined
        assert "30.0%" in joined

    def test_untested_files_recommendation(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap_report = CoverageGapReport(
            untested_files=["a.py", "b.py", "c.py"],
            overall_coverage=70.0,
            target_coverage=80.0,
        )
        cli_reporter._print_gap_recommendations(gap_report)
        texts = [str(c.args[0]) if c.args else "" for c in mock_console.print.call_args_list]
        joined = " ".join(texts)
        assert "3 completely untested" in joined

    def test_stale_tests_recommendation(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap_report = CoverageGapReport(
            stale_tests=[
                StaleTest(test_file="t.py", missing_imports=[], reason="gone"),
            ],
            overall_coverage=85.0,
            target_coverage=80.0,
        )
        cli_reporter._print_gap_recommendations(gap_report)
        texts = [str(c.args[0]) if c.args else "" for c in mock_console.print.call_args_list]
        joined = " ".join(texts)
        assert "1 stale test" in joined

    def test_coverage_at_target_no_improvement_rec(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap_report = CoverageGapReport(
            overall_coverage=80.0,
            target_coverage=80.0,
        )
        cli_reporter._print_gap_recommendations(gap_report)
        mock_console.print.assert_not_called()


# ── Fix progress ───────────────────────────────────────────────


class TestPrintFixProgress:
    """Tests for print_fix_progress."""

    def test_success(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_fix_progress("BUG-1", "verify", "success")
        output = mock_console.print.call_args.args[0]
        assert "[BUG-1]" in output
        assert "\u2713" in output
        assert "Bug verified" in output

    def test_failed_with_message(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_fix_progress(
            "BUG-2", "root_cause", "failed", "Could not find root cause"
        )
        output = mock_console.print.call_args.args[0]
        assert "[BUG-2]" in output
        assert "\u2717" in output
        assert "Root cause" in output
        assert "Could not find root cause" in output

    def test_skipped(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_fix_progress("BUG-3", "generate", "skipped")
        output = mock_console.print.call_args.args[0]
        assert "\u2298" in output
        assert "Fix generated" in output

    def test_verify_fix_step(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_fix_progress("BUG-4", "verify_fix", "success")
        output = mock_console.print.call_args.args[0]
        assert "Fix verified" in output

    def test_apply_step(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_fix_progress("BUG-5", "apply", "success")
        output = mock_console.print.call_args.args[0]
        assert "Applied to file" in output

    def test_unknown_step(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_fix_progress("BUG-6", "custom_step", "success")
        output = mock_console.print.call_args.args[0]
        assert "custom_step" in output

    def test_unknown_status(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_fix_progress("BUG-7", "verify", "unknown_status")
        output = mock_console.print.call_args.args[0]
        assert "[BUG-7]" in output


# ── Recommendations ────────────────────────────────────────────


class TestPrintRecommendations:
    """Tests for print_recommendations."""

    def test_empty(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_recommendations([])
        mock_console.print.assert_not_called()

    def test_multiple(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_recommendations(["Add tests", "Fix coverage", "Refactor"])
        calls = mock_console.print.call_args_list
        # Header + 3 recommendations
        assert len(calls) == 4
        assert "Recommendations" in calls[0].args[0]
        assert "1." in calls[1].args[0]
        assert "2." in calls[2].args[0]
        assert "3." in calls[3].args[0]


# ── Code analysis summary ──────────────────────────────────────


class TestPrintCodeAnalysisSummary:
    """Tests for print_code_analysis_summary."""

    def test_empty(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_code_analysis_summary({})
        mock_console.print.assert_not_called()

    def test_with_data(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        code_map1 = MagicMock()
        code_map1.functions = [MagicMock(), MagicMock()]
        code_map1.classes = [MagicMock()]
        code_map1.side_effects_map = {"db": True}

        code_map2 = MagicMock()
        code_map2.functions = [MagicMock()]
        code_map2.classes = []
        code_map2.side_effects_map = {}

        cli_reporter.print_code_analysis_summary({"file1.py": code_map1, "file2.py": code_map2})
        calls = mock_console.print.call_args_list
        # blank + header + details
        assert len(calls) == 3
        details = calls[2].args[0]
        assert "2" in details  # 2 files
        assert "3 functions" in details
        assert "1 classes" in details
        assert "1 with side effects" in details


# ── Pattern profile ────────────────────────────────────────────


class TestPrintPatternProfile:
    """Tests for print_pattern_profile."""

    def test_none(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_pattern_profile(None)
        mock_console.print.assert_not_called()

    def test_with_profile(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        profile = MagicMock()
        profile.naming_style = "snake_case"
        profile.assertion_style = "pytest"
        profile.files_analyzed = 10
        profile.mocking_patterns = ["unittest.mock", "pytest-mock", "monkeypatch"]

        cli_reporter.print_pattern_profile(profile)
        calls = mock_console.print.call_args_list
        assert len(calls) == 4  # blank, header, conventions, mocking
        mock_text = calls[3].args[0]
        assert "unittest.mock" in mock_text

    def test_no_mocking_patterns(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        profile = MagicMock()
        profile.naming_style = "camelCase"
        profile.assertion_style = "jest"
        profile.files_analyzed = 5
        profile.mocking_patterns = []

        cli_reporter.print_pattern_profile(profile)
        calls = mock_console.print.call_args_list
        # blank, header, conventions -- no mocking line
        assert len(calls) == 3


# ── Risk report ────────────────────────────────────────────────


class TestPrintRiskReport:
    """Tests for print_risk_report."""

    def test_none(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_risk_report(None)
        mock_console.print.assert_not_called()

    def test_empty_file_risks(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        report = MagicMock()
        report.file_risks = []
        cli_reporter.print_risk_report(report)
        mock_console.print.assert_not_called()

    def test_with_file_risks(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cwd = str(Path.cwd())

        domain = MagicMock()
        domain.value = "security"

        risk_score = MagicMock()
        risk_score.overall_score = 0.85
        risk_score.level.value = "critical"
        risk_score.criticality_domains = [domain]

        file_risk = MagicMock()
        file_risk.file_path = f"{cwd}/src/auth.py"
        file_risk.risk_score = risk_score
        file_risk.avg_complexity = 12.3
        file_risk.coverage_percentage = 30.0

        report = MagicMock()
        report.file_risks = [file_risk]

        cli_reporter.print_risk_report(report)
        # blank + table
        assert mock_console.print.call_count == 2

    def test_more_than_15_files_shows_remaining(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        risks = []
        for i in range(20):
            domain = MagicMock()
            domain.value = "none"
            risk_score = MagicMock()
            risk_score.overall_score = 0.5
            risk_score.level.value = "medium"
            risk_score.criticality_domains = [domain]

            fr = MagicMock()
            fr.file_path = f"src/file_{i}.py"
            fr.risk_score = risk_score
            fr.avg_complexity = 5.0
            fr.coverage_percentage = 60.0
            risks.append(fr)

        report = MagicMock()
        report.file_risks = risks

        cli_reporter.print_risk_report(report)
        calls = mock_console.print.call_args_list
        last_text = str(calls[-1].args[0])
        assert "5 more" in last_text


# ── Integration deps ──────────────────────────────────────────


class TestPrintIntegrationDeps:
    """Tests for print_integration_deps."""

    def test_empty(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_integration_deps([])
        mock_console.print.assert_not_called()

    def test_with_deps(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        dep = MagicMock()
        dep.dependency_type.value = "database"
        dep.module_name = "sqlalchemy"
        dep.mock_strategies = ["fixture"]

        report = MagicMock()
        report.source_path = Path("src/repo.py")
        report.dependencies = [dep]

        cli_reporter.print_integration_deps([report])
        calls = mock_console.print.call_args_list
        # blank + header + table
        assert len(calls) == 3

    def test_dep_with_no_mock_strategies(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        dep = MagicMock()
        dep.dependency_type.value = "http"
        dep.module_name = "requests"
        dep.mock_strategies = []

        report = MagicMock()
        report.source_path = Path("src/client.py")
        report.dependencies = [dep]

        cli_reporter.print_integration_deps([report])
        assert mock_console.print.call_count == 3


# ── Route flows ────────────────────────────────────────────────


class TestPrintRouteFlows:
    """Tests for print_route_flows."""

    def test_no_routes(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_route_flows(None, None)
        mock_console.print.assert_not_called()

    def test_empty_routes(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        discovery = MagicMock()
        discovery.routes = []
        cli_reporter.print_route_flows(discovery, None)
        mock_console.print.assert_not_called()

    def test_with_routes(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        method = MagicMock()
        method.value = "GET"

        route = MagicMock()
        route.path = "/api/users"
        route.methods = [method]
        route.route_type.value = "api"
        route.auth_required = True

        discovery = MagicMock()
        discovery.routes = [route]

        cli_reporter.print_route_flows(discovery, None)
        # blank + header + table
        assert mock_console.print.call_count == 3

    def test_with_routes_and_flows(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        method = MagicMock()
        method.value = "POST"

        route = MagicMock()
        route.path = "/api/login"
        route.methods = [method]
        route.route_type.value = "api"
        route.auth_required = False

        discovery = MagicMock()
        discovery.routes = [route]

        flow = MagicMock()
        flow.name = "Login flow"
        flow.routes = [route]
        flow.priority = 1
        flow.requires_auth = False

        flow_mapping = MagicMock()
        flow_mapping.flows = [flow]

        cli_reporter.print_route_flows(discovery, flow_mapping)
        # blank + header + table + blank + user flows header + flow table
        assert mock_console.print.call_count == 6

    def test_more_than_max_routes(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        routes = []
        for i in range(25):
            m = MagicMock()
            m.value = "GET"
            r = MagicMock()
            r.path = f"/api/route_{i}"
            r.methods = [m]
            r.route_type.value = "api"
            r.auth_required = False
            routes.append(r)

        discovery = MagicMock()
        discovery.routes = routes

        cli_reporter.print_route_flows(discovery, None)
        calls = mock_console.print.call_args_list
        last_text = str(calls[-1].args[0])
        assert "5 more" in last_text

    def test_route_no_auth(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        method = MagicMock()
        method.value = "DELETE"

        route = MagicMock()
        route.path = "/api/cleanup"
        route.methods = [method]
        route.route_type.value = "api"
        route.auth_required = False

        discovery = MagicMock()
        discovery.routes = [route]

        cli_reporter.print_route_flows(discovery, None)
        assert mock_console.print.call_count == 3


# ── Semantic gaps ──────────────────────────────────────────────


class TestPrintSemanticGaps:
    """Tests for print_semantic_gaps."""

    def test_empty(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        cli_reporter.print_semantic_gaps([])
        mock_console.print.assert_not_called()

    def test_with_gaps(self, cli_reporter: CLIReporter, mock_console: MagicMock) -> None:
        gap = MagicMock()
        gap.severity = "high"
        gap.file_path = "src/handler.py"
        gap.function_name = "handle_request"
        gap.category.value = "missing_test"
        gap.description = "No test covers the error branch"

        cli_reporter.print_semantic_gaps([gap])
        # blank + table
        assert mock_console.print.call_count == 2

    def test_long_function_name_truncated(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap = MagicMock()
        gap.severity = "medium"
        gap.file_path = "src/x.py"
        gap.function_name = "a" * 40
        gap.category.value = "edge_case"
        gap.description = "Edge case not tested"

        cli_reporter.print_semantic_gaps([gap])
        assert mock_console.print.call_count == 2

    def test_long_file_path_truncated(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap = MagicMock()
        gap.severity = "low"
        gap.file_path = "/very/long/path/to/some/deeply/nested/file.py"
        gap.function_name = "fn"
        gap.category.value = "boundary"
        gap.description = "Short"

        cli_reporter.print_semantic_gaps([gap])
        assert mock_console.print.call_count == 2

    def test_long_description_truncated(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap = MagicMock()
        gap.severity = "high"
        gap.file_path = "src/x.py"
        gap.function_name = "fn"
        gap.category.value = "boundary"
        gap.description = "D" * 60

        cli_reporter.print_semantic_gaps([gap])
        assert mock_console.print.call_count == 2

    def test_unknown_severity_fallback(
        self, cli_reporter: CLIReporter, mock_console: MagicMock
    ) -> None:
        gap = MagicMock()
        gap.severity = "critical"
        gap.file_path = "src/x.py"
        gap.function_name = "fn"
        gap.category.value = "logic"
        gap.description = "Logic bug"

        cli_reporter.print_semantic_gaps([gap])
        assert mock_console.print.call_count == 2


# ── Singleton instance ─────────────────────────────────────────


class TestSingleton:
    """Test the module-level singleton reporter."""

    def test_reporter_is_cli_reporter(self) -> None:
        assert isinstance(reporter, CLIReporter)

    def test_reporter_has_console(self) -> None:
        assert isinstance(reporter.console, Console)
