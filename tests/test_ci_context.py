"""Tests for CI context detection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from nit.utils.ci_context import (
    CIContext,
    _parse_int,
    detect_ci_context,
    get_git_working_branch,
    should_create_pr,
)


def test_detect_github_actions_pr_context() -> None:
    """Test GitHub Actions PR context detection."""
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_PR_NUMBER": "123",
        "GITHUB_REF_NAME": "feature/test",
        "GITHUB_BASE_REF": "main",
        "GITHUB_SHA": "abc123def456",
        "GITHUB_REPOSITORY": "owner/repo",
    }

    with patch.dict(os.environ, env, clear=True):
        context = detect_ci_context()

        assert context.is_ci
        assert context.is_pr
        assert context.pr_number == 123
        assert context.branch == "feature/test"
        assert context.base_branch == "main"
        assert context.commit_sha == "abc123def456"
        assert context.repo_owner == "owner"
        assert context.repo_name == "repo"


def test_detect_github_actions_non_pr_context() -> None:
    """Test GitHub Actions non-PR (push) context."""
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF_NAME": "main",
        "GITHUB_SHA": "xyz789",
        "GITHUB_REPOSITORY": "owner/repo",
    }

    with patch.dict(os.environ, env, clear=True):
        context = detect_ci_context()

        assert context.is_ci
        assert not context.is_pr
        assert context.pr_number is None
        assert context.branch == "main"
        assert context.base_branch is None
        assert context.repo_owner == "owner"
        assert context.repo_name == "repo"


def test_detect_gitlab_ci_mr_context() -> None:
    """Test GitLab CI MR (merge request) context."""
    env = {
        "GITLAB_CI": "true",
        "CI_MERGE_REQUEST_ID": "789",
        "CI_MERGE_REQUEST_IID": "456",
        "CI_COMMIT_REF_NAME": "feature/gitlab",
        "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "develop",
        "CI_COMMIT_SHA": "gitlab123",
        "CI_PROJECT_NAME": "my-project",
    }

    with patch.dict(os.environ, env, clear=True):
        context = detect_ci_context()

        assert context.is_ci
        assert context.is_pr
        assert context.pr_number == 456
        assert context.branch == "feature/gitlab"
        assert context.base_branch == "develop"
        assert context.commit_sha == "gitlab123"
        assert context.repo_name == "my-project"


def test_detect_circleci_pr_context() -> None:
    """Test CircleCI PR context."""
    env = {
        "CIRCLECI": "true",
        "CIRCLE_PR_NUMBER": "999",
        "CIRCLE_BRANCH": "feature/circle",
        "CIRCLE_SHA1": "circle456",
        "CIRCLE_PROJECT_USERNAME": "circleowner",
        "CIRCLE_PROJECT_REPONAME": "circlerepo",
    }

    with patch.dict(os.environ, env, clear=True):
        context = detect_ci_context()

        assert context.is_ci
        assert context.is_pr
        assert context.pr_number == 999
        assert context.branch == "feature/circle"
        assert context.repo_owner == "circleowner"
        assert context.repo_name == "circlerepo"


def test_detect_generic_ci() -> None:
    """Test generic CI detection (CI=true but no specific provider)."""
    env = {"CI": "true"}

    with patch.dict(os.environ, env, clear=True):
        context = detect_ci_context()

        assert context.is_ci
        assert not context.is_pr
        assert context.pr_number is None
        assert context.branch is None


def test_detect_local_context() -> None:
    """Test local (non-CI) context detection."""
    with patch.dict(os.environ, {}, clear=True):
        context = detect_ci_context()

        assert not context.is_ci
        assert not context.is_pr
        assert context.pr_number is None


def test_should_create_pr_in_pr_context() -> None:
    """Test that PR is NOT created when already in a PR."""
    context = CIContext(
        is_ci=True,
        is_pr=True,
        pr_number=123,
        branch="feature/test",
        base_branch="main",
        commit_sha="abc123",
        repo_owner="owner",
        repo_name="repo",
    )

    # Even with flag set, should not create PR
    assert not should_create_pr(context, create_pr_flag=True)
    assert not should_create_pr(context, create_pr_flag=False)


def test_should_create_pr_in_ci_non_pr() -> None:
    """Test PR creation in CI but not in PR context."""
    context = CIContext(
        is_ci=True,
        is_pr=False,
        pr_number=None,
        branch="main",
        base_branch=None,
        commit_sha="abc123",
        repo_owner="owner",
        repo_name="repo",
    )

    # Should respect flag
    assert should_create_pr(context, create_pr_flag=True)
    assert not should_create_pr(context, create_pr_flag=False)


def test_should_create_pr_locally() -> None:
    """Test PR creation in local (non-CI) context."""
    context = CIContext(
        is_ci=False,
        is_pr=False,
        pr_number=None,
        branch=None,
        base_branch=None,
        commit_sha=None,
        repo_owner=None,
        repo_name=None,
    )

    # Should respect flag and config default
    assert should_create_pr(context, create_pr_flag=True, config_default=False)
    assert should_create_pr(context, create_pr_flag=True, config_default=True)
    assert not should_create_pr(context, create_pr_flag=False, config_default=False)
    assert should_create_pr(context, create_pr_flag=False, config_default=True)


def test_should_create_pr_config_only_affects_local() -> None:
    """Test that config default only affects local runs."""
    ci_context = CIContext(
        is_ci=True,
        is_pr=False,
        pr_number=None,
        branch="main",
        base_branch=None,
        commit_sha="abc123",
        repo_owner="owner",
        repo_name="repo",
    )

    # Config default should NOT affect CI runs
    assert not should_create_pr(ci_context, create_pr_flag=False, config_default=True)


def test_parse_int_invalid() -> None:
    """Test parsing invalid integer strings."""
    assert _parse_int(None) is None
    assert _parse_int("") is None
    assert _parse_int("not-a-number") is None
    assert _parse_int("123") == 123
    assert _parse_int("0") == 0


def test_get_git_working_branch_success(tmp_path: Path) -> None:
    """Test getting current git branch."""
    # Create a git repo
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    # Create initial commit so we can checkout
    (tmp_path / "test.txt").write_text("test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "checkout", "-b", "test-branch"], cwd=tmp_path, check=True, capture_output=True
    )

    branch = get_git_working_branch(tmp_path)
    assert branch == "test-branch"


def test_get_git_working_branch_not_a_repo(tmp_path: Path) -> None:
    """Test getting git branch when not in a git repo."""
    branch = get_git_working_branch(tmp_path)
    assert branch is None


def test_circleci_pr_from_pull_request_url() -> None:
    """Test extracting PR number from CircleCI CIRCLE_PULL_REQUEST URL."""
    env = {
        "CIRCLECI": "true",
        "CIRCLE_PULL_REQUEST": "https://github.com/owner/repo/pull/555",
        "CIRCLE_BRANCH": "feature/test",
        "CIRCLE_SHA1": "abc123",
        "CIRCLE_PROJECT_USERNAME": "owner",
        "CIRCLE_PROJECT_REPONAME": "repo",
    }

    with patch.dict(os.environ, env, clear=True):
        context = detect_ci_context()

        assert context.is_ci
        assert context.is_pr
        assert context.pr_number == 555


def test_github_repository_parsing_edge_cases() -> None:
    """Test GitHub repository parsing with edge cases."""
    # Valid format
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REPOSITORY": "owner/repo",
    }

    with patch.dict(os.environ, env, clear=True):
        context = detect_ci_context()
        assert context.repo_owner == "owner"
        assert context.repo_name == "repo"

    # Invalid format (no slash)
    env["GITHUB_REPOSITORY"] = "invalid"
    with patch.dict(os.environ, env, clear=True):
        context = detect_ci_context()
        assert context.repo_owner is None
        assert context.repo_name is None

    # Empty
    env["GITHUB_REPOSITORY"] = ""
    with patch.dict(os.environ, env, clear=True):
        context = detect_ci_context()
        assert context.repo_owner is None
        assert context.repo_name is None
