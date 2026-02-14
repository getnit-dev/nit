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
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nit.memory.analytics_collector import get_analytics_collector
from nit.models.analytics import BugSnapshot
from nit.utils.git import (
    GitHubAPI,
    GitHubAPIError,
    GitOperationError,
    PullRequestParams,
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

    from nit.agents.analyzers.bug import BugReport
    from nit.agents.debuggers import GeneratedFix
    from nit.models.coverage import CoverageReport

logger = logging.getLogger(__name__)

# Minimum number of URL parts required to extract "pull" segment
_MIN_URL_PARTS_FOR_PR = 2

# Resolve full paths for executables
_GIT_PATH = shutil.which("git") or "git"
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
        base_branch: str = "main",
        use_gh_cli: bool | None = None,
    ) -> None:
        """Initialize the GitHub PR reporter.

        The GitHub token is read from the GITHUB_TOKEN environment variable
        when API mode is used.

        Args:
            repo_path: Path to the git repository.
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
            token = os.environ.get("GITHUB_TOKEN")
            self._api = GitHubAPI(token=token)

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
        summary: GenerationSummary,
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
                _run_subprocess(
                    [_GIT_PATH, "checkout", original_branch],
                    cwd=self._repo_path,
                )
                logger.info("Returned to original branch: %s", original_branch)
            except subprocess.CalledProcessError:
                logger.warning("Failed to return to original branch %s", original_branch)

            # Record PR creation to analytics
            if result.success and result.pr_url:
                try:
                    collector = get_analytics_collector(self._repo_path)
                    collector.record_pr_created(
                        pr_url=result.pr_url,
                        files=summary.files_created,
                        metadata={
                            "tests_generated": summary.tests_generated,
                            "tests_passed": summary.tests_passed,
                            "tests_failed": summary.tests_failed,
                            "draft": draft,
                        },
                    )
                except Exception:
                    logger.exception("Failed to record PR creation to analytics")

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

    def create_fix_pr(
        self,
        bug_report: BugReport,
        fix: GeneratedFix,
        file_path: str,
        *,
        draft: bool = False,
    ) -> PRCreationResult:
        """Create a PR for a single bug fix.

        This method:
        1. Creates a new branch (nit/fix-<bug-slug>-<hash>)
        2. Applies the fix to the source file
        3. Commits the fix
        4. Pushes the branch to origin
        5. Creates a pull request

        Args:
            bug_report: The bug that was fixed.
            fix: The generated fix.
            file_path: Path to the file being fixed.
            draft: Whether to create as a draft PR.

        Returns:
            Result of PR creation operation.
        """
        try:
            # Save current branch to return to later
            original_branch = get_current_branch(self._repo_path)
            logger.info("Currently on branch: %s", original_branch)

            # Generate branch name based on bug title
            branch_name = self._generate_fix_branch_name(bug_report)

            # Create and switch to new branch
            create_branch(self._repo_path, branch_name, base=self._base_branch)

            # Apply the fix
            target_path = self._repo_path / file_path
            target_path.write_text(fix.fixed_code, encoding="utf-8")

            # Add the fixed file
            add_files(self._repo_path, [file_path])

            # Commit changes
            commit_message = self._generate_fix_commit_message(bug_report, fix)
            _commit_sha = commit(self._repo_path, commit_message)

            # Push to remote
            push_branch(self._repo_path, branch_name)

            # Create PR
            pr_title = self._generate_fix_pr_title(bug_report)
            pr_body = self._generate_fix_pr_body(bug_report, fix, file_path)

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
                _run_subprocess(
                    [_GIT_PATH, "checkout", original_branch],
                    cwd=self._repo_path,
                )
                logger.info("Returned to original branch: %s", original_branch)
            except subprocess.CalledProcessError:
                logger.warning("Failed to return to original branch %s", original_branch)

            # Record bug fix to analytics
            if result.success:
                try:
                    collector = get_analytics_collector(self._repo_path)
                    collector.record_bug(
                        BugSnapshot(
                            timestamp=datetime.now(UTC).isoformat(),
                            bug_type=bug_report.bug_type.value,
                            severity=bug_report.severity.value,
                            status="fixed",
                            file_path=file_path,
                            line_number=bug_report.location.line_number,
                            title=bug_report.title,
                            pr_url=result.pr_url,
                        ),
                    )
                    if result.pr_url:
                        collector.record_pr_created(
                            pr_url=result.pr_url,
                            files=[file_path],
                            metadata={
                                "bug_fix": True,
                                "bug_type": bug_report.bug_type.value,
                                "draft": draft,
                            },
                        )
                except Exception:
                    logger.exception("Failed to record bug fix to analytics")

            return result

        except (GitOperationError, GitHubAPIError) as exc:
            logger.error("Failed to create fix PR: %s", exc)
            return PRCreationResult(
                success=False,
                error=str(exc),
            )
        except Exception:
            logger.exception("Unexpected error creating fix PR")
            return PRCreationResult(
                success=False,
                error="Unexpected error during fix PR creation",
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

    def _generate_commit_message(self, summary: GenerationSummary) -> str:
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

    def _generate_pr_title(self, summary: GenerationSummary) -> str:
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

    def _generate_pr_body(self, summary: GenerationSummary) -> str:
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

    def _add_pr_header(self, sections: list[str], summary: GenerationSummary) -> None:
        """Add PR header section."""
        sections.extend(
            [
                "## 🤖 nit Test Generation",
                "",
                (
                    f"This PR adds **{summary.tests_generated} generated tests** "
                    "to improve code coverage."
                ),
                "",
            ]
        )

    def _add_test_summary(self, sections: list[str], summary: GenerationSummary) -> None:
        """Add test summary section."""
        sections.append("### 📊 Test Summary")
        sections.append("")
        sections.append(f"- **Tests Generated:** {summary.tests_generated}")
        sections.append(f"- **Tests Passed:** {summary.tests_passed} ✅")
        if summary.tests_failed > 0:
            sections.append(f"- **Tests Failed:** {summary.tests_failed} ❌")
        sections.append("")

    def _add_coverage_section(self, sections: list[str], summary: GenerationSummary) -> None:
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

    def _add_files_section(self, sections: list[str], summary: GenerationSummary) -> None:
        """Add generated files section."""
        if not summary.files_created:
            return

        sections.append("### 📝 Files Created")
        sections.append("")
        sections.extend(f"- `{file_path}`" for file_path in sorted(summary.files_created))
        sections.append("")

    def _add_bugs_sections(self, sections: list[str], summary: GenerationSummary) -> None:
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
                "🤖 Generated by [nit](https://github.com/getnit-dev/nit)",
                "",
                "### Review Checklist",
                "",
                "- [ ] Review generated tests for correctness",
                "- [ ] Verify tests run successfully in CI",
                "- [ ] Check that coverage has improved",
                "- [ ] Ensure no unintended code changes",
            ]
        )

    def _generate_fix_branch_name(self, bug_report: BugReport) -> str:
        """Generate a unique branch name for a bug fix.

        Args:
            bug_report: The bug being fixed.

        Returns:
            Branch name like nit/fix-division-by-zero-abc123
        """
        # Create a slug from the bug title
        slug = bug_report.title.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")[:40]  # Limit length

        # Create hash for uniqueness
        content = f"{bug_report.title}{bug_report.location.file_path}"
        hash_obj = hashlib.sha256(content.encode())
        hash_str = hash_obj.hexdigest()[:8]

        return f"nit/fix-{slug}-{hash_str}"

    def _generate_fix_commit_message(self, bug_report: BugReport, fix: GeneratedFix) -> str:
        """Generate commit message for a bug fix.

        Args:
            bug_report: The bug being fixed.
            fix: The generated fix.

        Returns:
            Formatted commit message.
        """
        lines = [
            f"fix: {bug_report.title}",
            "",
            fix.explanation,
            "",
            f"Bug type: {bug_report.bug_type.value}",
            f"Severity: {bug_report.severity.value}",
            f"Location: {bug_report.location.file_path}:{bug_report.location.line_number}",
            "",
            "Co-Authored-By: nit <noreply@getnit.dev>",
        ]

        return "\n".join(lines)

    def _generate_fix_pr_title(self, bug_report: BugReport) -> str:
        """Generate PR title for a bug fix.

        Args:
            bug_report: The bug being fixed.

        Returns:
            PR title.
        """
        return f"fix: {bug_report.title}"

    def _generate_fix_pr_body(
        self, bug_report: BugReport, fix: GeneratedFix, file_path: str
    ) -> str:
        """Generate PR body for a bug fix.

        Args:
            bug_report: The bug being fixed.
            fix: The generated fix.
            file_path: Path to the fixed file.

        Returns:
            Formatted markdown PR body.
        """
        sections: list[str] = [
            "## 🐛 Bug Fix",
            "",
            f"This PR fixes a **{bug_report.bug_type.value}** bug detected by nit.",
            "",
            "### 📋 Bug Details",
            "",
            f"- **Title:** {bug_report.title}",
            f"- **Severity:** {bug_report.severity.value}",
            f"- **Type:** {bug_report.bug_type.value}",
            f"- **Location:** `{bug_report.location.file_path}:{bug_report.location.line_number}`",
        ]

        if bug_report.location.function_name:
            sections.append(f"- **Function:** `{bug_report.location.function_name}`")

        sections.extend(
            [
                "",
                "### 📝 Description",
                "",
                bug_report.description,
                "",
            ]
        )

        if bug_report.error_message:
            sections.extend(
                [
                    "### ⚠️ Error Message",
                    "",
                    f"```\n{bug_report.error_message}\n```",
                    "",
                ]
            )

        sections.extend(
            [
                "### 🔧 Fix Applied",
                "",
                fix.explanation,
                "",
                f"**File modified:** `{file_path}`",
                "",
            ]
        )

        if fix.safety_notes:
            sections.extend(
                [
                    "### 🛡️ Safety Notes",
                    "",
                ]
            )
            sections.extend(f"- {note}" for note in fix.safety_notes)
            sections.append("")

        sections.extend(
            [
                "---",
                "",
                "🤖 Generated by [nit](https://github.com/getnit-dev/nit)",
                "",
                "### Review Checklist",
                "",
                "- [ ] Review the fix for correctness",
                "- [ ] Verify tests pass in CI",
                "- [ ] Check for edge cases",
                "- [ ] Ensure no regressions",
            ]
        )

        return "\n".join(sections)

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
                _GH_PATH,
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

            result = _run_subprocess(cmd, cwd=self._repo_path)

            # gh CLI outputs the PR URL
            pr_url = result.stdout.strip()

            # Extract PR number from URL (e.g., https://github.com/owner/repo/pull/123)
            pr_number = None
            if pr_url:
                parts = pr_url.rstrip("/").split("/")
                if len(parts) >= _MIN_URL_PARTS_FOR_PR and parts[-2] == "pull":
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
            PullRequestParams(
                owner=self._owner,
                repo=self._repo,
                title=title,
                body=body,
                head=branch_name,
                base=self._base_branch,
                draft=draft,
            )
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
