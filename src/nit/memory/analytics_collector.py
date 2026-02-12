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
    BugSnapshot,
    CoverageSnapshot,
    DriftSnapshot,
    EventType,
    LLMUsage,
    TestExecutionSnapshot,
)

if TYPE_CHECKING:
    from pathlib import Path

    from nit.llm.usage_callback import BatchedUsageReporter
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
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float | None = None,
        duration_ms: float | None = None,
        cached_tokens: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an LLM usage event.

        Args:
            provider: LLM provider (e.g., "openai", "anthropic").
            model: Model name (e.g., "gpt-4", "claude-sonnet-4-5").
            prompt_tokens: Number of input tokens.
            completion_tokens: Number of output tokens.
            cost_usd: Estimated cost in USD (None for local models).
            duration_ms: Request duration in milliseconds.
            cached_tokens: Number of cached tokens (if applicable).
            metadata: Additional event metadata.
        """
        try:
            event = AnalyticsEvent(
                event_type=EventType.LLM_REQUEST,
                llm_usage=LLMUsage(
                    provider=provider,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    cost_usd=cost_usd,
                    duration_ms=duration_ms,
                    cached_tokens=cached_tokens,
                ),
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
        total: int,
        passed: int,
        failed: int,
        skipped: int = 0,
        duration_ms: float | None = None,
        flaky_tests: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a test execution snapshot.

        Args:
            total: Total number of tests.
            passed: Number of passed tests.
            failed: Number of failed tests.
            skipped: Number of skipped tests.
            duration_ms: Total execution time in milliseconds.
            flaky_tests: List of flaky test names.
            metadata: Additional event metadata.
        """
        try:
            event = AnalyticsEvent(
                event_type=EventType.TEST_EXECUTION,
                test_execution=TestExecutionSnapshot(
                    timestamp=datetime.now(UTC).isoformat(),
                    total_tests=total,
                    passed_tests=passed,
                    failed_tests=failed,
                    skipped_tests=skipped,
                    total_duration_ms=duration_ms,
                    flaky_tests=flaky_tests or [],
                ),
                tests_generated=None,  # For generated test runs, caller can set this
                tests_passing=passed,
                tests_failing=failed,
                metadata=metadata or {},
            )

            self._record_event(event, specialized_file="test_execution")

        except Exception:
            logger.exception("Failed to record test execution event")

    def record_bug(
        self,
        bug_type: str,
        severity: str,
        status: str,
        file_path: str,
        line_number: int | None = None,
        title: str = "",
        pr_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a bug event (discovered, fixed, ignored).

        Args:
            bug_type: Type of bug (from BugType enum value).
            severity: Severity level (from BugSeverity enum value).
            status: Bug status: "discovered", "fixed", "ignored".
            file_path: File where bug was found.
            line_number: Line number of bug.
            title: Short bug description.
            pr_url: URL of PR that fixed the bug (if fixed).
            metadata: Additional event metadata.
        """
        try:
            event = AnalyticsEvent(
                event_type=(EventType.BUG_FIXED if status == "fixed" else EventType.BUG_DISCOVERED),
                bug=BugSnapshot(
                    timestamp=datetime.now(UTC).isoformat(),
                    bug_type=bug_type,
                    severity=severity,
                    status=status,
                    file_path=file_path,
                    line_number=line_number,
                    title=title,
                    pr_url=pr_url,
                ),
                files=[file_path],
                metadata=metadata or {},
            )

            self._record_event(event, specialized_file="bug")

        except Exception:
            logger.exception("Failed to record bug event")

    def record_drift_test(
        self,
        test_id: str,
        test_name: str,
        similarity_score: float,
        passed: bool,
        drift_detected: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a drift test result.

        Args:
            test_id: Unique test identifier.
            test_name: Human-readable test name.
            similarity_score: Similarity score (0.0 to 1.0).
            passed: Whether drift test passed.
            drift_detected: Whether drift was detected.
            metadata: Additional event metadata.
        """
        try:
            event = AnalyticsEvent(
                event_type=EventType.DRIFT_TEST,
                drift=DriftSnapshot(
                    timestamp=datetime.now(UTC).isoformat(),
                    test_id=test_id,
                    test_name=test_name,
                    similarity_score=similarity_score,
                    passed=passed,
                    drift_detected=drift_detected,
                ),
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
