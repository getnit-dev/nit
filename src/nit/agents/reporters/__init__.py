"""Reporters for outputting test generation results."""

from __future__ import annotations

from nit.agents.reporters.github_comment import GitHubCommentReporter
from nit.agents.reporters.github_pr import GenerationSummary, GitHubPRReporter
from nit.agents.reporters.json_reporter import JSONReporter
from nit.agents.reporters.junit_xml import JUnitXMLReporter
from nit.agents.reporters.markdown_reporter import MarkdownReporter
from nit.agents.reporters.sarif import SARIFReporter
from nit.agents.reporters.slack import SlackReporter

__all__ = [
    "GenerationSummary",
    "GitHubCommentReporter",
    "GitHubPRReporter",
    "JSONReporter",
    "JUnitXMLReporter",
    "MarkdownReporter",
    "SARIFReporter",
    "SlackReporter",
]
