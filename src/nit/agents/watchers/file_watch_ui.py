"""Simple Rich-based UI display for the file watcher status.

Provides a lightweight status display that prints watcher state,
recently changed files, and test run results to the terminal.
"""

from __future__ import annotations

from rich.console import Console

_MAX_RECENT_CHANGES = 10

_STATUS_ICONS: dict[str, str] = {
    "IDLE": "[dim]...[/dim]",
    "RUNNING": "[bold cyan]>>>[/bold cyan]",
    "SUCCESS": "[bold green]OK[/bold green]",
    "FAILED": "[bold red]FAIL[/bold red]",
}


class FileWatchUI:
    """Rich terminal UI for displaying file watcher status.

    Prints formatted status updates to the console, including the
    current watcher state, list of changed files, and test results.
    """

    def __init__(self) -> None:
        """Initialize the file watch UI."""
        self._status: str = "IDLE"
        self._last_changes: list[str] = []
        self._last_result: str = ""
        self._console: Console = Console()

    def update_status(self, status: str) -> None:
        """Update the current watcher status.

        Args:
            status: New status value (IDLE, RUNNING, SUCCESS, FAILED).
        """
        self._status = status

    def update_changes(self, changed_files: list[str]) -> None:
        """Update the list of recently changed files.

        Keeps only the most recent files, up to the display limit.

        Args:
            changed_files: List of changed file paths.
        """
        self._last_changes = changed_files[-_MAX_RECENT_CHANGES:]

    def update_result(self, result: str) -> None:
        """Update the last test result summary.

        Args:
            result: Human-readable test result summary.
        """
        self._last_result = result

    def render(self) -> None:
        """Print the current status to the console.

        Displays a formatted status line showing the watcher state,
        number of changed files, and last test result.
        """
        icon = _STATUS_ICONS.get(self._status, self._status)
        change_count = len(self._last_changes)
        result_text = self._last_result or "no results yet"

        self._console.print(
            f"  {icon}  status={self._status}  changes={change_count}  result={result_text}"
        )

    def clear(self) -> None:
        """Clear the display and reset state."""
        self._status = "IDLE"
        self._last_changes = []
        self._last_result = ""
