"""Tests for dashboard reporter."""

from collections.abc import Generator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nit.agents.reporters.dashboard import DashboardReporter
from nit.memory.analytics_collector import AnalyticsCollector, reset_analytics_collector
from nit.models.coverage import CoverageReport


@pytest.fixture(autouse=True)
def reset_collector() -> Generator[None]:
    """Reset collector singleton after each test."""
    yield
    reset_analytics_collector()


def test_dashboard_reporter_init() -> None:
    """Test dashboard reporter initialization."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        reporter = DashboardReporter(project_root, days=30)

        assert reporter is not None
        assert reporter._days == 30


def test_generate_html_empty_data() -> None:
    """Test generating HTML with no data."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        reporter = DashboardReporter(project_root)

        dashboard_path = reporter.generate_html()

        assert dashboard_path.exists()
        assert dashboard_path.name == "index.html"
        content = dashboard_path.read_text()
        assert "nit Analytics Dashboard" in content
        assert "No coverage data available" in content


def test_generate_html_with_data() -> None:
    """Test generating HTML with some data."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        # Add some test data
        collector = AnalyticsCollector(project_root)

        # Add LLM usage
        collector.record_llm_usage(
            provider="openai",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.01,
        )

        # Add test execution
        collector.record_test_execution(
            total=100, passed=95, failed=5, skipped=0, duration_ms=5000.0
        )

        # Add coverage
        coverage = CoverageReport(
            packages={},
            overall_line_coverage=0.8,
            overall_branch_coverage=0.7,
            overall_function_coverage=0.9,
        )
        collector.record_coverage(coverage)

        # Generate dashboard
        reporter = DashboardReporter(project_root)
        dashboard_path = reporter.generate_html()

        assert dashboard_path.exists()
        content = dashboard_path.read_text()
        assert "nit Analytics Dashboard" in content
        assert "80.0%" in content  # Line coverage
        assert "100" in content  # Total tests


def test_dashboard_path() -> None:
    """Test dashboard is created in correct location."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        reporter = DashboardReporter(project_root)

        dashboard_path = reporter.generate_html()

        expected_path = project_root / ".nit" / "dashboard" / "index.html"
        assert dashboard_path == expected_path
        assert expected_path.exists()
