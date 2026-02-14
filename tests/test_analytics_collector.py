"""Tests for analytics collector."""

from collections.abc import Generator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nit.memory.analytics_collector import AnalyticsCollector, reset_analytics_collector
from nit.models.analytics import (
    BugSnapshot,
    DriftSnapshot,
    LLMUsage,
    TestExecutionSnapshot,
)
from nit.models.coverage import CoverageReport, PackageCoverage


@pytest.fixture(autouse=True)
def reset_collector() -> Generator[None]:
    """Reset collector singleton after each test."""
    yield
    reset_analytics_collector()


def test_collector_init() -> None:
    """Test collector initialization."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        collector = AnalyticsCollector(project_root)

        assert collector is not None


def test_record_llm_usage() -> None:
    """Test recording LLM usage."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        collector = AnalyticsCollector(project_root)

        collector.record_llm_usage(
            LLMUsage(
                provider="openai",
                model="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.01,
                duration_ms=500.0,
            ),
        )

        # Verify event was written
        history_file = project_root / ".nit" / "history" / "llm_usage.jsonl"
        assert history_file.exists()
        content = history_file.read_text()
        assert "openai" in content
        assert "gpt-4" in content


def test_record_coverage() -> None:
    """Test recording coverage."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        collector = AnalyticsCollector(project_root)

        coverage = CoverageReport(
            packages={
                "test_pkg": PackageCoverage(
                    name="test_pkg",
                    line_coverage=0.8,
                    branch_coverage=0.7,
                    function_coverage=0.9,
                )
            },
            overall_line_coverage=0.8,
            overall_branch_coverage=0.7,
            overall_function_coverage=0.9,
        )

        collector.record_coverage(coverage)

        # Verify event was written
        history_file = project_root / ".nit" / "history" / "coverage.jsonl"
        assert history_file.exists()


def test_record_test_execution() -> None:
    """Test recording test execution."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        collector = AnalyticsCollector(project_root)

        collector.record_test_execution(
            TestExecutionSnapshot(
                timestamp="2024-01-01T00:00:00+00:00",
                total_tests=100,
                passed_tests=95,
                failed_tests=5,
                skipped_tests=0,
                total_duration_ms=5000.0,
            ),
        )

        # Verify event was written
        history_file = project_root / ".nit" / "history" / "test_execution.jsonl"
        assert history_file.exists()
        content = history_file.read_text()
        assert "95" in content  # passed tests


def test_record_bug() -> None:
    """Test recording bug discovery."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        collector = AnalyticsCollector(project_root)

        collector.record_bug(
            BugSnapshot(
                timestamp="2024-01-01T00:00:00+00:00",
                bug_type="null_dereference",
                severity="high",
                status="discovered",
                file_path="src/test.py",
                line_number=42,
                title="Null pointer dereference",
            ),
        )

        # Verify event was written
        history_file = project_root / ".nit" / "history" / "bugs.jsonl"
        assert history_file.exists()
        content = history_file.read_text()
        assert "null_dereference" in content
        assert "src/test.py" in content


def test_record_drift_test() -> None:
    """Test recording drift test."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        collector = AnalyticsCollector(project_root)

        collector.record_drift_test(
            DriftSnapshot(
                timestamp="2024-01-01T00:00:00+00:00",
                test_id="test_1",
                test_name="Prompt consistency test",
                similarity_score=0.95,
                passed=True,
                drift_detected=False,
            ),
        )

        # Verify event was written
        history_file = project_root / ".nit" / "history" / "drift.jsonl"
        assert history_file.exists()
        content = history_file.read_text()
        assert "test_1" in content
        assert "0.95" in content


def test_record_pr_created() -> None:
    """Test recording PR creation."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        collector = AnalyticsCollector(project_root)

        collector.record_pr_created(
            pr_url="https://github.com/test/test/pull/1",
            files=["src/test.py", "src/foo.py"],
            metadata={"tests_generated": 5},
        )

        # Verify event was written
        history_file = project_root / ".nit" / "history" / "prs.jsonl"
        assert history_file.exists()
        content = history_file.read_text()
        assert "github.com" in content


def test_record_issue_created() -> None:
    """Test recording issue creation."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        collector = AnalyticsCollector(project_root)

        collector.record_issue_created(
            issue_url="https://github.com/test/test/issues/1",
            bug_type="null_dereference",
            severity="high",
        )

        # Verify event was written
        history_file = project_root / ".nit" / "history" / "issues.jsonl"
        assert history_file.exists()
