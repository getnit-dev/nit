"""GitHub issue reporter for creating issues for confirmed bugs.

This reporter (task 3.10):
1. Creates GitHub Issues for confirmed bugs
2. Formats issue body with bug description, reproduction steps, root cause analysis
3. Links issues to PRs when fix is generated
4. Supports both gh CLI (preferred) and GitHub API
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.memory.analytics_collector import get_analytics_collector
from nit.utils.git import (
    GitHubAPI,
    GitHubAPIError,
    get_remote_url,
    is_gh_cli_available,
)

if TYPE_CHECKING:
    from pathlib import Path

    from nit.agents.analyzers.bug import BugReport
    from nit.agents.debuggers.fix_gen import GeneratedFix
    from nit.agents.debuggers.root_cause import RootCause

logger = logging.getLogger(__name__)

# Constants
MAX_REPRODUCTION_TEST_LENGTH = 500  # Maximum length of reproduction test to include

# Minimum number of URL parts required to extract "issues" segment
_MIN_URL_PARTS_FOR_ISSUE = 2

# Resolve full paths for executables
_GH_PATH = shutil.which("gh") or "gh"


def _run_subprocess(
    cmd: list[str],
    *,
    cwd: Path | str | None = None,
    capture_output: bool = True,
    text: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command safely.

    This is a thin wrapper around subprocess.run that centralises all
    subprocess invocations for this module, using fully-resolved executable
    paths.

    Args:
        cmd: Command and arguments to run.
        cwd: Working directory.
        capture_output: Capture stdout/stderr.
        text: Decode output as text.
        check: Raise on non-zero exit code.

    Returns:
        Completed process result.
    """
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture_output,
        text=text,
        check=check,
    )


@dataclass
class IssueCreationResult:
    """Result of issue creation operation."""

    success: bool
    """Whether the issue was created successfully."""

    issue_url: str | None = None
    """URL of the created issue."""

    issue_number: int | None = None
    """Issue number."""

    error: str | None = None
    """Error message if creation failed."""


@dataclass
class BugIssueData:
    """Data for creating a bug issue."""

    bug_report: BugReport
    """Bug report from BugAnalyzer."""

    root_cause: RootCause | None = None
    """Root cause analysis (if available)."""

    generated_fix: GeneratedFix | None = None
    """Generated fix (if available)."""

    reproduction_test: str | None = None
    """Minimal reproduction test case."""

    pr_url: str | None = None
    """URL of the PR containing the fix (if available)."""

    pr_number: int | None = None
    """PR number containing the fix (if available)."""


class GitHubIssueReporter:
    """Reporter that creates GitHub Issues for confirmed bugs.

    Supports two modes:
    1. gh CLI mode (preferred): Uses gh issue create for native GitHub integration
    2. GitHub API mode: Uses GitHub REST API directly

    The reporter will automatically detect which mode to use based on gh CLI availability.
    """

    def __init__(
        self,
        repo_path: Path,
        *,
        use_gh_cli: bool | None = None,
    ) -> None:
        """Initialize the GitHub issue reporter.

        The GitHub token is read from the GITHUB_TOKEN environment variable
        when API mode is used.

        Args:
            repo_path: Path to the git repository.
            use_gh_cli: Force gh CLI usage. If None, auto-detect.

        Raises:
            GitHubAPIError: If GitHub API is needed but token is unavailable.
        """
        self._repo_path = repo_path.resolve()

        # Determine which mode to use
        if use_gh_cli is None:
            self._use_gh_cli = is_gh_cli_available()
        else:
            self._use_gh_cli = use_gh_cli

        if self._use_gh_cli:
            logger.info("Using gh CLI for issue creation")
            self._api = None
        else:
            logger.info("Using GitHub API for issue creation")
            token = os.environ.get("GITHUB_TOKEN")
            self._api = GitHubAPI(token=token)

        # Parse repository info from remote URL
        remote_url = get_remote_url(self._repo_path)
        self._owner, self._repo = self._parse_github_url(remote_url)

        if not self._owner or not self._repo:
            logger.warning("Could not parse GitHub owner/repo from remote URL: %s", remote_url)

        logger.info("Configured for repository: %s/%s", self._owner, self._repo)

    def create_bug_issue(self, issue_data: BugIssueData) -> IssueCreationResult:
        """Create a GitHub issue for a confirmed bug.

        Args:
            issue_data: Bug issue data with bug report and optional analysis/fix.

        Returns:
            Result of issue creation operation.
        """
        try:
            logger.info("Creating issue for bug: %s", issue_data.bug_report.title)

            # Generate issue title and body
            title = self._generate_issue_title(issue_data.bug_report)
            body = self._generate_issue_body(issue_data)
            labels = self._generate_labels(issue_data.bug_report)

            # Create the issue
            if self._use_gh_cli:
                result = self._create_issue_with_gh_cli(title, body, labels)
            else:
                result = self._create_issue_with_api(title, body, labels)

            logger.info("Created issue #%s: %s", result.issue_number, result.issue_url)

            # Record issue creation to analytics
            if result.success and result.issue_url:
                try:
                    collector = get_analytics_collector(self._repo_path)
                    collector.record_issue_created(
                        issue_url=result.issue_url,
                        bug_type=issue_data.bug_report.bug_type.value,
                        severity=issue_data.bug_report.severity.value,
                        metadata={
                            "bug_title": issue_data.bug_report.title,
                            "file_path": issue_data.bug_report.location.file_path,
                        },
                    )
                except Exception:
                    logger.exception("Failed to record issue creation to analytics")

            return result

        except (GitHubAPIError, subprocess.CalledProcessError) as exc:
            logger.error("Failed to create issue: %s", exc)
            return IssueCreationResult(
                success=False,
                error=str(exc),
            )
        except Exception:
            logger.exception("Unexpected error creating issue")
            return IssueCreationResult(
                success=False,
                error="Unexpected error during issue creation",
            )

    def link_issue_to_pr(self, issue_number: int, pr_number: int, pr_url: str) -> bool:
        """Link an issue to a PR containing its fix.

        Adds a comment to the issue indicating the fix PR.

        Args:
            issue_number: The issue number.
            pr_number: The PR number.
            pr_url: The PR URL.

        Returns:
            True if the link was successful, False otherwise.
        """
        try:
            comment = self._generate_pr_link_comment(pr_number, pr_url)

            if self._use_gh_cli:
                self._add_comment_with_gh_cli(issue_number, comment)
            else:
                self._add_comment_with_api(issue_number, comment)

            logger.info("Linked issue #%d to PR #%d", issue_number, pr_number)
            return True

        except (GitHubAPIError, subprocess.CalledProcessError) as exc:
            logger.error("Failed to link issue to PR: %s", exc)
            return False
        except Exception:
            logger.exception("Unexpected error linking issue to PR")
            return False

    def _generate_issue_title(self, bug_report: BugReport) -> str:
        """Generate issue title from bug report.

        Args:
            bug_report: Bug report.

        Returns:
            Issue title.
        """
        # Use severity emoji prefix
        severity_emojis = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🔵",
            "info": "⚪",
        }
        emoji = severity_emojis.get(bug_report.severity.value, "🐛")

        return f"{emoji} {bug_report.title}"

    def _generate_issue_body(self, issue_data: BugIssueData) -> str:
        """Generate detailed issue body with all bug information.

        Args:
            issue_data: Bug issue data.

        Returns:
            Formatted markdown issue body.
        """
        sections: list[str] = []

        # Header
        self._add_bug_header(sections, issue_data.bug_report)

        # Bug details section
        self._add_bug_details(sections, issue_data.bug_report)

        # Location section
        self._add_location_section(sections, issue_data.bug_report)

        # Error message and stack trace
        self._add_error_section(sections, issue_data.bug_report)

        # Reproduction steps
        self._add_reproduction_section(sections, issue_data)

        # Root cause analysis
        if issue_data.root_cause:
            self._add_root_cause_section(sections, issue_data.root_cause)

        # Suggested fix
        if issue_data.generated_fix:
            self._add_fix_section(sections, issue_data.generated_fix)

        # PR link (if available)
        if issue_data.pr_url and issue_data.pr_number:
            self._add_pr_link_section(sections, issue_data.pr_number, issue_data.pr_url)

        # Footer
        self._add_issue_footer(sections)

        return "\n".join(sections)

    def _add_bug_header(self, sections: list[str], bug_report: BugReport) -> None:
        """Add issue header section."""
        sections.extend(
            [
                "## 🐛 Bug Report",
                "",
                bug_report.description.split("\n\n")[0],  # First paragraph only
                "",
            ]
        )

    def _add_bug_details(self, sections: list[str], bug_report: BugReport) -> None:
        """Add bug details section."""
        sections.append("### Details")
        sections.append("")
        sections.append(f"- **Type:** {bug_report.bug_type.value.replace('_', ' ').title()}")
        sections.append(f"- **Severity:** {bug_report.severity.value.upper()}")
        sections.append(f"- **Confidence:** {bug_report.confidence:.0%}")
        sections.append("")

    def _add_location_section(self, sections: list[str], bug_report: BugReport) -> None:
        """Add bug location section."""
        sections.append("### Location")
        sections.append("")
        sections.append(f"- **File:** `{bug_report.location.file_path}`")

        if bug_report.location.line_number:
            sections.append(f"- **Line:** {bug_report.location.line_number}")

        if bug_report.location.function_name:
            sections.append(f"- **Function:** `{bug_report.location.function_name}`")

        if bug_report.location.code_snippet:
            sections.append("")
            sections.append("```")
            sections.append(bug_report.location.code_snippet)
            sections.append("```")

        sections.append("")

    def _add_error_section(self, sections: list[str], bug_report: BugReport) -> None:
        """Add error message and stack trace section."""
        sections.append("### Error Message")
        sections.append("")
        sections.append("```")
        sections.append(bug_report.error_message)
        sections.append("```")
        sections.append("")

        if bug_report.stack_trace:
            sections.append("<details>")
            sections.append("<summary>Stack Trace</summary>")
            sections.append("")
            sections.append("```")
            sections.append(bug_report.stack_trace)
            sections.append("```")
            sections.append("</details>")
            sections.append("")

    def _add_reproduction_section(self, sections: list[str], issue_data: BugIssueData) -> None:
        """Add reproduction steps section."""
        sections.append("### Reproduction")
        sections.append("")

        if issue_data.bug_report.reproduction_steps:
            sections.append("**Steps to reproduce:**")
            sections.append("")
            for i, step in enumerate(issue_data.bug_report.reproduction_steps, 1):
                sections.append(f"{i}. {step}")
            sections.append("")

        if issue_data.reproduction_test:
            sections.append("**Minimal test case:**")
            sections.append("")
            sections.append("```")
            # Truncate if too long
            test_code = issue_data.reproduction_test
            if len(test_code) > MAX_REPRODUCTION_TEST_LENGTH:
                test_code = test_code[:MAX_REPRODUCTION_TEST_LENGTH] + "\n... (truncated)"
            sections.append(test_code)
            sections.append("```")
            sections.append("")

    def _add_root_cause_section(self, sections: list[str], root_cause: RootCause) -> None:
        """Add root cause analysis section."""
        sections.append("### Root Cause Analysis")
        sections.append("")
        sections.append(f"**Category:** {root_cause.category.replace('_', ' ').title()}")
        sections.append("")
        sections.append(root_cause.description)
        sections.append("")

        if root_cause.missing_checks:
            sections.append("**Missing checks:**")
            sections.append("")
            sections.extend(f"- {check}" for check in root_cause.missing_checks)
            sections.append("")

        if root_cause.incorrect_assumptions:
            sections.append("**Incorrect assumptions:**")
            sections.append("")
            sections.extend(f"- {assumption}" for assumption in root_cause.incorrect_assumptions)
            sections.append("")

        if root_cause.affected_code:
            sections.append("**Affected code:**")
            sections.append("")
            sections.append("```")
            sections.append(root_cause.affected_code)
            sections.append("```")
            sections.append("")

    def _add_fix_section(self, sections: list[str], generated_fix: GeneratedFix) -> None:
        """Add suggested fix section."""
        sections.append("### Suggested Fix")
        sections.append("")
        sections.append(generated_fix.explanation)
        sections.append("")

        if generated_fix.patch:
            sections.append("<details>")
            sections.append("<summary>Patch</summary>")
            sections.append("")
            sections.append("```diff")
            sections.append(generated_fix.patch)
            sections.append("```")
            sections.append("</details>")
            sections.append("")

        if generated_fix.safety_notes:
            sections.append("**⚠️ Safety notes:**")
            sections.append("")
            sections.extend(f"- {note}" for note in generated_fix.safety_notes)
            sections.append("")

    def _add_pr_link_section(self, sections: list[str], pr_number: int, pr_url: str) -> None:
        """Add PR link section."""
        sections.append(f"### Fix Available in #{pr_number}")
        sections.append("")
        sections.append(f"A fix for this issue is available in PR #{pr_number}: {pr_url}")
        sections.append("")

    @staticmethod
    def _add_issue_footer(sections: list[str]) -> None:
        """Add issue footer."""
        sections.extend(
            [
                "---",
                "",
                "🤖 Detected and reported by [nit](https://github.com/getnit-dev/nit)",
            ]
        )

    def _generate_labels(self, bug_report: BugReport) -> list[str]:
        """Generate appropriate labels for the issue.

        Args:
            bug_report: Bug report.

        Returns:
            List of label names.
        """
        labels = ["bug"]

        # Add severity label
        labels.append(f"severity:{bug_report.severity.value}")

        # Add type label
        labels.append(f"type:{bug_report.bug_type.value}")

        # Add nit label for tracking
        labels.append("nit:detected")

        return labels

    def _generate_pr_link_comment(self, pr_number: int, pr_url: str) -> str:
        """Generate comment linking to fix PR.

        Args:
            pr_number: PR number.
            pr_url: PR URL.

        Returns:
            Comment text.
        """
        return f"🔧 A fix for this issue is available in #{pr_number}\n\n{pr_url}"

    def _create_issue_with_gh_cli(
        self, title: str, body: str, labels: list[str]
    ) -> IssueCreationResult:
        """Create issue using gh CLI.

        Args:
            title: Issue title.
            body: Issue body.
            labels: List of labels.

        Returns:
            Issue creation result.

        Raises:
            subprocess.CalledProcessError: If gh CLI command fails.
        """
        cmd = [
            _GH_PATH,
            "issue",
            "create",
            "--title",
            title,
            "--body",
            body,
        ]

        # Add labels
        for label in labels:
            cmd.extend(["--label", label])

        result = _run_subprocess(cmd, cwd=self._repo_path)

        # gh CLI outputs the issue URL
        issue_url = result.stdout.strip()

        # Extract issue number from URL (e.g., https://github.com/owner/repo/issues/123)
        issue_number = None
        if issue_url:
            parts = issue_url.rstrip("/").split("/")
            if len(parts) >= _MIN_URL_PARTS_FOR_ISSUE and parts[-2] == "issues":
                with contextlib.suppress(ValueError):
                    issue_number = int(parts[-1])

        logger.info("Created issue via gh CLI: %s", issue_url)

        return IssueCreationResult(
            success=True,
            issue_url=issue_url,
            issue_number=issue_number,
        )

    def _create_issue_with_api(
        self, title: str, body: str, labels: list[str]
    ) -> IssueCreationResult:
        """Create issue using GitHub API.

        Args:
            title: Issue title.
            body: Issue body.
            labels: List of labels.

        Returns:
            Issue creation result.

        Raises:
            GitHubAPIError: If API request fails.
        """
        if not self._api:
            raise GitHubAPIError("GitHub API not initialized")

        if not self._owner or not self._repo:
            raise GitHubAPIError("Repository owner/name not available")

        response = self._api.create_issue(
            owner=self._owner,
            repo=self._repo,
            title=title,
            body=body,
            labels=labels,
        )

        issue_url = response.get("html_url", "")
        issue_number = response.get("number")

        logger.info("Created issue via API: %s", issue_url)

        return IssueCreationResult(
            success=True,
            issue_url=issue_url,
            issue_number=issue_number,
        )

    def _add_comment_with_gh_cli(self, issue_number: int, comment: str) -> None:
        """Add a comment to an issue using gh CLI.

        Args:
            issue_number: Issue number.
            comment: Comment text.

        Raises:
            subprocess.CalledProcessError: If gh CLI command fails.
        """
        cmd = [
            _GH_PATH,
            "issue",
            "comment",
            str(issue_number),
            "--body",
            comment,
        ]

        _run_subprocess(cmd, cwd=self._repo_path)

        logger.info("Added comment to issue #%d via gh CLI", issue_number)

    def _add_comment_with_api(self, issue_number: int, comment: str) -> None:
        """Add a comment to an issue using GitHub API.

        Args:
            issue_number: Issue number.
            comment: Comment text.

        Raises:
            GitHubAPIError: If API request fails.
        """
        if not self._api:
            raise GitHubAPIError("GitHub API not initialized")

        if not self._owner or not self._repo:
            raise GitHubAPIError("Repository owner/name not available")

        self._api.create_issue_comment(
            owner=self._owner,
            repo=self._repo,
            issue_number=issue_number,
            body=comment,
        )

        logger.info("Added comment to issue #%d via API", issue_number)

    @staticmethod
    def _parse_github_url(url: str) -> tuple[str | None, str | None]:
        """Parse owner and repo from a GitHub URL.

        Args:
            url: GitHub URL (HTTPS or SSH format).

        Returns:
            Tuple of (owner, repo) or (None, None) if parsing fails.
        """
        # HTTPS: https://github.com/owner/repo.git
        https_pattern = r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$"
        # SSH: git@github.com:owner/repo.git
        ssh_pattern = r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$"

        for pattern in [https_pattern, ssh_pattern]:
            match = re.match(pattern, url)
            if match:
                owner, repo = match.groups()
                return owner, repo

        return None, None
