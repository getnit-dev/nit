"""Git and GitHub API utilities for nit.

This module provides utilities for interacting with Git repositories and the GitHub API.
Supports both gh CLI (preferred) and direct git+GitHub API operations.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# GitHub API constants
GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"  # noqa: S105


@dataclass
class GitHubPRInfo:
    """Information about a GitHub pull request."""

    owner: str
    """Repository owner (username or organization)."""

    repo: str
    """Repository name."""

    pr_number: int
    """Pull request number."""


class GitHubAPIError(Exception):
    """Exception raised when GitHub API operations fail."""


class GitHubAPI:
    """Client for interacting with the GitHub API.

    Handles authentication, API requests, and PR comment management.
    """

    def __init__(self, token: str | None = None) -> None:
        """Initialize the GitHub API client.

        Args:
            token: GitHub personal access token. If not provided, will try to read
                from GITHUB_TOKEN environment variable.

        Raises:
            GitHubAPIError: If no token is available.
        """
        self._token = token or os.environ.get(GITHUB_TOKEN_ENV)
        if not self._token:
            raise GitHubAPIError(
                f"GitHub token required. Set {GITHUB_TOKEN_ENV} environment variable "
                "or pass token to constructor."
            )

        self._session_headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def create_comment(self, pr_info: GitHubPRInfo, body: str) -> dict[str, Any]:
        """Create a new comment on a pull request.

        Args:
            pr_info: Pull request information.
            body: Comment body (markdown formatted).

        Returns:
            GitHub API response as a dictionary.

        Raises:
            GitHubAPIError: If the API request fails.
        """
        url = (
            f"{GITHUB_API_BASE}/repos/{pr_info.owner}/{pr_info.repo}/"
            f"issues/{pr_info.pr_number}/comments"
        )

        result: dict[str, Any] = self._post(url, {"body": body})
        return result

    def update_comment(self, pr_info: GitHubPRInfo, comment_id: int, body: str) -> dict[str, Any]:
        """Update an existing comment on a pull request.

        Args:
            pr_info: Pull request information.
            comment_id: ID of the comment to update.
            body: New comment body (markdown formatted).

        Returns:
            GitHub API response as a dictionary.

        Raises:
            GitHubAPIError: If the API request fails.
        """
        url = (
            f"{GITHUB_API_BASE}/repos/{pr_info.owner}/{pr_info.repo}/"
            f"issues/comments/{comment_id}"
        )

        result: dict[str, Any] = self._patch(url, {"body": body})
        return result

    def find_comment_by_marker(self, pr_info: GitHubPRInfo, marker: str) -> dict[str, Any] | None:
        """Find a comment on a PR by a unique marker string.

        Args:
            pr_info: Pull request information.
            marker: Unique marker to search for in comment body.

        Returns:
            Comment dict if found, None otherwise.

        Raises:
            GitHubAPIError: If the API request fails.
        """
        url = (
            f"{GITHUB_API_BASE}/repos/{pr_info.owner}/{pr_info.repo}/"
            f"issues/{pr_info.pr_number}/comments"
        )

        comments: list[dict[str, Any]] = self._get(url)

        for comment in comments:
            if marker in comment.get("body", ""):
                result: dict[str, Any] = comment
                return result

        return None

    def upsert_comment(self, pr_info: GitHubPRInfo, body: str, marker: str) -> dict[str, Any]:
        """Create or update a comment on a PR.

        If a comment with the given marker exists, it will be updated.
        Otherwise, a new comment will be created.

        Args:
            pr_info: Pull request information.
            body: Comment body (markdown formatted). Should include the marker.
            marker: Unique marker to identify this comment (e.g., "<!-- nit:coverage -->").

        Returns:
            GitHub API response as a dictionary.

        Raises:
            GitHubAPIError: If the API request fails.
        """
        # Check if marker is in body
        if marker not in body:
            logger.warning("Marker '%s' not found in comment body. Adding it.", marker)
            body = f"{marker}\n{body}"

        # Find existing comment
        existing = self.find_comment_by_marker(pr_info, marker)

        if existing:
            logger.info("Updating existing comment %d", existing["id"])
            return self.update_comment(pr_info, existing["id"], body)

        logger.info("Creating new comment")
        return self.create_comment(pr_info, body)

    def create_pull_request(  # noqa: PLR0913
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
        *,
        draft: bool = False,
    ) -> dict[str, Any]:
        """Create a new pull request.

        Args:
            owner: Repository owner.
            repo: Repository name.
            title: PR title.
            body: PR body (markdown formatted).
            head: Branch name containing changes.
            base: Branch to merge into.
            draft: Whether to create as a draft PR.

        Returns:
            GitHub API response with PR details.

        Raises:
            GitHubAPIError: If the API request fails.
        """
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls"

        data: dict[str, Any] = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        }

        logger.info("Creating PR: %s -> %s", head, base)
        result: dict[str, Any] = self._post(url, data)
        return result

    def _get(self, url: str) -> Any:
        """Make a GET request to the GitHub API.

        Args:
            url: Full API URL.

        Returns:
            Parsed JSON response.

        Raises:
            GitHubAPIError: If the request fails.
        """
        try:
            response = requests.get(url, headers=self._session_headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise GitHubAPIError(f"GET request failed: {exc}") from exc

    def _post(self, url: str, data: dict[str, Any]) -> Any:
        """Make a POST request to the GitHub API.

        Args:
            url: Full API URL.
            data: Request body data.

        Returns:
            Parsed JSON response.

        Raises:
            GitHubAPIError: If the request fails.
        """
        try:
            response = requests.post(url, json=data, headers=self._session_headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise GitHubAPIError(f"POST request failed: {exc}") from exc

    def _patch(self, url: str, data: dict[str, Any]) -> Any:
        """Make a PATCH request to the GitHub API.

        Args:
            url: Full API URL.
            data: Request body data.

        Returns:
            Parsed JSON response.

        Raises:
            GitHubAPIError: If the request fails.
        """
        try:
            response = requests.patch(url, json=data, headers=self._session_headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise GitHubAPIError(f"PATCH request failed: {exc}") from exc


def get_pr_info_from_env() -> GitHubPRInfo | None:
    """Get PR information from GitHub Actions environment variables.

    Returns:
        GitHubPRInfo if running in a PR context, None otherwise.
    """
    # GitHub Actions sets these environment variables for PRs
    github_repository = os.environ.get("GITHUB_REPOSITORY")
    github_event_name = os.environ.get("GITHUB_EVENT_NAME")
    github_ref = os.environ.get("GITHUB_REF")

    if not github_repository or github_event_name != "pull_request":
        return None

    # Parse owner/repo from GITHUB_REPOSITORY
    parts = github_repository.split("/")
    if len(parts) != 2:  # noqa: PLR2004
        return None

    owner, repo = parts

    # Parse PR number from GITHUB_REF (format: refs/pull/<number>/merge)
    if not github_ref or not github_ref.startswith("refs/pull/"):
        return None

    try:
        pr_number = int(github_ref.split("/")[2])
    except IndexError, ValueError:
        return None

    return GitHubPRInfo(owner=owner, repo=repo, pr_number=pr_number)


def get_pr_info_from_git(repo_path: Path) -> GitHubPRInfo | None:
    """Get PR information from git repository.

    This attempts to extract PR information from the git remote URL
    and current branch name.

    Args:
        repo_path: Path to git repository.

    Returns:
        GitHubPRInfo if PR information can be determined, None otherwise.
    """
    try:
        # Get remote URL
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],  # noqa: S607
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        remote_url = result.stdout.strip()

        # Parse owner/repo from GitHub URL
        # Supports both HTTPS and SSH formats
        owner, repo = _parse_github_url(remote_url)
        if not owner or not repo:
            return None

        # Try to get PR number from branch name (if it follows conventions)
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        branch_name = result.stdout.strip()

        # Try to extract PR number from branch name (e.g., "pr-123" or "123-feature")
        pr_number = _extract_pr_number_from_branch(branch_name)
        if pr_number:
            return GitHubPRInfo(owner=owner, repo=repo, pr_number=pr_number)

        return None

    except subprocess.CalledProcessError:
        return None


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


def _extract_pr_number_from_branch(branch_name: str) -> int | None:
    """Extract PR number from branch name if present.

    Args:
        branch_name: Git branch name.

    Returns:
        PR number if found, None otherwise.
    """
    # Try patterns like "pr-123", "pr/123", "123-feature"
    patterns = [
        r"^pr[/-](\d+)",  # pr-123 or pr/123
        r"^(\d+)[/-]",  # 123-feature or 123/feature
    ]

    for pattern in patterns:
        match = re.match(pattern, branch_name)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue

    return None


def compute_comment_marker(prefix: str) -> str:
    """Generate a unique marker for a GitHub comment.

    This creates an HTML comment marker that can be used to identify
    and update specific comments on a PR.

    Args:
        prefix: Prefix for the marker (e.g., "nit:coverage").

    Returns:
        HTML comment marker string.
    """
    # Create a hash of the prefix for uniqueness
    hash_obj = hashlib.sha256(prefix.encode())
    hash_str = hash_obj.hexdigest()[:8]

    return f"<!-- {prefix}:{hash_str} -->"


def is_gh_cli_available() -> bool:
    """Check if gh CLI is available.

    Returns:
        True if gh CLI is installed and authenticated, False otherwise.
    """
    try:
        # Check if gh is installed
        result = subprocess.run(
            ["gh", "--version"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False

        # Check if gh is authenticated
        result = subprocess.run(
            ["gh", "auth", "status"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    except FileNotFoundError:
        return False


class GitOperationError(Exception):
    """Exception raised when git operations fail."""


def get_current_branch(repo_path: Path) -> str:
    """Get the current git branch name.

    Args:
        repo_path: Path to git repository.

    Returns:
        Current branch name.

    Raises:
        GitOperationError: If the operation fails.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise GitOperationError(f"Failed to get current branch: {exc}") from exc


def create_branch(repo_path: Path, branch_name: str, *, base: str | None = None) -> None:
    """Create a new git branch.

    Args:
        repo_path: Path to git repository.
        branch_name: Name of the new branch.
        base: Optional base branch/commit. If None, creates from current HEAD.

    Raises:
        GitOperationError: If the operation fails.
    """
    try:
        cmd = ["git", "checkout", "-b", branch_name]
        if base:
            cmd.append(base)

        subprocess.run(  # noqa: S603
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("Created branch %s", branch_name)
    except subprocess.CalledProcessError as exc:
        raise GitOperationError(f"Failed to create branch {branch_name}: {exc}") from exc


def add_files(repo_path: Path, files: list[str]) -> None:
    """Add files to git staging area.

    Args:
        repo_path: Path to git repository.
        files: List of file paths to add (relative to repo root).

    Raises:
        GitOperationError: If the operation fails.
    """
    try:
        subprocess.run(  # noqa: S603
            ["git", "add", *files],  # noqa: S607
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("Added %d files to staging", len(files))
    except subprocess.CalledProcessError as exc:
        raise GitOperationError(f"Failed to add files: {exc}") from exc


def commit(repo_path: Path, message: str) -> str:
    """Commit staged changes.

    Args:
        repo_path: Path to git repository.
        message: Commit message.

    Returns:
        Commit SHA.

    Raises:
        GitOperationError: If the operation fails.
    """
    try:
        # Commit the changes
        subprocess.run(  # noqa: S603
            ["git", "commit", "-m", message],  # noqa: S607
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )

        # Get the commit SHA
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        commit_sha = result.stdout.strip()
        logger.info("Created commit %s", commit_sha[:8])
        return commit_sha
    except subprocess.CalledProcessError as exc:
        raise GitOperationError(f"Failed to commit: {exc}") from exc


def push_branch(repo_path: Path, branch_name: str, *, force: bool = False) -> None:
    """Push a branch to remote.

    Args:
        repo_path: Path to git repository.
        branch_name: Name of the branch to push.
        force: Whether to force push.

    Raises:
        GitOperationError: If the operation fails.
    """
    try:
        cmd = ["git", "push", "-u", "origin", branch_name]
        if force:
            cmd.append("--force")

        subprocess.run(  # noqa: S603
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("Pushed branch %s to origin", branch_name)
    except subprocess.CalledProcessError as exc:
        raise GitOperationError(f"Failed to push branch {branch_name}: {exc}") from exc


def get_remote_url(repo_path: Path) -> str:
    """Get the origin remote URL.

    Args:
        repo_path: Path to git repository.

    Returns:
        Remote URL.

    Raises:
        GitOperationError: If the operation fails.
    """
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],  # noqa: S607
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise GitOperationError(f"Failed to get remote URL: {exc}") from exc
