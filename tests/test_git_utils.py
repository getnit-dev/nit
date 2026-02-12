"""Tests for git and GitHub API utilities."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from nit.utils.git import (
    CommitInfo,
    GitHubAPI,
    GitHubAPIError,
    GitHubPRInfo,
    GitOperationError,
    PullRequestParams,
    _extract_pr_number_from_branch,
    _parse_github_url,
    add_files,
    commit,
    compute_comment_marker,
    create_branch,
    get_commits_between,
    get_current_branch,
    get_default_branch,
    get_pr_info_from_env,
    get_pr_info_from_git,
    get_remote_url,
    is_gh_cli_available,
    push_branch,
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


# ---------------------------------------------------------------------------
# _parse_github_url
# ---------------------------------------------------------------------------


class TestParseGitHubUrl:
    def test_https_url(self) -> None:
        owner, repo = _parse_github_url("https://github.com/foo/bar.git")
        assert owner == "foo"
        assert repo == "bar"

    def test_https_url_no_git_suffix(self) -> None:
        owner, repo = _parse_github_url("https://github.com/foo/bar")
        assert owner == "foo"
        assert repo == "bar"

    def test_ssh_url(self) -> None:
        owner, repo = _parse_github_url("git@github.com:foo/bar.git")
        assert owner == "foo"
        assert repo == "bar"

    def test_ssh_url_no_git_suffix(self) -> None:
        owner, repo = _parse_github_url("git@github.com:foo/bar")
        assert owner == "foo"
        assert repo == "bar"

    def test_non_github_url(self) -> None:
        owner, repo = _parse_github_url("https://gitlab.com/foo/bar.git")
        assert owner is None
        assert repo is None


# ---------------------------------------------------------------------------
# _extract_pr_number_from_branch
# ---------------------------------------------------------------------------


class TestExtractPRNumber:
    def test_pr_dash_pattern(self) -> None:
        assert _extract_pr_number_from_branch("pr-42") == 42

    def test_pr_slash_pattern(self) -> None:
        assert _extract_pr_number_from_branch("pr/123") == 123

    def test_number_dash_pattern(self) -> None:
        assert _extract_pr_number_from_branch("99-feature") == 99

    def test_no_number(self) -> None:
        assert _extract_pr_number_from_branch("feature-branch") is None

    def test_main_branch(self) -> None:
        assert _extract_pr_number_from_branch("main") is None


# ---------------------------------------------------------------------------
# is_gh_cli_available
# ---------------------------------------------------------------------------


class TestIsGhCliAvailable:
    @mock.patch("nit.utils.git.subprocess.run")
    def test_gh_available_and_authed(self, mock_run: mock.Mock) -> None:
        mock_run.return_value = mock.Mock(returncode=0)
        assert is_gh_cli_available() is True

    @mock.patch("nit.utils.git.subprocess.run")
    def test_gh_not_installed(self, mock_run: mock.Mock) -> None:
        mock_run.return_value = mock.Mock(returncode=1)
        assert is_gh_cli_available() is False

    @mock.patch("nit.utils.git.subprocess.run")
    def test_gh_not_found(self, mock_run: mock.Mock) -> None:
        mock_run.side_effect = FileNotFoundError("gh not found")
        assert is_gh_cli_available() is False

    @mock.patch("nit.utils.git.subprocess.run")
    def test_gh_installed_not_authed(self, mock_run: mock.Mock) -> None:
        # First call (--version) succeeds, second call (auth status) fails
        mock_run.side_effect = [
            mock.Mock(returncode=0),
            mock.Mock(returncode=1),
        ]
        assert is_gh_cli_available() is False


# ---------------------------------------------------------------------------
# get_commits_between
# ---------------------------------------------------------------------------


class TestGetCommitsBetween:
    @mock.patch("nit.utils.git.subprocess.run")
    def test_commits_parsed(self, mock_run: mock.Mock) -> None:
        mock_run.return_value = mock.Mock(
            stdout=(
                "abc123\nFirst commit\nbody text\n---COMMIT_END---\n"
                "def456\nSecond commit\n\n---COMMIT_END---\n"
            )
        )
        commits = get_commits_between(Path("/repo"), "v1.0", "HEAD")
        assert len(commits) == 2
        assert commits[0].sha == "abc123"
        assert commits[0].subject == "First commit"
        assert commits[0].body == "body text"
        assert commits[1].sha == "def456"
        assert commits[1].subject == "Second commit"

    @mock.patch("nit.utils.git.subprocess.run")
    def test_empty_output(self, mock_run: mock.Mock) -> None:
        mock_run.return_value = mock.Mock(stdout="")
        commits = get_commits_between(Path("/repo"), "v1.0", "HEAD")
        assert commits == []

    @mock.patch("nit.utils.git.subprocess.run")
    def test_git_error(self, mock_run: mock.Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        with pytest.raises(GitOperationError, match="Failed to get commits"):
            get_commits_between(Path("/repo"), "v1.0", "HEAD")

    def test_invalid_ref_newline(self) -> None:
        with pytest.raises(GitOperationError, match="unsafe characters"):
            get_commits_between(Path("/repo"), "v1\n.0", "HEAD")

    def test_invalid_ref_null(self) -> None:
        with pytest.raises(GitOperationError, match="unsafe characters"):
            get_commits_between(Path("/repo"), "v1.0", "HEAD\0")


# ---------------------------------------------------------------------------
# get_default_branch
# ---------------------------------------------------------------------------


class TestGetDefaultBranch:
    @mock.patch("nit.utils.git.subprocess.run")
    def test_symbolic_ref_success(self, mock_run: mock.Mock) -> None:
        mock_run.return_value = mock.Mock(stdout="refs/remotes/origin/main\n")
        assert get_default_branch(Path("/repo")) == "main"

    @mock.patch("nit.utils.git.subprocess.run")
    def test_fallback_main(self, mock_run: mock.Mock) -> None:
        # symbolic-ref fails, rev-parse for "main" succeeds
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git"),
            mock.Mock(returncode=0),
        ]
        assert get_default_branch(Path("/repo")) == "main"

    @mock.patch("nit.utils.git.subprocess.run")
    def test_fallback_master(self, mock_run: mock.Mock) -> None:
        # symbolic-ref fails, "main" fails, "master" succeeds
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git"),
            subprocess.CalledProcessError(1, "git"),
            mock.Mock(returncode=0),
        ]
        assert get_default_branch(Path("/repo")) == "master"

    @mock.patch("nit.utils.git.subprocess.run")
    def test_fallback_default(self, mock_run: mock.Mock) -> None:
        # Everything fails, defaults to "main"
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert get_default_branch(Path("/repo")) == "main"


# ---------------------------------------------------------------------------
# get_current_branch
# ---------------------------------------------------------------------------


class TestGetCurrentBranch:
    @mock.patch("nit.utils.git.subprocess.run")
    def test_success(self, mock_run: mock.Mock) -> None:
        mock_run.return_value = mock.Mock(stdout="feature-branch\n")
        assert get_current_branch(Path("/repo")) == "feature-branch"

    @mock.patch("nit.utils.git.subprocess.run")
    def test_failure(self, mock_run: mock.Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        with pytest.raises(GitOperationError, match="Failed to get current branch"):
            get_current_branch(Path("/repo"))


# ---------------------------------------------------------------------------
# create_branch
# ---------------------------------------------------------------------------


class TestCreateBranch:
    @mock.patch("nit.utils.git.subprocess.run")
    def test_create_branch_no_base(self, mock_run: mock.Mock) -> None:
        create_branch(Path("/repo"), "new-branch")
        cmd = mock_run.call_args[0][0]
        assert "checkout" in cmd
        assert "-b" in cmd
        assert "new-branch" in cmd

    @mock.patch("nit.utils.git.subprocess.run")
    def test_create_branch_with_base(self, mock_run: mock.Mock) -> None:
        create_branch(Path("/repo"), "new-branch", base="main")
        cmd = mock_run.call_args[0][0]
        assert "main" in cmd

    @mock.patch("nit.utils.git.subprocess.run")
    def test_create_branch_failure(self, mock_run: mock.Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        with pytest.raises(GitOperationError, match="Failed to create branch"):
            create_branch(Path("/repo"), "bad-branch")


# ---------------------------------------------------------------------------
# add_files
# ---------------------------------------------------------------------------


class TestAddFiles:
    @mock.patch("nit.utils.git.subprocess.run")
    def test_add_files(self, mock_run: mock.Mock) -> None:
        add_files(Path("/repo"), ["file1.py", "file2.py"])
        cmd = mock_run.call_args[0][0]
        assert "add" in cmd
        assert "file1.py" in cmd

    @mock.patch("nit.utils.git.subprocess.run")
    def test_add_files_failure(self, mock_run: mock.Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        with pytest.raises(GitOperationError, match="Failed to add files"):
            add_files(Path("/repo"), ["file.py"])


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


class TestCommit:
    @mock.patch("nit.utils.git.subprocess.run")
    def test_commit_success(self, mock_run: mock.Mock) -> None:
        mock_run.side_effect = [
            mock.Mock(),  # git commit
            mock.Mock(stdout="abc123\n"),  # git rev-parse HEAD
        ]
        sha = commit(Path("/repo"), "test message")
        assert sha == "abc123"

    @mock.patch("nit.utils.git.subprocess.run")
    def test_commit_failure(self, mock_run: mock.Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        with pytest.raises(GitOperationError, match="Failed to commit"):
            commit(Path("/repo"), "msg")


# ---------------------------------------------------------------------------
# push_branch
# ---------------------------------------------------------------------------


class TestPushBranch:
    @mock.patch("nit.utils.git.subprocess.run")
    def test_push_branch(self, mock_run: mock.Mock) -> None:
        push_branch(Path("/repo"), "feature")
        cmd = mock_run.call_args[0][0]
        assert "push" in cmd
        assert "feature" in cmd
        assert "--force" not in cmd

    @mock.patch("nit.utils.git.subprocess.run")
    def test_push_branch_force(self, mock_run: mock.Mock) -> None:
        push_branch(Path("/repo"), "feature", force=True)
        cmd = mock_run.call_args[0][0]
        assert "--force" in cmd

    @mock.patch("nit.utils.git.subprocess.run")
    def test_push_branch_failure(self, mock_run: mock.Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        with pytest.raises(GitOperationError, match="Failed to push branch"):
            push_branch(Path("/repo"), "feature")


# ---------------------------------------------------------------------------
# get_remote_url
# ---------------------------------------------------------------------------


class TestGetRemoteUrl:
    @mock.patch("nit.utils.git.subprocess.run")
    def test_success(self, mock_run: mock.Mock) -> None:
        mock_run.return_value = mock.Mock(stdout="https://github.com/foo/bar.git\n")
        url = get_remote_url(Path("/repo"))
        assert url == "https://github.com/foo/bar.git"

    @mock.patch("nit.utils.git.subprocess.run")
    def test_failure(self, mock_run: mock.Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        with pytest.raises(GitOperationError, match="Failed to get remote URL"):
            get_remote_url(Path("/repo"))


# ---------------------------------------------------------------------------
# GitHubAPI — extended tests
# ---------------------------------------------------------------------------


class TestGitHubAPIExtended:
    @mock.patch("nit.utils.git.requests")
    def test_create_pull_request(self, mock_requests: mock.Mock) -> None:
        mock_response = mock.Mock()
        mock_response.json.return_value = {
            "number": 42,
            "html_url": "https://github.com/...",
        }
        mock_requests.post.return_value = mock_response

        api = GitHubAPI(token="test-token")  # noqa: S106
        params = PullRequestParams(
            owner="o",
            repo="r",
            title="My PR",
            body="desc",
            head="feature",
            base="main",
        )
        result = api.create_pull_request(params)
        assert result["number"] == 42

    @mock.patch("nit.utils.git.requests")
    def test_create_issue(self, mock_requests: mock.Mock) -> None:
        mock_response = mock.Mock()
        mock_response.json.return_value = {"number": 1}
        mock_requests.post.return_value = mock_response

        api = GitHubAPI(token="test-token")  # noqa: S106
        result = api.create_issue("o", "r", "title", "body", labels=["bug"])
        assert result["number"] == 1

    @mock.patch("nit.utils.git.requests")
    def test_create_issue_no_labels(self, mock_requests: mock.Mock) -> None:
        mock_response = mock.Mock()
        mock_response.json.return_value = {"number": 2}
        mock_requests.post.return_value = mock_response

        api = GitHubAPI(token="test-token")  # noqa: S106
        result = api.create_issue("o", "r", "title", "body")
        assert result["number"] == 2

    @mock.patch("nit.utils.git.requests")
    def test_create_issue_comment(self, mock_requests: mock.Mock) -> None:
        mock_response = mock.Mock()
        mock_response.json.return_value = {"id": 77}
        mock_requests.post.return_value = mock_response

        api = GitHubAPI(token="test-token")  # noqa: S106
        result = api.create_issue_comment("o", "r", 5, "comment text")
        assert result["id"] == 77

    @mock.patch("nit.utils.git.requests")
    def test_get_error(self, mock_requests: mock.Mock) -> None:
        mock_requests.get.side_effect = Exception("timeout")
        api = GitHubAPI(token="test-token")  # noqa: S106
        pr = GitHubPRInfo(owner="o", repo="r", pr_number=1)
        with pytest.raises(GitHubAPIError, match="GET request failed"):
            api.find_comment_by_marker(pr, "marker")

    @mock.patch("nit.utils.git.requests")
    def test_patch_error(self, mock_requests: mock.Mock) -> None:
        mock_requests.patch.side_effect = Exception("timeout")
        api = GitHubAPI(token="test-token")  # noqa: S106
        pr = GitHubPRInfo(owner="o", repo="r", pr_number=1)
        with pytest.raises(GitHubAPIError, match="PATCH request failed"):
            api.update_comment(pr, 1, "body")

    @mock.patch("nit.utils.git.requests")
    def test_upsert_adds_marker(self, mock_requests: mock.Mock) -> None:
        """upsert_comment adds marker to body if missing."""
        get_resp = mock.Mock()
        get_resp.json.return_value = []
        mock_requests.get.return_value = get_resp

        post_resp = mock.Mock()
        post_resp.json.return_value = {"id": 1}
        mock_requests.post.return_value = post_resp

        api = GitHubAPI(token="test-token")  # noqa: S106
        pr = GitHubPRInfo(owner="o", repo="r", pr_number=1)
        result = api.upsert_comment(pr, "body without marker", "<!-- mark -->")
        assert result["id"] == 1
        # The marker should have been prepended
        call_body = mock_requests.post.call_args[1]["json"]["body"]
        assert "<!-- mark -->" in call_body


# ---------------------------------------------------------------------------
# get_pr_info_from_env — extended edge cases
# ---------------------------------------------------------------------------


class TestGetPRInfoFromEnvExtended:
    def test_invalid_repository_format(self) -> None:
        env = {
            "GITHUB_REPOSITORY": "invalid",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/pull/1/merge",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            assert get_pr_info_from_env() is None

    def test_ref_without_pull_prefix(self) -> None:
        env = {
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/heads/main",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            assert get_pr_info_from_env() is None

    def test_ref_with_bad_pr_number(self) -> None:
        env = {
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": "refs/pull/not-a-number/merge",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            assert get_pr_info_from_env() is None


# ---------------------------------------------------------------------------
# CommitInfo dataclass
# ---------------------------------------------------------------------------


class TestCommitInfo:
    def test_commit_info_creation(self) -> None:
        ci = CommitInfo(sha="abc", subject="msg", body="details")
        assert ci.sha == "abc"
        assert ci.subject == "msg"
        assert ci.body == "details"
