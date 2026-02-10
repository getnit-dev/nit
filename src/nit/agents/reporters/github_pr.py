"""GitHub PR reporter for creating PRs with generated/fixed tests.

This reporter (task 2.10):
1. Creates a new branch with generated tests
2. Commits test files to the branch
3. Pushes the branch to remote
4. Opens a pull request with descriptive body
5. Supports both gh CLI (preferred) and direct git+GitHub API operations
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import re
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nit.utils.git import (
    GitHubAPI,
    GitHubAPIError,
    GitOperationError,
    add_files,
    commit,
    create_branch,
    get_current_branch,
    get_remote_url,
    is_gh_cli_available,
    push_branch,
)

if TYPE_CHECKING:
    from pathlib import Path

    from nit.models.coverage import CoverageReport

logger = logging.getLogger(__name__)


@dataclass
class PRCreationResult:
    """Result of PR creation operation."""

    success: bool
    """Whether the PR was created successfully."""

    pr_url: str | None = None
    """URL of the created PR."""

    pr_number: int | None = None
    """PR number."""

    branch_name: str | None = None
    """Name of the branch created."""

    error: str | None = None
    """Error message if creation failed."""


@dataclass
class GenerationSummary:
    """Summary of test generation for PR body."""

    tests_generated: int = 0
    """Total number of tests generated."""

    tests_passed: int = 0
    """Number of tests that passed."""

    tests_failed: int = 0
    """Number of tests that failed."""

    files_created: list[str] = field(default_factory=list)
    """List of test files created."""

    coverage_before: CoverageReport | None = None
    """Coverage before test generation."""

    coverage_after: CoverageReport | None = None
    """Coverage after test generation."""

    bugs_found: list[str] = field(default_factory=list)
    """List of bugs discovered."""

    bugs_fixed: list[str] = field(default_factory=list)
    """List of bugs fixed (if --fix was used)."""


class GitHubPRReporter:
    """Reporter that creates GitHub PRs with generated/fixed tests.

    Supports two modes:
    1. gh CLI mode (preferred): Uses gh pr create for native GitHub integration
    2. Git + API mode: Uses git commands and GitHub API directly

    The reporter will automatically detect which mode to use based on gh CLI availability.
    """

    def __init__(
        self,
        repo_path: Path,
        *,
        github_token: str | None = None,
        base_branch: str = "main",
        use_gh_cli: bool | None = None,
    ) -> None:
        """Initialize the GitHub PR reporter.

        Args:
            repo_path: Path to the git repository.
            github_token: GitHub personal access token (only needed for API mode).
            base_branch: Base branch to create PRs against.
            use_gh_cli: Force gh CLI usage. If None, auto-detect.

        Raises:
            GitHubAPIError: If GitHub API is needed but token is unavailable.
            GitOperationError: If the repository is invalid.
        """
        self._repo_path = repo_path.resolve()
        self._base_branch = base_branch

        # Determine which mode to use
        if use_gh_cli is None:
            self._use_gh_cli = is_gh_cli_available()
        else:
            self._use_gh_cli = use_gh_cli

        if self._use_gh_cli:
            logger.info("Using gh CLI for PR creation")
            self._api = None
        else:
            logger.info("Using GitHub API for PR creation")
            self._api = GitHubAPI(token=github_token)

        # Parse repository info from remote URL
        remote_url = get_remote_url(self._repo_path)
        self._owner, self._repo = self._parse_github_url(remote_url)

        if not self._owner or not self._repo:
            raise GitOperationError(
                f"Could not parse GitHub owner/repo from remote URL: {remote_url}"
            )

        logger.info("Configured for repository: %s/%s", self._owner, self._repo)

    def create_pr_with_tests(
        self,
        summary: TestGenerationSummary,
        *,
        draft: bool = False,
    ) -> PRCreationResult:
        """Create a PR with generated tests.

        This method:
        1. Creates a new branch (nit/generated-tests-<hash>)
        2. Commits the generated test files
        3. Pushes the branch to origin
        4. Creates a pull request

        Args:
            summary: Test generation summary with files and statistics.
            draft: Whether to create as a draft PR.

        Returns:
            Result of PR creation operation.
        """
        if not summary.files_created:
            return PRCreationResult(
                success=False,
                error="No test files to commit",
            )

        try:
            # Save current branch to return to later
            original_branch = get_current_branch(self._repo_path)
            logger.info("Currently on branch: %s", original_branch)

            # Generate branch name based on content hash
            branch_name = self._generate_branch_name(summary.files_created)

            # Create and switch to new branch
            create_branch(self._repo_path, branch_name, base=self._base_branch)

            # Add test files
            add_files(self._repo_path, summary.files_created)

            # Commit changes
            commit_message = self._generate_commit_message(summary)
            _commit_sha = commit(self._repo_path, commit_message)

            # Push to remote
            push_branch(self._repo_path, branch_name)

            # Create PR
            pr_title = self._generate_pr_title(summary)
            pr_body = self._generate_pr_body(summary)

            if self._use_gh_cli:
                result = self._create_pr_with_gh_cli(
                    branch_name=branch_name,
                    title=pr_title,
                    body=pr_body,
                    draft=draft,
                )
            else:
                result = self._create_pr_with_api(
                    branch_name=branch_name,
                    title=pr_title,
                    body=pr_body,
                    draft=draft,
                )

            # Return to original branch
            try:
                subprocess.run(  # noqa: S603
                    ["git", "checkout", original_branch],  # noqa: S607
                    cwd=self._repo_path,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                logger.info("Returned to original branch: %s", original_branch)
            except subprocess.CalledProcessError:
                logger.warning("Failed to return to original branch %s", original_branch)

            return result

        except (GitOperationError, GitHubAPIError) as exc:
            logger.error("Failed to create PR: %s", exc)
            return PRCreationResult(
                success=False,
                error=str(exc),
            )
        except Exception:
            logger.exception("Unexpected error creating PR")
            return PRCreationResult(
                success=False,
                error="Unexpected error during PR creation",
            )

    def _generate_branch_name(self, files: list[str]) -> str:
        """Generate a unique branch name based on file content.

        Args:
            files: List of files being committed.

        Returns:
            Branch name like nit/generated-tests-abc123
        """
        # Create hash of file list for uniqueness
        content = "".join(sorted(files))
        hash_obj = hashlib.sha256(content.encode())
        hash_str = hash_obj.hexdigest()[:8]

        return f"nit/generated-tests-{hash_str}"

    def _generate_commit_message(self, summary: TestGenerationSummary) -> str:
        """Generate commit message for test generation.

        Args:
            summary: Test generation summary.

        Returns:
            Formatted commit message.
        """
        lines = [
            f"test: add {summary.tests_generated} generated tests",
            "",
            f"Generated {summary.tests_generated} tests using nit.",
        ]

        if summary.coverage_before and summary.coverage_after:
            before = summary.coverage_before.overall_line_coverage * 100
            after = summary.coverage_after.overall_line_coverage * 100
            delta = after - before
            lines.append(f"Coverage: {before:.1f}% → {after:.1f}% (+{delta:.1f}%)")

        if summary.bugs_found:
            lines.append(f"Bugs found: {len(summary.bugs_found)}")

        if summary.bugs_fixed:
            lines.append(f"Bugs fixed: {len(summary.bugs_fixed)}")

        lines.extend(
            [
                "",
                "Co-Authored-By: nit <noreply@getnit.dev>",
            ]
        )

        return "\n".join(lines)

    def _generate_pr_title(self, summary: TestGenerationSummary) -> str:
        """Generate PR title.

        Args:
            summary: Test generation summary.

        Returns:
            PR title.
        """
        if summary.bugs_fixed:
            return (
                f"test: add {summary.tests_generated} tests and fix {len(summary.bugs_fixed)} bugs"
            )
        return f"test: add {summary.tests_generated} generated tests"

    def _generate_pr_body(self, summary: TestGenerationSummary) -> str:
        """Generate PR body with test generation summary.

        Args:
            summary: Test generation summary.

        Returns:
            Formatted markdown PR body.
        """
        sections: list[str] = []

        # Header
        self._add_pr_header(sections, summary)

        # Test statistics
        self._add_test_summary(sections, summary)

        # Coverage improvement
        self._add_coverage_section(sections, summary)

        # Generated files
        self._add_files_section(sections, summary)

        # Bugs
        self._add_bugs_sections(sections, summary)

        # Footer
        self._add_pr_footer(sections)

        return "\n".join(sections)

    def _add_pr_header(self, sections: list[str], summary: TestGenerationSummary) -> None:
        """Add PR header section."""
        sections.extend(
            [
                "## 🤖 nit Test Generation",
                "",
                f"This PR adds **{summary.tests_generated} generated tests** to improve code coverage.",
                "",
            ]
        )

    def _add_test_summary(self, sections: list[str], summary: TestGenerationSummary) -> None:
        """Add test summary section."""
        sections.append("### 📊 Test Summary")
        sections.append("")
        sections.append(f"- **Tests Generated:** {summary.tests_generated}")
        sections.append(f"- **Tests Passed:** {summary.tests_passed} ✅")
        if summary.tests_failed > 0:
            sections.append(f"- **Tests Failed:** {summary.tests_failed} ❌")
        sections.append("")

    def _add_coverage_section(self, sections: list[str], summary: TestGenerationSummary) -> None:
        """Add coverage improvement section."""
        if not (summary.coverage_before and summary.coverage_after):
            return

        sections.append("### 📈 Coverage Improvement")
        sections.append("")
        before = summary.coverage_before.overall_line_coverage * 100
        after = summary.coverage_after.overall_line_coverage * 100
        delta = after - before
        sections.extend(
            [
                f"- **Before:** {before:.1f}%",
                f"- **After:** {after:.1f}%",
                f"- **Improvement:** +{delta:.1f}% 🎉",
                "",
            ]
        )

    def _add_files_section(self, sections: list[str], summary: TestGenerationSummary) -> None:
        """Add generated files section."""
        if not summary.files_created:
            return

        sections.append("### 📝 Files Created")
        sections.append("")
        sections.extend(f"- `{file_path}`" for file_path in sorted(summary.files_created))
        sections.append("")

    def _add_bugs_sections(self, sections: list[str], summary: TestGenerationSummary) -> None:
        """Add bugs found and fixed sections."""
        if summary.bugs_found:
            sections.extend(
                [
                    "### 🐛 Bugs Found",
                    "",
                    "The following issues were discovered during test generation:",
                    "",
                ]
            )
            sections.extend(f"- {bug}" for bug in summary.bugs_found)
            sections.append("")

        if summary.bugs_fixed:
            sections.extend(
                [
                    "### ✨ Bugs Fixed",
                    "",
                    "The following bugs were fixed:",
                    "",
                ]
            )
            sections.extend(f"- {bug}" for bug in summary.bugs_fixed)
            sections.append("")

    @staticmethod
    def _add_pr_footer(sections: list[str]) -> None:
        """Add PR footer with checklist."""
        sections.extend(
            [
                "---",
                "",
                "🤖 Generated by [nit](https://github.com/getnit/nit)",
                "",
                "### Review Checklist",
                "",
                "- [ ] Review generated tests for correctness",
                "- [ ] Verify tests run successfully in CI",
                "- [ ] Check that coverage has improved",
                "- [ ] Ensure no unintended code changes",
            ]
        )

    def _create_pr_with_gh_cli(
        self,
        branch_name: str,
        title: str,
        body: str,
        *,
        draft: bool = False,
    ) -> PRCreationResult:
        """Create PR using gh CLI.

        Args:
            branch_name: Branch containing changes.
            title: PR title.
            body: PR body.
            draft: Whether to create as draft.

        Returns:
            PR creation result.

        Raises:
            GitOperationError: If gh CLI command fails.
        """
        try:
            cmd = [
                "gh",
                "pr",
                "create",
                "--base",
                self._base_branch,
                "--head",
                branch_name,
                "--title",
                title,
                "--body",
                body,
            ]

            if draft:
                cmd.append("--draft")

            result = subprocess.run(  # noqa: S603
                cmd,
                cwd=self._repo_path,
                capture_output=True,
                text=True,
                check=True,
            )

            # gh CLI outputs the PR URL
            pr_url = result.stdout.strip()

            # Extract PR number from URL (e.g., https://github.com/owner/repo/pull/123)
            pr_number = None
            if pr_url:
                parts = pr_url.rstrip("/").split("/")
                if len(parts) >= 2 and parts[-2] == "pull":  # noqa: PLR2004
                    with contextlib.suppress(ValueError):
                        pr_number = int(parts[-1])

            logger.info("Created PR via gh CLI: %s", pr_url)

            return PRCreationResult(
                success=True,
                pr_url=pr_url,
                pr_number=pr_number,
                branch_name=branch_name,
            )

        except subprocess.CalledProcessError as exc:
            error_msg = f"gh CLI failed: {exc.stderr if exc.stderr else str(exc)}"
            raise GitOperationError(error_msg) from exc

    def _create_pr_with_api(
        self,
        branch_name: str,
        title: str,
        body: str,
        *,
        draft: bool = False,
    ) -> PRCreationResult:
        """Create PR using GitHub API.

        Args:
            branch_name: Branch containing changes.
            title: PR title.
            body: PR body.
            draft: Whether to create as draft.

        Returns:
            PR creation result.

        Raises:
            GitHubAPIError: If API request fails.
        """
        if not self._api:
            raise GitHubAPIError("GitHub API not initialized")

        if not self._owner or not self._repo:
            raise GitHubAPIError("Repository owner/name not available")

        response = self._api.create_pull_request(
            owner=self._owner,
            repo=self._repo,
            title=title,
            body=body,
            head=branch_name,
            base=self._base_branch,
            draft=draft,
        )

        pr_url = response.get("html_url", "")
        pr_number = response.get("number")

        logger.info("Created PR via API: %s", pr_url)

        return PRCreationResult(
            success=True,
            pr_url=pr_url,
            pr_number=pr_number,
            branch_name=branch_name,
        )

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
