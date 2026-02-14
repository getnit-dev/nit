"""Reporters for outputting test generation results."""

from __future__ import annotations

from nit.agents.reporters.github_comment import GitHubCommentReporter
from nit.agents.reporters.github_pr import GenerationSummary, GitHubPRReporter
from nit.agents.reporters.slack import SlackReporter

__all__ = [
    "GenerationSummary",
    "GitHubCommentReporter",
    "GitHubPRReporter",
    "SlackReporter",
]
