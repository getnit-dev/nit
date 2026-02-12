"""Tests for ScheduleWatcher agent (task 4.15.3)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.agents.base import TaskInput, TaskStatus
from nit.agents.watchers.schedule import (
    ScheduledRunResult,
    ScheduleWatcher,
    SubprocessResult,
)


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a temporary project root."""
    return tmp_path


@pytest.fixture
def mock_subprocess_runner() -> MagicMock:
    """Create a mock subprocess runner."""
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=SubprocessResult(
            exit_code=0,
            stdout="All tests passed\n",
            stderr="",
            combined_output="All tests passed\n",
            duration=1.5,
        )
    )
    return runner


@pytest.mark.asyncio
async def test_schedule_watcher_initialization(project_root: Path) -> None:
    """Test ScheduleWatcher initialization."""
    watcher = ScheduleWatcher(project_root, test_command="pytest")

    assert watcher.name == "schedule_watcher"
    assert watcher.description == "Executes full test suite on a cron schedule"
    assert watcher._test_command == "pytest"


@pytest.mark.asyncio
async def test_schedule_watcher_auto_detect_pytest(project_root: Path) -> None:
    """Test auto-detection of pytest command."""
    (project_root / "pyproject.toml").write_text("[tool.pytest]\n")

    watcher = ScheduleWatcher(project_root)
    assert watcher._test_command == "pytest"


@pytest.mark.asyncio
async def test_schedule_watcher_auto_detect_npm(project_root: Path) -> None:
    """Test auto-detection of npm test command."""
    (project_root / "package.json").write_text('{"name": "test-project"}')

    watcher = ScheduleWatcher(project_root)
    assert watcher._test_command == "npm test"


@pytest.mark.asyncio
async def test_schedule_watcher_auto_detect_cargo(project_root: Path) -> None:
    """Test auto-detection of cargo test command."""
    (project_root / "Cargo.toml").write_text('[package]\nname = "test"\n')

    watcher = ScheduleWatcher(project_root)
    assert watcher._test_command == "cargo test"


@pytest.mark.asyncio
async def test_schedule_watcher_auto_detect_go(project_root: Path) -> None:
    """Test auto-detection of go test command."""
    (project_root / "go.mod").write_text("module example.com/test\n")

    watcher = ScheduleWatcher(project_root)
    assert watcher._test_command == "go test ./..."


@pytest.mark.asyncio
async def test_schedule_watcher_auto_detect_maven(project_root: Path) -> None:
    """Test auto-detection of maven test command."""
    (project_root / "pom.xml").write_text("<project></project>")

    watcher = ScheduleWatcher(project_root)
    assert watcher._test_command == "mvn test"


@pytest.mark.asyncio
async def test_schedule_watcher_auto_detect_gradle(project_root: Path) -> None:
    """Test auto-detection of gradle test command."""
    (project_root / "build.gradle").write_text("")

    watcher = ScheduleWatcher(project_root)
    assert watcher._test_command == "./gradlew test"


@pytest.mark.asyncio
async def test_run_once_success(project_root: Path, mock_subprocess_runner: MagicMock) -> None:
    """Test running a single successful test run."""
    watcher = ScheduleWatcher(project_root, test_command="pytest")
    watcher._runner = mock_subprocess_runner

    result = await watcher.run_once()

    assert isinstance(result, ScheduledRunResult)
    assert result.success is True
    assert result.exit_code == 0
    assert "All tests passed" in result.output
    assert result.duration_seconds > 0
    assert result.error is None

    # Verify command was called
    mock_subprocess_runner.run.assert_called_once()


@pytest.mark.asyncio
async def test_run_once_failure(project_root: Path) -> None:
    """Test running a single failed test run."""
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=SubprocessResult(
            exit_code=1,
            stdout="",
            stderr="Tests failed\n",
            combined_output="Tests failed\n",
            duration=1.0,
        )
    )

    watcher = ScheduleWatcher(project_root, test_command="pytest")
    watcher._runner = runner

    result = await watcher.run_once()

    assert result.success is False
    assert result.exit_code == 1
    assert "Tests failed" in result.output


@pytest.mark.asyncio
async def test_run_once_exception(project_root: Path) -> None:
    """Test handling exceptions during test run."""
    runner = MagicMock()
    runner.run = AsyncMock(side_effect=RuntimeError("Command failed"))

    watcher = ScheduleWatcher(project_root, test_command="pytest")
    watcher._runner = runner

    result = await watcher.run_once()

    assert result.success is False
    assert result.exit_code == -1
    assert result.error == "Command failed"


@pytest.mark.asyncio
async def test_run_on_interval(project_root: Path, mock_subprocess_runner: MagicMock) -> None:
    """Test running tests on interval with max_runs."""
    watcher = ScheduleWatcher(project_root, test_command="pytest")
    watcher._runner = mock_subprocess_runner

    # Run 3 times with very short interval
    task = TaskInput(
        task_type="schedule",
        target=str(project_root),
        context={"interval": 0.1, "max_runs": 3},
    )

    output = await watcher.run(task)

    assert output.status == TaskStatus.COMPLETED
    assert output.result["report"]["total_runs"] == 3
    assert output.result["report"]["successful_runs"] == 3
    assert output.result["report"]["failed_runs"] == 0
    assert len(output.result["runs"]) == 3


@pytest.mark.asyncio
async def test_run_task_default_interval(
    project_root: Path, mock_subprocess_runner: MagicMock
) -> None:
    """Test running task with default interval."""
    watcher = ScheduleWatcher(project_root, test_command="pytest")
    watcher._runner = mock_subprocess_runner

    task = TaskInput(
        task_type="schedule",
        target=str(project_root),
        context={"max_runs": 1},  # Just one run to avoid long wait
    )

    output = await watcher.run(task)

    assert output.status == TaskStatus.COMPLETED
    assert output.result["report"]["total_runs"] == 1


@pytest.mark.asyncio
async def test_run_task_with_cron_schedule(
    project_root: Path, mock_subprocess_runner: MagicMock
) -> None:
    """Test running task with cron schedule (not yet implemented, uses interval)."""
    watcher = ScheduleWatcher(project_root, test_command="pytest")
    watcher._runner = mock_subprocess_runner

    task = TaskInput(
        task_type="schedule",
        target=str(project_root),
        context={"schedule": "0 2 * * *", "interval": 0.1, "max_runs": 1},
    )

    output = await watcher.run(task)

    # Currently falls back to interval mode
    assert output.status == TaskStatus.COMPLETED
    assert output.result["report"]["total_runs"] == 1


@pytest.mark.asyncio
async def test_get_run_history(project_root: Path, mock_subprocess_runner: MagicMock) -> None:
    """Test getting run history."""
    watcher = ScheduleWatcher(project_root, test_command="pytest")
    watcher._runner = mock_subprocess_runner

    # Run twice
    await watcher.run_once()
    await watcher.run_once()

    history = watcher.get_run_history()

    assert len(history) == 2
    assert all(isinstance(r, ScheduledRunResult) for r in history)
    assert all(r.success for r in history)


@pytest.mark.asyncio
async def test_run_history_persists_across_runs(
    project_root: Path, mock_subprocess_runner: MagicMock
) -> None:
    """Test that run history accumulates across multiple runs."""
    watcher = ScheduleWatcher(project_root, test_command="pytest")
    watcher._runner = mock_subprocess_runner

    # First set of runs
    task1 = TaskInput(
        task_type="schedule",
        target=str(project_root),
        context={"interval": 0.1, "max_runs": 2},
    )
    await watcher.run(task1)

    # Second set of runs
    task2 = TaskInput(
        task_type="schedule",
        target=str(project_root),
        context={"interval": 0.1, "max_runs": 2},
    )
    await watcher.run(task2)

    history = watcher.get_run_history()
    assert len(history) == 4


@pytest.mark.asyncio
async def test_timeout_configuration(project_root: Path) -> None:
    """Test custom timeout configuration."""
    watcher = ScheduleWatcher(project_root, test_command="pytest", timeout=300.0)

    assert watcher._timeout == 300.0


@pytest.mark.asyncio
async def test_run_task_failure_scenario(project_root: Path) -> None:
    """Test task execution when runs fail."""
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=SubprocessResult(
            exit_code=1,
            stdout="",
            stderr="Error",
            combined_output="Error",
            duration=1.0,
        )
    )

    watcher = ScheduleWatcher(project_root, test_command="pytest")
    watcher._runner = runner

    task = TaskInput(
        task_type="schedule",
        target=str(project_root),
        context={"interval": 0.1, "max_runs": 2},
    )

    output = await watcher.run(task)

    assert output.status == TaskStatus.COMPLETED
    assert output.result["report"]["total_runs"] == 2
    assert output.result["report"]["successful_runs"] == 0
    assert output.result["report"]["failed_runs"] == 2


@pytest.mark.asyncio
async def test_scheduled_run_result_structure(
    project_root: Path, mock_subprocess_runner: MagicMock
) -> None:
    """Test the structure of ScheduledRunResult."""
    watcher = ScheduleWatcher(project_root, test_command="pytest")
    watcher._runner = mock_subprocess_runner

    result = await watcher.run_once()

    # Verify all required fields are present
    assert hasattr(result, "run_id")
    assert hasattr(result, "scheduled_time")
    assert hasattr(result, "start_time")
    assert hasattr(result, "end_time")
    assert hasattr(result, "success")
    assert hasattr(result, "exit_code")
    assert hasattr(result, "output")
    assert hasattr(result, "duration_seconds")
    assert hasattr(result, "error")

    # Verify run_id format
    assert result.run_id.startswith("run-")

    # Verify timestamps are ISO format
    datetime.fromisoformat(result.scheduled_time)
    datetime.fromisoformat(result.start_time)
    datetime.fromisoformat(result.end_time)
