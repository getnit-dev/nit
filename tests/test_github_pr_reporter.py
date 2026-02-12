"""Tests for GitHub PR reporter."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from nit.agents.analyzers.bug import BugLocation, BugReport, BugSeverity, BugType
from nit.agents.debuggers.fix_gen import GeneratedFix
from nit.agents.reporters.github_pr import (
    GenerationSummary,
    GitHubPRReporter,
)
from nit.models.coverage import CoverageReport, PackageCoverage
from nit.utils.git import GitHubAPIError, GitOperationError

# Get absolute path to git executable for security
GIT_PATH = shutil.which("git") or "git"


@pytest.fixture
def temp_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository."""
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
def sample_coverage_before() -> CoverageReport:
    """Create sample coverage report (before)."""
    return CoverageReport(
        packages={
            "web": PackageCoverage(
                name="web",
                line_coverage=0.65,
                function_coverage=0.70,
                branch_coverage=0.60,
            ),
        },
        overall_line_coverage=0.65,
        overall_function_coverage=0.70,
        overall_branch_coverage=0.60,
    )


@pytest.fixture
def sample_coverage_after() -> CoverageReport:
    """Create sample coverage report (after)."""
    return CoverageReport(
        packages={
            "web": PackageCoverage(
                name="web",
                line_coverage=0.80,
                function_coverage=0.85,
                branch_coverage=0.75,
            ),
        },
        overall_line_coverage=0.80,
        overall_function_coverage=0.85,
        overall_branch_coverage=0.75,
    )


@pytest.fixture
def sample_summary(
    sample_coverage_before: CoverageReport, sample_coverage_after: CoverageReport
) -> GenerationSummary:
    """Create sample test generation summary."""
    return GenerationSummary(
        tests_generated=5,
        tests_passed=5,
        tests_failed=0,
        files_created=["tests/test_foo.py", "tests/test_bar.py"],
        coverage_before=sample_coverage_before,
        coverage_after=sample_coverage_after,
        bugs_found=["NullPointerException in foo.py:42"],
        bugs_fixed=[],
    )


class TestGitHubPRReporter:
    """Tests for GitHubPRReporter class."""

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_init_with_gh_cli(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        """Test reporter initialization with gh CLI available."""
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"

        reporter = GitHubPRReporter(temp_repo)

        assert reporter._use_gh_cli is True
        assert reporter._api is None
        assert reporter._owner == "test-owner"
        assert reporter._repo == "test-repo"

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.GitHubAPI")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
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

        reporter = GitHubPRReporter(temp_repo)

        assert reporter._use_gh_cli is False
        assert reporter._api is not None
        assert reporter._owner == "test-owner"
        assert reporter._repo == "test-repo"
        mock_api_class.assert_called_once()
        actual = mock_api_class.call_args.kwargs["token"]
        assert actual == expected_gh_value

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_init_invalid_remote(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        """Test reporter initialization with invalid remote URL."""
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://gitlab.com/owner/repo.git"

        with pytest.raises(GitOperationError, match="Could not parse GitHub owner/repo"):
            GitHubPRReporter(temp_repo)

    def test_generate_branch_name(self, temp_repo: Path) -> None:
        """Test branch name generation."""
        with (
            mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_pr.get_remote_url",
                return_value="https://github.com/test/repo.git",
            ),
        ):
            reporter = GitHubPRReporter(temp_repo)

            files = ["tests/test_foo.py", "tests/test_bar.py"]
            branch_name = reporter._generate_branch_name(files)

            assert branch_name.startswith("nit/generated-tests-")
            assert len(branch_name.split("-")[-1]) == 8  # 8-char hash

            # Same files should generate same branch name
            branch_name2 = reporter._generate_branch_name(files)
            assert branch_name == branch_name2

            # Different files should generate different branch name
            branch_name3 = reporter._generate_branch_name(["tests/test_baz.py"])
            assert branch_name != branch_name3

    def test_generate_commit_message(
        self, temp_repo: Path, sample_summary: GenerationSummary
    ) -> None:
        """Test commit message generation."""
        with (
            mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_pr.get_remote_url",
                return_value="https://github.com/test/repo.git",
            ),
        ):
            reporter = GitHubPRReporter(temp_repo)

            message = reporter._generate_commit_message(sample_summary)

            assert "test: add 5 generated tests" in message
            assert "65.0% → 80.0% (+15.0%)" in message
            assert "Bugs found: 1" in message
            assert "Co-Authored-By: nit" in message

    def test_generate_pr_title(self, temp_repo: Path, sample_summary: GenerationSummary) -> None:
        """Test PR title generation."""
        with (
            mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_pr.get_remote_url",
                return_value="https://github.com/test/repo.git",
            ),
        ):
            reporter = GitHubPRReporter(temp_repo)

            title = reporter._generate_pr_title(sample_summary)
            assert "add 5 generated tests" in title

            # With bugs fixed
            sample_summary.bugs_fixed = ["Fixed bug in foo.py"]
            title = reporter._generate_pr_title(sample_summary)
            assert "fix 1 bugs" in title

    def test_generate_pr_body(self, temp_repo: Path, sample_summary: GenerationSummary) -> None:
        """Test PR body generation."""
        with (
            mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_pr.get_remote_url",
                return_value="https://github.com/test/repo.git",
            ),
        ):
            reporter = GitHubPRReporter(temp_repo)

            body = reporter._generate_pr_body(sample_summary)

            assert "🤖 nit Test Generation" in body
            assert "**5 generated tests**" in body
            assert "📊 Test Summary" in body
            assert "Tests Generated:** 5" in body
            assert "Tests Passed:** 5 ✅" in body
            assert "📈 Coverage Improvement" in body
            assert "65.0%" in body
            assert "80.0%" in body
            assert "+15.0%" in body
            assert "📝 Files Created" in body
            assert "`tests/test_foo.py`" in body
            assert "`tests/test_bar.py`" in body
            assert "🐛 Bugs Found" in body
            assert "NullPointerException" in body
            assert "Review Checklist" in body

    @mock.patch("nit.agents.reporters.github_pr._GIT_PATH", "git")
    @mock.patch("nit.agents.reporters.github_pr._GH_PATH", "gh")
    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    @mock.patch("nit.agents.reporters.github_pr.subprocess.run")
    def test_create_pr_with_gh_cli_success(
        self,
        mock_subprocess: mock.Mock,
        mock_get_remote: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
        sample_summary: GenerationSummary,
    ) -> None:
        """Test successful PR creation with gh CLI."""
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"

        # Mock subprocess calls
        def subprocess_side_effect(*args: Any, **kwargs: Any) -> mock.Mock:
            cmd = args[0] if args else kwargs.get("args", [])
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""

            if any(c.endswith("gh") for c in cmd) and "pr" in cmd and "create" in cmd:
                result.stdout = "https://github.com/test-owner/test-repo/pull/123\n"

            return result

        mock_subprocess.side_effect = subprocess_side_effect

        # Create test files
        for file_path in sample_summary.files_created:
            full_path = temp_repo / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text("# test")

        reporter = GitHubPRReporter(temp_repo)
        result = reporter.create_pr_with_tests(sample_summary)

        assert result.success is True
        assert result.pr_url == "https://github.com/test-owner/test-repo/pull/123"
        assert result.pr_number == 123
        assert result.branch_name is not None
        assert result.error is None

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.GitHubAPI")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    @mock.patch("nit.agents.reporters.github_pr.subprocess.run")
    def test_create_pr_with_api_success(
        self,
        mock_subprocess: mock.Mock,
        mock_get_remote: mock.Mock,
        mock_api_class: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
        sample_summary: GenerationSummary,
    ) -> None:
        """Test successful PR creation with GitHub API."""
        mock_gh_available.return_value = False
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"

        # Mock GitHub API
        mock_api = mock.Mock()
        mock_api.create_pull_request.return_value = {
            "html_url": "https://github.com/test-owner/test-repo/pull/456",
            "number": 456,
        }
        mock_api_class.return_value = mock_api

        # Mock subprocess calls for git operations
        def subprocess_side_effect(*args: Any, **kwargs: Any) -> mock.Mock:
            result = mock.Mock()
            result.returncode = 0
            result.stdout = "abc123\n"
            result.stderr = ""
            return result

        mock_subprocess.side_effect = subprocess_side_effect

        # Create test files
        for file_path in sample_summary.files_created:
            full_path = temp_repo / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text("# test")

        reporter = GitHubPRReporter(temp_repo)
        result = reporter.create_pr_with_tests(sample_summary)

        assert result.success is True
        assert result.pr_url == "https://github.com/test-owner/test-repo/pull/456"
        assert result.pr_number == 456
        assert result.branch_name is not None
        assert result.error is None
        mock_api.create_pull_request.assert_called_once()

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_create_pr_no_files(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        """Test PR creation with no files to commit."""
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"

        reporter = GitHubPRReporter(temp_repo)
        summary = GenerationSummary(
            tests_generated=0,
            tests_passed=0,
            tests_failed=0,
            files_created=[],
        )

        result = reporter.create_pr_with_tests(summary)

        assert result.success is False
        assert result.error == "No test files to commit"

    @mock.patch("nit.agents.reporters.github_pr._GIT_PATH", "git")
    @mock.patch("nit.agents.reporters.github_pr._GH_PATH", "gh")
    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    @mock.patch("nit.agents.reporters.github_pr.subprocess.run")
    def test_create_pr_with_draft(
        self,
        mock_subprocess: mock.Mock,
        mock_get_remote: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
        sample_summary: GenerationSummary,
    ) -> None:
        """Test PR creation in draft mode."""
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test-owner/test-repo.git"

        # Track calls
        calls = []

        def subprocess_side_effect(*args: Any, **kwargs: Any) -> mock.Mock:
            cmd = args[0] if args else kwargs.get("args", [])
            calls.append(cmd)
            result = mock.Mock()
            result.returncode = 0
            result.stdout = "https://github.com/test-owner/test-repo/pull/123\n"
            result.stderr = ""
            return result

        mock_subprocess.side_effect = subprocess_side_effect

        # Create test files
        for file_path in sample_summary.files_created:
            full_path = temp_repo / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text("# test")

        reporter = GitHubPRReporter(temp_repo)
        result = reporter.create_pr_with_tests(sample_summary, draft=True)

        assert result.success is True

        # Verify --draft flag was used
        gh_calls = [c for c in calls if any(e.endswith("gh") for e in c) and "pr" in c]
        assert len(gh_calls) > 0
        assert "--draft" in gh_calls[0]

    def test_parse_github_url(self) -> None:
        """Test GitHub URL parsing."""
        # HTTPS format
        owner, repo = GitHubPRReporter._parse_github_url("https://github.com/owner/repo.git")
        assert owner == "owner"
        assert repo == "repo"

        # HTTPS without .git
        owner, repo = GitHubPRReporter._parse_github_url("https://github.com/owner/repo")
        assert owner == "owner"
        assert repo == "repo"

        # SSH format
        owner, repo = GitHubPRReporter._parse_github_url("git@github.com:owner/repo.git")
        assert owner == "owner"
        assert repo == "repo"

        # SSH without .git
        owner, repo = GitHubPRReporter._parse_github_url("git@github.com:owner/repo")
        assert owner == "owner"
        assert repo == "repo"

        # Invalid URL
        owner, repo = GitHubPRReporter._parse_github_url("https://gitlab.com/owner/repo.git")
        assert owner is None
        assert repo is None


# ── Additional coverage tests ─────────────────────────────────────


class TestGitHubPRReporterExtended:
    """Extended tests for untested paths in GitHubPRReporter."""

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_init_force_gh_cli_true(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        mock_get_remote.return_value = "https://github.com/owner/repo.git"
        reporter = GitHubPRReporter(temp_repo, use_gh_cli=True)
        assert reporter._use_gh_cli is True
        # is_gh_cli_available should not be called when forced
        mock_gh_available.assert_not_called()

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.GitHubAPI")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_init_force_gh_cli_false(
        self,
        mock_get_remote: mock.Mock,
        mock_api_class: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
    ) -> None:
        mock_get_remote.return_value = "https://github.com/owner/repo.git"
        reporter = GitHubPRReporter(temp_repo, use_gh_cli=False)
        assert reporter._use_gh_cli is False
        mock_gh_available.assert_not_called()

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_generate_commit_message_no_coverage_no_bugs(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"
        reporter = GitHubPRReporter(temp_repo)
        summary = GenerationSummary(
            tests_generated=3,
            tests_passed=3,
            files_created=["tests/test_a.py"],
        )
        message = reporter._generate_commit_message(summary)
        assert "test: add 3 generated tests" in message
        assert "Coverage:" not in message
        assert "Bugs found:" not in message

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_generate_commit_message_with_bugs_fixed(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"
        reporter = GitHubPRReporter(temp_repo)
        summary = GenerationSummary(
            tests_generated=2,
            tests_passed=2,
            files_created=["t.py"],
            bugs_fixed=["fix1", "fix2"],
        )
        message = reporter._generate_commit_message(summary)
        assert "Bugs fixed: 2" in message

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_generate_pr_body_no_coverage_no_bugs(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"
        reporter = GitHubPRReporter(temp_repo)
        summary = GenerationSummary(
            tests_generated=1,
            tests_passed=1,
            files_created=["t.py"],
        )
        body = reporter._generate_pr_body(summary)
        assert "Coverage Improvement" not in body
        assert "Bugs Found" not in body
        assert "Bugs Fixed" not in body

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_generate_pr_body_with_failed_tests(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"
        reporter = GitHubPRReporter(temp_repo)
        summary = GenerationSummary(
            tests_generated=3,
            tests_passed=2,
            tests_failed=1,
            files_created=["t.py"],
        )
        body = reporter._generate_pr_body(summary)
        assert "Tests Failed:** 1" in body

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_generate_pr_body_with_bugs_fixed(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"
        reporter = GitHubPRReporter(temp_repo)
        summary = GenerationSummary(
            tests_generated=1,
            tests_passed=1,
            files_created=["t.py"],
            bugs_fixed=["Fixed NPE in foo.py"],
        )
        body = reporter._generate_pr_body(summary)
        assert "Bugs Fixed" in body
        assert "Fixed NPE in foo.py" in body

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_generate_pr_body_no_files(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"
        reporter = GitHubPRReporter(temp_repo)
        summary = GenerationSummary(
            tests_generated=0,
            tests_passed=0,
            files_created=[],
        )
        body = reporter._generate_pr_body(summary)
        assert "Files Created" not in body


class TestGitHubPRReporterFixPR:
    """Tests for create_fix_pr and related helpers."""

    def _make_reporter(self, temp_repo: Path) -> GitHubPRReporter:
        with (
            mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available", return_value=True),
            mock.patch(
                "nit.agents.reporters.github_pr.get_remote_url",
                return_value="https://github.com/test/repo.git",
            ),
        ):
            return GitHubPRReporter(temp_repo)

    def _make_bug_report(self) -> Any:
        return BugReport(
            bug_type=BugType.NULL_DEREFERENCE,
            severity=BugSeverity.HIGH,
            title="Division by Zero in calculate()",
            description="The calculate function divides by zero when input is 0.",
            location=BugLocation(
                file_path="src/calc.py",
                line_number=42,
                function_name="calculate",
            ),
            error_message="ZeroDivisionError: division by zero",
        )

    def _make_fix(self) -> Any:
        return GeneratedFix(
            fixed_code="def calculate(x):\n    if x == 0:\n        return 0\n    return 1/x\n",
            patch="--- a/calc.py\n+++ b/calc.py\n",
            explanation="Added zero check before division.",
            changed_lines=[2, 3],
            safety_notes=["Check callers for None inputs"],
        )

    def test_generate_fix_branch_name(self, temp_repo: Path) -> None:
        reporter = self._make_reporter(temp_repo)
        bug = self._make_bug_report()
        branch = reporter._generate_fix_branch_name(bug)
        assert branch.startswith("nit/fix-")
        assert "division" in branch.lower()

    def test_generate_fix_commit_message(self, temp_repo: Path) -> None:
        reporter = self._make_reporter(temp_repo)
        bug = self._make_bug_report()
        fix = self._make_fix()
        msg = reporter._generate_fix_commit_message(bug, fix)
        assert "fix: Division by Zero" in msg
        assert "Added zero check" in msg
        assert "null_dereference" in msg
        assert "Co-Authored-By: nit" in msg

    def test_generate_fix_pr_title(self, temp_repo: Path) -> None:
        reporter = self._make_reporter(temp_repo)
        bug = self._make_bug_report()
        title = reporter._generate_fix_pr_title(bug)
        assert title == "fix: Division by Zero in calculate()"

    def test_generate_fix_pr_body(self, temp_repo: Path) -> None:
        reporter = self._make_reporter(temp_repo)
        bug = self._make_bug_report()
        fix = self._make_fix()
        body = reporter._generate_fix_pr_body(bug, fix, "src/calc.py")
        assert "Bug Fix" in body
        assert "null_dereference" in body
        assert "high" in body
        assert "Division by Zero" in body
        assert "ZeroDivisionError" in body
        assert "Added zero check" in body
        assert "src/calc.py" in body
        assert "Safety Notes" in body
        assert "Check callers" in body
        assert "calculate" in body
        assert "Review Checklist" in body

    def test_generate_fix_pr_body_no_function_name(self, temp_repo: Path) -> None:
        reporter = self._make_reporter(temp_repo)
        bug = BugReport(
            bug_type=BugType.LOGIC_ERROR,
            severity=BugSeverity.MEDIUM,
            title="Logic error",
            description="Wrong logic",
            location=BugLocation(file_path="src/x.py", line_number=10),
            error_message="",
        )
        fix = GeneratedFix(
            fixed_code="fixed",
            patch="",
            explanation="Fixed logic",
            changed_lines=[10],
            safety_notes=[],
        )
        body = reporter._generate_fix_pr_body(bug, fix, "src/x.py")
        assert "Function" not in body
        assert "Error Message" not in body
        assert "Safety Notes" not in body

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    @mock.patch("nit.agents.reporters.github_pr.subprocess.run")
    def test_create_fix_pr_success(
        self,
        mock_subprocess: mock.Mock,
        mock_get_remote: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"

        def subprocess_side_effect(*args: Any, **kwargs: Any) -> mock.Mock:
            cmd = args[0] if args else kwargs.get("args", [])
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            if any(str(c).endswith("gh") for c in cmd) and "pr" in cmd:
                result.stdout = "https://github.com/test/repo/pull/99\n"
            return result

        mock_subprocess.side_effect = subprocess_side_effect

        # Create the file to fix
        (temp_repo / "src").mkdir(parents=True, exist_ok=True)
        (temp_repo / "src" / "calc.py").write_text("def calculate(x): return 1/x\n")

        reporter = GitHubPRReporter(temp_repo)
        bug = self._make_bug_report()
        fix = self._make_fix()
        result = reporter.create_fix_pr(bug, fix, "src/calc.py")
        assert result.success is True
        assert result.pr_url is not None

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_create_fix_pr_git_error(
        self,
        mock_get_remote: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"

        with mock.patch(
            "nit.agents.reporters.github_pr.get_current_branch",
            side_effect=GitOperationError("git error"),
        ):
            reporter = GitHubPRReporter(temp_repo)
            bug = self._make_bug_report()
            fix = self._make_fix()
            result = reporter.create_fix_pr(bug, fix, "src/calc.py")
            assert result.success is False
            assert "git error" in (result.error or "")

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_create_fix_pr_unexpected_error(
        self,
        mock_get_remote: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"

        with mock.patch(
            "nit.agents.reporters.github_pr.get_current_branch",
            side_effect=RuntimeError("boom"),
        ):
            reporter = GitHubPRReporter(temp_repo)
            bug = self._make_bug_report()
            fix = self._make_fix()
            result = reporter.create_fix_pr(bug, fix, "src/calc.py")
            assert result.success is False
            assert "Unexpected error" in (result.error or "")


class TestGitHubPRReporterCreatePRErrors:
    """Tests for error handling in create_pr_with_tests."""

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_create_pr_git_operation_error(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"

        with mock.patch(
            "nit.agents.reporters.github_pr.get_current_branch",
            side_effect=GitOperationError("branch error"),
        ):
            reporter = GitHubPRReporter(temp_repo)
            summary = GenerationSummary(
                tests_generated=1,
                tests_passed=1,
                files_created=["t.py"],
            )
            result = reporter.create_pr_with_tests(summary)
            assert result.success is False
            assert "branch error" in (result.error or "")

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_create_pr_unexpected_error(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"

        with mock.patch(
            "nit.agents.reporters.github_pr.get_current_branch",
            side_effect=RuntimeError("kaboom"),
        ):
            reporter = GitHubPRReporter(temp_repo)
            summary = GenerationSummary(
                tests_generated=1,
                tests_passed=1,
                files_created=["t.py"],
            )
            result = reporter.create_pr_with_tests(summary)
            assert result.success is False
            assert "Unexpected error" in (result.error or "")

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.GitHubAPI")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    @mock.patch("nit.agents.reporters.github_pr.subprocess.run")
    def test_create_pr_with_api_no_owner(
        self,
        mock_subprocess: mock.Mock,
        mock_get_remote: mock.Mock,
        mock_api_class: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
    ) -> None:
        mock_gh_available.return_value = False
        mock_get_remote.return_value = "https://github.com/owner/repo.git"

        mock_api = mock.Mock()
        mock_api_class.return_value = mock_api

        def subprocess_side_effect(*args: Any, **kwargs: Any) -> mock.Mock:
            result = mock.Mock()
            result.returncode = 0
            result.stdout = "abc123"
            result.stderr = ""
            return result

        mock_subprocess.side_effect = subprocess_side_effect

        reporter = GitHubPRReporter(temp_repo)
        # Forcibly clear owner to test the guard
        reporter._owner = None
        reporter._repo = None

        with pytest.raises(GitHubAPIError, match="owner/name"):
            reporter._create_pr_with_api(branch_name="nit/test", title="title", body="body")

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_create_pr_with_api_no_api_instance(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock, temp_repo: Path
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/owner/repo.git"

        reporter = GitHubPRReporter(temp_repo)
        reporter._api = None

        with pytest.raises(GitHubAPIError, match="not initialized"):
            reporter._create_pr_with_api(branch_name="nit/test", title="title", body="body")

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    def test_parse_github_url_empty_string(
        self, mock_get_remote: mock.Mock, mock_gh_available: mock.Mock
    ) -> None:
        owner, repo = GitHubPRReporter._parse_github_url("")
        assert owner is None
        assert repo is None

    @mock.patch("nit.agents.reporters.github_pr.is_gh_cli_available")
    @mock.patch("nit.agents.reporters.github_pr.get_remote_url")
    @mock.patch("nit.agents.reporters.github_pr.subprocess.run")
    def test_create_pr_gh_cli_pr_number_extraction_no_pull(
        self,
        mock_subprocess: mock.Mock,
        mock_get_remote: mock.Mock,
        mock_gh_available: mock.Mock,
        temp_repo: Path,
    ) -> None:
        mock_gh_available.return_value = True
        mock_get_remote.return_value = "https://github.com/test/repo.git"

        def subprocess_side_effect(*args: Any, **kwargs: Any) -> mock.Mock:
            cmd = args[0] if args else kwargs.get("args", [])
            result = mock.Mock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            # Return a non-standard URL without /pull/
            if any(str(c).endswith("gh") for c in cmd) and "pr" in cmd and "create" in cmd:
                result.stdout = "https://github.com/test/repo/issues/42\n"
            return result

        mock_subprocess.side_effect = subprocess_side_effect

        reporter = GitHubPRReporter(temp_repo)
        pr_result = reporter._create_pr_with_gh_cli(
            branch_name="nit/test", title="title", body="body"
        )
        assert pr_result.success is True
        assert pr_result.pr_number is None
