"""Tests for the nit watch command."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from nit.cli import _display_coverage_trend, _display_watch_run, cli

if TYPE_CHECKING:
    from pathlib import Path


class TestWatchCommand:
    def test_watch_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["watch", "--help"])
        assert result.exit_code == 0
        assert "--interval" in result.output
        assert "--coverage" in result.output
        assert "--max-runs" in result.output
        assert "--test-command" in result.output
        assert "--timeout" in result.output

    def test_watch_single_run(self, tmp_path: Path) -> None:
        """Test watch with --max-runs 1 completes a single iteration."""
        mock_run_result = MagicMock()
        mock_run_result.success = True
        mock_run_result.duration_seconds = 1.5
        mock_run_result.exit_code = 0
        mock_run_result.error = None

        with patch(
            "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
            new_callable=AsyncMock,
            return_value=mock_run_result,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["watch", "--path", str(tmp_path), "--max-runs", "1"],
            )

            assert result.exit_code == 0
            assert "Tests passed" in result.output

    def test_watch_with_coverage(self, tmp_path: Path) -> None:
        """Test watch with coverage monitoring enabled."""
        mock_run_result = MagicMock()
        mock_run_result.success = True
        mock_run_result.duration_seconds = 2.0
        mock_run_result.exit_code = 0
        mock_run_result.error = None

        mock_snapshot = MagicMock()
        mock_snapshot.overall_line_coverage = 85.0
        mock_snapshot.overall_function_coverage = 90.0

        mock_trend = MagicMock()
        mock_trend.current_snapshot = mock_snapshot
        mock_trend.trend = "stable"
        mock_trend.alerts = []

        with (
            patch(
                "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
                new_callable=AsyncMock,
                return_value=mock_run_result,
            ),
            patch(
                "nit.agents.watchers.coverage.CoverageWatcher.collect_and_analyze",
                new_callable=AsyncMock,
                return_value=mock_trend,
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "watch",
                    "--path",
                    str(tmp_path),
                    "--max-runs",
                    "1",
                    "--coverage",
                ],
            )

            assert result.exit_code == 0
            assert "Coverage" in result.output

    def test_watch_failed_tests(self, tmp_path: Path) -> None:
        """Test watch displays failure information."""
        mock_run_result = MagicMock()
        mock_run_result.success = False
        mock_run_result.duration_seconds = 3.0
        mock_run_result.exit_code = 1
        mock_run_result.error = "Tests failed"

        with patch(
            "nit.agents.watchers.schedule.ScheduleWatcher.run_once",
            new_callable=AsyncMock,
            return_value=mock_run_result,
        ):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["watch", "--path", str(tmp_path), "--max-runs", "1"],
            )

            assert result.exit_code == 0
            assert "Tests failed" in result.output


class TestDisplayWatchRun:
    def test_display_success(self) -> None:
        run_result = MagicMock()
        run_result.success = True
        run_result.duration_seconds = 1.0
        run_result.exit_code = 0
        run_result.error = None

        # Should not raise
        _display_watch_run(run_result)

    def test_display_failure(self) -> None:
        run_result = MagicMock()
        run_result.success = False
        run_result.duration_seconds = 2.0
        run_result.exit_code = 1
        run_result.error = "Something went wrong"

        # Should not raise
        _display_watch_run(run_result)


class TestDisplayCoverageTrend:
    def test_display_trend(self) -> None:
        snapshot = MagicMock()
        snapshot.overall_line_coverage = 80.0
        snapshot.overall_function_coverage = 75.0

        trend_report = MagicMock()
        trend_report.current_snapshot = snapshot
        trend_report.trend = "stable"
        trend_report.alerts = []

        # Should not raise
        _display_coverage_trend(trend_report)
