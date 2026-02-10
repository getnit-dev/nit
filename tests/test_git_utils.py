"""Tests for git and GitHub API utilities."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from nit.utils.git import (
    GitHubAPI,
    GitHubAPIError,
    GitHubPRInfo,
    compute_comment_marker,
    get_pr_info_from_env,
    get_pr_info_from_git,
)


class TestGitHubAPI:
    """Tests for GitHubAPI class."""

    def test_init_with_token(self) -> None:
        """Test GitHubAPI initialization with explicit token."""
        api = GitHubAPI(token="test-token")  # noqa: S106
        assert api._token == "test-token"  # noqa: S105

    def test_init_from_env(self) -> None:
        """Test GitHubAPI initialization from environment variable."""
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "env-token"}):
            api = GitHubAPI()
            assert api._token == "env-token"  # noqa: S105

    def test_init_no_token_raises(self) -> None:
        """Test GitHubAPI initialization fails without token."""
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            pytest.raises(GitHubAPIError, match="GitHub token required"),
        ):
            GitHubAPI()

    @mock.patch("nit.utils.git.requests")
    def test_create_comment_success(self, mock_requests: mock.Mock) -> None:
        """Test creating a comment on a PR."""
        # Mock successful API response
        mock_response = mock.Mock()
        mock_response.json.return_value = {"id": 123, "html_url": "https://github.com/..."}
        mock_requests.post.return_value = mock_response

        api = GitHubAPI(token="test-token")  # noqa: S106
        pr_info = GitHubPRInfo(owner="test-owner", repo="test-repo", pr_number=42)

        result = api.create_comment(pr_info, "Test comment")

        assert result["id"] == 123
        assert "html_url" in result

        # Verify API call
        mock_requests.post.assert_called_once()
        call_args = mock_requests.post.call_args
        assert "test-owner/test-repo" in call_args[0][0]
        assert call_args[1]["json"]["body"] == "Test comment"

    @mock.patch("nit.utils.git.requests")
    def test_update_comment_success(self, mock_requests: mock.Mock) -> None:
        """Test updating an existing comment."""
        mock_response = mock.Mock()
        mock_response.json.return_value = {"id": 456, "html_url": "https://github.com/..."}
        mock_requests.patch.return_value = mock_response

        api = GitHubAPI(token="test-token")  # noqa: S106
        pr_info = GitHubPRInfo(owner="test-owner", repo="test-repo", pr_number=42)

        result = api.update_comment(pr_info, 456, "Updated comment")

        assert result["id"] == 456

        # Verify API call
        mock_requests.patch.assert_called_once()
        call_args = mock_requests.patch.call_args
        assert "456" in call_args[0][0]
        assert call_args[1]["json"]["body"] == "Updated comment"

    @mock.patch("nit.utils.git.requests")
    def test_find_comment_by_marker_found(self, mock_requests: mock.Mock) -> None:
        """Test finding a comment by marker."""
        mock_response = mock.Mock()
        mock_response.json.return_value = [
            {"id": 1, "body": "Other comment"},
            {"id": 2, "body": "<!-- marker:abc --> My comment"},
            {"id": 3, "body": "Another comment"},
        ]
        mock_requests.get.return_value = mock_response

        api = GitHubAPI(token="test-token")  # noqa: S106
        pr_info = GitHubPRInfo(owner="test-owner", repo="test-repo", pr_number=42)

        result = api.find_comment_by_marker(pr_info, "<!-- marker:abc -->")

        assert result is not None
        assert result["id"] == 2

    @mock.patch("nit.utils.git.requests")
    def test_find_comment_by_marker_not_found(self, mock_requests: mock.Mock) -> None:
        """Test finding a comment by marker when it doesn't exist."""
        mock_response = mock.Mock()
        mock_response.json.return_value = [
            {"id": 1, "body": "Other comment"},
            {"id": 3, "body": "Another comment"},
        ]
        mock_requests.get.return_value = mock_response

        api = GitHubAPI(token="test-token")  # noqa: S106
        pr_info = GitHubPRInfo(owner="test-owner", repo="test-repo", pr_number=42)

        result = api.find_comment_by_marker(pr_info, "<!-- marker:xyz -->")

        assert result is None

    @mock.patch("nit.utils.git.requests")
    def test_upsert_comment_creates_new(self, mock_requests: mock.Mock) -> None:
        """Test upsert creates a new comment when none exists."""
        # Mock no existing comments
        get_response = mock.Mock()
        get_response.json.return_value = []
        mock_requests.get.return_value = get_response

        # Mock successful create
        post_response = mock.Mock()
        post_response.json.return_value = {"id": 789, "html_url": "https://github.com/..."}
        mock_requests.post.return_value = post_response

        api = GitHubAPI(token="test-token")  # noqa: S106
        pr_info = GitHubPRInfo(owner="test-owner", repo="test-repo", pr_number=42)

        result = api.upsert_comment(
            pr_info, "<!-- marker:test --> New comment", "<!-- marker:test -->"
        )

        assert result["id"] == 789
        mock_requests.post.assert_called_once()
        mock_requests.patch.assert_not_called()

    @mock.patch("nit.utils.git.requests")
    def test_upsert_comment_updates_existing(self, mock_requests: mock.Mock) -> None:
        """Test upsert updates an existing comment."""
        # Mock existing comment found
        get_response = mock.Mock()
        get_response.json.return_value = [{"id": 999, "body": "<!-- marker:test --> Old comment"}]
        mock_requests.get.return_value = get_response

        # Mock successful update
        patch_response = mock.Mock()
        patch_response.json.return_value = {"id": 999, "html_url": "https://github.com/..."}
        mock_requests.patch.return_value = patch_response

        api = GitHubAPI(token="test-token")  # noqa: S106
        pr_info = GitHubPRInfo(owner="test-owner", repo="test-repo", pr_number=42)

        result = api.upsert_comment(
            pr_info, "<!-- marker:test --> Updated comment", "<!-- marker:test -->"
        )

        assert result["id"] == 999
        mock_requests.patch.assert_called_once()
        mock_requests.post.assert_not_called()

    @mock.patch("nit.utils.git.requests")
    def test_api_error_handling(self, mock_requests: mock.Mock) -> None:
        """Test API error handling."""
        mock_requests.post.side_effect = Exception("Network error")

        api = GitHubAPI(token="test-token")  # noqa: S106
        pr_info = GitHubPRInfo(owner="test-owner", repo="test-repo", pr_number=42)

        with pytest.raises(GitHubAPIError, match="POST request failed"):
            api.create_comment(pr_info, "Test")


class TestGetPRInfoFromEnv:
    """Tests for get_pr_info_from_env function."""

    def test_pr_context_detected(self) -> None:
        """Test PR info extraction from GitHub Actions environment."""
        env = {
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/pull/123/merge",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            pr_info = get_pr_info_from_env()

        assert pr_info is not None
        assert pr_info.owner == "owner"
        assert pr_info.repo == "repo"
        assert pr_info.pr_number == 123

    def test_non_pr_context_returns_none(self) -> None:
        """Test returns None when not in PR context."""
        env = {
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/main",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            pr_info = get_pr_info_from_env()

        assert pr_info is None

    def test_missing_env_vars_returns_none(self) -> None:
        """Test returns None when environment variables are missing."""
        with mock.patch.dict(os.environ, {}, clear=True):
            pr_info = get_pr_info_from_env()

        assert pr_info is None

    def test_invalid_ref_format_returns_none(self) -> None:
        """Test returns None when ref format is invalid."""
        env = {
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "invalid-ref",
        }

        with mock.patch.dict(os.environ, env, clear=True):
            pr_info = get_pr_info_from_env()

        assert pr_info is None


class TestGetPRInfoFromGit:
    """Tests for get_pr_info_from_git function."""

    @mock.patch("nit.utils.git.subprocess.run")
    def test_https_url_parsed(self, mock_run: mock.Mock, tmp_path: Path) -> None:
        """Test parsing GitHub info from HTTPS remote URL."""
        # Mock git config for remote URL
        url_result = mock.Mock()
        url_result.stdout = "https://github.com/owner/repo.git\n"
        url_result.returncode = 0

        # Mock git rev-parse for branch
        branch_result = mock.Mock()
        branch_result.stdout = "pr-456\n"
        branch_result.returncode = 0

        mock_run.side_effect = [url_result, branch_result]

        pr_info = get_pr_info_from_git(tmp_path)

        assert pr_info is not None
        assert pr_info.owner == "owner"
        assert pr_info.repo == "repo"
        assert pr_info.pr_number == 456

    @mock.patch("nit.utils.git.subprocess.run")
    def test_ssh_url_parsed(self, mock_run: mock.Mock, tmp_path: Path) -> None:
        """Test parsing GitHub info from SSH remote URL."""
        url_result = mock.Mock()
        url_result.stdout = "git@github.com:owner/repo.git\n"

        branch_result = mock.Mock()
        branch_result.stdout = "123-feature\n"

        mock_run.side_effect = [url_result, branch_result]

        pr_info = get_pr_info_from_git(tmp_path)

        assert pr_info is not None
        assert pr_info.owner == "owner"
        assert pr_info.repo == "repo"
        assert pr_info.pr_number == 123

    @mock.patch("nit.utils.git.subprocess.run")
    def test_no_pr_number_in_branch(self, mock_run: mock.Mock, tmp_path: Path) -> None:
        """Test returns None when branch doesn't contain PR number."""
        url_result = mock.Mock()
        url_result.stdout = "https://github.com/owner/repo.git\n"

        branch_result = mock.Mock()
        branch_result.stdout = "feature-branch\n"

        mock_run.side_effect = [url_result, branch_result]

        pr_info = get_pr_info_from_git(tmp_path)

        assert pr_info is None

    @mock.patch("nit.utils.git.subprocess.run")
    def test_git_command_fails(self, mock_run: mock.Mock, tmp_path: Path) -> None:
        """Test returns None when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        pr_info = get_pr_info_from_git(tmp_path)

        assert pr_info is None


class TestComputeCommentMarker:
    """Tests for compute_comment_marker function."""

    def test_marker_format(self) -> None:
        """Test marker has correct format."""
        marker = compute_comment_marker("nit:test")

        assert marker.startswith("<!-- nit:test:")
        assert marker.endswith(" -->")
        assert len(marker) > len("<!-- nit:test: -->")

    def test_marker_uniqueness(self) -> None:
        """Test different prefixes generate different markers."""
        marker1 = compute_comment_marker("nit:coverage")
        marker2 = compute_comment_marker("nit:tests")

        assert marker1 != marker2

    def test_marker_consistency(self) -> None:
        """Test same prefix always generates same marker."""
        marker1 = compute_comment_marker("nit:report")
        marker2 = compute_comment_marker("nit:report")

        assert marker1 == marker2
