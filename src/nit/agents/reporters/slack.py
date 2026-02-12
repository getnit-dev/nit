"""Slack reporter for sending webhook notifications about critical events.

This reporter (task 4.14.1):
1. Sends webhook notifications for critical events (bugs found, coverage drops, drift alerts)
2. Formats messages with Slack blocks for rich presentation
3. Includes relevant details and action links
4. Supports configurable webhook URL from .nit.yml
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from nit.models.coverage import CoverageReport

logger = logging.getLogger(__name__)

# --- Display limits (avoid Slack message size caps) ---
_MAX_BUGS_DISPLAYED = 5
_MAX_COVERAGE_DISPLAYED = 10
_MAX_DRIFT_DISPLAYED = 5
_MAX_PREVIEW_LENGTH = 200

# --- HTTP constants ---
_HTTP_TIMEOUT_SECONDS = 10.0
_HTTP_OK = 200


@dataclass
class BugEvent:
    """Details of a bug discovery event."""

    file_path: str
    """Source file where bug was found."""

    function_name: str | None = None
    """Function name where bug was found (if applicable)."""

    bug_type: str = ""
    """Type of bug (e.g., null dereference, undefined return, etc.)."""

    description: str = ""
    """Human-readable description of the bug."""

    severity: str = "medium"
    """Severity level: low, medium, high, critical."""

    github_issue_url: str | None = None
    """GitHub issue URL if created."""

    github_pr_url: str | None = None
    """GitHub PR URL with fix if created."""


@dataclass
class CoverageEvent:
    """Details of a coverage drop event."""

    package: str
    """Package name."""

    before: float
    """Coverage percentage before."""

    after: float
    """Coverage percentage after."""

    threshold: float
    """Configured coverage threshold."""

    @property
    def delta(self) -> float:
        """Coverage delta (negative means drop)."""
        return self.after - self.before


@dataclass
class DriftEvent:
    """Details of a drift detection event."""

    test_name: str
    """Name of the drift test that failed."""

    endpoint: str
    """LLM endpoint being monitored."""

    similarity_score: float
    """Similarity score (0.0-1.0)."""

    threshold: float
    """Configured similarity threshold."""

    baseline_output: str
    """Expected baseline output."""

    actual_output: str
    """Actual output received."""


class SlackReporter:
    """Reporter that sends notifications to Slack via webhook.

    Sends rich formatted messages using Slack Block Kit for:
    - Bug discoveries
    - Coverage drops below threshold
    - LLM drift alerts
    """

    def __init__(self, webhook_url: str) -> None:
        """Initialize the Slack reporter.

        Args:
            webhook_url: Slack webhook URL for sending messages.

        Raises:
            ValueError: If webhook_url is empty.
        """
        if not webhook_url:
            msg = "Slack webhook URL is required"
            raise ValueError(msg)

        self.webhook_url = webhook_url

    def send_bug_alert(self, bugs: list[BugEvent]) -> bool:
        """Send a notification about discovered bugs.

        Args:
            bugs: List of bug events to report.

        Returns:
            True if notification was sent successfully, False otherwise.
        """
        if not bugs:
            return True

        blocks = self._build_bug_blocks(bugs)
        return self._send_message(blocks, text=f"🐛 Found {len(bugs)} bug(s)")

    def send_coverage_alert(self, events: list[CoverageEvent]) -> bool:
        """Send a notification about coverage drops.

        Args:
            events: List of coverage drop events.

        Returns:
            True if notification was sent successfully, False otherwise.
        """
        if not events:
            return True

        blocks = self._build_coverage_blocks(events)
        total_drops = sum(1 for e in events if e.delta < 0)
        return self._send_message(blocks, text=f"📉 Coverage dropped in {total_drops} package(s)")

    def send_drift_alert(self, events: list[DriftEvent]) -> bool:
        """Send a notification about LLM drift detections.

        Args:
            events: List of drift events.

        Returns:
            True if notification was sent successfully, False otherwise.
        """
        if not events:
            return True

        blocks = self._build_drift_blocks(events)
        return self._send_message(blocks, text=f"🔄 Detected drift in {len(events)} test(s)")

    def send_summary(
        self,
        coverage_before: CoverageReport | None = None,
        coverage_after: CoverageReport | None = None,
        tests_generated: int = 0,
        bugs_found: int = 0,
        drift_alerts: int = 0,
    ) -> bool:
        """Send a comprehensive summary of test generation results.

        Args:
            coverage_before: Coverage report before generation.
            coverage_after: Coverage report after generation.
            tests_generated: Number of tests generated.
            bugs_found: Number of bugs discovered.
            drift_alerts: Number of drift alerts triggered.

        Returns:
            True if notification was sent successfully, False otherwise.
        """
        blocks = self._build_summary_blocks(
            coverage_before, coverage_after, tests_generated, bugs_found, drift_alerts
        )
        return self._send_message(blocks, text="✅ nit test generation complete")

    def _build_bug_blocks(self, bugs: list[BugEvent]) -> list[dict[str, Any]]:
        """Build Slack blocks for bug alert.

        Args:
            bugs: List of bug events.

        Returns:
            List of Slack block objects.
        """
        blocks: list[dict[str, Any]] = []

        # Header
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🐛 Found {len(bugs)} Bug{'' if len(bugs) == 1 else 's'}",
                },
            }
        )

        # Bug details
        for bug in bugs[:_MAX_BUGS_DISPLAYED]:
            severity_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🟢",
            }.get(bug.severity, "⚪")

            fields: list[dict[str, Any]] = [
                {
                    "type": "mrkdwn",
                    "text": f"*File:*\n`{bug.file_path}`",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Severity:*\n{severity_emoji} {bug.severity.capitalize()}",
                },
            ]

            if bug.function_name:
                fields.append(
                    {
                        "type": "mrkdwn",
                        "text": f"*Function:*\n`{bug.function_name}`",
                    }
                )

            if bug.bug_type:
                fields.append(
                    {
                        "type": "mrkdwn",
                        "text": f"*Type:*\n{bug.bug_type}",
                    }
                )

            blocks.append(
                {
                    "type": "section",
                    "fields": fields,
                }
            )

            if bug.description:
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"```{bug.description}```",
                        },
                    }
                )

            # Action buttons if available
            elements: list[dict[str, Any]] = []
            if bug.github_issue_url:
                elements.append(
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Issue"},
                        "url": bug.github_issue_url,
                    }
                )
            if bug.github_pr_url:
                elements.append(
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Fix"},
                        "url": bug.github_pr_url,
                    }
                )

            if elements:
                blocks.append({"type": "actions", "elements": elements})

            blocks.append({"type": "divider"})

        # Show count if more bugs exist
        if len(bugs) > _MAX_BUGS_DISPLAYED:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (f"_...and {len(bugs) - _MAX_BUGS_DISPLAYED} more bug(s)_"),
                        }
                    ],
                }
            )

        return blocks

    def _build_coverage_blocks(self, events: list[CoverageEvent]) -> list[dict[str, Any]]:
        """Build Slack blocks for coverage alert.

        Args:
            events: List of coverage events.

        Returns:
            List of Slack block objects.
        """
        blocks: list[dict[str, Any]] = []

        # Header
        drops = [e for e in events if e.delta < 0]
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": (
                        f"📉 Coverage Dropped in {len(drops)} "
                        f"Package{'' if len(drops) == 1 else 's'}"
                    ),
                },
            }
        )

        # Coverage details
        for event in events[:_MAX_COVERAGE_DISPLAYED]:
            delta_emoji = "📈" if event.delta > 0 else "📉" if event.delta < 0 else "━"

            blocks.append(
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Package:*\n`{event.package}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Delta:*\n{delta_emoji} {event.delta:+.1f}%",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Before:*\n{event.before:.1f}%",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*After:*\n{event.after:.1f}%",
                        },
                    ],
                }
            )

        if len(events) > _MAX_COVERAGE_DISPLAYED:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (
                                f"_...and {len(events) - _MAX_COVERAGE_DISPLAYED}"
                                " more package(s)_"
                            ),
                        }
                    ],
                }
            )

        return blocks

    def _build_drift_blocks(self, events: list[DriftEvent]) -> list[dict[str, Any]]:
        """Build Slack blocks for drift alert.

        Args:
            events: List of drift events.

        Returns:
            List of Slack block objects.
        """
        blocks: list[dict[str, Any]] = []

        # Header
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": (
                        f"🔄 Detected Drift in {len(events)} "
                        f"Test{'' if len(events) == 1 else 's'}"
                    ),
                },
            }
        )

        # Drift details
        for event in events[:_MAX_DRIFT_DISPLAYED]:
            blocks.append(
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Test:*\n`{event.test_name}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Endpoint:*\n`{event.endpoint}`",
                        },
                        {
                            "type": "mrkdwn",
                            "text": (
                                f"*Similarity:*\n{event.similarity_score:.2f} "
                                f"(threshold: {event.threshold:.2f})"
                            ),
                        },
                    ],
                }
            )

            # Show baseline vs actual (truncated)
            baseline_preview = (
                event.baseline_output[:_MAX_PREVIEW_LENGTH] + "..."
                if len(event.baseline_output) > _MAX_PREVIEW_LENGTH
                else event.baseline_output
            )
            actual_preview = (
                event.actual_output[:_MAX_PREVIEW_LENGTH] + "..."
                if len(event.actual_output) > _MAX_PREVIEW_LENGTH
                else event.actual_output
            )

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Expected:*\n```{baseline_preview}```\n"
                            f"*Actual:*\n```{actual_preview}```"
                        ),
                    },
                }
            )

            blocks.append({"type": "divider"})

        if len(events) > _MAX_DRIFT_DISPLAYED:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (
                                f"_...and {len(events) - _MAX_DRIFT_DISPLAYED}"
                                " more drift test(s)_"
                            ),
                        }
                    ],
                }
            )

        return blocks

    def _build_summary_blocks(
        self,
        coverage_before: CoverageReport | None,
        coverage_after: CoverageReport | None,
        tests_generated: int,
        bugs_found: int,
        drift_alerts: int,
    ) -> list[dict[str, Any]]:
        """Build Slack blocks for summary report.

        Args:
            coverage_before: Coverage report before generation.
            coverage_after: Coverage report after generation.
            tests_generated: Number of tests generated.
            bugs_found: Number of bugs discovered.
            drift_alerts: Number of drift alerts triggered.

        Returns:
            List of Slack block objects.
        """
        blocks: list[dict[str, Any]] = []

        # Header
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "✅ nit Test Generation Complete",
                },
            }
        )

        # Summary metrics
        fields: list[dict[str, Any]] = []

        if tests_generated > 0:
            fields.append(
                {
                    "type": "mrkdwn",
                    "text": f"*Tests Generated:*\n{tests_generated}",
                }
            )

        if coverage_before and coverage_after:
            before_pct = coverage_before.overall_line_coverage * 100
            after_pct = coverage_after.overall_line_coverage * 100
            delta = after_pct - before_pct
            delta_emoji = "📈" if delta > 0 else "📉" if delta < 0 else "━"

            fields.extend(
                [
                    {
                        "type": "mrkdwn",
                        "text": f"*Coverage Before:*\n{before_pct:.1f}%",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Coverage After:*\n{after_pct:.1f}%",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Coverage Delta:*\n{delta_emoji} {delta:+.1f}%",
                    },
                ]
            )

        if bugs_found > 0:
            fields.append(
                {
                    "type": "mrkdwn",
                    "text": f"*Bugs Found:*\n🐛 {bugs_found}",
                }
            )

        if drift_alerts > 0:
            fields.append(
                {
                    "type": "mrkdwn",
                    "text": f"*Drift Alerts:*\n🔄 {drift_alerts}",
                }
            )

        if fields:
            blocks.append(
                {
                    "type": "section",
                    "fields": fields,
                }
            )

        # Footer
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Generated by *nit* 🐛",
                    }
                ],
            }
        )

        return blocks

    def _send_message(self, blocks: list[dict[str, Any]], text: str = "") -> bool:
        """Send a message to Slack via webhook.

        Args:
            blocks: List of Slack block objects.
            text: Fallback text for notifications.

        Returns:
            True if message was sent successfully, False otherwise.
        """
        payload = {
            "blocks": blocks,
            "text": text,  # Fallback text
        }

        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = client.post(
                    self.webhook_url,
                    content=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code == _HTTP_OK:
                    logger.info("Successfully sent Slack notification")
                    return True

                logger.warning("Slack webhook returned status %d", response.status_code)
                return False

        except httpx.HTTPStatusError as exc:
            logger.error("HTTP error sending Slack notification: %s", exc)
            return False
        except httpx.TransportError as exc:
            logger.error("Transport error sending Slack notification: %s", exc)
            return False
        except Exception:
            logger.exception("Unexpected error sending Slack notification")
            return False
