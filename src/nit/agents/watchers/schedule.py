"""ScheduleWatcher agent for executing tests on cron schedule (task 4.15.1).

Executes full test suite on a cron schedule and reports results.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.utils.subprocess_runner import run_subprocess

logger = logging.getLogger(__name__)


@dataclass
class SubprocessResult:
    """Result of subprocess execution (schedule watcher specific)."""

    exit_code: int
    """Exit code from the subprocess."""

    stdout: str
    """Standard output."""

    stderr: str
    """Standard error."""

    combined_output: str
    """Combined stdout and stderr."""

    duration: float
    """Execution duration in seconds."""


class SubprocessRunner:
    """Simple wrapper for run_subprocess to facilitate mocking in tests."""

    async def run(self, command: str, *, cwd: str, timeout: float) -> SubprocessResult:
        """Run a subprocess command.

        Args:
            command: Shell command to execute.
            cwd: Working directory.
            timeout: Timeout in seconds.

        Returns:
            SubprocessResult with execution details.
        """
        # Parse command string into list (simple split by spaces)
        # Note: This is a simple implementation. For complex commands with quotes,
        # a more sophisticated parser would be needed.
        cmd_parts = command.split()

        result = await run_subprocess(
            cmd_parts,
            cwd=Path(cwd),
            timeout=timeout,
        )

        # Convert to match expected interface
        return SubprocessResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            combined_output=result.stdout + result.stderr,
            duration=result.duration_ms / 1000.0,  # Convert ms to seconds
        )


@dataclass
class ScheduledRunResult:
    """Result of a scheduled test run."""

    run_id: str
    """Unique identifier for this run."""

    scheduled_time: str
    """ISO timestamp when the run was scheduled."""

    start_time: str
    """ISO timestamp when the run started."""

    end_time: str
    """ISO timestamp when the run completed."""

    success: bool
    """Whether the test suite passed."""

    exit_code: int
    """Exit code from the test command."""

    output: str
    """Combined stdout/stderr from the test run."""

    duration_seconds: float
    """Total execution time in seconds."""

    error: str | None = None
    """Error message if the run failed."""


@dataclass
class ScheduleReport:
    """Report of scheduled test runs."""

    total_runs: int
    successful_runs: int
    failed_runs: int
    runs: list[ScheduledRunResult] = field(default_factory=list)


class ScheduleWatcher(BaseAgent):
    """Agent for executing full test suite on cron schedule (task 4.15.1).

    Runs tests periodically based on a cron expression or interval.
    Example usage: `nit watch --schedule "0 2 * * *"` (daily at 2am)
    """

    def __init__(
        self,
        project_root: Path,
        test_command: str | None = None,
        *,
        timeout: float = 600.0,
    ) -> None:
        """Initialize the schedule watcher.

        Args:
            project_root: Root directory of the project.
            test_command: Command to run tests (e.g., "pytest", "npm test").
                If None, attempts to auto-detect from project structure.
            timeout: Maximum seconds to wait for test execution (default: 10 minutes).
        """
        self._project_root = project_root
        self._test_command = test_command or self._detect_test_command()
        self._timeout = timeout
        self._runner = SubprocessRunner()
        self._run_history: list[ScheduledRunResult] = []

    @property
    def name(self) -> str:
        """Agent identifier."""
        return "schedule_watcher"

    @property
    def description(self) -> str:
        """Human-readable description."""
        return "Executes full test suite on a cron schedule"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute scheduled test task.

        Task context can include:
        - schedule: cron expression (e.g., "0 2 * * *") or None for one-time run
        - interval: seconds between runs (alternative to cron, default: 3600)
        - max_runs: maximum number of runs before stopping (default: unlimited)

        Args:
            task: The scheduled test task.

        Returns:
            Task output with run results.
        """
        schedule = task.context.get("schedule")
        interval = task.context.get("interval", 3600)
        max_runs = task.context.get("max_runs")

        try:
            if schedule:
                # Cron-based scheduling (not implemented yet, just document)
                logger.warning("Cron scheduling not yet implemented, using interval mode")
                report = await self._run_on_interval(interval, max_runs)
            else:
                # Interval-based scheduling
                report = await self._run_on_interval(interval, max_runs)

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "report": {
                        "total_runs": report.total_runs,
                        "successful_runs": report.successful_runs,
                        "failed_runs": report.failed_runs,
                    },
                    "runs": [
                        {
                            "run_id": r.run_id,
                            "scheduled_time": r.scheduled_time,
                            "start_time": r.start_time,
                            "end_time": r.end_time,
                            "success": r.success,
                            "exit_code": r.exit_code,
                            "duration_seconds": r.duration_seconds,
                            "error": r.error,
                        }
                        for r in report.runs
                    ],
                },
            )

        except Exception as e:
            logger.error("Scheduled test execution failed: %s", e)
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[str(e)],
            )

    async def run_once(self) -> ScheduledRunResult:
        """Execute a single scheduled test run.

        Returns:
            Result of the test run.
        """
        run_id = f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        scheduled_time = datetime.now(UTC).isoformat()
        start_time = datetime.now(UTC).isoformat()

        logger.info("Starting scheduled test run: %s", run_id)
        logger.info("Executing command: %s", self._test_command)

        start = time.time()

        try:
            result = await self._runner.run(
                command=self._test_command,
                cwd=str(self._project_root),
                timeout=self._timeout,
            )

            end_time = datetime.now(UTC).isoformat()

            run_result = ScheduledRunResult(
                run_id=run_id,
                scheduled_time=scheduled_time,
                start_time=start_time,
                end_time=end_time,
                success=result.exit_code == 0,
                exit_code=result.exit_code,
                output=result.combined_output,
                duration_seconds=result.duration,
            )

            self._run_history.append(run_result)
            logger.info("Test run completed: %s (success=%s)", run_id, run_result.success)

            return run_result

        except Exception as e:
            duration = time.time() - start
            end_time = datetime.now(UTC).isoformat()

            logger.error("Test run failed: %s - %s", run_id, e)

            run_result = ScheduledRunResult(
                run_id=run_id,
                scheduled_time=scheduled_time,
                start_time=start_time,
                end_time=end_time,
                success=False,
                exit_code=-1,
                output="",
                duration_seconds=duration,
                error=str(e),
            )

            self._run_history.append(run_result)
            return run_result

    async def _run_on_interval(self, interval: int, max_runs: int | None = None) -> ScheduleReport:
        """Run tests repeatedly on a fixed interval.

        Args:
            interval: Seconds between runs.
            max_runs: Maximum number of runs (None for unlimited).

        Returns:
            Report of all runs.
        """
        run_count = 0
        runs = []

        while max_runs is None or run_count < max_runs:
            result = await self.run_once()
            runs.append(result)
            run_count += 1

            if max_runs is None or run_count < max_runs:
                logger.info("Waiting %d seconds until next run...", interval)
                await asyncio.sleep(interval)

        successful = sum(1 for r in runs if r.success)
        failed = sum(1 for r in runs if not r.success)

        return ScheduleReport(
            total_runs=len(runs),
            successful_runs=successful,
            failed_runs=failed,
            runs=runs,
        )

    def _detect_test_command(self) -> str:
        """Auto-detect test command from project structure.

        Returns:
            Test command to execute.
        """
        # Check for common test configurations
        if (self._project_root / "package.json").exists():
            # Node.js project - check for test script
            return "npm test"

        if (self._project_root / "pyproject.toml").exists() or (
            self._project_root / "pytest.ini"
        ).exists():
            # Python pytest project
            return "pytest"

        if (self._project_root / "Cargo.toml").exists():
            # Rust project
            return "cargo test"

        if (self._project_root / "go.mod").exists():
            # Go project
            return "go test ./..."

        if (self._project_root / "pom.xml").exists():
            # Maven project
            return "mvn test"

        if (self._project_root / "build.gradle").exists() or (
            self._project_root / "build.gradle.kts"
        ).exists():
            # Gradle project
            return "./gradlew test"

        # Default fallback
        logger.warning("Could not auto-detect test command, using generic 'make test'")
        return "make test"

    def get_run_history(self) -> list[ScheduledRunResult]:
        """Get history of all scheduled runs.

        Returns:
            List of all run results.
        """
        return self._run_history.copy()
