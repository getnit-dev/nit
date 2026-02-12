"""Tests for CoverageWatcher agent (task 4.15.3)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.adapters.coverage.base import CoverageReport, FileCoverage, LineCoverage
from nit.agents.base import TaskInput, TaskStatus
from nit.agents.watchers.coverage import CoverageAlert, CoverageSnapshot, CoverageWatcher


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a temporary project root with .nit directory."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".nit").mkdir()
    (project / ".nit" / "memory").mkdir()
    return project


@pytest.fixture
def mock_coverage_report() -> CoverageReport:
    """Create a mock coverage report."""
    return CoverageReport(
        files={
            "src/main.py": FileCoverage(
                file_path="src/main.py",
                lines=[
                    LineCoverage(line_number=1, execution_count=1),
                    LineCoverage(line_number=2, execution_count=1),
                    LineCoverage(line_number=3, execution_count=0),
                ],
            ),
            "src/utils.py": FileCoverage(
                file_path="src/utils.py",
                lines=[
                    LineCoverage(line_number=1, execution_count=1),
                    LineCoverage(line_number=2, execution_count=1),
                ],
            ),
        }
    )


@pytest.fixture
def mock_coverage_adapter(mock_coverage_report: CoverageReport) -> MagicMock:
    """Create a mock coverage adapter."""
    adapter = MagicMock()
    adapter.name = "mock_coverage"
    adapter.detect.return_value = True
    adapter.run_coverage = AsyncMock(return_value=mock_coverage_report)
    return adapter


@pytest.mark.asyncio
async def test_coverage_watcher_initialization(project_root: Path) -> None:
    """Test CoverageWatcher initialization."""
    watcher = CoverageWatcher(project_root)

    assert watcher.name == "coverage_watcher"
    assert (
        watcher.description
        == "Tracks coverage trends over time and alerts on drops below threshold"
    )
    assert watcher._coverage_threshold == 80.0
    assert watcher._drop_threshold == 5.0


@pytest.mark.asyncio
async def test_coverage_watcher_custom_thresholds(project_root: Path) -> None:
    """Test CoverageWatcher with custom thresholds."""
    watcher = CoverageWatcher(
        project_root,
        coverage_threshold=90.0,
        drop_threshold=10.0,
    )

    assert watcher._coverage_threshold == 90.0
    assert watcher._drop_threshold == 10.0


@pytest.mark.asyncio
async def test_collect_and_analyze_first_run(
    project_root: Path, mock_coverage_adapter: MagicMock
) -> None:
    """Test collecting coverage for the first time."""
    watcher = CoverageWatcher(project_root, coverage_threshold=50.0)
    watcher._adapters = [mock_coverage_adapter]

    report = await watcher.collect_and_analyze()

    assert isinstance(report.current_snapshot, CoverageSnapshot)
    assert report.current_snapshot.overall_line_coverage > 0
    assert report.previous_snapshot is None
    assert report.trend == "stable"
    assert len(report.alerts) == 0  # First run, no previous data
    assert report.history_count == 1


@pytest.mark.asyncio
async def test_collect_and_analyze_with_metadata(
    project_root: Path, mock_coverage_adapter: MagicMock
) -> None:
    """Test collecting coverage with metadata."""
    watcher = CoverageWatcher(project_root)
    watcher._adapters = [mock_coverage_adapter]

    metadata = {"git_commit": "abc123", "ci_build": "42"}
    report = await watcher.collect_and_analyze(metadata)

    assert report.current_snapshot.metadata == metadata


@pytest.mark.asyncio
async def test_coverage_trend_increasing(
    project_root: Path, mock_coverage_adapter: MagicMock
) -> None:
    """Test detecting increasing coverage trend."""
    watcher = CoverageWatcher(project_root, coverage_threshold=50.0)
    watcher._adapters = [mock_coverage_adapter]

    # First run - lower coverage
    low_report = CoverageReport(
        files={
            "src/main.py": FileCoverage(
                file_path="src/main.py",
                lines=[
                    LineCoverage(line_number=1, execution_count=1),
                    LineCoverage(line_number=2, execution_count=0),
                    LineCoverage(line_number=3, execution_count=0),
                ],
            ),
        }
    )
    mock_coverage_adapter.run_coverage = AsyncMock(return_value=low_report)
    await watcher.collect_and_analyze()

    # Second run - higher coverage
    high_report = CoverageReport(
        files={
            "src/main.py": FileCoverage(
                file_path="src/main.py",
                lines=[
                    LineCoverage(line_number=1, execution_count=1),
                    LineCoverage(line_number=2, execution_count=1),
                    LineCoverage(line_number=3, execution_count=1),
                ],
            ),
        }
    )
    mock_coverage_adapter.run_coverage = AsyncMock(return_value=high_report)
    report = await watcher.collect_and_analyze()

    assert report.trend == "increasing"


@pytest.mark.asyncio
async def test_coverage_trend_decreasing(
    project_root: Path, mock_coverage_adapter: MagicMock
) -> None:
    """Test detecting decreasing coverage trend."""
    watcher = CoverageWatcher(project_root, coverage_threshold=50.0)
    watcher._adapters = [mock_coverage_adapter]

    # First run - high coverage
    high_report = CoverageReport(
        files={
            "src/main.py": FileCoverage(
                file_path="src/main.py",
                lines=[
                    LineCoverage(line_number=1, execution_count=1),
                    LineCoverage(line_number=2, execution_count=1),
                    LineCoverage(line_number=3, execution_count=1),
                ],
            ),
        }
    )
    mock_coverage_adapter.run_coverage = AsyncMock(return_value=high_report)
    await watcher.collect_and_analyze()

    # Second run - low coverage
    low_report = CoverageReport(
        files={
            "src/main.py": FileCoverage(
                file_path="src/main.py",
                lines=[
                    LineCoverage(line_number=1, execution_count=1),
                    LineCoverage(line_number=2, execution_count=0),
                    LineCoverage(line_number=3, execution_count=0),
                ],
            ),
        }
    )
    mock_coverage_adapter.run_coverage = AsyncMock(return_value=low_report)
    report = await watcher.collect_and_analyze()

    assert report.trend == "decreasing"


@pytest.mark.asyncio
async def test_alert_below_threshold(project_root: Path, mock_coverage_adapter: MagicMock) -> None:
    """Test alert when coverage is below threshold."""
    watcher = CoverageWatcher(project_root, coverage_threshold=90.0)
    watcher._adapters = [mock_coverage_adapter]

    report = await watcher.collect_and_analyze()

    # Should have alert since coverage is below 90%
    assert len(report.alerts) > 0
    assert any("below threshold" in alert.message for alert in report.alerts)


@pytest.mark.asyncio
async def test_alert_on_coverage_drop(project_root: Path, mock_coverage_adapter: MagicMock) -> None:
    """Test alert when coverage drops significantly."""
    watcher = CoverageWatcher(project_root, coverage_threshold=50.0, drop_threshold=10.0)
    watcher._adapters = [mock_coverage_adapter]

    # First run - high coverage
    high_report = CoverageReport(
        files={
            "src/main.py": FileCoverage(
                file_path="src/main.py",
                lines=[LineCoverage(line_number=i, execution_count=1) for i in range(1, 101)],
            ),
        }
    )
    mock_coverage_adapter.run_coverage = AsyncMock(return_value=high_report)
    await watcher.collect_and_analyze()

    # Second run - significant drop
    low_report = CoverageReport(
        files={
            "src/main.py": FileCoverage(
                file_path="src/main.py",
                lines=[
                    LineCoverage(line_number=i, execution_count=1 if i <= 80 else 0)
                    for i in range(1, 101)
                ],
            ),
        }
    )
    mock_coverage_adapter.run_coverage = AsyncMock(return_value=low_report)
    report = await watcher.collect_and_analyze()

    # Should have critical alert for coverage drop
    assert len(report.alerts) > 0
    critical_alerts = [a for a in report.alerts if a.severity == "critical"]
    assert len(critical_alerts) > 0
    assert any("dropped" in alert.message for alert in critical_alerts)


@pytest.mark.asyncio
async def test_get_history(project_root: Path, mock_coverage_adapter: MagicMock) -> None:
    """Test getting coverage history."""
    watcher = CoverageWatcher(project_root)
    watcher._adapters = [mock_coverage_adapter]

    # Collect coverage 3 times
    await watcher.collect_and_analyze()
    await watcher.collect_and_analyze()
    await watcher.collect_and_analyze()

    history = watcher.get_history()

    assert len(history) == 3
    assert all(isinstance(s, CoverageSnapshot) for s in history)


@pytest.mark.asyncio
async def test_get_history_with_limit(project_root: Path, mock_coverage_adapter: MagicMock) -> None:
    """Test getting limited coverage history."""
    watcher = CoverageWatcher(project_root)
    watcher._adapters = [mock_coverage_adapter]

    # Collect coverage 5 times
    for _ in range(5):
        await watcher.collect_and_analyze()

    history = watcher.get_history(limit=2)

    assert len(history) == 2


@pytest.mark.asyncio
async def test_history_persistence(project_root: Path, mock_coverage_adapter: MagicMock) -> None:
    """Test that history is saved and loaded from disk."""
    # First watcher instance
    watcher1 = CoverageWatcher(project_root)
    watcher1._adapters = [mock_coverage_adapter]
    await watcher1.collect_and_analyze()

    # Second watcher instance (simulates restart)
    watcher2 = CoverageWatcher(project_root)
    watcher2._adapters = [mock_coverage_adapter]
    history = watcher2.get_history()

    assert len(history) == 1
    assert history[0].overall_line_coverage > 0


@pytest.mark.asyncio
async def test_history_limit_enforcement(
    project_root: Path, mock_coverage_adapter: MagicMock
) -> None:
    """Test that history is limited to configured size."""
    watcher = CoverageWatcher(project_root, history_limit=5)
    watcher._adapters = [mock_coverage_adapter]

    # Collect more than the limit
    for _ in range(10):
        await watcher.collect_and_analyze()

    history = watcher.get_history()

    assert len(history) == 5


@pytest.mark.asyncio
async def test_run_task_collect_mode(project_root: Path, mock_coverage_adapter: MagicMock) -> None:
    """Test running task in collect mode."""
    watcher = CoverageWatcher(project_root, coverage_threshold=50.0)
    watcher._adapters = [mock_coverage_adapter]

    task = TaskInput(
        task_type="coverage_watch",
        target=str(project_root),
        context={"mode": "collect"},
    )

    output = await watcher.run(task)

    assert output.status == TaskStatus.COMPLETED
    assert "current_coverage" in output.result
    assert "trend" in output.result
    assert "alerts" in output.result


@pytest.mark.asyncio
async def test_run_task_report_mode(project_root: Path, mock_coverage_adapter: MagicMock) -> None:
    """Test running task in report mode."""
    watcher = CoverageWatcher(project_root)
    watcher._adapters = [mock_coverage_adapter]

    # Collect first
    await watcher.collect_and_analyze()

    # Then get report
    task = TaskInput(
        task_type="coverage_watch",
        target=str(project_root),
        context={"mode": "report"},
    )

    output = await watcher.run(task)

    assert output.status == TaskStatus.COMPLETED
    assert "current_coverage" in output.result


@pytest.mark.asyncio
async def test_run_task_no_history_report_mode(project_root: Path) -> None:
    """Test running report mode when no history exists."""
    watcher = CoverageWatcher(project_root)

    task = TaskInput(
        task_type="coverage_watch",
        target=str(project_root),
        context={"mode": "report"},
    )

    output = await watcher.run(task)

    assert output.status == TaskStatus.FAILED
    assert "No coverage history available" in output.errors[0]


@pytest.mark.asyncio
async def test_no_adapter_detected(project_root: Path) -> None:
    """Test when no coverage adapter is detected."""
    watcher = CoverageWatcher(project_root)
    # Don't add any adapters that will detect successfully

    task = TaskInput(
        task_type="coverage_watch",
        target=str(project_root),
        context={"mode": "collect"},
    )

    output = await watcher.run(task)

    assert output.status == TaskStatus.FAILED
    assert "No coverage adapter detected" in output.errors[0]


@pytest.mark.asyncio
async def test_coverage_snapshot_structure(
    project_root: Path, mock_coverage_adapter: MagicMock
) -> None:
    """Test the structure of CoverageSnapshot."""
    watcher = CoverageWatcher(project_root)
    watcher._adapters = [mock_coverage_adapter]

    report = await watcher.collect_and_analyze()
    snapshot = report.current_snapshot

    # Verify all required fields are present
    assert hasattr(snapshot, "timestamp")
    assert hasattr(snapshot, "overall_line_coverage")
    assert hasattr(snapshot, "overall_function_coverage")
    assert hasattr(snapshot, "overall_branch_coverage")
    assert hasattr(snapshot, "file_count")
    assert hasattr(snapshot, "metadata")

    # Verify timestamp is ISO format
    datetime.fromisoformat(snapshot.timestamp)


@pytest.mark.asyncio
async def test_alert_structure() -> None:
    """Test the structure of CoverageAlert."""
    alert = CoverageAlert(
        severity="critical",
        message="Test message",
        current_coverage=70.0,
        previous_coverage=85.0,
        drop_percentage=15.0,
        threshold=5.0,
    )

    assert alert.severity == "critical"
    assert alert.message == "Test message"
    assert alert.current_coverage == 70.0
    assert alert.previous_coverage == 85.0
    assert alert.drop_percentage == 15.0
    assert alert.threshold == 5.0


@pytest.mark.asyncio
async def test_json_serialization_roundtrip(
    project_root: Path, mock_coverage_adapter: MagicMock
) -> None:
    """Test that coverage history can be serialized and deserialized."""
    watcher = CoverageWatcher(project_root)
    watcher._adapters = [mock_coverage_adapter]

    # Collect coverage
    original_report = await watcher.collect_and_analyze(metadata={"test_key": "test_value"})

    # Load it back
    loaded_history = watcher.get_history()

    assert len(loaded_history) == 1
    loaded_snapshot = loaded_history[0]

    # Verify data matches
    assert (
        loaded_snapshot.overall_line_coverage
        == original_report.current_snapshot.overall_line_coverage
    )
    assert (
        loaded_snapshot.overall_function_coverage
        == original_report.current_snapshot.overall_function_coverage
    )
    assert (
        loaded_snapshot.overall_branch_coverage
        == original_report.current_snapshot.overall_branch_coverage
    )
    assert loaded_snapshot.file_count == original_report.current_snapshot.file_count
    assert loaded_snapshot.metadata == {"test_key": "test_value"}
