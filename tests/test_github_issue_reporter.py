"""Tests for GitHub issue reporter."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest import mock

import pytest

from nit.agents.analyzers.bug import (
    BugLocation,
    BugReport,
    BugSeverity,
    BugType,
)
from nit.agents.debuggers.fix_gen import GeneratedFix
from nit.agents.debuggers.root_cause import RootCause
from nit.agents.reporters.github_issue import (
    BugIssueData,
    GitHubIssueReporter,
)
from nit.utils.git import GitHubAPIError

# Get absolute path to git executable for security
GIT_PATH = shutil.which("git") or "git"


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository."""
    import subprocess  # noqa: PLC0415

    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Set up remote
    subprocess.run(
        [
            GIT_PATH,
            "remote",
            "add",
            "origin",
            "https://github.com/test-owner/test-repo.git",
        ],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repo")
    subprocess.run([GIT_PATH, "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    return repo_path


@pytest.fixture
def sample_bug_report() -> BugReport:
    """Create a sample bug report."""
    return BugReport(
        bug_type=BugType.NULL_DEREFERENCE,
        severity=BugSeverity.HIGH,
        title="Null Dereference in getUserData",
        description=(
            "Attempting to access a property on a null value.\n\n"
            "Error: Cannot read property 'name' of null"
        ),
        location=BugLocation(
            file_path="src/user.ts",
            line_number=42,
            function_name="getUserData",
            code_snippet="return user.name;",
        ),
        error_message="Cannot read property 'name' of null",
        stack_trace=(
            "TypeError: Cannot read property 'name' of null\n"
            "  at getUserData (src/user.ts:42:15)"
        ),
        reproduction_steps=[
            "Call getUserData with invalid ID",
            "Function returns null",
            "Access .name property",
        ],
        is_code_bug=True,
        confidence=0.95,
    )


@pytest.fixture
def sample_root_cause() -> RootCause:
    """Create a sample root cause analysis."""
    return RootCause(
        category="missing_validation",
        description=(
            "The function does not validate that the user exists "
            "before accessing its properties."
        ),
        affected_code="return user.name;",
        missing_checks=["Check if user is null before accessing properties"],
        incorrect_assumptions=["Assumed user would always be found"],
        confidence=0.9,
    )


@pytest.fixture
def sample_fix() -> GeneratedFix:
    """Create a sample generated fix."""
    return GeneratedFix(
        fixed_code="if (!user) {\n  return null;\n}\nreturn user.name;",
        patch="@@ -40,1 +40,4 @@\n+if (!user) {\n+  return null;\n+}\n return user.name;",
        explanation=(
            "Added null check before accessing user.name property to prevent null dereference."
        ),
        changed_lines=[40, 41, 42],
        safety_notes=["This changes the function signature - callers must now handle null return"],
        confidence=0.85,
    )


@pytest.fixture
def sample_issue_data(
    sample_bug_report: BugReport,
    sample_root_cause: RootCause,
    sample_fix: GeneratedFix,
) -> BugIssueData:
    """Create sample bug issue data."""
    return BugIssueData(
        bug_report=sample_bug_report,
        root_cause=sample_root_cause,
        generated_fix=sample_fix,
        reproduction_test=(
            'test("reproduce null dereference", () => {\n'
            "  const result = getUserData(-1);\n"
            "  expect(result).not.toThrow();\n"
            "});"
        ),
        pr_url="https://github.com/test-owner/test-repo/pull/42",
        pr_number=42,
    )


class TestGitHubIssueReporter:
    """Tests for GitHubIssueReporter class."""

    @mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_issue.get_remote_url")
    def test_init_with_gh_cli(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        """Test reporter initialization with gh CLI available."""
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"

        reporter = GitHubIssueReporter(temp_repo)

        assert reporter._use_gh_cli is True
        assert reporter._api is None
        assert reporter._owner == "test-owner"
        assert reporter._repo == "test-repo"

    @mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_issue.GitHubAPI")
    @mock.patch("nit.agents.reporters.github_issue.get_remote_url")
    def test_init_without_gh_cli(
        self,
        mock_get_remote: mock.Mock,
        mock_api_class: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test reporter initialization without gh CLI."""
        mock_gh_available.return_value = False
        mock_get_remote.return_value = "git@github.com:test-owner/test-repo.git"
        expected_gh_value = "ghp_testtoken123"
        monkeypatch.setenv("GITHUB_TOKEN", expected_gh_value)

        reporter = GitHubIssueReporter(temp_repo)

        assert reporter._use_gh_cli is False
        assert reporter._api is not None
        assert reporter._owner == "test-owner"
        assert reporter._repo == "test-repo"
        mock_api_class.assert_called_once()
        actual = mock_api_class.call_args.kwargs["token"]
        assert actual == expected_gh_value

    @mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_issue.get_remote_url")
    def test_init_invalid_remote_warning(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        """Test reporter initialization with invalid remote URL logs warning."""
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://gitlab.com/owner/repo.git"

        # Should not raise, just log warning
        reporter = GitHubIssueReporter(temp_repo)
        assert reporter._owner is None
        assert reporter._repo is None

    def test_generate_issue_title(self, temp_repo: Path, sample_bug_report: BugReport) -> None:
        """Test issue title generation."""
        with (
            mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_issue.get_remote_url",
                return_value="https://github.com/test/repo.git",
            ),
        ):
            reporter = GitHubIssueReporter(temp_repo)
            title = reporter._generate_issue_title(sample_bug_report)

            assert "🟠" in title  # HIGH severity emoji
            assert "Null Dereference in getUserData" in title

    def test_generate_issue_title_critical(
        self, temp_repo: Path, sample_bug_report: BugReport
    ) -> None:
        """Test issue title generation for critical bug."""
        sample_bug_report.severity = BugSeverity.CRITICAL

        with (
            mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_issue.get_remote_url",
                return_value="https://github.com/test/repo.git",
            ),
        ):
            reporter = GitHubIssueReporter(temp_repo)
            title = reporter._generate_issue_title(sample_bug_report)

            assert "🔴" in title  # CRITICAL severity emoji

    def test_generate_labels(self, temp_repo: Path, sample_bug_report: BugReport) -> None:
        """Test label generation."""
        with (
            mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_issue.get_remote_url",
                return_value="https://github.com/test/repo.git",
            ),
        ):
            reporter = GitHubIssueReporter(temp_repo)
            labels = reporter._generate_labels(sample_bug_report)

            assert "bug" in labels
            assert "severity:high" in labels
            assert "type:null_dereference" in labels
            assert "nit:detected" in labels

    def test_generate_issue_body_minimal(
        self, temp_repo: Path, sample_bug_report: BugReport
    ) -> None:
        """Test issue body generation with minimal data."""
        issue_data = BugIssueData(bug_report=sample_bug_report)

        with (
            mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_issue.get_remote_url",
                return_value="https://github.com/test/repo.git",
            ),
        ):
            reporter = GitHubIssueReporter(temp_repo)
            body = reporter._generate_issue_body(issue_data)

            # Check all required sections
            assert "## 🐛 Bug Report" in body
            assert "### Details" in body
            assert "### Location" in body
            assert "### Error Message" in body
            assert "`src/user.ts`" in body
            assert "Cannot read property 'name' of null" in body
            assert "🤖 Detected and reported by [nit]" in body

    def test_generate_issue_body_complete(
        self, temp_repo: Path, sample_issue_data: BugIssueData
    ) -> None:
        """Test issue body generation with all data."""
        with (
            mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_issue.get_remote_url",
                return_value="https://github.com/test/repo.git",
            ),
        ):
            reporter = GitHubIssueReporter(temp_repo)
            body = reporter._generate_issue_body(sample_issue_data)

            # Check all sections are present
            assert "## 🐛 Bug Report" in body
            assert "### Details" in body
            assert "### Location" in body
            assert "### Error Message" in body
            assert "### Reproduction" in body
            assert "### Root Cause Analysis" in body
            assert "### Suggested Fix" in body
            assert "### Fix Available in #42" in body

            # Check specific content
            assert "missing validation" in body.lower()
            assert "Added null check" in body
            assert "https://github.com/test-owner/test-repo/pull/42" in body

    @mock.patch("nit.agents.reporters.github_issue.subprocess.run")
    @mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_issue.get_remote_url")
    def test_create_issue_with_gh_cli(
        self,
        mock_get_remote: mock.Mock,
        mock_gh_available: mock.Mock,
        mock_subprocess: mock.Mock,
        temp_repo: Path,
        sample_issue_data: BugIssueData,
    ) -> None:
        """Test issue creation using gh CLI."""
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"
        mock_subprocess.return_value = mock.Mock(
            stdout="https://github.com/test-owner/test-repo/issues/123\n",
            returncode=0,
        )

        reporter = GitHubIssueReporter(temp_repo)
        result = reporter.create_bug_issue(sample_issue_data)

        assert result.success is True
        assert result.issue_url == "https://github.com/test-owner/test-repo/issues/123"
        assert result.issue_number == 123
        assert result.error is None

        # Verify gh CLI was called correctly
        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args
        assert call_args[0][0][0].endswith("gh")
        assert call_args[0][0][1] == "issue"
        assert call_args[0][0][2] == "create"
        assert "--label" in call_args[0][0]

    @mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_issue.GitHubAPI")
    @mock.patch("nit.agents.reporters.github_issue.get_remote_url")
    @mock.patch.object(GitHubIssueReporter, "_create_issue_with_api")
    def test_create_issue_with_api(
        self,
        mock_create_api: mock.Mock,
        mock_get_remote: mock.Mock,
        mock_api_class: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
        sample_issue_data: BugIssueData,
    ) -> None:
        """Test issue creation using GitHub API."""
        mock_gh_available.return_value = False
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"
        mock_create_api.return_value = mock.Mock(
            success=True,
            issue_url="https://github.com/test-owner/test-repo/issues/456",
            issue_number=456,
        )

        reporter = GitHubIssueReporter(temp_repo)
        result = reporter.create_bug_issue(sample_issue_data)

        assert result.success is True
        mock_create_api.assert_called_once()

    @mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_issue.GitHubAPI")
    @mock.patch("nit.agents.reporters.github_issue.get_remote_url")
    def test_create_issue_with_api_integration(
        self,
        mock_get_remote: mock.Mock,
        mock_api_class: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
        sample_issue_data: BugIssueData,
    ) -> None:
        """Test issue creation with mocked API calls."""
        mock_gh_available.return_value = False
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"

        mock_api = mock.Mock()
        mock_api.create_issue.return_value = {
            "html_url": "https://github.com/test-owner/test-repo/issues/789",
            "number": 789,
        }
        mock_api_class.return_value = mock_api

        reporter = GitHubIssueReporter(temp_repo)
        result = reporter.create_bug_issue(sample_issue_data)

        assert result.success is True
        assert result.issue_number == 789
        mock_api.create_issue.assert_called_once()

    @mock.patch("nit.agents.reporters.github_issue.subprocess.run")
    @mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_issue.get_remote_url")
    def test_link_issue_to_pr_gh_cli(
        self,
        mock_get_remote: mock.Mock,
        mock_gh_available: mock.Mock,
        mock_subprocess: mock.Mock,
        temp_repo: Path,
    ) -> None:
        """Test linking issue to PR using gh CLI."""
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"
        mock_subprocess.return_value = mock.Mock(stdout="", returncode=0)

        reporter = GitHubIssueReporter(temp_repo)
        success = reporter.link_issue_to_pr(
            issue_number=123,
            pr_number=456,
            pr_url="https://github.com/test-owner/test-repo/pull/456",
        )

        assert success is True
        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args
        assert call_args[0][0][0].endswith("gh")
        assert call_args[0][0][1] == "issue"
        assert call_args[0][0][2] == "comment"
        assert "123" in call_args[0][0]

    @mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_issue.GitHubAPI")
    @mock.patch("nit.agents.reporters.github_issue.get_remote_url")
    def test_link_issue_to_pr_api(
        self,
        mock_get_remote: mock.Mock,
        mock_api_class: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
    ) -> None:
        """Test linking issue to PR using GitHub API."""
        mock_gh_available.return_value = False
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"

        mock_api = mock.Mock()
        mock_api.create_issue_comment.return_value = {"id": 12345}
        mock_api_class.return_value = mock_api

        reporter = GitHubIssueReporter(temp_repo)
        success = reporter.link_issue_to_pr(
            issue_number=123,
            pr_number=456,
            pr_url="https://github.com/test-owner/test-repo/pull/456",
        )

        assert success is True
        mock_api.create_issue_comment.assert_called_once_with(
            owner="test-owner",
            repo="test-repo",
            issue_number=123,
            body=mock.ANY,
        )

    @mock.patch("nit.agents.reporters.github_issue.subprocess.run")
    @mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_issue.get_remote_url")
    def test_create_issue_gh_cli_failure(
        self,
        mock_get_remote: mock.Mock,
        mock_gh_available: mock.Mock,
        mock_subprocess: mock.Mock,
        temp_repo: Path,
        sample_issue_data: BugIssueData,
    ) -> None:
        """Test issue creation failure with gh CLI."""
        import subprocess  # noqa: PLC0415

        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"
        mock_subprocess.side_effect = subprocess.CalledProcessError(
            1, ["gh", "issue", "create"], stderr="Error creating issue"
        )

        reporter = GitHubIssueReporter(temp_repo)
        result = reporter.create_bug_issue(sample_issue_data)

        assert result.success is False
        assert result.error is not None

    @mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_issue.GitHubAPI")
    @mock.patch("nit.agents.reporters.github_issue.get_remote_url")
    def test_create_issue_api_failure(
        self,
        mock_get_remote: mock.Mock,
        mock_api_class: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
        sample_issue_data: BugIssueData,
    ) -> None:
        """Test issue creation failure with GitHub API."""
        mock_gh_available.return_value = False
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"

        mock_api = mock.Mock()
        mock_api.create_issue.side_effect = GitHubAPIError("API error")
        mock_api_class.return_value = mock_api

        reporter = GitHubIssueReporter(temp_repo)
        result = reporter.create_bug_issue(sample_issue_data)

        assert result.success is False
        assert "API error" in str(result.error)

    def test_generate_pr_link_comment(self, temp_repo: Path) -> None:
        """Test PR link comment generation."""
        with (
            mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_issue.get_remote_url",
                return_value="https://github.com/test/repo.git",
            ),
        ):
            reporter = GitHubIssueReporter(temp_repo)
            comment = reporter._generate_pr_link_comment(42, "https://github.com/test/repo/pull/42")

            assert "🔧" in comment
            assert "#42" in comment
            assert "https://github.com/test/repo/pull/42" in comment

    def test_parse_github_url_https(self, temp_repo: Path) -> None:
        """Test parsing HTTPS GitHub URL."""
        with (
            mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_issue.get_remote_url",
                return_value="https://github.com/owner/repo.git",
            ),
        ):
            reporter = GitHubIssueReporter(temp_repo)
            owner, repo = reporter._parse_github_url("https://github.com/owner/repo.git")

            assert owner == "owner"
            assert repo == "repo"

    def test_parse_github_url_ssh(self, temp_repo: Path) -> None:
        """Test parsing SSH GitHub URL."""
        with (
            mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_issue.get_remote_url",
                return_value="git@github.com:owner/repo.git",
            ),
        ):
            reporter = GitHubIssueReporter(temp_repo)
            owner, repo = reporter._parse_github_url("git@github.com:owner/repo.git")

            assert owner == "owner"
            assert repo == "repo"

    def test_parse_github_url_invalid(self, temp_repo: Path) -> None:
        """Test parsing invalid GitHub URL."""
        with (
            mock.patch("nit.agents.reporters.github_issue.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_issue.get_remote_url",
                return_value="https://github.com/owner/repo.git",
            ),
        ):
            reporter = GitHubIssueReporter(temp_repo)
            owner, repo = reporter._parse_github_url("https://invalid.com/foo/bar")

            assert owner is None
            assert repo is None
