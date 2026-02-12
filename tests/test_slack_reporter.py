"""Tests for Slack webhook reporter."""

from __future__ import annotations

import json
from unittest import mock

import httpx
import pytest

from nit.agents.reporters.slack import (
    BugEvent,
    CoverageEvent,
    DriftEvent,
    SlackReporter,
)
from nit.models.coverage import CoverageReport, PackageCoverage


@pytest.fixture
def slack_reporter() -> SlackReporter:
    """Create a SlackReporter instance with test webhook URL."""
    return SlackReporter(webhook_url="https://hooks.slack.com/services/TEST/WEBHOOK/URL")


@pytest.fixture
def sample_bug_events() -> list[BugEvent]:
    """Create sample bug events."""
    return [
        BugEvent(
            file_path="src/auth.py",
            function_name="validate_token",
            bug_type="null dereference",
            description="Token validation does not check for None",
            severity="high",
            github_issue_url="https://github.com/owner/repo/issues/42",
            github_pr_url="https://github.com/owner/repo/pull/43",
        ),
        BugEvent(
            file_path="src/utils.py",
            function_name="parse_data",
            bug_type="uncaught exception",
            description="JSON parsing can raise ValueError",
            severity="medium",
        ),
        BugEvent(
            file_path="src/api.py",
            bug_type="undefined return",
            description="Function does not return value in all paths",
            severity="low",
        ),
    ]


@pytest.fixture
def sample_coverage_events() -> list[CoverageEvent]:
    """Create sample coverage events."""
    return [
        CoverageEvent(package="web", before=85.5, after=78.2, threshold=80.0),
        CoverageEvent(package="api", before=72.0, after=75.5, threshold=75.0),
        CoverageEvent(package="utils", before=90.0, after=88.0, threshold=85.0),
    ]


@pytest.fixture
def sample_drift_events() -> list[DriftEvent]:
    """Create sample drift events."""
    return [
        DriftEvent(
            test_name="test_summary_generation",
            endpoint="openai/gpt-4o",
            similarity_score=0.65,
            threshold=0.85,
            baseline_output="This is a concise summary of the document.",
            actual_output="Here's a brief overview of the content.",
        ),
        DriftEvent(
            test_name="test_translation",
            endpoint="anthropic/claude-sonnet-4-5",
            similarity_score=0.72,
            threshold=0.90,
            baseline_output="Bonjour le monde",
            actual_output="Salut le monde",
        ),
    ]


@pytest.fixture
def sample_coverage_before() -> CoverageReport:
    """Create sample coverage report (before)."""
    return CoverageReport(
        packages={
            "web": PackageCoverage(
                name="web",
                line_coverage=0.65,
                function_coverage=0.70,
                branch_coverage=0.60,
            ),
            "api": PackageCoverage(
                name="api",
                line_coverage=0.80,
                function_coverage=0.85,
                branch_coverage=0.75,
            ),
        },
        overall_line_coverage=0.725,
        overall_function_coverage=0.775,
        overall_branch_coverage=0.675,
    )


@pytest.fixture
def sample_coverage_after() -> CoverageReport:
    """Create sample coverage report (after)."""
    return CoverageReport(
        packages={
            "web": PackageCoverage(
                name="web",
                line_coverage=0.75,
                function_coverage=0.80,
                branch_coverage=0.70,
            ),
            "api": PackageCoverage(
                name="api",
                line_coverage=0.85,
                function_coverage=0.90,
                branch_coverage=0.80,
            ),
        },
        overall_line_coverage=0.80,
        overall_function_coverage=0.85,
        overall_branch_coverage=0.75,
    )


def _mock_httpx_response(status_code: int = 200) -> httpx.Response:
    """Create a mock httpx.Response with the given status code."""
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://hooks.slack.com/services/TEST"),
    )


class TestSlackReporter:
    """Tests for SlackReporter class."""

    def test_init_success(self) -> None:
        """Test reporter initialization with valid webhook URL."""
        reporter = SlackReporter(webhook_url="https://hooks.slack.com/services/TEST")
        assert reporter.webhook_url == "https://hooks.slack.com/services/TEST"

    def test_init_empty_url_raises(self) -> None:
        """Test that empty webhook URL raises ValueError."""
        with pytest.raises(ValueError, match="Slack webhook URL is required"):
            SlackReporter(webhook_url="")

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_send_bug_alert_success(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
        sample_bug_events: list[BugEvent],
    ) -> None:
        """Test sending bug alert successfully."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.return_value = _mock_httpx_response(200)
        mock_client_cls.return_value = mock_client

        result = slack_reporter.send_bug_alert(sample_bug_events)

        assert result is True
        assert mock_client.post.called

        # Verify the request was made correctly
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == slack_reporter.webhook_url

        # Verify payload structure
        payload = json.loads(call_kwargs[1]["content"])
        assert "blocks" in payload
        assert "text" in payload
        assert "Found 3 bug(s)" in payload["text"]

        # Verify blocks contain expected content
        blocks = payload["blocks"]
        assert len(blocks) > 0
        assert blocks[0]["type"] == "header"
        assert "3 Bug" in blocks[0]["text"]["text"]

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_send_bug_alert_empty_list(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
    ) -> None:
        """Test that sending empty bug list returns True without making request."""
        result = slack_reporter.send_bug_alert([])

        assert result is True
        assert not mock_client_cls.called

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_send_bug_alert_http_error(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
        sample_bug_events: list[BugEvent],
    ) -> None:
        """Test handling of HTTP error when sending bug alert."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.side_effect = httpx.HTTPStatusError(
            message="Internal Server Error",
            request=httpx.Request("POST", "https://test.com"),
            response=httpx.Response(500),
        )
        mock_client_cls.return_value = mock_client

        result = slack_reporter.send_bug_alert(sample_bug_events)

        assert result is False

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_send_coverage_alert_success(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
        sample_coverage_events: list[CoverageEvent],
    ) -> None:
        """Test sending coverage alert successfully."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.return_value = _mock_httpx_response(200)
        mock_client_cls.return_value = mock_client

        result = slack_reporter.send_coverage_alert(sample_coverage_events)

        assert result is True
        assert mock_client.post.called

        # Verify payload
        call_kwargs = mock_client.post.call_args
        payload = json.loads(call_kwargs[1]["content"])

        assert "blocks" in payload
        assert "Coverage dropped" in payload["text"]

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_send_drift_alert_success(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
        sample_drift_events: list[DriftEvent],
    ) -> None:
        """Test sending drift alert successfully."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.return_value = _mock_httpx_response(200)
        mock_client_cls.return_value = mock_client

        result = slack_reporter.send_drift_alert(sample_drift_events)

        assert result is True
        assert mock_client.post.called

        # Verify payload
        call_kwargs = mock_client.post.call_args
        payload = json.loads(call_kwargs[1]["content"])

        assert "blocks" in payload
        assert "Detected drift" in payload["text"]

        # Verify drift details in blocks
        blocks = payload["blocks"]
        assert blocks[0]["type"] == "header"

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_send_summary_success(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
        sample_coverage_before: CoverageReport,
        sample_coverage_after: CoverageReport,
    ) -> None:
        """Test sending summary report successfully."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.return_value = _mock_httpx_response(200)
        mock_client_cls.return_value = mock_client

        result = slack_reporter.send_summary(
            coverage_before=sample_coverage_before,
            coverage_after=sample_coverage_after,
            tests_generated=15,
            bugs_found=3,
            drift_alerts=2,
        )

        assert result is True
        assert mock_client.post.called

        # Verify payload
        call_kwargs = mock_client.post.call_args
        payload = json.loads(call_kwargs[1]["content"])

        assert "blocks" in payload
        assert "nit test generation complete" in payload["text"]

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_send_message_with_non_200_status(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
    ) -> None:
        """Test that non-200 status code is handled correctly."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.return_value = _mock_httpx_response(400)
        mock_client_cls.return_value = mock_client

        result = slack_reporter.send_summary(tests_generated=5)

        assert result is False

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_build_bug_blocks_with_github_links(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
    ) -> None:
        """Test that bug blocks include GitHub action buttons when URLs provided."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.return_value = _mock_httpx_response(200)
        mock_client_cls.return_value = mock_client

        bug_with_links = BugEvent(
            file_path="src/test.py",
            bug_type="test bug",
            description="Test description",
            severity="high",
            github_issue_url="https://github.com/test/repo/issues/1",
            github_pr_url="https://github.com/test/repo/pull/2",
        )

        slack_reporter.send_bug_alert([bug_with_links])

        # Get the payload
        call_kwargs = mock_client.post.call_args
        payload = json.loads(call_kwargs[1]["content"])

        # Find the actions block
        blocks = payload["blocks"]
        actions_blocks = [b for b in blocks if b.get("type") == "actions"]

        assert len(actions_blocks) > 0
        actions = actions_blocks[0]["elements"]
        assert len(actions) == 2
        assert any("View Issue" in str(a) for a in actions)
        assert any("View Fix" in str(a) for a in actions)

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_build_bug_blocks_limits_display(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
    ) -> None:
        """Test that bug blocks are limited to avoid message size issues."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.return_value = _mock_httpx_response(200)
        mock_client_cls.return_value = mock_client

        # Create 10 bugs
        many_bugs = [
            BugEvent(
                file_path=f"src/file{i}.py",
                bug_type="test bug",
                description=f"Bug {i}",
                severity="medium",
            )
            for i in range(10)
        ]

        slack_reporter.send_bug_alert(many_bugs)

        # Get the payload
        call_kwargs = mock_client.post.call_args
        payload = json.loads(call_kwargs[1]["content"])

        # Should show "...and N more" message
        blocks_text = str(payload["blocks"])
        assert "more bug" in blocks_text.lower()

    def test_coverage_event_delta(self) -> None:
        """Test CoverageEvent delta calculation."""
        event = CoverageEvent(package="test", before=80.0, after=85.0, threshold=75.0)
        assert event.delta == 5.0

        event_drop = CoverageEvent(package="test", before=85.0, after=78.0, threshold=80.0)
        assert event_drop.delta == -7.0

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_build_coverage_blocks_shows_delta(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
    ) -> None:
        """Test that coverage blocks show delta with correct emoji."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.return_value = _mock_httpx_response(200)
        mock_client_cls.return_value = mock_client

        events = [
            CoverageEvent(package="up", before=70.0, after=80.0, threshold=75.0),
            CoverageEvent(package="down", before=85.0, after=75.0, threshold=80.0),
        ]

        slack_reporter.send_coverage_alert(events)

        # Get the payload
        call_kwargs = mock_client.post.call_args
        payload = json.loads(call_kwargs[1]["content"])

        blocks_text = str(payload["blocks"])
        assert "\U0001f4c8" in blocks_text  # Up arrow for increase
        assert "\U0001f4c9" in blocks_text  # Down arrow for decrease

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_build_drift_blocks_truncates_long_output(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
    ) -> None:
        """Test that drift blocks truncate long output to avoid size limits."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.return_value = _mock_httpx_response(200)
        mock_client_cls.return_value = mock_client

        long_output = "x" * 500  # Very long output
        event = DriftEvent(
            test_name="test",
            endpoint="test/endpoint",
            similarity_score=0.5,
            threshold=0.8,
            baseline_output=long_output,
            actual_output=long_output,
        )

        slack_reporter.send_drift_alert([event])

        # Get the payload
        call_kwargs = mock_client.post.call_args
        payload = json.loads(call_kwargs[1]["content"])

        # Should include "..." to indicate truncation
        blocks_text = str(payload["blocks"])
        assert "..." in blocks_text

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_send_message_timeout_error(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
    ) -> None:
        """Test handling of timeout error."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectTimeout("Connection timed out")
        mock_client_cls.return_value = mock_client

        result = slack_reporter.send_summary(tests_generated=1)

        assert result is False

    @mock.patch("nit.agents.reporters.slack.httpx.Client")
    def test_severity_emojis_in_bug_blocks(
        self,
        mock_client_cls: mock.Mock,
        slack_reporter: SlackReporter,
    ) -> None:
        """Test that different severity levels show correct emojis."""
        mock_client = mock.Mock()
        mock_client.__enter__ = mock.Mock(return_value=mock_client)
        mock_client.__exit__ = mock.Mock(return_value=False)
        mock_client.post.return_value = _mock_httpx_response(200)
        mock_client_cls.return_value = mock_client

        bugs = [
            BugEvent(
                file_path="test1.py", bug_type="test", description="test", severity="critical"
            ),
            BugEvent(file_path="test2.py", bug_type="test", description="test", severity="high"),
            BugEvent(file_path="test3.py", bug_type="test", description="test", severity="medium"),
            BugEvent(file_path="test4.py", bug_type="test", description="test", severity="low"),
        ]

        slack_reporter.send_bug_alert(bugs)

        # Get the payload
        call_kwargs = mock_client.post.call_args
        payload = json.loads(call_kwargs[1]["content"])

        blocks_text = str(payload["blocks"])
        assert "\U0001f534" in blocks_text  # critical
        assert "\U0001f7e0" in blocks_text  # high
        assert "\U0001f7e1" in blocks_text  # medium
        assert "\U0001f7e2" in blocks_text  # low
