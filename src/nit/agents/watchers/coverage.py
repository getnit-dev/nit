"""CoverageWatcher agent for tracking coverage trends (task 4.15.2).

Tracks coverage trends over time and alerts on drops below threshold.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from nit.adapters.coverage import (
    CoveragePyAdapter,
    GcovAdapter,
    GoCoverAdapter,
    IstanbulAdapter,
    JaCoCoAdapter,
)
from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus

if TYPE_CHECKING:
    from pathlib import Path

    from nit.adapters.coverage.base import CoverageAdapter

logger = logging.getLogger(__name__)

# Constants
_MIN_HISTORY_FOR_COMPARISON = 2  # Minimum history entries needed for comparison


@dataclass
class CoverageSnapshot:
    """Snapshot of coverage at a point in time."""

    timestamp: str
    """ISO timestamp when coverage was measured."""

    overall_line_coverage: float
    """Overall line coverage percentage (0.0-100.0)."""

    overall_function_coverage: float
    """Overall function coverage percentage (0.0-100.0)."""

    overall_branch_coverage: float
    """Overall branch coverage percentage (0.0-100.0)."""

    file_count: int
    """Total number of files with coverage data."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata (e.g., git commit, CI build number)."""


@dataclass
class CoverageAlert:
    """Alert for coverage drop."""

    severity: str
    """Alert severity: 'critical', 'warning', 'info'."""

    message: str
    """Human-readable alert message."""

    current_coverage: float
    """Current coverage percentage."""

    previous_coverage: float
    """Previous coverage percentage."""

    drop_percentage: float
    """Percentage point drop."""

    threshold: float
    """Configured threshold."""


@dataclass
class CoverageTrendReport:
    """Report of coverage trends over time."""

    current_snapshot: CoverageSnapshot
    """Current coverage snapshot."""

    previous_snapshot: CoverageSnapshot | None = None
    """Previous coverage snapshot for comparison."""

    trend: str = "stable"
    """Trend indicator: 'increasing', 'decreasing', 'stable'."""

    alerts: list[CoverageAlert] = field(default_factory=list)
    """Coverage alerts (if any)."""

    history_count: int = 0
    """Total number of snapshots in history."""


class CoverageWatcher(BaseAgent):
    """Agent for tracking coverage trends over time (task 4.15.2).

    Monitors coverage trends, stores historical data, and alerts on drops
    below configured thresholds.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        coverage_threshold: float = 80.0,
        drop_threshold: float = 5.0,
        history_limit: int = 100,
    ) -> None:
        """Initialize the coverage watcher.

        Args:
            project_root: Root directory of the project.
            coverage_threshold: Minimum acceptable coverage percentage (default: 80%).
            drop_threshold: Alert if coverage drops by more than this percentage
                (default: 5.0 percentage points).
            history_limit: Maximum number of historical snapshots to keep (default: 100).
        """
        self._project_root = project_root
        self._coverage_threshold = coverage_threshold
        self._drop_threshold = drop_threshold
        self._history_limit = history_limit
        self._memory_dir = project_root / ".nit" / "memory"
        self._coverage_history_file = self._memory_dir / "coverage_history.json"
        self._adapters = self._initialize_adapters()

    @property
    def name(self) -> str:
        """Agent identifier."""
        return "coverage_watcher"

    @property
    def description(self) -> str:
        """Human-readable description."""
        return "Tracks coverage trends over time and alerts on drops below threshold"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute coverage trend monitoring task.

        Task context can include:
        - mode: "collect" | "report" (default: "collect")
        - metadata: Optional metadata to attach to snapshot (e.g., git commit)

        Args:
            task: The coverage monitoring task.

        Returns:
            Task output with trend report.
        """
        mode = task.context.get("mode", "collect")
        metadata = task.context.get("metadata", {})

        try:
            if mode == "collect":
                report = await self.collect_and_analyze(metadata)
            else:
                report = await self.get_current_trend()

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "current_coverage": {
                        "timestamp": report.current_snapshot.timestamp,
                        "line_coverage": report.current_snapshot.overall_line_coverage,
                        "function_coverage": report.current_snapshot.overall_function_coverage,
                        "branch_coverage": report.current_snapshot.overall_branch_coverage,
                        "file_count": report.current_snapshot.file_count,
                    },
                    "trend": report.trend,
                    "alerts": [
                        {
                            "severity": alert.severity,
                            "message": alert.message,
                            "current": alert.current_coverage,
                            "previous": alert.previous_coverage,
                            "drop": alert.drop_percentage,
                        }
                        for alert in report.alerts
                    ],
                    "history_count": report.history_count,
                },
            )

        except Exception as e:
            logger.error("Coverage monitoring failed: %s", e)
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[str(e)],
            )

    async def collect_and_analyze(
        self, metadata: dict[str, Any] | None = None
    ) -> CoverageTrendReport:
        """Collect current coverage and analyze trends.

        Args:
            metadata: Optional metadata to attach to snapshot.

        Returns:
            Coverage trend report.
        """
        # Detect and run appropriate coverage adapter
        adapter = self._detect_coverage_adapter()
        if not adapter:
            raise RuntimeError("No coverage adapter detected for this project")

        logger.info("Running coverage with adapter: %s", adapter.name)
        coverage_report = await adapter.run_coverage(self._project_root)

        # Create snapshot
        snapshot = CoverageSnapshot(
            timestamp=datetime.now(UTC).isoformat(),
            overall_line_coverage=coverage_report.overall_line_coverage,
            overall_function_coverage=coverage_report.overall_function_coverage,
            overall_branch_coverage=coverage_report.overall_branch_coverage,
            file_count=len(coverage_report.files),
            metadata=metadata or {},
        )

        # Load history and compare
        history = self._load_history()
        previous_snapshot = history[-1] if history else None

        # Analyze trend
        trend = self._determine_trend(snapshot, previous_snapshot)

        # Check for alerts
        alerts = self._check_alerts(snapshot, previous_snapshot)

        # Save snapshot to history
        history.append(snapshot)
        self._save_history(history)

        logger.info(
            "Coverage collected: %.2f%% line, %.2f%% function, %.2f%% branch",
            snapshot.overall_line_coverage,
            snapshot.overall_function_coverage,
            snapshot.overall_branch_coverage,
        )

        return CoverageTrendReport(
            current_snapshot=snapshot,
            previous_snapshot=previous_snapshot,
            trend=trend,
            alerts=alerts,
            history_count=len(history),
        )

    async def get_current_trend(self) -> CoverageTrendReport:
        """Get current coverage trend from history.

        Returns:
            Coverage trend report.
        """
        history = self._load_history()

        if not history:
            raise RuntimeError("No coverage history available")

        current = history[-1]
        previous = history[-2] if len(history) >= _MIN_HISTORY_FOR_COMPARISON else None

        trend = self._determine_trend(current, previous)
        alerts = self._check_alerts(current, previous)

        return CoverageTrendReport(
            current_snapshot=current,
            previous_snapshot=previous,
            trend=trend,
            alerts=alerts,
            history_count=len(history),
        )

    def get_history(self, limit: int | None = None) -> list[CoverageSnapshot]:
        """Get coverage history.

        Args:
            limit: Maximum number of snapshots to return (most recent first).

        Returns:
            List of coverage snapshots.
        """
        history = self._load_history()
        if limit:
            return history[-limit:]
        return history

    def _determine_trend(self, current: CoverageSnapshot, previous: CoverageSnapshot | None) -> str:
        """Determine coverage trend.

        Args:
            current: Current coverage snapshot.
            previous: Previous coverage snapshot.

        Returns:
            Trend indicator: 'increasing', 'decreasing', or 'stable'.
        """
        if not previous:
            return "stable"

        current_avg = (
            current.overall_line_coverage
            + current.overall_function_coverage
            + current.overall_branch_coverage
        ) / 3.0

        previous_avg = (
            previous.overall_line_coverage
            + previous.overall_function_coverage
            + previous.overall_branch_coverage
        ) / 3.0

        diff = current_avg - previous_avg

        if diff > 1.0:
            return "increasing"
        if diff < -1.0:
            return "decreasing"
        return "stable"

    def _check_alerts(
        self, current: CoverageSnapshot, previous: CoverageSnapshot | None
    ) -> list[CoverageAlert]:
        """Check for coverage alerts.

        Args:
            current: Current coverage snapshot.
            previous: Previous coverage snapshot.

        Returns:
            List of coverage alerts.
        """
        alerts = []

        # Check if below threshold
        if current.overall_line_coverage < self._coverage_threshold:
            message = (
                f"Line coverage ({current.overall_line_coverage:.2f}%) is below "
                f"threshold ({self._coverage_threshold:.2f}%)"
            )
            alerts.append(
                CoverageAlert(
                    severity="warning",
                    message=message,
                    current_coverage=current.overall_line_coverage,
                    previous_coverage=previous.overall_line_coverage if previous else 0.0,
                    drop_percentage=0.0,
                    threshold=self._coverage_threshold,
                )
            )

        # Check for drops
        if previous:
            line_drop = previous.overall_line_coverage - current.overall_line_coverage
            if line_drop > self._drop_threshold:
                message = (
                    f"Line coverage dropped by {line_drop:.2f} percentage points "
                    f"({previous.overall_line_coverage:.2f}% → "
                    f"{current.overall_line_coverage:.2f}%)"
                )
                alerts.append(
                    CoverageAlert(
                        severity="critical",
                        message=message,
                        current_coverage=current.overall_line_coverage,
                        previous_coverage=previous.overall_line_coverage,
                        drop_percentage=line_drop,
                        threshold=self._drop_threshold,
                    )
                )

            function_drop = previous.overall_function_coverage - current.overall_function_coverage
            if function_drop > self._drop_threshold:
                message = (
                    f"Function coverage dropped by {function_drop:.2f} percentage points "
                    f"({previous.overall_function_coverage:.2f}% → "
                    f"{current.overall_function_coverage:.2f}%)"
                )
                alerts.append(
                    CoverageAlert(
                        severity="critical",
                        message=message,
                        current_coverage=current.overall_function_coverage,
                        previous_coverage=previous.overall_function_coverage,
                        drop_percentage=function_drop,
                        threshold=self._drop_threshold,
                    )
                )

        return alerts

    def _load_history(self) -> list[CoverageSnapshot]:
        """Load coverage history from disk.

        Returns:
            List of coverage snapshots.
        """
        if not self._coverage_history_file.exists():
            return []

        try:
            with self._coverage_history_file.open() as f:
                data = json.load(f)
                return [
                    CoverageSnapshot(
                        timestamp=item["timestamp"],
                        overall_line_coverage=item["overall_line_coverage"],
                        overall_function_coverage=item["overall_function_coverage"],
                        overall_branch_coverage=item["overall_branch_coverage"],
                        file_count=item["file_count"],
                        metadata=item.get("metadata", {}),
                    )
                    for item in data
                ]
        except Exception as e:
            logger.error("Failed to load coverage history: %s", e)
            return []

    def _save_history(self, history: list[CoverageSnapshot]) -> None:
        """Save coverage history to disk.

        Args:
            history: List of coverage snapshots to save.
        """
        # Enforce history limit
        if len(history) > self._history_limit:
            history = history[-self._history_limit :]

        # Ensure directory exists
        self._memory_dir.mkdir(parents=True, exist_ok=True)

        try:
            data = [
                {
                    "timestamp": snapshot.timestamp,
                    "overall_line_coverage": snapshot.overall_line_coverage,
                    "overall_function_coverage": snapshot.overall_function_coverage,
                    "overall_branch_coverage": snapshot.overall_branch_coverage,
                    "file_count": snapshot.file_count,
                    "metadata": snapshot.metadata,
                }
                for snapshot in history
            ]

            with self._coverage_history_file.open("w") as f:
                json.dump(data, f, indent=2)

            logger.debug("Saved coverage history: %d snapshots", len(history))

        except Exception as e:
            logger.error("Failed to save coverage history: %s", e)

    def _initialize_adapters(self) -> list[CoverageAdapter]:
        """Initialize all available coverage adapters.

        Returns:
            List of coverage adapters.
        """
        return [
            IstanbulAdapter(),
            CoveragePyAdapter(),
            GcovAdapter(),
            GoCoverAdapter(),
            JaCoCoAdapter(),
        ]

    def _detect_coverage_adapter(self) -> CoverageAdapter | None:
        """Detect which coverage adapter to use for this project.

        Returns:
            The detected coverage adapter, or None if none detected.
        """
        for adapter in self._adapters:
            if adapter.detect(self._project_root):
                return adapter
        return None
