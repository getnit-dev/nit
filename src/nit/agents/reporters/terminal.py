"""Terminal reporter with rich output formatting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

if TYPE_CHECKING:
    from nit.models.coverage import CoverageReport
    from nit.models.test_result import TestResult

console = Console()


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


# Singleton instance for easy import
reporter = CLIReporter()
