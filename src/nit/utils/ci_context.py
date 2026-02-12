"""CI and PR context detection utilities."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Expected number of parts when splitting "owner/repo"
_OWNER_REPO_PARTS = 2


def _git_executable() -> str:
    """Resolve the full path to the ``git`` executable."""
    return shutil.which("git") or "git"


@dataclass
class CIContext:
    """Detected CI/PR execution context."""

    is_ci: bool
    """Running in CI environment."""

    is_pr: bool
    """Running in context of a pull request."""

    pr_number: int | None
    """PR number if in PR context."""

    branch: str | None
    """Current branch name."""

    base_branch: str | None
    """Base/target branch for PR."""

    commit_sha: str | None
    """Current commit SHA."""

    repo_owner: str | None
    """Repository owner (org or user)."""

    repo_name: str | None
    """Repository name."""


def detect_ci_context() -> CIContext:
    """Detect CI and PR context from environment variables.

    Supports GitHub Actions, GitLab CI, CircleCI, and generic CI detection.

    Returns:
        CIContext with detected values.
    """
    # GitHub Actions
    if os.getenv("GITHUB_ACTIONS") == "true":
        event_name = os.getenv("GITHUB_EVENT_NAME", "")
        is_pr = event_name == "pull_request"

        # Extract repo info from GITHUB_REPOSITORY (format: owner/repo)
        repo_full = os.getenv("GITHUB_REPOSITORY", "")
        repo_parts = repo_full.split("/") if repo_full else []
        repo_owner = repo_parts[0] if len(repo_parts) == _OWNER_REPO_PARTS else None
        repo_name = repo_parts[1] if len(repo_parts) == _OWNER_REPO_PARTS else None

        return CIContext(
            is_ci=True,
            is_pr=is_pr,
            pr_number=_parse_int(os.getenv("GITHUB_PR_NUMBER")),
            branch=os.getenv("GITHUB_REF_NAME"),
            base_branch=os.getenv("GITHUB_BASE_REF") if is_pr else None,
            commit_sha=os.getenv("GITHUB_SHA"),
            repo_owner=repo_owner,
            repo_name=repo_name,
        )

    # GitLab CI
    if os.getenv("GITLAB_CI") == "true":
        is_pr = bool(os.getenv("CI_MERGE_REQUEST_ID"))
        return CIContext(
            is_ci=True,
            is_pr=is_pr,
            pr_number=_parse_int(os.getenv("CI_MERGE_REQUEST_IID")),
            branch=os.getenv("CI_COMMIT_REF_NAME"),
            base_branch=os.getenv("CI_MERGE_REQUEST_TARGET_BRANCH_NAME") if is_pr else None,
            commit_sha=os.getenv("CI_COMMIT_SHA"),
            repo_owner=None,  # Not directly available
            repo_name=os.getenv("CI_PROJECT_NAME"),
        )

    # CircleCI
    if os.getenv("CIRCLECI") == "true":
        pr_num_str = (
            os.getenv("CIRCLE_PR_NUMBER") or os.getenv("CIRCLE_PULL_REQUEST", "").split("/")[-1]
        )
        is_pr = bool(pr_num_str)
        return CIContext(
            is_ci=True,
            is_pr=is_pr,
            pr_number=_parse_int(pr_num_str),
            branch=os.getenv("CIRCLE_BRANCH"),
            base_branch=None,  # Not directly available
            commit_sha=os.getenv("CIRCLE_SHA1"),
            repo_owner=os.getenv("CIRCLE_PROJECT_USERNAME"),
            repo_name=os.getenv("CIRCLE_PROJECT_REPONAME"),
        )

    # Generic CI detection (CI env var)
    if os.getenv("CI") == "true":
        return CIContext(
            is_ci=True,
            is_pr=False,
            pr_number=None,
            branch=None,
            base_branch=None,
            commit_sha=None,
            repo_owner=None,
            repo_name=None,
        )

    # Not in CI
    return CIContext(
        is_ci=False,
        is_pr=False,
        pr_number=None,
        branch=None,
        base_branch=None,
        commit_sha=None,
        repo_owner=None,
        repo_name=None,
    )


def _parse_int(value: str | None) -> int | None:
    """Parse string to int, return None if invalid."""
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def should_create_pr(
    ci_context: CIContext, create_pr_flag: bool, config_default: bool = False
) -> bool:
    """Determine whether to create a new PR based on context and flags.

    Logic:
    - In CI within a PR: Never create a new PR (add commits to existing)
    - In CI outside PR: Create PR if flag is set
    - Locally: Create PR only if flag is set, otherwise respect config default

    Args:
        ci_context: Detected CI context.
        create_pr_flag: User passed --pr flag.
        config_default: Default from .nit.yml (pick.create_pr_by_default).

    Returns:
        True if a new PR should be created.
    """
    # If already in a PR, never create a new one
    if ci_context.is_pr:
        return False

    # If user explicitly passed --pr flag, honor it (unless already in PR)
    if create_pr_flag:
        return True

    # Otherwise use config default (only for local runs)
    return not ci_context.is_ci and config_default


def get_git_working_branch(project_root: Path) -> str | None:
    """Get current git branch name from git command.

    Args:
        project_root: Project root directory.

    Returns:
        Branch name or None if not in git repo.
    """
    try:
        result = subprocess.run(
            [_git_executable(), "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
