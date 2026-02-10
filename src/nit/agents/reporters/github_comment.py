"""GitHub comment reporter for posting coverage deltas and test summaries to PRs.

This reporter (task 2.3):
1. Posts PR comments with coverage delta table
2. Includes generated tests summary
3. Reports issues found and drift status
4. Uses GitHub API to create/update comments (upsert to avoid duplicates)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nit.utils.git import (
    GitHubAPI,
    GitHubAPIError,
    GitHubPRInfo,
    compute_comment_marker,
    get_pr_info_from_env,
)

if TYPE_CHECKING:
    from nit.agents.analyzers.diff import DiffAnalysisResult
    from nit.models.coverage import CoverageReport

logger = logging.getLogger(__name__)


@dataclass
class FullReportData:
    """Data for a comprehensive GitHub PR comment report."""

    coverage_before: CoverageReport | None = None
    """Coverage report before test generation."""

    coverage_after: CoverageReport | None = None
    """Coverage report after test generation."""

    tests_generated: int = 0
    """Number of tests generated."""

    tests_passed: int = 0
    """Number of tests that passed."""

    tests_failed: int = 0
    """Number of tests that failed."""

    issues_found: list[str] = field(default_factory=list)
    """List of issue descriptions found during testing."""

    drift_status: str | None = None
    """LLM drift status message (if applicable)."""

    diff_result: DiffAnalysisResult | None = None
    """Optional diff analysis result for context."""


class GitHubCommentReporter:
    """Reporter that posts test generation results as GitHub PR comments.

    Creates or updates PR comments with:
    - Coverage delta (before/after comparison)
    - Generated tests summary
    - Issues found
    - Drift status (if applicable)
    """

    def __init__(self, github_token: str | None = None) -> None:
        """Initialize the GitHub comment reporter.

        Args:
            github_token: GitHub personal access token. If not provided,
                will try to read from GITHUB_TOKEN environment variable.

        Raises:
            GitHubAPIError: If no token is available.
        """
        self._api = GitHubAPI(token=github_token)
        self._marker = compute_comment_marker("nit:report")

    def post_coverage_delta(
        self,
        pr_info: GitHubPRInfo,
        before: CoverageReport,
        after: CoverageReport,
        diff_result: DiffAnalysisResult | None = None,
    ) -> dict[str, str]:
        """Post a coverage delta report as a PR comment.

        Args:
            pr_info: Pull request information.
            before: Coverage report before test generation.
            after: Coverage report after test generation.
            diff_result: Optional diff analysis result for context.

        Returns:
            Dict with status and comment URL.

        Raises:
            GitHubAPIError: If posting the comment fails.
        """
        logger.info(
            "Posting coverage delta to PR #%d in %s/%s",
            pr_info.pr_number,
            pr_info.owner,
            pr_info.repo,
        )

        # Format the comment body
        body = self._format_coverage_delta(before, after, diff_result)

        # Create or update comment
        result = self._api.upsert_comment(pr_info, body, self._marker)

        logger.info("Successfully posted comment: %s", result.get("html_url"))

        return {
            "status": "success",
            "comment_url": result.get("html_url", ""),
        }

    def post_test_generation_summary(
        self,
        pr_info: GitHubPRInfo,
        tests_generated: int,
        tests_passed: int,
        tests_failed: int,
        files_changed: int,
    ) -> dict[str, str]:
        """Post a test generation summary as a PR comment.

        Args:
            pr_info: Pull request information.
            tests_generated: Number of tests generated.
            tests_passed: Number of tests that passed.
            tests_failed: Number of tests that failed.
            files_changed: Number of files changed in this PR.

        Returns:
            Dict with status and comment URL.

        Raises:
            GitHubAPIError: If posting the comment fails.
        """
        logger.info(
            "Posting test generation summary to PR #%d in %s/%s",
            pr_info.pr_number,
            pr_info.owner,
            pr_info.repo,
        )

        body = self._format_test_summary(tests_generated, tests_passed, tests_failed, files_changed)

        result = self._api.upsert_comment(pr_info, body, self._marker)

        return {
            "status": "success",
            "comment_url": result.get("html_url", ""),
        }

    def post_full_report(
        self, pr_info: GitHubPRInfo, report_data: FullReportData
    ) -> dict[str, str]:
        """Post a comprehensive report with all available information.

        Args:
            pr_info: Pull request information.
            report_data: Report data containing coverage, tests, issues, etc.

        Returns:
            Dict with status and comment URL.

        Raises:
            GitHubAPIError: If posting the comment fails.
        """
        logger.info(
            "Posting full report to PR #%d in %s/%s",
            pr_info.pr_number,
            pr_info.owner,
            pr_info.repo,
        )

        # Build comprehensive report
        sections: list[str] = []

        # Header
        sections.append("## 🤖 nit Test Generation Report")
        sections.append("")

        # Coverage delta section
        if report_data.coverage_before and report_data.coverage_after:
            sections.append("### 📊 Coverage Delta")
            sections.append("")
            sections.append(
                self._format_coverage_table(report_data.coverage_before, report_data.coverage_after)
            )
            sections.append("")

        # Test generation summary
        if report_data.tests_generated > 0:
            sections.append("### ✅ Tests Generated")
            sections.append("")
            sections.append(f"- **Generated:** {report_data.tests_generated} tests")
            sections.append(f"- **Passed:** {report_data.tests_passed} ✓")
            if report_data.tests_failed > 0:
                sections.append(f"- **Failed:** {report_data.tests_failed} ✗")
            sections.append("")

        # Issues found
        if report_data.issues_found:
            sections.append("### ⚠️ Issues Found")
            sections.append("")
            sections.extend(f"- {issue}" for issue in report_data.issues_found)
            sections.append("")

        # Drift status
        if report_data.drift_status:
            sections.append("### 🔄 Drift Status")
            sections.append("")
            sections.append(report_data.drift_status)
            sections.append("")

        # Changed files context
        if report_data.diff_result:
            sections.append("### 📝 Files Analyzed")
            sections.append("")
            sections.append(
                f"- **Source files changed:** {len(report_data.diff_result.changed_source_files)}"
            )
            sections.append(
                f"- **Test files changed:** {len(report_data.diff_result.changed_test_files)}"
            )
            sections.append(
                f"- **Total affected files:** {len(report_data.diff_result.affected_source_files)}"
            )
            sections.append("")

        # Footer
        sections.append("---")
        sections.append("*Generated by [nit](https://github.com/getnit-dev/nit) 🐛*")

        body = "\n".join(sections)

        # Add marker for upsert
        body = f"{self._marker}\n{body}"

        result = self._api.upsert_comment(pr_info, body, self._marker)

        return {
            "status": "success",
            "comment_url": result.get("html_url", ""),
        }

    def _format_coverage_delta(
        self,
        before: CoverageReport,
        after: CoverageReport,
        diff_result: DiffAnalysisResult | None = None,
    ) -> str:
        """Format coverage delta as markdown.

        Args:
            before: Coverage report before test generation.
            after: Coverage report after test generation.
            diff_result: Optional diff analysis result for context.

        Returns:
            Formatted markdown string.
        """
        sections: list[str] = []

        sections.append("## 📊 Coverage Report")
        sections.append("")
        sections.append(self._format_coverage_table(before, after))
        sections.append("")

        if diff_result:
            sections.append("### Files Analyzed")
            sections.append("")
            sections.append(f"- Source files changed: {len(diff_result.changed_source_files)}")
            sections.append(f"- Test files changed: {len(diff_result.changed_test_files)}")
            sections.append("")

        sections.append("---")
        sections.append("*Generated by [nit](https://github.com/getnit-dev/nit) 🐛*")

        return f"{self._marker}\n" + "\n".join(sections)

    def _format_coverage_table(self, before: CoverageReport, after: CoverageReport) -> str:
        """Format coverage comparison as a markdown table.

        Args:
            before: Coverage report before test generation.
            after: Coverage report after test generation.

        Returns:
            Formatted markdown table.
        """
        lines: list[str] = []

        # Table header
        lines.append("| Package | Before | After | Δ |")
        lines.append("|---------|--------|-------|---|")

        # Per-package rows
        all_packages = sorted(set(before.packages.keys()) | set(after.packages.keys()))

        for pkg_name in all_packages:
            before_pkg = before.packages.get(pkg_name)
            after_pkg = after.packages.get(pkg_name)

            if before_pkg and after_pkg:
                before_pct = before_pkg.line_coverage * 100
                after_pct = after_pkg.line_coverage * 100
                delta = after_pct - before_pct

                # Format with color indicators
                delta_str = self._format_delta(delta)

                lines.append(f"| {pkg_name} | {before_pct:.1f}% | {after_pct:.1f}% | {delta_str} |")

        # Overall row
        before_overall = before.overall_line_coverage * 100
        after_overall = after.overall_line_coverage * 100
        overall_delta = after_overall - before_overall
        overall_delta_str = self._format_delta(overall_delta)

        lines.append(
            f"| **Overall** | **{before_overall:.1f}%** | **{after_overall:.1f}%** | "
            f"**{overall_delta_str}** |"
        )

        return "\n".join(lines)

    def _format_delta(self, delta: float) -> str:
        """Format a delta value with appropriate indicators.

        Args:
            delta: Delta value (positive or negative).

        Returns:
            Formatted string with emoji indicators.
        """
        if delta > 0:
            return f"+{delta:.1f}% 📈"
        if delta < 0:
            return f"{delta:.1f}% 📉"
        return "0.0% ━"

    def _format_test_summary(
        self, tests_generated: int, tests_passed: int, tests_failed: int, files_changed: int
    ) -> str:
        """Format test generation summary as markdown.

        Args:
            tests_generated: Number of tests generated.
            tests_passed: Number of tests that passed.
            tests_failed: Number of tests that failed.
            files_changed: Number of files changed in this PR.

        Returns:
            Formatted markdown string.
        """
        sections: list[str] = []

        sections.append("## ✅ Test Generation Summary")
        sections.append("")
        sections.append(f"**Files Changed:** {files_changed}")
        sections.append(f"**Tests Generated:** {tests_generated}")
        sections.append("")
        sections.append("### Results")
        sections.append("")
        sections.append(f"- ✅ Passed: {tests_passed}")

        if tests_failed > 0:
            sections.append(f"- ❌ Failed: {tests_failed}")

        sections.append("")
        sections.append("---")
        sections.append("*Generated by [nit](https://github.com/getnit-dev/nit) 🐛*")

        return f"{self._marker}\n" + "\n".join(sections)


def create_reporter_from_env() -> GitHubCommentReporter | None:
    """Create a GitHub comment reporter from environment variables.

    Returns:
        GitHubCommentReporter if running in a GitHub Actions PR context, None otherwise.
    """
    try:
        pr_info = get_pr_info_from_env()
        if not pr_info:
            logger.debug("Not running in a GitHub Actions PR context")
            return None

        return GitHubCommentReporter()

    except GitHubAPIError as exc:
        logger.error("Failed to create GitHub reporter: %s", exc)
        return None


def post_coverage_report_from_env(
    before: CoverageReport,
    after: CoverageReport,
    diff_result: DiffAnalysisResult | None = None,
) -> bool:
    """Post a coverage report to GitHub from environment context.

    Convenience function for use in CI/CD environments.

    Args:
        before: Coverage report before test generation.
        after: Coverage report after test generation.
        diff_result: Optional diff analysis result for context.

    Returns:
        True if the report was posted successfully, False otherwise.
    """
    try:
        pr_info = get_pr_info_from_env()
        if not pr_info:
            logger.info("Not running in a GitHub Actions PR context, skipping GitHub comment")
            return False

        reporter = GitHubCommentReporter()
        result = reporter.post_coverage_delta(pr_info, before, after, diff_result)

        logger.info("Posted coverage report: %s", result.get("comment_url"))
        return True

    except GitHubAPIError as exc:
        logger.error("Failed to post coverage report: %s", exc)
        return False
    except Exception:
        logger.exception("Unexpected error posting coverage report")
        return False
