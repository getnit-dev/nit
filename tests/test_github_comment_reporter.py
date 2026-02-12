"""Tests for GitHub comment reporter."""

from __future__ import annotations

from unittest import mock

import pytest

from nit.agents.analyzers.diff import DiffAnalysisResult
from nit.agents.reporters.github_comment import (
    FullReportData,
    GitHubCommentReporter,
    create_reporter_from_env,
    post_coverage_report_from_env,
)
from nit.models.coverage import CoverageReport, PackageCoverage
from nit.utils.git import GitHubAPIError, GitHubPRInfo


@pytest.fixture
def mock_api() -> mock.Mock:
    """Create a mocked GitHub API."""
    api_mock = mock.Mock()
    api_mock.upsert_comment.return_value = {
        "id": 123,
        "html_url": "https://github.com/owner/repo/pull/42#issuecomment-123",
    }
    return api_mock


@pytest.fixture
def sample_pr_info() -> GitHubPRInfo:
    """Create sample PR info."""
    return GitHubPRInfo(owner="test-owner", repo="test-repo", pr_number=42)


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
            "api": PackageCoverage(
                name="api",
                line_coverage=0.80,
                function_coverage=0.85,
                branch_coverage=0.75,
            ),
        },
        overall_line_coverage=0.725,
        overall_function_coverage=0.775,
        overall_branch_coverage=0.675,
    )


@pytest.fixture
def sample_coverage_after() -> CoverageReport:
    """Create sample coverage report (after)."""
    return CoverageReport(
        packages={
            "web": PackageCoverage(
                name="web",
                line_coverage=0.75,
                function_coverage=0.80,
                branch_coverage=0.70,
            ),
            "api": PackageCoverage(
                name="api",
                line_coverage=0.85,
                function_coverage=0.90,
                branch_coverage=0.80,
            ),
        },
        overall_line_coverage=0.80,
        overall_function_coverage=0.85,
        overall_branch_coverage=0.75,
    )


@pytest.fixture
def sample_diff_result() -> DiffAnalysisResult:
    """Create sample diff analysis result."""
    return DiffAnalysisResult(
        changed_source_files=["src/foo.py", "src/bar.py"],
        changed_test_files=["tests/test_baz.py"],
        affected_source_files=["src/foo.py", "src/bar.py", "src/baz.py"],
    )


class TestGitHubCommentReporter:
    """Tests for GitHubCommentReporter class."""

    @mock.patch("nit.agents.reporters.github_comment.GitHubAPI")
    def test_init_success(self, mock_api_class: mock.Mock) -> None:
        """Test reporter initialization."""
        reporter = GitHubCommentReporter(github_token="test-token")  # noqa: S106

        assert reporter is not None
        mock_api_class.assert_called_once_with(token="test-token")  # noqa: S106

    @mock.patch("nit.agents.reporters.github_comment.GitHubAPI")
    def test_post_coverage_delta(
        self,
        mock_api_class: mock.Mock,
        mock_api: mock.Mock,
        sample_pr_info: GitHubPRInfo,
        sample_coverage_before: CoverageReport,
        sample_coverage_after: CoverageReport,
    ) -> None:
        """Test posting coverage delta report."""
        mock_api_class.return_value = mock_api

        reporter = GitHubCommentReporter(github_token="test-token")  # noqa: S106
        result = reporter.post_coverage_delta(
            sample_pr_info, sample_coverage_before, sample_coverage_after
        )

        assert result["status"] == "success"
        assert "comment_url" in result

        # Verify upsert_comment was called
        mock_api.upsert_comment.assert_called_once()
        call_args = mock_api.upsert_comment.call_args

        # Check PR info
        assert call_args[0][0] == sample_pr_info

        # Check body contains expected elements
        body = call_args[0][1]
        assert "Coverage Report" in body
        assert "web" in body
        assert "api" in body
        assert "Overall" in body

    @mock.patch("nit.agents.reporters.github_comment.GitHubAPI")
    def test_coverage_delta_table_format(
        self,
        mock_api_class: mock.Mock,
        mock_api: mock.Mock,
        sample_pr_info: GitHubPRInfo,
        sample_coverage_before: CoverageReport,
        sample_coverage_after: CoverageReport,
    ) -> None:
        """Test coverage delta table formatting."""
        mock_api_class.return_value = mock_api

        reporter = GitHubCommentReporter(github_token="test-token")  # noqa: S106
        reporter.post_coverage_delta(sample_pr_info, sample_coverage_before, sample_coverage_after)

        body = mock_api.upsert_comment.call_args[0][1]

        # Check table structure
        assert "| Package | Before | After | Δ |" in body
        assert "|---------|--------|-------|---|" in body

        # Check percentage values
        assert "65.0%" in body  # web before
        assert "75.0%" in body  # web after
        assert "+10.0%" in body  # web delta

        # Check emoji indicators
        assert "📈" in body  # improvement indicator

    @mock.patch("nit.agents.reporters.github_comment.GitHubAPI")
    def test_post_coverage_delta_with_diff_result(
        self,
        mock_api_class: mock.Mock,
        mock_api: mock.Mock,
        sample_pr_info: GitHubPRInfo,
        sample_coverage_before: CoverageReport,
        sample_coverage_after: CoverageReport,
        sample_diff_result: DiffAnalysisResult,
    ) -> None:
        """Test posting coverage delta with diff result."""
        mock_api_class.return_value = mock_api

        reporter = GitHubCommentReporter(github_token="test-token")  # noqa: S106
        reporter.post_coverage_delta(
            sample_pr_info, sample_coverage_before, sample_coverage_after, sample_diff_result
        )

        body = mock_api.upsert_comment.call_args[0][1]

        # Check diff info is included
        assert "Files Analyzed" in body
        assert "Source files changed: 2" in body
        assert "Test files changed: 1" in body

    @mock.patch("nit.agents.reporters.github_comment.GitHubAPI")
    def test_post_test_generation_summary(
        self,
        mock_api_class: mock.Mock,
        mock_api: mock.Mock,
        sample_pr_info: GitHubPRInfo,
    ) -> None:
        """Test posting test generation summary."""
        mock_api_class.return_value = mock_api

        reporter = GitHubCommentReporter(github_token="test-token")  # noqa: S106
        result = reporter.post_test_generation_summary(
            sample_pr_info,
            tests_generated=15,
            tests_passed=12,
            tests_failed=3,
            files_changed=5,
        )

        assert result["status"] == "success"

        body = mock_api.upsert_comment.call_args[0][1]

        assert "Test Generation Summary" in body
        assert "Files Changed:** 5" in body
        assert "Tests Generated:** 15" in body
        assert "Passed: 12" in body
        assert "Failed: 3" in body

    @mock.patch("nit.agents.reporters.github_comment.GitHubAPI")
    def test_post_full_report(
        self,
        mock_api_class: mock.Mock,
        mock_api: mock.Mock,
        sample_pr_info: GitHubPRInfo,
        sample_coverage_before: CoverageReport,
        sample_coverage_after: CoverageReport,
        sample_diff_result: DiffAnalysisResult,
    ) -> None:
        """Test posting comprehensive report."""
        mock_api_class.return_value = mock_api

        reporter = GitHubCommentReporter(github_token="test-token")  # noqa: S106
        report_data = FullReportData(
            coverage_before=sample_coverage_before,
            coverage_after=sample_coverage_after,
            tests_generated=10,
            tests_passed=8,
            tests_failed=2,
            issues_found=["Issue 1: null pointer", "Issue 2: type error"],
            drift_status="No drift detected",
            diff_result=sample_diff_result,
        )
        result = reporter.post_full_report(sample_pr_info, report_data)

        assert result["status"] == "success"

        body = mock_api.upsert_comment.call_args[0][1]

        # Check all sections are present
        assert "nit Test Generation Report" in body
        assert "Coverage Delta" in body
        assert "Tests Generated" in body
        assert "Issues Found" in body
        assert "Drift Status" in body
        assert "Files Analyzed" in body

        # Check specific content
        assert "Issue 1: null pointer" in body
        assert "No drift detected" in body
        assert "Generated:** 10" in body

    @mock.patch("nit.agents.reporters.github_comment.GitHubAPI")
    def test_format_delta_positive(self, mock_api_class: mock.Mock, mock_api: mock.Mock) -> None:
        """Test delta formatting for positive change."""
        mock_api_class.return_value = mock_api

        reporter = GitHubCommentReporter(github_token="test-token")  # noqa: S106
        delta_str = reporter._format_delta(5.5)

        assert "+5.5%" in delta_str
        assert "📈" in delta_str

    @mock.patch("nit.agents.reporters.github_comment.GitHubAPI")
    def test_format_delta_negative(self, mock_api_class: mock.Mock, mock_api: mock.Mock) -> None:
        """Test delta formatting for negative change."""
        mock_api_class.return_value = mock_api

        reporter = GitHubCommentReporter(github_token="test-token")  # noqa: S106
        delta_str = reporter._format_delta(-3.2)

        assert "-3.2%" in delta_str
        assert "📉" in delta_str

    @mock.patch("nit.agents.reporters.github_comment.GitHubAPI")
    def test_format_delta_zero(self, mock_api_class: mock.Mock, mock_api: mock.Mock) -> None:
        """Test delta formatting for no change."""
        mock_api_class.return_value = mock_api

        reporter = GitHubCommentReporter(github_token="test-token")  # noqa: S106
        delta_str = reporter._format_delta(0.0)

        assert "0.0%" in delta_str
        assert "━" in delta_str

    @mock.patch("nit.agents.reporters.github_comment.GitHubAPI")
    def test_api_error_propagates(
        self,
        mock_api_class: mock.Mock,
        mock_api: mock.Mock,
        sample_pr_info: GitHubPRInfo,
        sample_coverage_before: CoverageReport,
        sample_coverage_after: CoverageReport,
    ) -> None:
        """Test API errors are propagated."""
        mock_api.upsert_comment.side_effect = GitHubAPIError("API request failed")
        mock_api_class.return_value = mock_api

        reporter = GitHubCommentReporter(github_token="test-token")  # noqa: S106

        with pytest.raises(GitHubAPIError):
            reporter.post_coverage_delta(
                sample_pr_info, sample_coverage_before, sample_coverage_after
            )


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    @mock.patch("nit.agents.reporters.github_comment.get_pr_info_from_env")
    @mock.patch("nit.agents.reporters.github_comment.GitHubCommentReporter")
    def test_create_reporter_from_env_success(
        self, mock_reporter_class: mock.Mock, mock_get_pr_info: mock.Mock
    ) -> None:
        """Test creating reporter from environment."""
        mock_get_pr_info.return_value = GitHubPRInfo(owner="owner", repo="repo", pr_number=123)

        reporter = create_reporter_from_env()

        assert reporter is not None
        mock_reporter_class.assert_called_once()

    @mock.patch("nit.agents.reporters.github_comment.get_pr_info_from_env")
    def test_create_reporter_from_env_no_pr_context(self, mock_get_pr_info: mock.Mock) -> None:
        """Test creating reporter when not in PR context."""
        mock_get_pr_info.return_value = None

        reporter = create_reporter_from_env()

        assert reporter is None

    @mock.patch("nit.agents.reporters.github_comment.get_pr_info_from_env")
    @mock.patch("nit.agents.reporters.github_comment.GitHubCommentReporter")
    def test_post_coverage_report_from_env_success(
        self,
        mock_reporter_class: mock.Mock,
        mock_get_pr_info: mock.Mock,
        sample_coverage_before: CoverageReport,
        sample_coverage_after: CoverageReport,
    ) -> None:
        """Test posting coverage report from environment."""
        mock_get_pr_info.return_value = GitHubPRInfo(owner="owner", repo="repo", pr_number=123)

        mock_reporter = mock.Mock()
        mock_reporter.post_coverage_delta.return_value = {
            "status": "success",
            "comment_url": "https://github.com/...",
        }
        mock_reporter_class.return_value = mock_reporter

        result = post_coverage_report_from_env(sample_coverage_before, sample_coverage_after)

        assert result is True
        mock_reporter.post_coverage_delta.assert_called_once()

    @mock.patch("nit.agents.reporters.github_comment.get_pr_info_from_env")
    def test_post_coverage_report_from_env_no_pr_context(
        self,
        mock_get_pr_info: mock.Mock,
        sample_coverage_before: CoverageReport,
        sample_coverage_after: CoverageReport,
    ) -> None:
        """Test posting coverage report when not in PR context."""
        mock_get_pr_info.return_value = None

        result = post_coverage_report_from_env(sample_coverage_before, sample_coverage_after)

        assert result is False

    @mock.patch("nit.agents.reporters.github_comment.get_pr_info_from_env")
    @mock.patch("nit.agents.reporters.github_comment.GitHubCommentReporter")
    def test_post_coverage_report_from_env_api_error(
        self,
        mock_reporter_class: mock.Mock,
        mock_get_pr_info: mock.Mock,
        sample_coverage_before: CoverageReport,
        sample_coverage_after: CoverageReport,
    ) -> None:
        """Test posting coverage report handles API errors."""
        mock_get_pr_info.return_value = GitHubPRInfo(owner="owner", repo="repo", pr_number=123)

        mock_reporter = mock.Mock()
        mock_reporter.post_coverage_delta.side_effect = GitHubAPIError("Failed")
        mock_reporter_class.return_value = mock_reporter

        result = post_coverage_report_from_env(sample_coverage_before, sample_coverage_after)

        assert result is False
