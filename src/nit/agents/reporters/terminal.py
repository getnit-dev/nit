"""Terminal reporter with rich output formatting."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

if TYPE_CHECKING:
    from rich.status import Status

    from nit.agents.analyzers.coverage import CoverageGapReport, FunctionGap
    from nit.models.coverage import CoverageReport
    from nit.models.test_result import TestResult

console = Console()


_PERFECT_RATE = 100.0
_GOOD_RATE = 80.0
_SECONDS_PER_MINUTE = 60.0


def _pass_rate_color(rate: float) -> str:
    """Return a Rich color name for a given pass-rate percentage."""
    if rate >= _PERFECT_RATE:
        return "green"
    if rate >= _GOOD_RATE:
        return "yellow"
    return "red"


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    if seconds >= _SECONDS_PER_MINUTE:
        return f"{seconds / _SECONDS_PER_MINUTE:.1f}m"
    return f"{seconds:.1f}s"


# Display limits for truncation and pagination
_MAX_UNTESTED_FILES_DISPLAY = 5
_MAX_FUNCTION_NAME_LENGTH = 30
_MAX_FILE_PATH_LENGTH = 35
_MAX_STALE_MISSING_IMPORTS_LENGTH = 28
_MAX_STALE_REASON_LENGTH = 40
_MAX_ROUTES_DISPLAY = 20
_MAX_SEMANTIC_FUNC_LENGTH = 20
_MAX_SEMANTIC_FILE_LENGTH = 30
_MAX_SEMANTIC_DESC_LENGTH = 35


class CLIReporter:
    """Rich terminal output reporter for test generation and execution."""

    def __init__(self) -> None:
        """Initialize the CLI reporter."""
        self.console = console

    def print_header(self, title: str) -> None:
        """Print a bold header."""
        self.console.print(f"\n[bold cyan]{title}[/bold cyan]\n")

    def print_success(self, message: str) -> None:
        """Print a success message."""
        self.console.print(f"[green]✓[/green] {message}")

    def print_error(self, message: str) -> None:
        """Print an error message."""
        self.console.print(f"[red]✗[/red] {message}")

    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        self.console.print(f"[yellow]⚠[/yellow] {message}")

    def print_info(self, message: str) -> None:
        """Print an info message."""
        self.console.print(f"[dim]{message}[/dim]")

    # ── Pipeline progress display ──────────────────────────────────────

    def print_pipeline_header(self, name: str) -> None:
        """Print a styled banner for a pipeline run."""
        self.console.print()
        self.console.print(
            Panel(
                f"[bold white]{name}[/bold white]",
                border_style="cyan",
                padding=(0, 2),
            )
        )

    def print_step_header(self, step: int, total: int, description: str) -> None:
        """Print a pipeline step header with step number."""
        self.console.print(f"\n[bold cyan]▸ Step {step}/{total}[/bold cyan]  {description}")

    def print_step_done(self, description: str, duration_s: float) -> None:
        """Print step completion with elapsed time."""
        time_str = _format_duration(duration_s)
        self.console.print(f"  [green]✓[/green] {description} [dim]({time_str})[/dim]")

    def print_step_skip(self, description: str) -> None:
        """Print a skipped step."""
        self.console.print(f"  [yellow]⊘[/yellow] {description} [dim](skipped)[/dim]")

    def create_status(self, message: str) -> Status:
        """Create a Rich Status spinner for long-running operations."""
        return self.console.status(message)

    def print_test_summary_bar(
        self,
        passed: int,
        failed: int,
        skipped: int,
        errors: int,
        duration_ms: float,
    ) -> None:
        """Print a visual bar showing test result distribution with stats."""
        total = passed + failed + skipped + errors
        if total == 0:
            self.console.print("  [dim]No tests executed[/dim]")
            return

        pass_rate = passed / total * 100
        bar = self._build_result_bar(passed, failed, skipped, errors)

        # Duration
        duration_s = duration_ms / 1000
        dur_str = _format_duration(duration_s)

        rate_color = _pass_rate_color(pass_rate)

        self.console.print()
        self.console.print(
            f"  [bold]{total}[/bold] tests  {bar}  "
            f"[bold {rate_color}]{pass_rate:.0f}%[/bold {rate_color}] pass rate  "
            f"[dim]⏱ {dur_str}[/dim]"
        )

        # Breakdown line
        parts: list[str] = []
        if passed:
            parts.append(f"[green]✓ {passed} passed[/green]")
        if failed:
            parts.append(f"[red]✗ {failed} failed[/red]")
        if skipped:
            parts.append(f"[yellow]⊘ {skipped} skipped[/yellow]")
        if errors:
            parts.append(f"[magenta]⚠ {errors} errors[/magenta]")

        self.console.print(f"  {'  '.join(parts)}")
        self.console.print()

    def print_analysis_progress(self, current: int, total: int, label: str) -> None:
        """Print inline progress for iterative analysis steps."""
        self.console.print(f"  [dim]({current}/{total})[/dim] {label}")

    def _build_result_bar(
        self,
        passed: int,
        failed: int,
        skipped: int,
        errors: int,
        width: int = 40,
    ) -> str:
        """Build a colored bar string proportional to result counts."""
        total = passed + failed + skipped + errors
        if total == 0:
            return f"[dim]{'░' * width}[/dim]"

        segments = [
            (passed, "green"),
            (failed, "red"),
            (skipped, "yellow"),
            (errors, "magenta"),
        ]

        # Build character-by-character then group by color
        chars: list[tuple[str, str]] = []
        for count, color in segments:
            n = round(count / total * width)
            chars.extend([("█", color)] * n)

        # Trim or pad to exact width
        chars = chars[:width]
        while len(chars) < width:
            chars.append(("░", "dim"))

        # Group consecutive same-color runs for efficient markup
        result = ""
        i = 0
        while i < len(chars):
            char, color = chars[i]
            j = i + 1
            while j < len(chars) and chars[j][1] == color:
                j += 1
            run_len = j - i
            result += f"[{color}]{char * run_len}[/{color}]"
            i = j

        return result

    # ── End pipeline progress ──────────────────────────────────────────

    def print_coverage_summary(self, report: CoverageReport) -> None:
        """Print a coverage summary table."""
        table = Table(title="Coverage Summary", title_style="bold cyan")
        table.add_column("Package", style="bold")
        table.add_column("Line Coverage", justify="right")
        table.add_column("Function Coverage", justify="right")
        table.add_column("Branch Coverage", justify="right")

        for pkg_name, pkg_coverage in report.packages.items():
            line_pct = pkg_coverage.line_coverage * 100
            func_pct = pkg_coverage.function_coverage * 100
            branch_pct = pkg_coverage.branch_coverage * 100

            # Color code based on coverage percentage
            line_color = self._get_coverage_color(line_pct)
            func_color = self._get_coverage_color(func_pct)
            branch_color = self._get_coverage_color(branch_pct)

            table.add_row(
                pkg_name,
                f"[{line_color}]{line_pct:.1f}%[/{line_color}]",
                f"[{func_color}]{func_pct:.1f}%[/{func_color}]",
                f"[{branch_color}]{branch_pct:.1f}%[/{branch_color}]",
            )

        # Add overall coverage
        overall_line = report.overall_line_coverage * 100
        overall_func = report.overall_function_coverage * 100
        overall_branch = report.overall_branch_coverage * 100

        line_color = self._get_coverage_color(overall_line)
        func_color = self._get_coverage_color(overall_func)
        branch_color = self._get_coverage_color(overall_branch)

        table.add_section()
        table.add_row(
            "[bold]Overall[/bold]",
            f"[bold {line_color}]{overall_line:.1f}%[/bold {line_color}]",
            f"[bold {func_color}]{overall_func:.1f}%[/bold {func_color}]",
            f"[bold {branch_color}]{overall_branch:.1f}%[/bold {branch_color}]",
        )

        self.console.print(table)

    def print_test_results(self, results: list[TestResult]) -> None:
        """Print test execution results."""
        table = Table(title="Test Results", title_style="bold cyan")
        table.add_column("Test", style="bold")
        table.add_column("Status", justify="center")
        table.add_column("Duration", justify="right")
        table.add_column("Message")

        for result in results:
            status_icon = "✓" if result.passed else "✗"
            status_color = "green" if result.passed else "red"
            duration = f"{result.duration:.2f}s" if result.duration else "-"

            table.add_row(
                result.name,
                f"[{status_color}]{status_icon}[/{status_color}]",
                duration,
                result.error_message[:80] if result.error_message else "",
            )

        self.console.print(table)

        # Print summary
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed

        summary_color = "green" if failed == 0 else "red"
        self.console.print(
            f"\n[{summary_color}]Total: {total} | "
            f"Passed: {passed} | Failed: {failed}[/{summary_color}]"
        )

    def create_progress(self, total: int | None = None) -> Progress:
        """Create a progress bar for long-running operations.

        Args:
            total: Total number of items, or None for indeterminate progress.

        Returns:
            A Rich Progress instance.
        """
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn() if total else TextColumn(""),
            TextColumn("[progress.percentage]{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=self.console,
        )

    def _get_coverage_color(self, percentage: float) -> str:
        """Get a color based on coverage percentage."""
        high_threshold = 80.0
        medium_threshold = 50.0

        if percentage >= high_threshold:
            return "green"
        if percentage >= medium_threshold:
            return "yellow"
        return "red"

    def _strip_workdir(self, file_path: str) -> str:
        """Strip the current working directory from file path for cleaner display.

        Args:
            file_path: Full or relative file path.

        Returns:
            Path relative to current working directory.
        """
        cwd = Path.cwd()
        try:
            # Try to make it relative to cwd
            return str(Path(file_path).relative_to(cwd))
        except ValueError:
            # If it's not under cwd, return as-is
            return file_path

    def print_bug_analysis(self, bugs: list[Any]) -> None:
        """Print bug analysis results.

        Args:
            bugs: List of BugReport objects
        """
        if not bugs:
            self.print_info("No bugs found in test failures")
            return

        table = Table(title=f"Bugs Found ({len(bugs)})", title_style="bold red")
        table.add_column("Location", style="bold")
        table.add_column("Type", justify="left")
        table.add_column("Severity", justify="center")

        for bug in bugs:
            severity_color = {
                "HIGH": "red",
                "MEDIUM": "yellow",
                "LOW": "dim",
            }.get(getattr(bug, "severity", "MEDIUM"), "yellow")

            location = (
                f"{bug.file_path}:{bug.line_number}"
                if hasattr(bug, "line_number")
                else str(bug.file_path)
            )
            bug_type = getattr(bug, "bug_type", "Unknown")
            severity = getattr(bug, "severity", "MEDIUM")

            table.add_row(
                location,
                bug_type,
                f"[{severity_color}]{severity}[/{severity_color}]",
            )

        self.console.print(table)

    def print_coverage_gaps(self, gaps: dict[str, Any]) -> None:
        """Print coverage gap analysis.

        Args:
            gaps: Dictionary with file coverage data
        """
        if not gaps:
            self.print_success("No coverage gaps found")
            return

        table = Table(title="Coverage Gaps", title_style="bold yellow")
        table.add_column("File", style="bold")
        table.add_column("Coverage", justify="right")
        table.add_column("Risk", justify="center")
        table.add_column("Functions", justify="right")

        for file_path, gap_info in gaps.items():
            coverage = gap_info.get("coverage", 0.0) * 100
            risk_level = gap_info.get("risk_level", "MEDIUM")
            uncovered_count = gap_info.get("uncovered_functions", 0)

            coverage_color = self._get_coverage_color(coverage)
            risk_color = {
                "HIGH": "red",
                "MEDIUM": "yellow",
                "LOW": "green",
            }.get(risk_level, "yellow")

            table.add_row(
                file_path,
                f"[{coverage_color}]{coverage:.0f}%[/{coverage_color}]",
                f"[{risk_color}]{risk_level}[/{risk_color}]",
                f"{uncovered_count} uncovered",
            )

        self.console.print(table)

    def print_semantic_gap_analysis(
        self,
        gap_report: CoverageGapReport,
        *,
        has_llm_gaps: bool = False,
    ) -> None:
        """Print semantic coverage gap analysis with function-level details.

        Args:
            gap_report: Coverage gap analysis report from CoverageAnalyzer.
            has_llm_gaps: Whether LLM-based semantic gaps were also found.
        """
        if not gap_report.function_gaps and not gap_report.untested_files:
            self.print_success("No significant coverage gaps found")
            return

        # Show overall coverage vs target
        self.console.print()
        self.console.print("[bold cyan]Coverage Gap Analysis[/bold cyan]")
        if has_llm_gaps:
            self.console.print(
                "[dim]Gaps identified using heuristics + LLM semantic analysis[/dim]"
            )
        else:
            self.console.print(
                "[dim]Gaps identified using heuristics (configure LLM for deeper analysis)[/dim]"
            )
        self.console.print()

        current_cov = gap_report.overall_coverage
        target_cov = gap_report.target_coverage
        cov_color = self._get_coverage_color(current_cov)

        self.console.print(
            f"Overall Coverage: [{cov_color}]{current_cov:.1f}%[/{cov_color}] "
            f"(Target: {target_cov:.1f}%)"
        )
        self.console.print()

        # Untested files (if any)
        if gap_report.untested_files:
            self.console.print(
                f"[bold red]Untested Files ({len(gap_report.untested_files)}):[/bold red]"
            )
            for file_path in gap_report.untested_files[:_MAX_UNTESTED_FILES_DISPLAY]:
                self.console.print(f"  • {file_path}")
            if len(gap_report.untested_files) > _MAX_UNTESTED_FILES_DISPLAY:
                remaining = len(gap_report.untested_files) - _MAX_UNTESTED_FILES_DISPLAY
                self.console.print(f"  ... and {remaining} more")
            self.console.print()

        # Function-level gaps by priority
        if gap_report.function_gaps:
            self._print_function_gaps_table(gap_report.function_gaps)

        # Stale tests (if any)
        if gap_report.stale_tests:
            self._print_stale_tests_table(gap_report.stale_tests)

        # Recommendations
        self._print_gap_recommendations(gap_report)

    def _print_function_gaps_table(self, function_gaps: list[FunctionGap]) -> None:
        """Print table of function-level coverage gaps.

        Args:
            function_gaps: List of function gaps sorted by priority.
        """
        # Group by priority
        critical = [g for g in function_gaps if g.priority.value == "critical"]
        high = [g for g in function_gaps if g.priority.value == "high"]
        medium = [g for g in function_gaps if g.priority.value == "medium"]
        low = [g for g in function_gaps if g.priority.value == "low"]

        table = Table(title="Function Coverage Gaps", title_style="bold yellow")
        table.add_column("Priority", style="bold", width=12)
        table.add_column("Function", style="bold", width=25)
        table.add_column("File", width=45)
        table.add_column("Complexity", justify="center", width=10)
        table.add_column("Coverage", justify="right", width=8)
        table.add_column("Visibility", justify="center", width=10)

        # Show all gaps from each priority level
        for gap in critical:
            self._add_gap_row(table, gap, "red")

        for gap in high:
            self._add_gap_row(table, gap, "yellow")

        for gap in medium:
            self._add_gap_row(table, gap, "dim yellow")

        for gap in low:
            self._add_gap_row(table, gap, "dim")

        self.console.print(table)

    def _print_stale_tests_table(self, stale_tests: list[Any]) -> None:
        """Print table of stale test files.

        Args:
            stale_tests: List of StaleTest objects.
        """
        self.console.print()
        table = Table(title=f"Stale Tests ({len(stale_tests)})", title_style="bold yellow")
        table.add_column("Test File", style="bold", width=50)
        table.add_column("Missing Modules", width=30)
        table.add_column("Reason", width=40)

        for stale in stale_tests:
            test_file = self._strip_workdir(stale.test_file)
            missing = ", ".join(stale.missing_imports) if stale.missing_imports else "-"
            if len(missing) > _MAX_STALE_MISSING_IMPORTS_LENGTH:
                missing = missing[:25] + "..."
            reason = (
                stale.reason
                if len(stale.reason) <= _MAX_STALE_REASON_LENGTH
                else stale.reason[:37] + "..."
            )

            table.add_row(test_file, f"[dim]{missing}[/dim]", reason)

        self.console.print(table)

    def _add_gap_row(self, table: Table, gap: FunctionGap, color: str) -> None:
        """Add a single gap row to the table.

        Args:
            table: Rich Table instance.
            gap: Function gap to display.
            color: Color for the priority indicator.
        """
        priority_icon = {
            "critical": "🔴",
            "high": "🟡",
            "medium": "🟠",
            "low": "⚪",
        }.get(gap.priority.value, "•")

        visibility = "public" if gap.is_public else "private"
        cov_color = self._get_coverage_color(gap.coverage_percentage)

        func_name = (
            gap.function_name[:_MAX_FUNCTION_NAME_LENGTH] + "..."
            if len(gap.function_name) > _MAX_FUNCTION_NAME_LENGTH
            else gap.function_name
        )

        # Strip working directory from file path
        file_path = self._strip_workdir(gap.file_path)
        if len(file_path) > _MAX_FILE_PATH_LENGTH:
            file_path = "..." + file_path[-(_MAX_FILE_PATH_LENGTH - 3) :]

        # Format priority to fit on one line with icon
        priority_text = gap.priority.value.upper()

        table.add_row(
            f"[{color}]{priority_icon}\n{priority_text}[/{color}]",
            func_name,
            file_path,
            str(gap.complexity),
            f"[{cov_color}]{gap.coverage_percentage:.0f}%[/{cov_color}]",
            f"[dim]{visibility}[/dim]",
        )

    def _print_gap_recommendations(self, gap_report: CoverageGapReport) -> None:
        """Print recommendations based on gap analysis.

        Args:
            gap_report: Gap analysis report.
        """
        recommendations: list[str] = []

        critical_count = len(
            [g for g in gap_report.function_gaps if g.priority.value == "critical"]
        )
        high_count = len([g for g in gap_report.function_gaps if g.priority.value == "high"])

        if critical_count > 0:
            recommendations.append(
                f"Address {critical_count} CRITICAL gaps first: "
                "high complexity or public API with zero coverage"
            )

        if high_count > 0:
            recommendations.append(
                f"Address {high_count} HIGH priority gaps: "
                "moderate complexity or public API with low coverage"
            )

        if gap_report.untested_files:
            recommendations.append(
                f"Create test files for {len(gap_report.untested_files)} completely untested files"
            )

        if gap_report.stale_tests:
            recommendations.append(
                f"Update or remove {len(gap_report.stale_tests)} stale test files"
            )

        gap_percentage = gap_report.target_coverage - gap_report.overall_coverage
        if gap_percentage > 0:
            recommendations.append(
                f"Improve coverage by {gap_percentage:.1f}% "
                f"to reach target of {gap_report.target_coverage:.1f}%"
            )

        if recommendations:
            self.print_recommendations(recommendations)

    def print_fix_progress(self, bug_id: str, step: str, status: str, message: str = "") -> None:
        """Print progress for a bug fix.

        Args:
            bug_id: Bug identifier
            step: Current step (verify, root_cause, generate, verify_fix, apply)
            status: Status (success, failed, skipped)
            message: Additional message
        """
        icons = {
            "success": "✓",
            "failed": "✗",
            "skipped": "⊘",
        }
        colors = {
            "success": "green",
            "failed": "red",
            "skipped": "yellow",
        }

        icon = icons.get(status, "•")
        color = colors.get(status, "white")

        step_text = {
            "verify": "Bug verified",
            "root_cause": "Root cause",
            "generate": "Fix generated",
            "verify_fix": "Fix verified",
            "apply": "Applied to file",
        }.get(step, step)

        # Display with bug ID prefix
        display_text = f"[{bug_id}] [{color}]{icon}[/{color}] {step_text}"
        if message:
            display_text += f": {message}"

        self.console.print(display_text)

    def print_recommendations(self, recommendations: list[str]) -> None:
        """Print recommendations list.

        Args:
            recommendations: List of recommendation strings
        """
        if not recommendations:
            return

        self.console.print("\n[bold cyan]Recommendations:[/bold cyan]")
        for i, rec in enumerate(recommendations, 1):
            self.console.print(f"  {i}. {rec}")

    # ── Deep analysis display ──────────────────────────────────────────

    def print_code_analysis_summary(self, code_maps: dict[str, Any]) -> None:
        """Print compact summary of deep code analysis.

        Args:
            code_maps: Code analysis results keyed by file path.
        """
        if not code_maps:
            return

        total_funcs = 0
        total_classes = 0
        side_effect_files = 0

        for code_map in code_maps.values():
            total_funcs += len(code_map.functions)
            total_classes += len(code_map.classes)
            if code_map.side_effects_map:
                side_effect_files += 1

        self.console.print()
        self.console.print("[bold cyan]Code Analysis[/bold cyan]")
        self.console.print(
            f"  Analyzed [bold]{len(code_maps)}[/bold] files: "
            f"{total_funcs} functions, {total_classes} classes, "
            f"{side_effect_files} with side effects"
        )

    def print_pattern_profile(self, profile: Any) -> None:
        """Print detected test convention profile.

        Args:
            profile: ConventionProfile from PatternAnalyzer.
        """
        if not profile:
            return

        self.console.print()
        self.console.print("[bold cyan]Test Conventions[/bold cyan]")
        parts = [
            f"{profile.naming_style} naming",
            f"{profile.assertion_style} assertions",
            f"{profile.files_analyzed} files analyzed",
        ]
        self.console.print(f"  {', '.join(parts)}")

        if profile.mocking_patterns:
            mocks = ", ".join(profile.mocking_patterns[:3])
            self.console.print(f"  Mocking: {mocks}")

    def print_risk_report(self, risk_report: Any) -> None:
        """Print risk analysis summary table.

        Args:
            risk_report: RiskReport from RiskAnalyzer.
        """
        if not risk_report or not risk_report.file_risks:
            return

        self.console.print()
        table = Table(title="Risk Analysis", title_style="bold cyan")
        table.add_column("File", style="bold", width=40)
        table.add_column("Risk", justify="center", width=10)
        table.add_column("Score", justify="right", width=8)
        table.add_column("Complexity", justify="right", width=10)
        table.add_column("Coverage", justify="right", width=10)
        table.add_column("Domains", width=20)

        # Show top 15 files sorted by risk score
        _max_risk_rows = 15
        sorted_risks = sorted(
            risk_report.file_risks,
            key=lambda f: f.risk_score.overall_score,
            reverse=True,
        )

        for file_risk in sorted_risks[:_max_risk_rows]:
            level = file_risk.risk_score.level.value.upper()
            level_color = {
                "CRITICAL": "red",
                "HIGH": "yellow",
                "MEDIUM": "dim yellow",
                "LOW": "dim",
            }.get(level, "dim")

            domains = [
                d.value for d in file_risk.risk_score.criticality_domains if d.value != "none"
            ]
            domain_str = ", ".join(domains) if domains else "-"

            file_path = self._strip_workdir(file_risk.file_path)
            if len(file_path) > _MAX_FILE_PATH_LENGTH + 5:
                file_path = "..." + file_path[-(_MAX_FILE_PATH_LENGTH + 2) :]

            cov_color = self._get_coverage_color(file_risk.coverage_percentage)

            table.add_row(
                file_path,
                f"[{level_color}]{level}[/{level_color}]",
                f"{file_risk.risk_score.overall_score:.2f}",
                f"{file_risk.avg_complexity:.1f}",
                f"[{cov_color}]{file_risk.coverage_percentage:.0f}%[/{cov_color}]",
                f"[dim]{domain_str}[/dim]",
            )

        self.console.print(table)

        remaining = len(sorted_risks) - _max_risk_rows
        if remaining > 0:
            self.console.print(f"  [dim]... and {remaining} more files[/dim]")

    def print_integration_deps(self, reports: list[Any]) -> None:
        """Print integration dependency analysis.

        Args:
            reports: List of IntegrationDependencyReport objects.
        """
        if not reports:
            return

        self.console.print()
        self.console.print(
            f"[bold cyan]Integration Dependencies[/bold cyan] "
            f"({len(reports)} files need integration tests)"
        )

        table = Table()
        table.add_column("File", style="bold", width=35)
        table.add_column("Type", width=15)
        table.add_column("Module", width=20)
        table.add_column("Mock Strategy", width=25)

        for report in reports:
            file_name = self._strip_workdir(str(report.source_path))
            if len(file_name) > _MAX_FILE_PATH_LENGTH:
                file_name = "..." + file_name[-(_MAX_FILE_PATH_LENGTH - 3) :]
            for dep in report.dependencies:
                mock = dep.mock_strategies[0] if dep.mock_strategies else "-"
                table.add_row(
                    file_name,
                    dep.dependency_type.value,
                    dep.module_name,
                    f"[dim]{mock}[/dim]",
                )
                file_name = ""  # Only show file name once per group

        self.console.print(table)

    def print_route_flows(self, route_discovery: Any, flow_mapping: Any | None) -> None:
        """Print discovered routes and user flows.

        Args:
            route_discovery: RouteDiscoveryResult.
            flow_mapping: FlowMappingResult (optional).
        """
        if not route_discovery or not route_discovery.routes:
            return

        self.console.print()
        self.console.print("[bold cyan]Route Discovery[/bold cyan]")

        table = Table()
        table.add_column("Path", style="bold", width=30)
        table.add_column("Methods", width=15)
        table.add_column("Type", width=10)
        table.add_column("Auth", justify="center", width=6)

        for route in route_discovery.routes[:_MAX_ROUTES_DISPLAY]:
            methods = ", ".join(m.value for m in route.methods)
            auth = "[green]✓[/green]" if route.auth_required else "[dim]-[/dim]"
            table.add_row(
                route.path,
                methods,
                route.route_type.value,
                auth,
            )

        self.console.print(table)

        if len(route_discovery.routes) > _MAX_ROUTES_DISPLAY:
            remaining = len(route_discovery.routes) - _MAX_ROUTES_DISPLAY
            self.console.print(f"  [dim]... and {remaining} more routes[/dim]")

        # User flows
        if flow_mapping and flow_mapping.flows:
            self.console.print()
            self.console.print("[bold cyan]User Flows[/bold cyan]")

            flow_table = Table()
            flow_table.add_column("Flow", style="bold", width=25)
            flow_table.add_column("Routes", justify="right", width=8)
            flow_table.add_column("Priority", justify="right", width=10)
            flow_table.add_column("Auth", justify="center", width=6)

            for flow in flow_mapping.flows:
                auth = "[green]✓[/green]" if flow.requires_auth else "[dim]-[/dim]"
                flow_table.add_row(
                    flow.name,
                    str(len(flow.routes)),
                    str(flow.priority),
                    auth,
                )

            self.console.print(flow_table)

    def print_semantic_gaps(self, gaps: list[Any]) -> None:
        """Print LLM-identified semantic test gaps.

        Args:
            gaps: List of SemanticGap objects.
        """
        if not gaps:
            return

        self.console.print()
        table = Table(
            title=f"Semantic Test Gaps ({len(gaps)})",
            title_style="bold cyan",
        )
        table.add_column("Function", style="bold", width=20)
        table.add_column("File", width=30)
        table.add_column("Category", width=12)
        table.add_column("Severity", justify="center", width=10)
        table.add_column("Description", width=35)

        for gap in gaps:
            severity_color = {
                "high": "red",
                "medium": "yellow",
                "low": "dim",
            }.get(gap.severity, "yellow")

            file_path = self._strip_workdir(gap.file_path)
            if len(file_path) > _MAX_SEMANTIC_FILE_LENGTH:
                file_path = "..." + file_path[-(_MAX_SEMANTIC_FILE_LENGTH - 3) :]

            func_name = gap.function_name
            if len(func_name) > _MAX_SEMANTIC_FUNC_LENGTH:
                func_name = func_name[: _MAX_SEMANTIC_FUNC_LENGTH - 3] + "..."

            desc = gap.description
            if len(desc) > _MAX_SEMANTIC_DESC_LENGTH:
                desc = desc[: _MAX_SEMANTIC_DESC_LENGTH - 3] + "..."

            table.add_row(
                func_name,
                file_path,
                gap.category.value,
                f"[{severity_color}]{gap.severity}[/{severity_color}]",
                desc,
            )

        self.console.print(table)


# Singleton instance for easy import
reporter = CLIReporter()
