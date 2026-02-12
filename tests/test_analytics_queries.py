"""Tests for AnalyticsQueries — coverage, bugs, drift, LLM usage, memory, and activity."""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.memory.analytics_history import AnalyticsHistory
from nit.memory.analytics_queries import AnalyticsQueries
from nit.models.analytics import (
    AnalyticsEvent,
    BugSnapshot,
    CoverageSnapshot,
    DriftSnapshot,
    EventType,
    LLMUsage,
    TestExecutionSnapshot,
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a minimal project with .nit/history/ directory."""
    (tmp_path / ".nit" / "history").mkdir(parents=True)
    # Also create .nit/memory dir for GlobalMemory
    (tmp_path / ".nit" / "memory").mkdir(parents=True)
    return tmp_path


def _append_event(project: Path, event: AnalyticsEvent, file_key: str) -> None:
    """Write an event to the given history JSONL file."""
    history = AnalyticsHistory(project)
    history.append_event(event, specialized_file=file_key)


class TestGetCoverageTrend:
    """Tests for get_coverage_trend."""

    def test_empty_history(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        result = queries.get_coverage_trend(days=30)
        assert result == []

    def test_returns_coverage_snapshots(self, project: Path) -> None:
        event = AnalyticsEvent(
            event_type=EventType.COVERAGE_RUN,
            timestamp="2026-02-10T12:00:00+00:00",
            coverage=CoverageSnapshot(
                timestamp="2026-02-10T12:00:00+00:00",
                overall_line_coverage=0.85,
                overall_branch_coverage=0.72,
                overall_function_coverage=0.90,
                per_package={"nit": {"line": 0.85}},
            ),
        )
        _append_event(project, event, "coverage")

        queries = AnalyticsQueries(project)
        trend = queries.get_coverage_trend(days=30)
        assert len(trend) >= 1
        assert trend[0]["overall_line"] == 0.85
        assert trend[0]["overall_branch"] == 0.72
        assert trend[0]["packages"] == {"nit": {"line": 0.85}}


class TestGetBugTimeline:
    """Tests for get_bug_timeline."""

    def test_empty_history(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        result = queries.get_bug_timeline(days=30)
        assert result == []

    def test_aggregates_bugs_by_day(self, project: Path) -> None:
        discovered = AnalyticsEvent(
            event_type=EventType.BUG_DISCOVERED,
            timestamp="2026-02-10T12:00:00+00:00",
            bug=BugSnapshot(
                timestamp="2026-02-10T12:00:00+00:00",
                bug_type="logic_error",
                severity="high",
                status="discovered",
                file_path="src/foo.py",
                title="Null pointer",
            ),
        )
        fixed = AnalyticsEvent(
            event_type=EventType.BUG_FIXED,
            timestamp="2026-02-10T14:00:00+00:00",
            bug=BugSnapshot(
                timestamp="2026-02-10T14:00:00+00:00",
                bug_type="logic_error",
                severity="high",
                status="fixed",
                file_path="src/foo.py",
                title="Null pointer",
            ),
        )
        _append_event(project, discovered, "bug")
        _append_event(project, fixed, "bug")

        queries = AnalyticsQueries(project)
        timeline = queries.get_bug_timeline(days=30)
        assert len(timeline) >= 1
        day_entry = timeline[0]
        assert day_entry["date"] == "2026-02-10"
        assert day_entry["discovered"] == 1
        assert day_entry["fixed"] == 1
        assert day_entry["open"] == 0


class TestGetTestHealth:
    """Tests for get_test_health."""

    def test_empty_history(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        result = queries.get_test_health()
        assert result["total_tests"] == 0
        assert result["pass_rate"] == 0.0

    def test_computes_pass_rate(self, project: Path) -> None:
        event = AnalyticsEvent(
            event_type=EventType.TEST_EXECUTION,
            timestamp="2026-02-10T12:00:00+00:00",
            test_execution=TestExecutionSnapshot(
                timestamp="2026-02-10T12:00:00+00:00",
                total_tests=10,
                passed_tests=8,
                failed_tests=2,
                total_duration_ms=1500.0,
                flaky_tests=["test_flaky"],
            ),
        )
        _append_event(project, event, "test_execution")

        queries = AnalyticsQueries(project)
        health = queries.get_test_health()
        assert health["total_tests"] == 10
        assert health["passed_tests"] == 8
        assert health["pass_rate"] == pytest.approx(80.0)
        assert health["avg_duration_ms"] == pytest.approx(1500.0)
        assert "test_flaky" in health["flaky_tests"]


class TestGetDriftSummary:
    """Tests for get_drift_summary."""

    def test_empty_history(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        result = queries.get_drift_summary(days=30)
        assert result == []

    def test_groups_by_test_id(self, project: Path) -> None:
        event = AnalyticsEvent(
            event_type=EventType.DRIFT_TEST,
            timestamp="2026-02-10T12:00:00+00:00",
            drift=DriftSnapshot(
                timestamp="2026-02-10T12:00:00+00:00",
                test_id="drift-1",
                test_name="API contract",
                similarity_score=0.95,
                passed=True,
                drift_detected=False,
            ),
        )
        _append_event(project, event, "drift")

        queries = AnalyticsQueries(project)
        summary = queries.get_drift_summary(days=30)
        assert len(summary) == 1
        assert summary[0]["test_name"] == "API contract"
        assert summary[0]["test_id"] == "drift-1"
        assert len(summary[0]["results"]) == 1
        assert summary[0]["results"][0]["similarity"] == 0.95


class TestGetLlmUsageSummary:
    """Tests for get_llm_usage_summary."""

    def test_empty_history(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        result = queries.get_llm_usage_summary(days=30)
        assert result["total_tokens"] == 0
        assert result["total_cost_usd"] == 0.0

    def test_aggregates_usage(self, project: Path) -> None:
        event = AnalyticsEvent(
            event_type=EventType.LLM_REQUEST,
            timestamp="2026-02-10T12:00:00+00:00",
            llm_usage=LLMUsage(
                provider="openai",
                model="gpt-4o",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.05,
            ),
        )
        _append_event(project, event, "llm_usage")

        queries = AnalyticsQueries(project)
        summary = queries.get_llm_usage_summary(days=30)
        assert summary["total_tokens"] == 150
        assert summary["total_cost_usd"] == pytest.approx(0.05)
        assert "gpt-4o" in summary["by_model"]
        assert summary["by_model"]["gpt-4o"]["requests"] == 1
        assert "openai" in summary["by_provider"]
        assert "2026-02-10" in summary["by_day"]


class TestGetMemoryInsights:
    """Tests for get_memory_insights."""

    def test_returns_structure(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        result = queries.get_memory_insights()
        assert "conventions" in result
        assert "known_patterns" in result
        assert "failed_patterns" in result
        assert "stats" in result


class TestGetActivityTimeline:
    """Tests for get_activity_timeline."""

    def test_empty_history(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        result = queries.get_activity_timeline(limit=10)
        assert result == []

    def test_returns_recent_events(self, project: Path) -> None:
        event = AnalyticsEvent(
            event_type=EventType.PR_CREATED,
            timestamp="2026-02-10T12:00:00+00:00",
            pr_url="https://github.com/example/repo/pull/1",
        )
        history = AnalyticsHistory(project)
        history.append_event(event)

        queries = AnalyticsQueries(project)
        timeline = queries.get_activity_timeline(limit=10)
        assert len(timeline) >= 1
        assert timeline[0]["type"] == "pr_created"
        assert "PR created" in timeline[0]["description"]


class TestFormatEventDescription:
    """Tests for _format_event_description."""

    def test_llm_request(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        event = AnalyticsEvent(
            event_type=EventType.LLM_REQUEST,
            llm_usage=LLMUsage(
                provider="openai",
                model="gpt-4o",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )
        desc = queries._format_event_description(event)
        assert "openai" in desc
        assert "gpt-4o" in desc
        assert "15" in desc

    def test_coverage_run(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        event = AnalyticsEvent(
            event_type=EventType.COVERAGE_RUN,
            coverage=CoverageSnapshot(
                timestamp="2026-02-10T12:00:00+00:00",
                overall_line_coverage=0.85,
                overall_branch_coverage=0.70,
                overall_function_coverage=0.90,
            ),
        )
        desc = queries._format_event_description(event)
        assert "Coverage" in desc
        assert "85.0%" in desc

    def test_bug_discovered(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        event = AnalyticsEvent(
            event_type=EventType.BUG_DISCOVERED,
            bug=BugSnapshot(
                timestamp="2026-02-10T12:00:00+00:00",
                bug_type="logic_error",
                severity="high",
                status="discovered",
                file_path="src/foo.py",
                title="Null ref",
            ),
        )
        desc = queries._format_event_description(event)
        assert "Bug discovered" in desc
        assert "Null ref" in desc

    def test_bug_fixed(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        event = AnalyticsEvent(
            event_type=EventType.BUG_FIXED,
            bug=BugSnapshot(
                timestamp="2026-02-10T12:00:00+00:00",
                bug_type="logic_error",
                severity="high",
                status="fixed",
                file_path="src/foo.py",
                title="Fixed bug",
            ),
        )
        desc = queries._format_event_description(event)
        assert "Bug fixed" in desc

    def test_drift_test(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        event = AnalyticsEvent(
            event_type=EventType.DRIFT_TEST,
            drift=DriftSnapshot(
                timestamp="2026-02-10T12:00:00+00:00",
                test_id="d1",
                test_name="API contract",
                similarity_score=0.88,
                passed=True,
                drift_detected=False,
            ),
        )
        desc = queries._format_event_description(event)
        assert "Drift test" in desc
        assert "API contract" in desc

    def test_issue_created(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        event = AnalyticsEvent(
            event_type=EventType.ISSUE_CREATED,
            issue_url="https://github.com/example/repo/issues/1",
        )
        desc = queries._format_event_description(event)
        assert "Issue created" in desc

    def test_fallback_event_type(self, project: Path) -> None:
        queries = AnalyticsQueries(project)
        event = AnalyticsEvent(event_type=EventType.TEST_GENERATION)
        desc = queries._format_event_description(event)
        assert desc == "test_generation"
