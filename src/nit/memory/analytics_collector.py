"""Central analytics collector for local and remote event tracking.

This module provides a singleton AnalyticsCollector that:
1. Records all analytics events locally to `.nit/history/` (ALWAYS)
2. Optionally sends events to remote platform (if enabled)
3. Provides thread-safe, non-blocking event recording
4. Never crashes the main operation on failure
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from nit.memory.analytics_history import AnalyticsHistory
from nit.models.analytics import (
    AnalyticsEvent,
    CoverageSnapshot,
    EventType,
)

if TYPE_CHECKING:
    from pathlib import Path

    from nit.llm.usage_callback import BatchedUsageReporter
    from nit.models.analytics import (
        BugSnapshot,
        DriftSnapshot,
        LLMUsage,
        TestExecutionSnapshot,
    )
    from nit.models.coverage import CoverageReport

logger = logging.getLogger(__name__)

# Singleton holder — using a mutable dict avoids ``global`` statements
_collector_state: dict[str, AnalyticsCollector | None] = {"instance": None}
_collector_lock = threading.Lock()


class AnalyticsCollector:
    """Central collector for all analytics events.

    This class coordinates:
    - Local storage via AnalyticsHistory (JSONL files)
    - Optional remote platform sync via BatchedUsageReporter
    - Thread-safe event recording
    - Non-blocking operation (failures logged, not raised)
    """

    def __init__(
        self,
        project_root: Path,
        platform_reporter: BatchedUsageReporter | None = None,
    ) -> None:
        """Initialize the analytics collector.

        Args:
            project_root: Root directory of the project.
            platform_reporter: Optional platform reporter for remote sync.
        """
        self._project_root = project_root
        self._history = AnalyticsHistory(project_root)
        self._platform_reporter = platform_reporter
        self._lock = threading.Lock()

        logger.info("Analytics collector initialized for %s", project_root)

    def record_llm_usage(
        self,
        usage: LLMUsage,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an LLM usage event.

        Args:
            usage: LLM usage metrics for the request.
            metadata: Additional event metadata.
        """
        try:
            event = AnalyticsEvent(
                event_type=EventType.LLM_REQUEST,
                llm_usage=usage,
                metadata=metadata or {},
            )

            self._record_event(event, specialized_file="llm_usage")

        except Exception:
            logger.exception("Failed to record LLM usage event")

    def record_coverage(
        self,
        coverage: CoverageReport,
        package_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a coverage snapshot.

        Args:
            coverage: Coverage report from adapter.
            package_name: Optional package name if package-specific.
            metadata: Additional event metadata.
        """
        try:
            # Build per-package coverage dict
            per_package = {
                name: {
                    "line": pkg.line_coverage,
                    "branch": pkg.branch_coverage,
                    "function": pkg.function_coverage,
                }
                for name, pkg in coverage.packages.items()
            }

            event = AnalyticsEvent(
                event_type=EventType.COVERAGE_RUN,
                coverage=CoverageSnapshot(
                    timestamp=datetime.now(UTC).isoformat(),
                    overall_line_coverage=coverage.overall_line_coverage,
                    overall_branch_coverage=coverage.overall_branch_coverage,
                    overall_function_coverage=coverage.overall_function_coverage,
                    per_package=per_package,
                ),
                package_name=package_name,
                metadata=metadata or {},
            )

            self._record_event(event, specialized_file="coverage")

        except Exception:
            logger.exception("Failed to record coverage event")

    def record_test_execution(
        self,
        snapshot: TestExecutionSnapshot,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a test execution snapshot.

        Args:
            snapshot: Test execution snapshot with results.
            metadata: Additional event metadata.
        """
        try:
            event = AnalyticsEvent(
                event_type=EventType.TEST_EXECUTION,
                test_execution=snapshot,
                tests_passing=snapshot.passed_tests,
                tests_failing=snapshot.failed_tests,
                metadata=metadata or {},
            )

            self._record_event(event, specialized_file="test_execution")

        except Exception:
            logger.exception("Failed to record test execution event")

    def record_bug(
        self,
        snapshot: BugSnapshot,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a bug event (discovered, fixed, ignored).

        Args:
            snapshot: Bug snapshot with details.
            metadata: Additional event metadata.
        """
        try:
            event = AnalyticsEvent(
                event_type=(
                    EventType.BUG_FIXED if snapshot.status == "fixed" else EventType.BUG_DISCOVERED
                ),
                bug=snapshot,
                files=[snapshot.file_path],
                metadata=metadata or {},
            )

            self._record_event(event, specialized_file="bug")

        except Exception:
            logger.exception("Failed to record bug event")

    def record_drift_test(
        self,
        snapshot: DriftSnapshot,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a drift test result.

        Args:
            snapshot: Drift test result snapshot.
            metadata: Additional event metadata.
        """
        try:
            event = AnalyticsEvent(
                event_type=EventType.DRIFT_TEST,
                drift=snapshot,
                metadata=metadata or {},
            )

            self._record_event(event, specialized_file="drift")

        except Exception:
            logger.exception("Failed to record drift test event")

    def record_pr_created(
        self,
        pr_url: str,
        files: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a PR creation event.

        Args:
            pr_url: URL of the created PR.
            files: List of files included in the PR.
            metadata: Additional event metadata (e.g., tests_generated, draft).
        """
        try:
            event = AnalyticsEvent(
                event_type=EventType.PR_CREATED,
                pr_url=pr_url,
                files=files,
                metadata=metadata or {},
            )

            self._record_event(event, specialized_file="pr")

        except Exception:
            logger.exception("Failed to record PR creation event")

    def record_issue_created(
        self,
        issue_url: str,
        bug_type: str,
        severity: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an issue creation event.

        Args:
            issue_url: URL of the created issue.
            bug_type: Type of bug (from BugType enum value).
            severity: Severity level (from BugSeverity enum value).
            metadata: Additional event metadata.
        """
        try:
            event = AnalyticsEvent(
                event_type=EventType.ISSUE_CREATED,
                issue_url=issue_url,
                metadata={
                    "bug_type": bug_type,
                    "severity": severity,
                    **(metadata or {}),
                },
            )

            self._record_event(event, specialized_file="issue")

        except Exception:
            logger.exception("Failed to record issue creation event")

    def _record_event(
        self,
        event: AnalyticsEvent,
        specialized_file: str | None = None,
    ) -> None:
        """Record an event to local history.

        Thread-safe method that writes to JSONL files.

        Args:
            event: The analytics event to record.
            specialized_file: Optional specialized file key for efficient queries.
        """
        with self._lock:
            try:
                # Always write locally
                self._history.append_event(event, specialized_file=specialized_file)
                logger.debug(
                    "Recorded %s event (local)",
                    event.event_type.value,
                )

            except Exception:
                logger.exception("Failed to write event to local history")

    def flush(self) -> None:
        """Flush any buffered events.

        This is a no-op for the local history (writes are immediate),
        but can be used for cleanup or final logging.
        """
        logger.debug("Analytics collector flushed")


def get_analytics_collector(
    project_root: Path,
    platform_reporter: BatchedUsageReporter | None = None,
) -> AnalyticsCollector:
    """Get or create the singleton analytics collector.

    Args:
        project_root: Root directory of the project.
        platform_reporter: Optional platform reporter for remote sync.

    Returns:
        The singleton AnalyticsCollector instance.
    """
    with _collector_lock:
        instance = _collector_state["instance"]
        if instance is None:
            instance = AnalyticsCollector(
                project_root,
                platform_reporter=platform_reporter,
            )
            _collector_state["instance"] = instance
        return instance


def reset_analytics_collector() -> None:
    """Reset the singleton collector (for testing)."""
    with _collector_lock:
        _collector_state["instance"] = None
