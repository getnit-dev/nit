"""Query interface for analytics data aggregation.

Provides high-level queries for dashboard data visualization.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from nit.memory.analytics_history import AnalyticsHistory
from nit.memory.global_memory import GlobalMemory
from nit.models.analytics import EventType

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

# Constants for test health thresholds
_MAX_TEST_EXECUTIONS_TO_ANALYZE = 100


class AnalyticsQueries:
    """Query interface for analytics data.

    Aggregates historical events for dashboard visualization.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize analytics queries.

        Args:
            project_root: Root directory of the project.
        """
        self._history = AnalyticsHistory(project_root)
        self._memory = GlobalMemory(project_root)

    def get_coverage_trend(self, days: int = 30) -> list[dict[str, Any]]:
        """Get coverage trend over time.

        Args:
            days: Number of days to look back.

        Returns:
            List of coverage snapshots: [{timestamp, overall_line, overall_branch, packages}]
        """
        try:
            return [
                {
                    "timestamp": event.coverage.timestamp,
                    "overall_line": event.coverage.overall_line_coverage,
                    "overall_branch": event.coverage.overall_branch_coverage,
                    "overall_function": event.coverage.overall_function_coverage,
                    "packages": event.coverage.per_package,
                }
                for event in self._history.get_events_since(days=days, from_file="coverage")
                if event.coverage
            ]

        except Exception:
            logger.exception("Failed to get coverage trend")
            return []

    def get_bug_timeline(self, days: int = 30) -> list[dict[str, Any]]:
        """Get bug discovery/fix timeline aggregated by day.

        Args:
            days: Number of days to look back.

        Returns:
            List of daily bug counts: [{date, discovered, fixed, open}]
        """
        # Aggregate bugs by day
        bugs_by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"discovered": 0, "fixed": 0})

        try:
            for event in self._history.get_events_since(days=days, from_file="bugs"):
                if event.bug:
                    # Extract date from timestamp
                    date = event.bug.timestamp.split("T")[0]

                    if event.bug.status == "discovered":
                        bugs_by_day[date]["discovered"] += 1
                    elif event.bug.status == "fixed":
                        bugs_by_day[date]["fixed"] += 1

        except Exception:
            logger.exception("Failed to get bug timeline")

        # Convert to sorted list
        return [
            {
                "date": date,
                "discovered": counts["discovered"],
                "fixed": counts["fixed"],
                "open": counts["discovered"] - counts["fixed"],
            }
            for date, counts in sorted(bugs_by_day.items())
        ]

    def get_test_health(self) -> dict[str, Any]:
        """Get test health summary.

        Returns:
            Dictionary with total_tests, passed_tests, failed_tests,
            pass_rate, flaky_tests, and avg_duration_ms.
        """
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        durations: list[float] = []
        flaky_tests_set: set[str] = set()

        try:
            # Get last test executions (limited to _MAX_TEST_EXECUTIONS_TO_ANALYZE)
            for count, event in enumerate(
                self._history.read_events(
                    event_type=EventType.TEST_EXECUTION, from_file="test_execution"
                )
            ):
                if event.test_execution:
                    total_tests = event.test_execution.total_tests
                    passed_tests = event.test_execution.passed_tests
                    failed_tests = event.test_execution.failed_tests

                    if event.test_execution.total_duration_ms:
                        durations.append(event.test_execution.total_duration_ms)

                    if event.test_execution.flaky_tests:
                        flaky_tests_set.update(event.test_execution.flaky_tests)

                    if count + 1 >= _MAX_TEST_EXECUTIONS_TO_ANALYZE:
                        break

        except Exception:
            logger.exception("Failed to get test health")

        pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0.0
        avg_duration = sum(durations) / len(durations) if durations else 0.0

        return {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "pass_rate": pass_rate,
            "flaky_tests": list(flaky_tests_set),
            "avg_duration_ms": avg_duration,
        }

    def get_drift_summary(self, days: int = 30) -> list[dict[str, Any]]:
        """Get drift test summary with results over time.

        Args:
            days: Number of days to look back.

        Returns:
            List of drift tests with results including test_name, test_id,
            and results list with timestamp, similarity, and passed status.
        """
        # Group results by test_id
        tests_by_id: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"test_name": "", "test_id": "", "results": []}
        )

        try:
            for event in self._history.get_events_since(days=days, from_file="drift"):
                if event.drift:
                    test_id = event.drift.test_id
                    tests_by_id[test_id]["test_name"] = event.drift.test_name
                    tests_by_id[test_id]["test_id"] = test_id
                    tests_by_id[test_id]["results"].append(
                        {
                            "timestamp": event.drift.timestamp,
                            "similarity": event.drift.similarity_score,
                            "passed": event.drift.passed,
                        }
                    )

        except Exception:
            logger.exception("Failed to get drift summary")

        return list(tests_by_id.values())

    def get_llm_usage_summary(self, days: int = 30) -> dict[str, Any]:
        """Get LLM usage and cost summary.

        Args:
            days: Number of days to look back.

        Returns:
            Dict with: {total_tokens, total_cost_usd, by_model, by_provider, by_day}
        """
        total_tokens = 0
        total_cost_usd = 0.0
        by_model: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"tokens": 0, "cost": 0.0, "requests": 0}
        )
        by_provider: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"tokens": 0, "cost": 0.0, "requests": 0}
        )
        by_day: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"tokens": 0, "cost": 0.0, "requests": 0}
        )

        try:
            for event in self._history.get_events_since(days=days, from_file="llm_usage"):
                if event.llm_usage:
                    usage = event.llm_usage
                    tokens = usage.total_tokens
                    cost = usage.cost_usd or 0.0

                    total_tokens += tokens
                    total_cost_usd += cost

                    # By model
                    by_model[usage.model]["tokens"] += tokens
                    by_model[usage.model]["cost"] += cost
                    by_model[usage.model]["requests"] += 1

                    # By provider
                    by_provider[usage.provider]["tokens"] += tokens
                    by_provider[usage.provider]["cost"] += cost
                    by_provider[usage.provider]["requests"] += 1

                    # By day
                    date = event.timestamp.split("T")[0]
                    by_day[date]["tokens"] += tokens
                    by_day[date]["cost"] += cost
                    by_day[date]["requests"] += 1

        except Exception:
            logger.exception("Failed to get LLM usage summary")

        return {
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost_usd,
            "by_model": dict(by_model),
            "by_provider": dict(by_provider),
            "by_day": dict(by_day),
        }

    def get_memory_insights(self) -> dict[str, Any]:
        """Get learned patterns and conventions from memory.

        Returns:
            Dict with: {conventions, known_patterns, failed_patterns, stats}
        """
        try:
            return {
                "conventions": self._memory.get_conventions(),
                "known_patterns": self._memory.get_known_patterns(),
                "failed_patterns": self._memory.get_failed_patterns(),
                "stats": self._memory.get_stats(),
            }
        except Exception:
            logger.exception("Failed to get memory insights")
            return {
                "conventions": {},
                "known_patterns": [],
                "failed_patterns": [],
                "stats": {},
            }

    def get_activity_timeline(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent activity timeline (all event types).

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of events with: [{timestamp, type, description}]
        """
        try:
            return [
                {
                    "timestamp": event.timestamp,
                    "type": event.event_type.value,
                    "description": self._format_event_description(event),
                }
                for event in self._history.read_events(limit=limit)
            ]

        except Exception:
            logger.exception("Failed to get activity timeline")
            return []

    @staticmethod
    def _format_event_description(event: Any) -> str:
        """Format a human-readable description for an event.

        Args:
            event: The analytics event.

        Returns:
            Human-readable description.
        """
        formatters: dict[EventType, Callable[[Any], str | None]] = {
            EventType.LLM_REQUEST: lambda e: (
                f"{e.llm_usage.provider}/{e.llm_usage.model}: {e.llm_usage.total_tokens} tokens"
                if e.llm_usage
                else None
            ),
            EventType.COVERAGE_RUN: lambda e: (
                f"Coverage: {e.coverage.overall_line_coverage * 100:.1f}%" if e.coverage else None
            ),
            EventType.BUG_DISCOVERED: lambda e: (
                f"Bug discovered: {e.bug.title}" if e.bug else None
            ),
            EventType.BUG_FIXED: lambda e: (f"Bug fixed: {e.bug.title}" if e.bug else None),
            EventType.DRIFT_TEST: lambda e: (
                f"Drift test: {e.drift.test_name} ({e.drift.similarity_score:.2f})"
                if e.drift
                else None
            ),
            EventType.PR_CREATED: lambda e: f"PR created: {e.pr_url}",
            EventType.ISSUE_CREATED: lambda e: f"Issue created: {e.issue_url}",
        }

        formatter = formatters.get(event.event_type)
        if formatter is not None:
            result = formatter(event)
            if result is not None:
                return result

        return str(event.event_type.value)
