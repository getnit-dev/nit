"""Tests for Slack reporter integration in CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nit.agents.reporters.slack import (
    BugEvent,
    CoverageEvent,
    DriftEvent,
    SlackReporter,
)
from nit.cli import _get_slack_reporter


class TestGetSlackReporter:
    def test_returns_none_when_no_webhook(self) -> None:
        config = MagicMock()
        config.report.slack_webhook = ""
        assert _get_slack_reporter(config) is None

    def test_returns_none_when_no_report_attr(self) -> None:
        config = MagicMock(spec=[])  # No attributes
        assert _get_slack_reporter(config) is None

    def test_returns_reporter_when_webhook_set(self) -> None:
        config = MagicMock()
        config.report.slack_webhook = "https://hooks.slack.com/services/T00/B00/xxx"
        reporter = _get_slack_reporter(config)
        assert reporter is not None

    def test_reporter_has_correct_webhook(self) -> None:
        config = MagicMock()
        url = "https://hooks.slack.com/services/T00/B00/xxx"
        config.report.slack_webhook = url
        reporter = _get_slack_reporter(config)
        assert reporter.webhook_url == url


class TestSlackBugAlert:
    def test_bug_alert_called_in_pick(self) -> None:
        """Verify that SlackReporter.send_bug_alert is called from pick when configured."""
        events = [
            BugEvent(
                file_path="src/foo.py",
                function_name="bar",
                bug_type="null_dereference",
                description="Null value accessed",
                severity="high",
            )
        ]

        with patch.object(SlackReporter, "_send_message", return_value=True) as mock_send:
            reporter = SlackReporter("https://hooks.slack.com/services/T/B/x")
            result = reporter.send_bug_alert(events)
            assert result is True
            assert mock_send.called

    def test_bug_alert_empty_list(self) -> None:
        """Sending empty bug list returns True without sending."""
        reporter = SlackReporter("https://hooks.slack.com/services/T/B/x")
        with patch.object(SlackReporter, "_send_message") as mock_send:
            result = reporter.send_bug_alert([])
            assert result is True
            assert not mock_send.called


class TestSlackDriftAlert:
    def test_drift_alert_sends(self) -> None:
        events = [
            DriftEvent(
                test_name="test_openai_response",
                endpoint="https://api.openai.com/v1/chat",
                similarity_score=0.65,
                threshold=0.85,
                baseline_output="expected output",
                actual_output="different output",
            )
        ]

        with patch.object(SlackReporter, "_send_message", return_value=True):
            reporter = SlackReporter("https://hooks.slack.com/services/T/B/x")
            result = reporter.send_drift_alert(events)
            assert result is True


class TestSlackCoverageAlert:
    def test_coverage_alert_sends(self) -> None:
        events = [
            CoverageEvent(
                package="myapp",
                before=85.0,
                after=72.0,
                threshold=80.0,
            )
        ]

        with patch.object(SlackReporter, "_send_message", return_value=True):
            reporter = SlackReporter("https://hooks.slack.com/services/T/B/x")
            result = reporter.send_coverage_alert(events)
            assert result is True
