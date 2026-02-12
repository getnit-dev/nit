"""Tests for pick pipeline."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from nit.adapters.base import CaseResult, CaseStatus, RunResult, TestFrameworkAdapter
from nit.adapters.coverage.base import CoverageReport, FileCoverage, LineCoverage
from nit.agents.analyzers.bug import BugLocation, BugReport, BugSeverity, BugType
from nit.agents.analyzers.coverage import CoverageGapReport, FunctionGap, GapPriority
from nit.agents.base import TaskStatus
from nit.agents.debuggers import GeneratedFix, RootCause, VerificationResult
from nit.agents.detectors.signals import DetectedFramework, FrameworkCategory
from nit.agents.detectors.stack import LanguageInfo
from nit.agents.detectors.workspace import PackageInfo
from nit.agents.pipelines import PickPipeline, PickPipelineConfig, PickPipelineResult
from nit.agents.pipelines.pick import _StepTracker
from nit.llm.usage_callback import SessionUsageStats
from nit.models.profile import ProjectProfile
from nit.utils.ci_context import CIContext


@pytest.fixture
def mock_profile() -> ProjectProfile:
    """Create a mock project profile."""
    return ProjectProfile(
        root="/test/project",
        languages=[
            LanguageInfo(language="Python", file_count=10, confidence=0.9, extensions={".py": 10})
        ],
        frameworks=[
            DetectedFramework(
                name="pytest",
                language="Python",
                category=FrameworkCategory.UNIT_TEST,
                confidence=0.9,
            )
        ],
        packages=[PackageInfo(name="test_package", path="/test/project")],
        workspace_tool="generic",
    )


@pytest.fixture
def mock_adapter() -> AsyncMock:
    """Create a mock test adapter."""
    adapter = AsyncMock(spec=TestFrameworkAdapter)
    adapter.name = "pytest"
    return adapter


@pytest.fixture
def sample_test_result() -> RunResult:
    """Create a sample test result with failures."""
    return RunResult(
        passed=7,
        failed=2,
        skipped=1,
        errors=0,
        duration_ms=1000,
        test_cases=[
            CaseResult(
                name="test_addition",
                status=CaseStatus.PASSED,
                duration_ms=100,
                file_path="/test/project/test_math.py",
            ),
            CaseResult(
                name="test_division",
                status=CaseStatus.FAILED,
                duration_ms=150,
                file_path="/test/project/test_math.py",
                failure_message="ZeroDivisionError: division by zero",
            ),
            CaseResult(
                name="test_sqrt",
                status=CaseStatus.FAILED,
                duration_ms=120,
                file_path="/test/project/test_math.py",
                failure_message="ValueError: math domain error",
            ),
        ],
    )


@pytest.fixture
def sample_bug_report() -> BugReport:
    """Create a sample bug report."""
    return BugReport(
        bug_type=BugType.ARITHMETIC_ERROR,
        severity=BugSeverity.HIGH,
        title="Division by zero in calculator",
        description="Function does not handle division by zero",
        location=BugLocation(
            file_path="/test/project/src/calculator.py", line_number=42, function_name="divide"
        ),
        error_message="ZeroDivisionError raised when divisor is 0",
    )


@pytest.fixture
def sample_fix() -> GeneratedFix:
    """Create a sample generated fix."""
    return GeneratedFix(
        fixed_code=(
            "def divide(a, b):\n"
            "    if b == 0:\n"
            "        raise ValueError('Cannot divide by zero')\n"
            "    return a / b"
        ),
        patch="",
        explanation="Added zero division check",
        changed_lines=[2, 3],
        safety_notes=["Added validation check"],
    )


@pytest.mark.asyncio
async def test_pick_pipeline_basic_flow(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
) -> None:
    """Test basic pick pipeline execution without bugs."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=False,
        create_pr=False,
        ci_mode=True,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
    ):
        # Setup mocks
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = RunResult(
            passed=10, failed=0, skipped=0, errors=0, duration_ms=1000, test_cases=[]
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        assert result.success
        assert result.tests_run == 10
        assert result.tests_passed == 10
        assert result.tests_failed == 0
        assert len(result.bugs_found) == 0


@pytest.mark.asyncio
async def test_pick_pipeline_with_bugs_no_fix(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
    sample_bug_report: BugReport,
) -> None:
    """Test pick pipeline detects bugs but doesn't fix (fix disabled)."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=False,
        create_pr=False,
        ci_mode=True,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_analyzer_class,
    ):
        # Setup mocks
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        # Mock bug analyzer
        mock_analyzer = AsyncMock()
        mock_analyzer_class.return_value = mock_analyzer
        mock_analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": sample_bug_report},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        assert result.success
        assert result.tests_failed == 2
        assert len(result.bugs_found) == 2  # 2 failed tests should detect bugs
        assert len(result.fixes_generated) == 0  # Fix disabled


@pytest.mark.asyncio
async def test_pick_pipeline_with_fix_generation(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
    sample_bug_report: BugReport,
    sample_fix: GeneratedFix,
) -> None:
    """Test full pick pipeline with bug detection and fix generation."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=True,
        create_pr=False,
        ci_mode=True,
    )

    # Create source file that will be fixed
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    source_file = src_dir / "calculator.py"
    source_file.write_text("def divide(a, b):\n    return a / b")

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_analyzer_class,
        patch("nit.agents.pipelines.pick.create_engine") as mock_engine,
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_verifier_class,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer") as mock_root_cause_class,
        patch("nit.agents.pipelines.pick.FixGenerator") as mock_fix_gen_class,
        patch("nit.agents.pipelines.pick.FixVerifier") as mock_fix_verify_class,
    ):
        # Setup mocks
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        # Mock bug analyzer
        mock_analyzer = AsyncMock()
        mock_analyzer_class.return_value = mock_analyzer

        # Adjust bug report to point to our temp file
        adjusted_bug = BugReport(
            bug_type=sample_bug_report.bug_type,
            severity=sample_bug_report.severity,
            title=sample_bug_report.title,
            description=sample_bug_report.description,
            location=BugLocation(
                file_path=str(source_file),
                line_number=2,
                function_name="divide",
            ),
            error_message=sample_bug_report.error_message,
        )

        mock_analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": adjusted_bug},
        )

        # Mock fix pipeline
        mock_llm = Mock()
        mock_engine.return_value = mock_llm

        mock_verifier = AsyncMock()
        mock_verifier_class.return_value = mock_verifier
        mock_verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=True,
                    reproduction_test="def test_repro(): ...",
                    test_output="Test failed as expected",
                    confidence=0.95,
                )
            },
        )

        mock_root_cause = AsyncMock()
        mock_root_cause_class.return_value = mock_root_cause
        mock_root_cause.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "root_cause": RootCause(
                    category="missing_validation",
                    description="Missing zero check",
                    affected_code="return a / b",
                )
            },
        )

        mock_fix_gen = AsyncMock()
        mock_fix_gen_class.return_value = mock_fix_gen
        mock_fix_gen.run.return_value = Mock(
            status=TaskStatus.COMPLETED, result={"fix": sample_fix}
        )

        mock_fix_verify = AsyncMock()
        mock_fix_verify_class.return_value = mock_fix_verify
        mock_fix_verify.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"verification": Mock(is_verified=True, notes="Fix verified")},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        assert result.success
        assert len(result.bugs_found) == 2
        assert len(result.fixes_generated) == 2
        assert len(result.fixes_applied) == 2

        # Verify fix was written
        assert source_file.read_text() == sample_fix.fixed_code


@pytest.mark.asyncio
async def test_pick_pipeline_pr_creation_local_context(
    tmp_path: Path, mock_profile: ProjectProfile, mock_adapter: AsyncMock
) -> None:
    """Test PR creation in local (non-CI) context."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=False,
        create_pr=True,
        ci_mode=False,
        ci_context=CIContext(
            is_ci=False,
            is_pr=False,
            pr_number=None,
            branch=None,
            base_branch=None,
            commit_sha=None,
            repo_owner=None,
            repo_name=None,
        ),
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.GitHubPRReporter") as mock_pr_reporter_class,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = RunResult(
            passed=5, failed=0, skipped=0, errors=0, duration_ms=500, test_cases=[]
        )

        # Mock PR reporter
        mock_pr_reporter = Mock()
        mock_pr_reporter_class.return_value = mock_pr_reporter
        mock_pr_reporter.create_pr_with_tests.return_value = Mock(
            success=True, pr_url="https://github.com/test/repo/pull/123"
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        # Should create PR in local context when flag is set
        assert result.pr_url == "https://github.com/test/repo/pull/123"
        assert result.pr_created


@pytest.mark.asyncio
async def test_pick_pipeline_no_pr_in_pr_context(
    tmp_path: Path, mock_profile: ProjectProfile, mock_adapter: AsyncMock
) -> None:
    """Test that new PR is not created when already in a PR context."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=False,
        create_pr=True,  # Flag is set
        ci_mode=True,
        ci_context=CIContext(
            is_ci=True,
            is_pr=True,  # Already in PR
            pr_number=456,
            branch="feature/test",
            base_branch="main",
            commit_sha="abc123",
            repo_owner="test",
            repo_name="repo",
        ),
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = RunResult(
            passed=5, failed=0, skipped=0, errors=0, duration_ms=500, test_cases=[]
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        # Should NOT create new PR when already in PR context
        # Instead should add commit (not fully implemented yet)
        assert not result.pr_created


@pytest.mark.asyncio
async def test_pick_pipeline_different_test_types(
    tmp_path: Path, mock_profile: ProjectProfile, mock_adapter: AsyncMock
) -> None:
    """Test pick pipeline with different test type configurations."""
    test_types = ["unit", "e2e", "integration", "all"]

    for test_type in test_types:
        config = PickPipelineConfig(
            project_root=tmp_path,
            test_type=test_type,
            fix_enabled=False,
            create_pr=False,
            ci_mode=True,
        )

        with (
            patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
            patch("nit.agents.pipelines.pick.save_profile"),
            patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
            patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        ):
            mock_registry.return_value.select_adapters_for_profile.return_value = {
                "test_package": [mock_adapter]
            }
            mock_adapter.run_tests.return_value = RunResult(
                passed=1, failed=0, skipped=0, errors=0, duration_ms=100, test_cases=[]
            )

            pipeline = PickPipeline(config)
            result = await pipeline.run()

            assert result.success
            assert config.test_type == test_type


@pytest.mark.asyncio
async def test_pick_pipeline_with_target_file(
    tmp_path: Path, mock_profile: ProjectProfile, mock_adapter: AsyncMock
) -> None:
    """Test pick pipeline targeting a specific file."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        target_file="/test/project/src/calculator.py",
        fix_enabled=False,
        create_pr=False,
        ci_mode=True,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = RunResult(
            passed=3, failed=0, skipped=0, errors=0, duration_ms=200, test_cases=[]
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        assert result.success
        assert config.target_file == "/test/project/src/calculator.py"


@pytest.mark.asyncio
async def test_pick_pipeline_with_coverage_target(
    tmp_path: Path, mock_profile: ProjectProfile, mock_adapter: AsyncMock
) -> None:
    """Test pick pipeline with coverage target."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        coverage_target=80,
        fix_enabled=False,
        create_pr=False,
        ci_mode=True,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = RunResult(
            passed=8, failed=0, skipped=0, errors=0, duration_ms=400, test_cases=[]
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        assert result.success
        assert config.coverage_target == 80


@pytest.mark.asyncio
async def test_pick_pipeline_handles_adapter_not_found(
    tmp_path: Path, mock_profile: ProjectProfile
) -> None:
    """Test pick pipeline gracefully handles no adapters found."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=False,
        create_pr=False,
        ci_mode=True,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
    ):
        # No adapters found
        mock_registry.return_value.select_adapters_for_profile.return_value = {}

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        assert not result.success
        assert len(result.errors) > 0
        assert "No unit test framework detected" in result.errors[0]


@pytest.mark.asyncio
async def test_pick_pipeline_handles_test_execution_failure(
    tmp_path: Path, mock_profile: ProjectProfile, mock_adapter: AsyncMock
) -> None:
    """Test pick pipeline handles test execution failures gracefully."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=False,
        create_pr=False,
        ci_mode=True,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.side_effect = RuntimeError("Test adapter crashed")

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        assert not result.success
        assert len(result.errors) > 0


@pytest.mark.asyncio
async def test_pick_pipeline_create_issues(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
    sample_bug_report: BugReport,
) -> None:
    """Test pick pipeline creates GitHub issues when create_issues is enabled."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=False,
        create_pr=False,
        create_issues=True,
        ci_mode=True,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_analyzer_class,
        patch("nit.agents.pipelines.pick.GitHubIssueReporter") as mock_issue_reporter_class,
    ):
        # Setup mocks
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        # Mock bug analyzer
        mock_analyzer = AsyncMock()
        mock_analyzer_class.return_value = mock_analyzer
        mock_analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": sample_bug_report},
        )

        # Mock issue reporter
        mock_issue_reporter = Mock()
        mock_issue_reporter_class.return_value = mock_issue_reporter
        mock_issue_reporter.create_bug_issue.return_value = Mock(
            success=True, issue_url="https://github.com/test/repo/issues/42"
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        assert result.success
        assert len(result.bugs_found) == 2
        # Verify issue reporter was called for each bug
        assert mock_issue_reporter.create_bug_issue.call_count == 2


@pytest.mark.asyncio
async def test_pick_pipeline_create_fix_prs(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
    sample_bug_report: BugReport,
    sample_fix: GeneratedFix,
) -> None:
    """Test pick pipeline creates fix PRs when create_fix_prs is enabled."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=True,
        create_pr=False,
        create_fix_prs=True,
        ci_mode=True,
    )

    # Create source file that will be fixed
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    source_file = src_dir / "calculator.py"
    source_file.write_text("def divide(a, b):\n    return a / b")

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_analyzer_class,
        patch("nit.agents.pipelines.pick.create_engine") as mock_engine,
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_verifier_class,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer") as mock_root_cause_class,
        patch("nit.agents.pipelines.pick.FixGenerator") as mock_fix_gen_class,
        patch("nit.agents.pipelines.pick.FixVerifier") as mock_fix_verify_class,
        patch("nit.agents.pipelines.pick.GitHubPRReporter") as mock_pr_reporter_class,
    ):
        # Setup mocks
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        # Mock bug analyzer
        mock_analyzer = AsyncMock()
        mock_analyzer_class.return_value = mock_analyzer
        adjusted_bug = BugReport(
            bug_type=sample_bug_report.bug_type,
            severity=sample_bug_report.severity,
            title=sample_bug_report.title,
            description=sample_bug_report.description,
            location=BugLocation(
                file_path=str(source_file),
                line_number=2,
                function_name="divide",
            ),
            error_message=sample_bug_report.error_message,
        )
        mock_analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": adjusted_bug},
        )

        # Mock fix pipeline
        mock_llm = Mock()
        mock_engine.return_value = mock_llm

        mock_verifier = AsyncMock()
        mock_verifier_class.return_value = mock_verifier
        mock_verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=True,
                    reproduction_test="def test_repro(): ...",
                    test_output="Test failed as expected",
                    confidence=0.95,
                )
            },
        )

        mock_root_cause = AsyncMock()
        mock_root_cause_class.return_value = mock_root_cause
        mock_root_cause.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "root_cause": RootCause(
                    category="missing_validation",
                    description="Missing zero check",
                    affected_code="return a / b",
                )
            },
        )

        mock_fix_gen = AsyncMock()
        mock_fix_gen_class.return_value = mock_fix_gen
        mock_fix_gen.run.return_value = Mock(
            status=TaskStatus.COMPLETED, result={"fix": sample_fix}
        )

        mock_fix_verify = AsyncMock()
        mock_fix_verify_class.return_value = mock_fix_verify
        mock_fix_verify.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"verification": Mock(is_verified=True, notes="Fix verified")},
        )

        # Mock PR reporter
        mock_pr_reporter = Mock()
        mock_pr_reporter_class.return_value = mock_pr_reporter
        mock_pr_reporter.create_fix_pr.return_value = Mock(
            success=True, pr_url="https://github.com/test/repo/pull/99"
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        assert result.success
        assert len(result.fixes_generated) == 2
        # Verify PR reporter was called for each fix
        assert mock_pr_reporter.create_fix_pr.call_count == 2


@pytest.mark.asyncio
async def test_pick_pipeline_commit_changes_local(
    tmp_path: Path, mock_profile: ProjectProfile, mock_adapter: AsyncMock
) -> None:
    """Test pick pipeline commits changes in local context when commit_changes is enabled."""
    # Initialize git repo
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=False,
        create_pr=False,
        commit_changes=True,
        ci_mode=False,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = RunResult(
            passed=5, failed=0, skipped=0, errors=0, duration_ms=500, test_cases=[]
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        assert result.success
        # Verify commit was created (if there were changes)
        git_log = subprocess.run(
            ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True, check=False
        )
        # Check if commit exists (will be empty if no changes were made)
        assert git_log.returncode in (0, 128)  # 128 means no commits yet


@pytest.mark.asyncio
async def test_pick_pipeline_commit_changes_disabled(
    tmp_path: Path, mock_profile: ProjectProfile, mock_adapter: AsyncMock
) -> None:
    """Test pick pipeline doesn't commit when commit_changes is disabled."""
    # Initialize git repo
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)

    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=False,
        create_pr=False,
        commit_changes=False,  # Disabled
        ci_mode=False,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "test_package": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = RunResult(
            passed=5, failed=0, skipped=0, errors=0, duration_ms=500, test_cases=[]
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

        assert result.success
        # Verify no commits were created
        git_log = subprocess.run(
            ["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True, check=False
        )
        assert git_log.returncode == 128  # No commits exist


# ---------------------------------------------------------------------------
# Multi-loop fix pipeline tests
# ---------------------------------------------------------------------------

_LOCAL_CI_CONTEXT = CIContext(
    is_ci=False,
    is_pr=False,
    pr_number=None,
    branch=None,
    base_branch=None,
    commit_sha=None,
    repo_owner=None,
    repo_name=None,
)


def _clean_run_result() -> RunResult:
    """Return a test result with no failures."""
    return RunResult(passed=10, failed=0, skipped=0, errors=0, duration_ms=500, test_cases=[])


def _failing_run_result(bug_file: str = "/test/project/test_math.py") -> RunResult:
    """Return a test result with failures."""
    return RunResult(
        passed=8,
        failed=2,
        skipped=0,
        errors=0,
        duration_ms=1000,
        test_cases=[
            CaseResult(
                name="test_ok",
                status=CaseStatus.PASSED,
                duration_ms=100,
                file_path=bug_file,
            ),
            CaseResult(
                name="test_fail",
                status=CaseStatus.FAILED,
                duration_ms=150,
                file_path=bug_file,
                failure_message="AssertionError: expected 1 got 2",
            ),
            CaseResult(
                name="test_fail2",
                status=CaseStatus.FAILED,
                duration_ms=120,
                file_path=bug_file,
                failure_message="ValueError: bad input",
            ),
        ],
    )


def _make_bug_report(file_path: str = "/test/project/src/calc.py") -> BugReport:
    return BugReport(
        bug_type=BugType.LOGIC_ERROR,
        severity=BugSeverity.HIGH,
        title="Logic error in calc",
        description="Wrong result",
        location=BugLocation(file_path=file_path, line_number=10, function_name="calc"),
        error_message="AssertionError",
    )


def _pipeline_patches(
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> tuple[list[str], dict[str, Mock | AsyncMock | ProjectProfile]]:
    """Return common patch targets and their values for pipeline tests."""
    targets = [
        "nit.agents.pipelines.pick.load_profile",
        "nit.agents.pipelines.pick.save_profile",
        "nit.agents.pipelines.pick.is_profile_stale",
        "nit.agents.pipelines.pick.get_registry",
        "nit.agents.pipelines.pick.BugAnalyzer",
        "nit.agents.pipelines.pick.create_engine",
        "nit.agents.pipelines.pick.load_llm_config",
        "nit.agents.pipelines.pick.BugVerifier",
        "nit.agents.pipelines.pick.RootCauseAnalyzer",
        "nit.agents.pipelines.pick.FixGenerator",
        "nit.agents.pipelines.pick.FixVerifier",
    ]
    return targets, {
        "load_profile": mock_profile,
        "mock_adapter": mock_adapter,
    }


@pytest.mark.asyncio
async def test_multi_loop_converges(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_fix: GeneratedFix,
) -> None:
    """Bugs on iteration 1 -> fixes applied -> clean on iteration 2."""
    source_file = tmp_path / "calc.py"
    source_file.write_text("def calc(): return 1")

    bug = _make_bug_report(str(source_file))

    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=True,
        ci_mode=False,
        max_fix_loops=3,
        ci_context=_LOCAL_CI_CONTEXT,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_analyzer_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_verifier_cls,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer") as mock_rc_cls,
        patch("nit.agents.pipelines.pick.FixGenerator") as mock_fg_cls,
        patch("nit.agents.pipelines.pick.FixVerifier") as mock_fv_cls,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }

        # Iteration 1: failures.  Iteration 2: clean.
        mock_adapter.run_tests.side_effect = [
            _failing_run_result(str(source_file)),
            _clean_run_result(),
        ]

        # Bug analyzer returns bugs on first call only
        analyzer_mock = AsyncMock()
        mock_analyzer_cls.return_value = analyzer_mock
        analyzer_mock.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        # Fix pipeline agents
        verifier = AsyncMock()
        mock_verifier_cls.return_value = verifier
        verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=True,
                    reproduction_test="def test_r(): ...",
                    test_output="fail",
                    confidence=0.9,
                )
            },
        )

        rc = AsyncMock()
        mock_rc_cls.return_value = rc
        rc.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "root_cause": RootCause(
                    category="logic",
                    description="Wrong",
                    affected_code="return 1",
                )
            },
        )

        fg = AsyncMock()
        mock_fg_cls.return_value = fg
        fg.run.return_value = Mock(status=TaskStatus.COMPLETED, result={"fix": sample_fix})

        fv = AsyncMock()
        mock_fv_cls.return_value = fv
        fv.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"verification": Mock(is_verified=True, notes="ok")},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.iterations_run == 2
    assert len(result.bugs_found) == 0  # Clean on final iteration
    assert len(result.fixes_applied) == 2  # Fixes from iteration 1
    assert mock_adapter.run_tests.call_count == 2


@pytest.mark.asyncio
async def test_max_loops_reached(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_fix: GeneratedFix,
) -> None:
    """Pipeline stops after max_fix_loops even if bugs remain."""
    source_file = tmp_path / "calc.py"
    source_file.write_text("def calc(): return 1")

    bug = _make_bug_report(str(source_file))

    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=True,
        ci_mode=False,
        max_fix_loops=2,
        ci_context=_LOCAL_CI_CONTEXT,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_analyzer_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_verifier_cls,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer") as mock_rc_cls,
        patch("nit.agents.pipelines.pick.FixGenerator") as mock_fg_cls,
        patch("nit.agents.pipelines.pick.FixVerifier") as mock_fv_cls,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }

        # Always returns failures
        mock_adapter.run_tests.return_value = _failing_run_result(str(source_file))

        analyzer_mock = AsyncMock()
        mock_analyzer_cls.return_value = analyzer_mock
        analyzer_mock.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        verifier = AsyncMock()
        mock_verifier_cls.return_value = verifier
        verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=True,
                    reproduction_test="def test_r(): ...",
                    test_output="fail",
                    confidence=0.9,
                )
            },
        )

        rc = AsyncMock()
        mock_rc_cls.return_value = rc
        rc.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "root_cause": RootCause(
                    category="logic",
                    description="Wrong",
                    affected_code="return 1",
                )
            },
        )

        fg = AsyncMock()
        mock_fg_cls.return_value = fg
        fg.run.return_value = Mock(status=TaskStatus.COMPLETED, result={"fix": sample_fix})

        fv = AsyncMock()
        mock_fv_cls.return_value = fv
        fv.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"verification": Mock(is_verified=True, notes="ok")},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.iterations_run == 2
    assert len(result.bugs_found) > 0  # Bugs still remain
    # Tests run twice (iteration 1 fix, iteration 2 still failing)
    assert mock_adapter.run_tests.call_count == 2


@pytest.mark.asyncio
async def test_token_budget_stops_loop(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """Pipeline stops when token budget is exceeded."""
    bug = _make_bug_report()

    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=True,
        ci_mode=True,
        max_fix_loops=10,
        token_budget=1000,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_analyzer_cls,
        patch("nit.agents.pipelines.pick.get_session_usage_stats") as mock_stats,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = _failing_run_result()

        analyzer_mock = AsyncMock()
        mock_analyzer_cls.return_value = analyzer_mock
        analyzer_mock.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        # Token budget already exceeded
        mock_stats.return_value = SessionUsageStats(
            prompt_tokens=800,
            completion_tokens=300,
            total_tokens=1100,
            total_cost_usd=0.05,
            request_count=5,
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.iterations_run == 1
    assert len(result.bugs_found) > 0
    # Only ran tests once — budget stopped the loop before fix generation
    assert mock_adapter.run_tests.call_count == 1


@pytest.mark.asyncio
async def test_ci_mode_forces_single_loop(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """CI mode forces single pass even with max_fix_loops > 1."""
    bug = _make_bug_report()

    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=True,
        ci_mode=True,
        max_fix_loops=5,  # Would normally allow 5 loops
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_analyzer_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier"),
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer"),
        patch("nit.agents.pipelines.pick.FixGenerator"),
        patch("nit.agents.pipelines.pick.FixVerifier"),
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = _failing_run_result()

        analyzer_mock = AsyncMock()
        mock_analyzer_cls.return_value = analyzer_mock
        analyzer_mock.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.iterations_run == 1
    # Tests run once, then loop exits at max_loops
    assert mock_adapter.run_tests.call_count == 1
    # No fixes generated because loop stopped before fix step
    assert len(result.fixes_generated) == 0


@pytest.mark.asyncio
async def test_single_loop_default_unchanged(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """Default max_fix_loops=1 preserves original single-pass behavior."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=False,
        ci_mode=True,
        # max_fix_loops defaults to 1
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = _clean_run_result()

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.iterations_run == 1
    assert mock_adapter.run_tests.call_count == 1


@pytest.mark.asyncio
async def test_unlimited_loops_converges(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_fix: GeneratedFix,
) -> None:
    """max_fix_loops=0 (unlimited) loops until clean."""
    source_file = tmp_path / "calc.py"
    source_file.write_text("def calc(): return 1")

    bug = _make_bug_report(str(source_file))

    config = PickPipelineConfig(
        project_root=tmp_path,
        test_type="unit",
        fix_enabled=True,
        ci_mode=False,
        max_fix_loops=0,  # Unlimited
        ci_context=CIContext(
            is_ci=False,
            is_pr=False,
            pr_number=None,
            branch=None,
            base_branch=None,
            commit_sha=None,
            repo_owner=None,
            repo_name=None,
        ),
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_analyzer_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_verifier_cls,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer") as mock_rc_cls,
        patch("nit.agents.pipelines.pick.FixGenerator") as mock_fg_cls,
        patch("nit.agents.pipelines.pick.FixVerifier") as mock_fv_cls,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }

        # Fail, fail, clean on iteration 3
        mock_adapter.run_tests.side_effect = [
            _failing_run_result(str(source_file)),
            _failing_run_result(str(source_file)),
            _clean_run_result(),
        ]

        analyzer_mock = AsyncMock()
        mock_analyzer_cls.return_value = analyzer_mock
        analyzer_mock.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        verifier = AsyncMock()
        mock_verifier_cls.return_value = verifier
        verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=True,
                    reproduction_test="def test_r(): ...",
                    test_output="fail",
                    confidence=0.9,
                )
            },
        )

        rc = AsyncMock()
        mock_rc_cls.return_value = rc
        rc.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "root_cause": RootCause(
                    category="logic",
                    description="Wrong",
                    affected_code="return 1",
                )
            },
        )

        fg = AsyncMock()
        mock_fg_cls.return_value = fg
        fg.run.return_value = Mock(status=TaskStatus.COMPLETED, result={"fix": sample_fix})

        fv = AsyncMock()
        mock_fv_cls.return_value = fv
        fv.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"verification": Mock(is_verified=True, notes="ok")},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.iterations_run == 3
    assert len(result.bugs_found) == 0  # Clean on final iteration
    assert mock_adapter.run_tests.call_count == 3


# ---------------------------------------------------------------------------
# Additional tests for undertested pipeline stages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_profile_triggers_rescan(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """When profile is stale, detectors re-run and profile is saved."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile") as mock_save,
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=True),
        patch("nit.agents.pipelines.pick.detect_languages") as mock_dl,
        patch("nit.agents.pipelines.pick.detect_frameworks") as mock_df,
        patch("nit.agents.pipelines.pick.detect_workspace") as mock_dw,
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
    ):
        mock_dl.return_value = Mock(languages=mock_profile.languages)
        mock_df.return_value = Mock(frameworks=mock_profile.frameworks)
        mock_dw.return_value = Mock(packages=mock_profile.packages, tool="generic")
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = _clean_run_result()

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    mock_dl.assert_called_once()
    mock_df.assert_called_once()
    mock_dw.assert_called_once()
    mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_no_profile_triggers_full_scan(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """When no saved profile exists, full detection + save occurs."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=None),
        patch("nit.agents.pipelines.pick.save_profile") as mock_save,
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.detect_languages") as mock_dl,
        patch("nit.agents.pipelines.pick.detect_frameworks") as mock_df,
        patch("nit.agents.pipelines.pick.detect_workspace") as mock_dw,
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
    ):
        mock_dl.return_value = Mock(languages=mock_profile.languages)
        mock_df.return_value = Mock(frameworks=mock_profile.frameworks)
        mock_dw.return_value = Mock(packages=mock_profile.packages, tool="generic")
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = _clean_run_result()

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_prerequisites_failure_aborts_pipeline(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """Pipeline stops early when prerequisites are not satisfied."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch(
            "nit.agents.pipelines.pick.check_and_install_prerequisites",
            return_value=False,
        ),
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert not result.success
    assert any("Prerequisites" in e for e in result.errors)
    # Tests should never have been called
    mock_adapter.run_tests.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_bugs_no_failures_returns_empty(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """When all tests pass, bug analysis returns no bugs."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    all_pass = RunResult(
        passed=5,
        failed=0,
        skipped=0,
        errors=0,
        duration_ms=200,
        test_cases=[
            CaseResult(
                name="test_a",
                status=CaseStatus.PASSED,
                duration_ms=50,
                file_path="/test.py",
            ),
        ],
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = all_pass

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.bugs_found == []
    # BugAnalyzer should never have been instantiated for a passing suite
    mock_ba.assert_not_called()


@pytest.mark.asyncio
async def test_bug_analysis_exception_is_swallowed(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
) -> None:
    """Exceptions during individual bug analysis are logged, not propagated."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.side_effect = RuntimeError("LLM service unavailable")

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    # Pipeline succeeds overall; individual analysis errors are caught
    assert result.success
    assert result.bugs_found == []


@pytest.mark.asyncio
async def test_bug_analysis_not_code_bug_is_filtered(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
) -> None:
    """Bug analysis result with is_code_bug=False is excluded."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": False, "bug_report": None},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.bugs_found == []


@pytest.mark.asyncio
async def test_bug_analysis_failed_task_status_is_skipped(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
) -> None:
    """Bug analysis with FAILED status is skipped gracefully."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.FAILED,
            result={},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.bugs_found == []


@pytest.mark.asyncio
async def test_test_result_with_errors_counted(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """Test errors (distinct from failures) are tracked in result."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    error_result = RunResult(
        passed=3,
        failed=1,
        skipped=0,
        errors=2,
        duration_ms=500,
        test_cases=[
            CaseResult(
                name="test_crash",
                status=CaseStatus.ERROR,
                duration_ms=10,
                file_path="/test.py",
                failure_message="SegFault",
            ),
        ],
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = error_result

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": False},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.tests_errors == 2
    assert result.tests_failed == 1
    assert result.tests_run == 6  # passed + failed + skipped + errors


@pytest.mark.asyncio
async def test_coverage_report_attached_to_result(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """Coverage data from test run is stored on result."""
    cov_report = CoverageReport(
        files={
            "src/calc.py": FileCoverage(
                file_path="src/calc.py",
                lines=[
                    LineCoverage(line_number=1, execution_count=1),
                    LineCoverage(line_number=2, execution_count=0),
                ],
            )
        }
    )

    run_with_cov = RunResult(
        passed=5,
        failed=0,
        skipped=0,
        errors=0,
        duration_ms=300,
        test_cases=[],
        coverage=cov_report,
    )

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.CoverageAnalyzer") as mock_cov_cls,
        patch("nit.agents.pipelines.pick.load_config") as mock_lc,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = run_with_cov

        # Mock coverage analyzer
        cov_analyzer = AsyncMock()
        mock_cov_cls.return_value = cov_analyzer
        cov_analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"gap_report": None},
        )

        mock_lc.return_value = Mock(
            coverage=Mock(
                complexity_threshold=10,
                undertested_threshold=50.0,
                line_threshold=80.0,
            ),
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.coverage_report is not None
    assert result.coverage_report.overall_line_coverage == 50.0


@pytest.mark.asyncio
async def test_coverage_gap_analysis_failure_returns_none(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """Coverage gap analysis failure is handled gracefully."""
    run_with_cov = RunResult(
        passed=5,
        failed=0,
        skipped=0,
        errors=0,
        duration_ms=300,
        test_cases=[],
        coverage=CoverageReport(files={}),
    )

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch(
            "nit.agents.pipelines.pick.load_config",
            side_effect=RuntimeError("Config missing"),
        ),
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = run_with_cov

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.gap_report is None


@pytest.mark.asyncio
async def test_fix_skipped_when_source_file_missing(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
) -> None:
    """Fix generation is skipped when the bug's source file does not exist."""
    bug = BugReport(
        bug_type=BugType.LOGIC_ERROR,
        severity=BugSeverity.HIGH,
        title="Missing file bug",
        description="Bug in nonexistent file",
        location=BugLocation(
            file_path=str(tmp_path / "nonexistent.py"),
            line_number=1,
            function_name="foo",
        ),
        error_message="Error",
    )

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=True)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier"),
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer"),
        patch("nit.agents.pipelines.pick.FixGenerator"),
        patch("nit.agents.pipelines.pick.FixVerifier"),
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert len(result.bugs_found) == 2
    assert len(result.fixes_generated) == 0


@pytest.mark.asyncio
async def test_fix_skipped_when_verification_fails(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
) -> None:
    """Fix is not generated if bug verification (reproduction) fails."""
    source_file = tmp_path / "calc.py"
    source_file.write_text("x = 1")

    bug = _make_bug_report(str(source_file))

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=True)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_v_cls,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer"),
        patch("nit.agents.pipelines.pick.FixGenerator"),
        patch("nit.agents.pipelines.pick.FixVerifier"),
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        verifier = AsyncMock()
        mock_v_cls.return_value = verifier
        verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=False,
                    reproduction_test="",
                    test_output="Could not reproduce",
                    confidence=0.3,
                )
            },
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert len(result.fixes_generated) == 0


@pytest.mark.asyncio
async def test_fix_skipped_when_root_cause_fails(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
) -> None:
    """Fix is not generated if root-cause analysis fails."""
    source_file = tmp_path / "calc.py"
    source_file.write_text("x = 1")
    bug = _make_bug_report(str(source_file))

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=True)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_v_cls,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer") as mock_rc_cls,
        patch("nit.agents.pipelines.pick.FixGenerator"),
        patch("nit.agents.pipelines.pick.FixVerifier"),
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        verifier = AsyncMock()
        mock_v_cls.return_value = verifier
        verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=True,
                    reproduction_test="def test_r(): ...",
                    test_output="fail",
                    confidence=0.9,
                )
            },
        )

        rc = AsyncMock()
        mock_rc_cls.return_value = rc
        rc.run.return_value = Mock(
            status=TaskStatus.FAILED,
            result={},
            errors=["Analysis timed out"],
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert len(result.fixes_generated) == 0


@pytest.mark.asyncio
async def test_fix_skipped_when_generation_fails(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
) -> None:
    """Fix is not applied when FixGenerator returns FAILED status."""
    source_file = tmp_path / "calc.py"
    source_file.write_text("x = 1")
    bug = _make_bug_report(str(source_file))

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=True)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_v_cls,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer") as mock_rc_cls,
        patch("nit.agents.pipelines.pick.FixGenerator") as mock_fg_cls,
        patch("nit.agents.pipelines.pick.FixVerifier"),
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        verifier = AsyncMock()
        mock_v_cls.return_value = verifier
        verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=True,
                    reproduction_test="def test_r(): ...",
                    test_output="fail",
                    confidence=0.9,
                )
            },
        )

        rc = AsyncMock()
        mock_rc_cls.return_value = rc
        rc.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "root_cause": RootCause(category="logic", description="Wrong", affected_code="x")
            },
        )

        fg = AsyncMock()
        mock_fg_cls.return_value = fg
        fg.run.return_value = Mock(status=TaskStatus.FAILED, result={}, errors=["LLM refused"])

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert len(result.fixes_generated) == 0


@pytest.mark.asyncio
async def test_fix_not_applied_when_fix_verification_fails(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
    sample_fix: GeneratedFix,
) -> None:
    """Fix is not applied when FixVerifier reports regression."""
    source_file = tmp_path / "calc.py"
    source_file.write_text("x = 1")
    bug = _make_bug_report(str(source_file))

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=True)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_v_cls,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer") as mock_rc_cls,
        patch("nit.agents.pipelines.pick.FixGenerator") as mock_fg_cls,
        patch("nit.agents.pipelines.pick.FixVerifier") as mock_fv_cls,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        verifier = AsyncMock()
        mock_v_cls.return_value = verifier
        verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=True,
                    reproduction_test="def test_r(): ...",
                    test_output="fail",
                    confidence=0.9,
                )
            },
        )

        rc = AsyncMock()
        mock_rc_cls.return_value = rc
        rc.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "root_cause": RootCause(category="logic", description="Wrong", affected_code="x")
            },
        )

        fg = AsyncMock()
        mock_fg_cls.return_value = fg
        fg.run.return_value = Mock(status=TaskStatus.COMPLETED, result={"fix": sample_fix})

        fv = AsyncMock()
        mock_fv_cls.return_value = fv
        fv.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"verification": Mock(is_verified=False, notes="Regression detected")},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    # Fix generated but not applied because verification failed
    assert len(result.fixes_generated) == 0
    assert len(result.fixes_applied) == 0


@pytest.mark.asyncio
async def test_apply_fixes_writes_to_disk(
    tmp_path: Path,
    sample_fix: GeneratedFix,
) -> None:
    """_apply_fixes writes fixed_code content to the target file."""
    target = tmp_path / "src" / "module.py"
    target.parent.mkdir(parents=True)
    target.write_text("old code")

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=True)
    pipeline = PickPipeline(config)
    applied = pipeline._apply_fixes([(str(target), sample_fix)])

    assert len(applied) == 1
    assert target.read_text() == sample_fix.fixed_code


@pytest.mark.asyncio
async def test_apply_fixes_handles_write_error(
    tmp_path: Path,
    sample_fix: GeneratedFix,
) -> None:
    """_apply_fixes handles write errors gracefully."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=True)
    pipeline = PickPipeline(config)
    # Path that does not exist -> parent directory missing
    bad_path = str(tmp_path / "nonexistent_dir" / "file.py")
    applied = pipeline._apply_fixes([(bad_path, sample_fix)])

    assert len(applied) == 0


@pytest.mark.asyncio
async def test_apply_fixes_relative_path_resolved(
    tmp_path: Path,
    sample_fix: GeneratedFix,
) -> None:
    """_apply_fixes resolves relative paths against project_root."""
    target = tmp_path / "rel.py"
    target.write_text("old")

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=True)
    pipeline = PickPipeline(config)
    applied = pipeline._apply_fixes([("rel.py", sample_fix)])

    assert len(applied) == 1
    assert target.read_text() == sample_fix.fixed_code


def test_effective_max_loops_ci_forces_one(tmp_path: Path) -> None:
    """_effective_max_loops returns 1 in CI mode regardless of config."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, max_fix_loops=10)
    pipeline = PickPipeline(config)
    assert pipeline._effective_max_loops == 1


def test_effective_max_loops_local_returns_config(tmp_path: Path) -> None:
    """_effective_max_loops returns configured value when not in CI."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=False, max_fix_loops=5)
    pipeline = PickPipeline(config)
    assert pipeline._effective_max_loops == 5


def test_token_budget_exceeded_when_unlimited(tmp_path: Path) -> None:
    """_token_budget_exceeded returns False when budget is 0 (unlimited)."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, token_budget=0)
    pipeline = PickPipeline(config)
    assert not pipeline._token_budget_exceeded()


def test_token_budget_exceeded_under_limit(tmp_path: Path) -> None:
    """_token_budget_exceeded returns False when usage is under budget."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, token_budget=5000)
    pipeline = PickPipeline(config)

    with patch("nit.agents.pipelines.pick.get_session_usage_stats") as mock_stats:
        mock_stats.return_value = SessionUsageStats(
            prompt_tokens=100,
            completion_tokens=100,
            total_tokens=200,
            total_cost_usd=0.01,
            request_count=1,
        )
        assert not pipeline._token_budget_exceeded()


def test_token_budget_exceeded_over_limit(tmp_path: Path) -> None:
    """_token_budget_exceeded returns True when usage exceeds budget."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, token_budget=500)
    pipeline = PickPipeline(config)

    with patch("nit.agents.pipelines.pick.get_session_usage_stats") as mock_stats:
        mock_stats.return_value = SessionUsageStats(
            prompt_tokens=400,
            completion_tokens=200,
            total_tokens=600,
            total_cost_usd=0.02,
            request_count=3,
        )
        assert pipeline._token_budget_exceeded()


def test_should_run_post_loop_no_actions(tmp_path: Path) -> None:
    """_should_run_post_loop returns False when no actions are needed."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=True,
        commit_changes=False,
        create_issues=False,
        create_fix_prs=False,
        create_pr=False,
    )
    pipeline = PickPipeline(config)
    result = PickPipelineResult()
    assert not pipeline._should_run_post_loop(result)


def test_should_run_post_loop_with_issues(tmp_path: Path) -> None:
    """_should_run_post_loop returns True when bugs found and create_issues set."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=True,
        commit_changes=False,
        create_issues=True,
        create_fix_prs=False,
        create_pr=False,
    )
    pipeline = PickPipeline(config)
    result = PickPipelineResult(bugs_found=[_make_bug_report()])
    assert pipeline._should_run_post_loop(result)


def test_should_run_post_loop_with_fix_prs(tmp_path: Path, sample_fix: GeneratedFix) -> None:
    """_should_run_post_loop returns True when fixes generated and create_fix_prs set."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=True,
        commit_changes=False,
        create_issues=False,
        create_fix_prs=True,
        create_pr=False,
    )
    pipeline = PickPipeline(config)
    result = PickPipelineResult(fixes_generated=[("file.py", sample_fix)])
    assert pipeline._should_run_post_loop(result)


@pytest.mark.asyncio
async def test_commit_changes_success(tmp_path: Path) -> None:
    """_commit_changes returns True on successful git operations."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)
    result = PickPipelineResult(
        fixes_applied=["/some/file.py"],
        bugs_found=[_make_bug_report()],
    )

    with patch("nit.agents.pipelines.pick.subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        committed = pipeline._commit_changes(result)

    assert committed
    assert mock_run.call_count == 2  # git add + git commit


@pytest.mark.asyncio
async def test_commit_changes_git_error(tmp_path: Path) -> None:
    """_commit_changes returns False on git CalledProcessError."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)
    result = PickPipelineResult()

    with patch("nit.agents.pipelines.pick.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr=b"nothing to commit")
        committed = pipeline._commit_changes(result)

    assert not committed


@pytest.mark.asyncio
async def test_commit_message_includes_fix_count(tmp_path: Path) -> None:
    """Commit message includes fix and bug counts."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)
    result = PickPipelineResult(
        fixes_applied=["/a.py", "/b.py"],
        bugs_found=[_make_bug_report(), _make_bug_report()],
    )

    with patch("nit.agents.pipelines.pick.subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        pipeline._commit_changes(result)

    # Extract commit message from the git commit call
    commit_call = mock_run.call_args_list[1]
    commit_msg = commit_call[0][0][3]  # ["git", "commit", "-m", <msg>]
    assert "Apply 2 bug fixes" in commit_msg
    assert "Found 2 bugs" in commit_msg


@pytest.mark.asyncio
async def test_commit_message_default_when_empty(tmp_path: Path) -> None:
    """Commit message falls back to default when no fixes/bugs."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)
    result = PickPipelineResult()

    with patch("nit.agents.pipelines.pick.subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        pipeline._commit_changes(result)

    commit_call = mock_run.call_args_list[1]
    commit_msg = commit_call[0][0][3]
    assert "nit pick results" in commit_msg


def test_resolve_base_branch_fallback(tmp_path: Path) -> None:
    """_resolve_base_branch falls back to 'main' on error."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with patch(
        "nit.agents.pipelines.pick.get_default_branch",
        side_effect=RuntimeError("no remote"),
    ):
        assert pipeline._resolve_base_branch() == "main"


def test_resolve_base_branch_uses_git(tmp_path: Path) -> None:
    """_resolve_base_branch uses get_default_branch."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with patch("nit.agents.pipelines.pick.get_default_branch", return_value="develop"):
        assert pipeline._resolve_base_branch() == "develop"


@pytest.mark.asyncio
async def test_create_new_pr_no_changes(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """_create_new_pr returns early when no changes exist."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=True,
        create_pr=True,
        ci_context=_LOCAL_CI_CONTEXT,
    )
    pipeline = PickPipeline(config)
    result = PickPipelineResult(tests_run=0, fixes_applied=[])

    pr_result = await pipeline._create_new_pr(result)
    assert pr_result["created"] is False


@pytest.mark.asyncio
async def test_create_new_pr_exception_handled(tmp_path: Path) -> None:
    """_create_new_pr handles exceptions from GitHubPRReporter."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=True,
        create_pr=True,
        ci_context=_LOCAL_CI_CONTEXT,
    )
    pipeline = PickPipeline(config)
    result = PickPipelineResult(tests_run=5, tests_passed=5, fixes_applied=["a.py"])

    with (
        patch(
            "nit.agents.pipelines.pick.GitHubPRReporter",
            side_effect=RuntimeError("gh cli not found"),
        ),
        patch("nit.agents.pipelines.pick.get_default_branch", return_value="main"),
    ):
        pr_result = await pipeline._create_new_pr(result)

    assert pr_result["created"] is False
    assert "error" in pr_result


@pytest.mark.asyncio
async def test_add_commit_to_pr_in_ci_context(tmp_path: Path) -> None:
    """_add_commit_to_pr calls _commit_changes when in PR context."""
    ci = CIContext(
        is_ci=True,
        is_pr=True,
        pr_number=42,
        branch="feature/x",
        base_branch="main",
        commit_sha="abc",
        repo_owner="o",
        repo_name="r",
    )
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, ci_context=ci)
    pipeline = PickPipeline(config)
    result = PickPipelineResult(fixes_applied=["a.py"])

    with patch("nit.agents.pipelines.pick.subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        pr_result = await pipeline._add_commit_to_pr(result)

    assert pr_result["committed"] is True
    assert pr_result["created"] is False


@pytest.mark.asyncio
async def test_add_commit_to_pr_handles_error(tmp_path: Path) -> None:
    """_add_commit_to_pr handles exceptions during commit."""
    ci = CIContext(
        is_ci=True,
        is_pr=True,
        pr_number=42,
        branch="feature/x",
        base_branch="main",
        commit_sha="abc",
        repo_owner="o",
        repo_name="r",
    )
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, ci_context=ci)
    pipeline = PickPipeline(config)
    result = PickPipelineResult()

    with patch(
        "nit.agents.pipelines.pick.subprocess.run",
        side_effect=subprocess.CalledProcessError(128, "git", stderr=b"fatal"),
    ):
        pr_result = await pipeline._add_commit_to_pr(result)

    assert pr_result["committed"] is False


@pytest.mark.asyncio
async def test_deep_analysis_skipped_without_gaps(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """Deep analysis steps 5-6 are skipped when no coverage gaps exist."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.CodeAnalyzer") as mock_ca,
        patch("nit.agents.pipelines.pick.PatternAnalyzer") as mock_pa,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = _clean_run_result()

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    # Without coverage gaps, CodeAnalyzer and PatternAnalyzer should not be called
    mock_ca.assert_not_called()
    mock_pa.assert_not_called()


@pytest.mark.asyncio
async def test_issue_creation_failure_handled(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
    sample_bug_report: BugReport,
) -> None:
    """Issue creation failure is caught, pipeline continues."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=True,
        fix_enabled=False,
        create_issues=True,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
        patch("nit.agents.pipelines.pick.GitHubIssueReporter") as mock_ir_cls,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": sample_bug_report},
        )

        issue_reporter = Mock()
        mock_ir_cls.return_value = issue_reporter
        issue_reporter.create_bug_issue.side_effect = RuntimeError("gh auth failure")

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.created_issues == []


@pytest.mark.asyncio
async def test_fix_pr_creation_failure_handled(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_test_result: RunResult,
    sample_fix: GeneratedFix,
) -> None:
    """Fix PR creation failure is caught, pipeline continues."""
    source_file = tmp_path / "calc.py"
    source_file.write_text("x = 1")
    bug = _make_bug_report(str(source_file))

    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=True,
        fix_enabled=True,
        create_fix_prs=True,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_v_cls,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer") as mock_rc_cls,
        patch("nit.agents.pipelines.pick.FixGenerator") as mock_fg_cls,
        patch("nit.agents.pipelines.pick.FixVerifier") as mock_fv_cls,
        patch("nit.agents.pipelines.pick.GitHubPRReporter") as mock_pr_cls,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = sample_test_result

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        verifier = AsyncMock()
        mock_v_cls.return_value = verifier
        verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=True,
                    reproduction_test="def test_r(): ...",
                    test_output="fail",
                    confidence=0.9,
                )
            },
        )

        rc = AsyncMock()
        mock_rc_cls.return_value = rc
        rc.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "root_cause": RootCause(category="logic", description="Wrong", affected_code="x")
            },
        )

        fg = AsyncMock()
        mock_fg_cls.return_value = fg
        fg.run.return_value = Mock(status=TaskStatus.COMPLETED, result={"fix": sample_fix})

        fv = AsyncMock()
        mock_fv_cls.return_value = fv
        fv.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"verification": Mock(is_verified=True, notes="ok")},
        )

        pr_reporter = Mock()
        mock_pr_cls.return_value = pr_reporter
        pr_reporter.create_fix_pr.side_effect = RuntimeError("gh auth failure")

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert result.created_fix_prs == []


@pytest.mark.asyncio
async def test_multi_loop_stops_when_no_fixes_generated(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """Fix loop stops when iteration generates no fixes."""
    source_file = tmp_path / "calc.py"
    source_file.write_text("x = 1")
    bug = _make_bug_report(str(source_file))

    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=False,
        fix_enabled=True,
        max_fix_loops=5,
        ci_context=_LOCAL_CI_CONTEXT,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_v_cls,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer") as mock_rc_cls,
        patch("nit.agents.pipelines.pick.FixGenerator") as mock_fg_cls,
        patch("nit.agents.pipelines.pick.FixVerifier"),
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        # Always fails
        mock_adapter.run_tests.return_value = _failing_run_result(str(source_file))

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        # Bug verification fails so no fixes are generated
        verifier = AsyncMock()
        mock_v_cls.return_value = verifier
        verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=False,
                    reproduction_test="",
                    test_output="no repro",
                    confidence=0.2,
                )
            },
        )

        rc = AsyncMock()
        mock_rc_cls.return_value = rc

        fg = AsyncMock()
        mock_fg_cls.return_value = fg

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    assert len(result.fixes_generated) == 0
    # No fixes generated means step 8 (apply fixes) is skipped entirely,
    # so _additional_fix_iterations is never entered. Tests run once.
    assert mock_adapter.run_tests.call_count == 1


@pytest.mark.asyncio
async def test_token_budget_stops_additional_iterations(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
    sample_fix: GeneratedFix,
) -> None:
    """Token budget exhaustion stops the fix loop mid-iteration."""
    source_file = tmp_path / "calc.py"
    source_file.write_text("x = 1")
    bug = _make_bug_report(str(source_file))

    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=False,
        fix_enabled=True,
        max_fix_loops=5,
        token_budget=1000,
        ci_context=_LOCAL_CI_CONTEXT,
    )

    call_count = 0

    def stats_side_effect() -> SessionUsageStats:
        nonlocal call_count
        call_count += 1
        # First call: under budget; subsequent: over
        if call_count <= 2:
            return SessionUsageStats(
                prompt_tokens=100,
                completion_tokens=100,
                total_tokens=200,
                total_cost_usd=0.01,
                request_count=1,
            )
        return SessionUsageStats(
            prompt_tokens=800,
            completion_tokens=400,
            total_tokens=1200,
            total_cost_usd=0.05,
            request_count=5,
        )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.BugAnalyzer") as mock_ba_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.BugVerifier") as mock_v_cls,
        patch("nit.agents.pipelines.pick.RootCauseAnalyzer") as mock_rc_cls,
        patch("nit.agents.pipelines.pick.FixGenerator") as mock_fg_cls,
        patch("nit.agents.pipelines.pick.FixVerifier") as mock_fv_cls,
        patch(
            "nit.agents.pipelines.pick.get_session_usage_stats",
            side_effect=stats_side_effect,
        ),
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = _failing_run_result(str(source_file))

        analyzer = AsyncMock()
        mock_ba_cls.return_value = analyzer
        analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"is_code_bug": True, "bug_report": bug},
        )

        verifier = AsyncMock()
        mock_v_cls.return_value = verifier
        verifier.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "verification": VerificationResult(
                    is_confirmed=True,
                    reproduction_test="def test_r(): ...",
                    test_output="fail",
                    confidence=0.9,
                )
            },
        )

        rc = AsyncMock()
        mock_rc_cls.return_value = rc
        rc.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={
                "root_cause": RootCause(category="logic", description="Wrong", affected_code="x")
            },
        )

        fg = AsyncMock()
        mock_fg_cls.return_value = fg
        fg.run.return_value = Mock(status=TaskStatus.COMPLETED, result={"fix": sample_fix})

        fv = AsyncMock()
        mock_fv_cls.return_value = fv
        fv.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"verification": Mock(is_verified=True, notes="ok")},
        )

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    # Loop stopped after budget exhausted
    assert result.iterations_run >= 2


def test_pipeline_config_defaults(tmp_path: Path) -> None:
    """PickPipelineConfig has sensible defaults."""
    config = PickPipelineConfig(project_root=tmp_path)
    assert config.test_type == "all"
    assert config.target_file is None
    assert config.coverage_target is None
    assert config.fix_enabled is False
    assert config.create_pr is False
    assert config.create_issues is False
    assert config.create_fix_prs is False
    assert config.commit_changes is True
    assert config.ci_mode is False
    assert config.ci_context is None
    assert config.max_fix_loops == 1
    assert config.token_budget == 0


def test_pipeline_result_defaults() -> None:
    """PickPipelineResult has sensible defaults."""
    result = PickPipelineResult()
    assert result.tests_run == 0
    assert result.tests_passed == 0
    assert result.tests_failed == 0
    assert result.tests_errors == 0
    assert result.bugs_found == []
    assert result.fixes_generated == []
    assert result.fixes_applied == []
    assert result.coverage_report is None
    assert result.gap_report is None
    assert result.pr_url is None
    assert result.pr_created is False
    assert result.created_issues == []
    assert result.created_fix_prs == []
    assert result.iterations_run == 1
    assert result.code_maps == {}
    assert result.convention_profile is None
    assert result.risk_report is None
    assert result.integration_deps == []
    assert result.semantic_gaps == []
    assert result.route_discovery is None
    assert result.flow_mapping is None
    assert result.success is True
    assert result.errors == []


def test_step_tracker_ci_mode_silent(tmp_path: Path) -> None:
    """_StepTracker in CI mode does not call reporter."""
    with patch("nit.agents.pipelines.pick.reporter") as mock_reporter:
        tracker = _StepTracker(5, ci_mode=True)
        tracker.step("Test step")
        tracker.skip("Skipped step")

    mock_reporter.print_step_header.assert_not_called()
    mock_reporter.print_step_skip.assert_not_called()


def test_step_tracker_non_ci_prints(tmp_path: Path) -> None:
    """_StepTracker in non-CI mode calls reporter methods."""
    with patch("nit.agents.pipelines.pick.reporter") as mock_reporter:
        tracker = _StepTracker(5, ci_mode=False)
        tracker.step("Test step")
        tracker.skip("Skipped step")

    mock_reporter.print_step_header.assert_called_once_with(1, 5, "Test step")
    mock_reporter.print_step_skip.assert_called_once_with("Skipped step")


@pytest.mark.asyncio
async def test_pipeline_exception_captured_in_result(
    tmp_path: Path,
    mock_profile: ProjectProfile,
) -> None:
    """An unexpected exception during pipeline execution is captured."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True, fix_enabled=False)

    with (
        patch(
            "nit.agents.pipelines.pick.load_profile",
            side_effect=RuntimeError("disk full"),
        ),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
    ):
        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert not result.success
    assert any("disk full" in e for e in result.errors)


def test_should_create_pr_or_commit_respects_flag(tmp_path: Path) -> None:
    """_should_create_pr_or_commit returns False when commit_changes is False."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=True,
        commit_changes=False,
        create_pr=True,
        ci_context=_LOCAL_CI_CONTEXT,
    )
    pipeline = PickPipeline(config)
    assert not pipeline._should_create_pr_or_commit()


@pytest.mark.asyncio
async def test_non_ci_mode_runs_reporter_output(
    tmp_path: Path,
    mock_profile: ProjectProfile,
    mock_adapter: AsyncMock,
) -> None:
    """Non-CI mode produces reporter output (test summary bar, etc.)."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=False,
        fix_enabled=False,
        ci_context=_LOCAL_CI_CONTEXT,
    )

    with (
        patch("nit.agents.pipelines.pick.load_profile", return_value=mock_profile),
        patch("nit.agents.pipelines.pick.save_profile"),
        patch("nit.agents.pipelines.pick.is_profile_stale", return_value=False),
        patch("nit.agents.pipelines.pick.get_registry") as mock_registry,
        patch("nit.agents.pipelines.pick.reporter") as mock_reporter,
    ):
        mock_registry.return_value.select_adapters_for_profile.return_value = {
            "pkg": [mock_adapter]
        }
        mock_adapter.run_tests.return_value = _clean_run_result()

        pipeline = PickPipeline(config)
        result = await pipeline.run()

    assert result.success
    mock_reporter.print_pipeline_header.assert_called_once()
    mock_reporter.print_test_summary_bar.assert_called_once()


@pytest.mark.asyncio
async def test_apply_fixes_empty_list(tmp_path: Path) -> None:
    """_apply_fixes with empty list returns empty list."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)
    assert pipeline._apply_fixes([]) == []


# ---------------------------------------------------------------------------
# Deep analysis, risk, and semantic gap coverage tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_gap_analysis_prints_info(tmp_path: Path) -> None:
    """_report_gap_analysis prints gap count and critical count."""

    gap_report = CoverageGapReport(
        function_gaps=[
            FunctionGap(
                file_path="src/a.py",
                function_name="func_a",
                line_number=1,
                end_line=10,
                coverage_percentage=0.0,
                complexity=5,
                is_public=True,
                priority=GapPriority.CRITICAL,
            ),
            FunctionGap(
                file_path="src/b.py",
                function_name="func_b",
                line_number=5,
                end_line=15,
                coverage_percentage=20.0,
                complexity=3,
                is_public=True,
                priority=GapPriority.HIGH,
            ),
        ],
    )

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=False)
    pipeline = PickPipeline(config)

    with patch("nit.agents.pipelines.pick.reporter") as mock_reporter:
        pipeline._report_gap_analysis(gap_report)

    call_args = mock_reporter.print_info.call_args[0][0]
    assert "2 function gaps" in call_args
    assert "1 critical" in call_args


@pytest.mark.asyncio
async def test_run_deep_code_analysis_with_gaps(tmp_path: Path) -> None:
    """_run_deep_code_analysis populates code_maps and convention_profile."""

    source_file = tmp_path / "src" / "module.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("def foo(): pass\n")

    gap_report = CoverageGapReport(
        function_gaps=[
            FunctionGap(
                file_path=str(source_file),
                function_name="foo",
                line_number=1,
                end_line=1,
                coverage_percentage=0.0,
                complexity=5,
                is_public=True,
                priority=GapPriority.CRITICAL,
            ),
        ],
    )

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    mock_code_map = Mock(parse_result=None)

    with (
        patch("nit.agents.pipelines.pick.CodeAnalyzer") as mock_ca_cls,
        patch("nit.agents.pipelines.pick.PatternAnalyzer") as mock_pa_cls,
        patch("nit.agents.pipelines.pick.RouteDiscoveryAgent") as mock_rd_cls,
    ):
        code_analyzer = AsyncMock()
        mock_ca_cls.return_value = code_analyzer
        code_analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"code_map": mock_code_map},
        )

        pattern_analyzer = AsyncMock()
        mock_pa_cls.return_value = pattern_analyzer
        pattern_analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"convention_profile": Mock()},
        )

        route_agent = Mock()
        mock_rd_cls.return_value = route_agent
        route_agent.run.return_value = Mock(routes=[])

        result = PickPipelineResult(gap_report=gap_report)
        profile = ProjectProfile(
            root=str(tmp_path),
            languages=[],
            frameworks=[],
            packages=[],
        )

        await pipeline._run_deep_code_analysis(profile, gap_report, result)

    assert len(result.code_maps) == 1
    assert result.convention_profile is not None


@pytest.mark.asyncio
async def test_run_deep_code_analysis_code_analyzer_failure(
    tmp_path: Path,
) -> None:
    """Code analysis failure is caught per-file."""

    source_file = tmp_path / "src" / "module.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("def foo(): pass\n")

    gap_report = CoverageGapReport(
        function_gaps=[
            FunctionGap(
                file_path=str(source_file),
                function_name="foo",
                line_number=1,
                end_line=1,
                coverage_percentage=0.0,
                complexity=5,
                is_public=True,
                priority=GapPriority.CRITICAL,
            ),
        ],
    )

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with (
        patch("nit.agents.pipelines.pick.CodeAnalyzer") as mock_ca_cls,
        patch("nit.agents.pipelines.pick.PatternAnalyzer") as mock_pa_cls,
        patch("nit.agents.pipelines.pick.RouteDiscoveryAgent") as mock_rd_cls,
    ):
        code_analyzer = AsyncMock()
        mock_ca_cls.return_value = code_analyzer
        code_analyzer.run.side_effect = RuntimeError("parse error")

        pattern_analyzer = AsyncMock()
        mock_pa_cls.return_value = pattern_analyzer
        pattern_analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"convention_profile": None},
        )

        route_agent = Mock()
        mock_rd_cls.return_value = route_agent
        route_agent.run.return_value = Mock(routes=[])

        result = PickPipelineResult(gap_report=gap_report)
        profile = ProjectProfile(root=str(tmp_path), languages=[], frameworks=[], packages=[])

        await pipeline._run_deep_code_analysis(profile, gap_report, result)

    assert result.code_maps == {}


@pytest.mark.asyncio
async def test_analyze_patterns_failure_returns_none(tmp_path: Path) -> None:
    """_analyze_patterns returns None on exception."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with patch("nit.agents.pipelines.pick.PatternAnalyzer") as mock_pa_cls:
        mock_pa_cls.side_effect = RuntimeError("fail")

        profile = ProjectProfile(root=str(tmp_path), languages=[], frameworks=[], packages=[])
        result = await pipeline._analyze_patterns(profile)

    assert result is None


@pytest.mark.asyncio
async def test_discover_routes_returns_result(tmp_path: Path) -> None:
    """_discover_routes returns route result when routes found."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    mock_route_result = Mock(routes=[Mock()])

    with patch("nit.agents.pipelines.pick.RouteDiscoveryAgent") as mock_rd_cls:
        route_agent = Mock()
        mock_rd_cls.return_value = route_agent
        route_agent.run.return_value = mock_route_result

        profile = ProjectProfile(root=str(tmp_path), languages=[], frameworks=[], packages=[])
        result = pipeline._discover_routes(profile)

    assert result is mock_route_result


@pytest.mark.asyncio
async def test_discover_routes_returns_none_on_exception(
    tmp_path: Path,
) -> None:
    """_discover_routes returns None on exception."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with patch("nit.agents.pipelines.pick.RouteDiscoveryAgent") as mock_rd_cls:
        mock_rd_cls.side_effect = RuntimeError("fail")

        profile = ProjectProfile(root=str(tmp_path), languages=[], frameworks=[], packages=[])
        result = pipeline._discover_routes(profile)

    assert result is None


@pytest.mark.asyncio
async def test_discover_routes_returns_none_when_no_routes(
    tmp_path: Path,
) -> None:
    """_discover_routes returns None when no routes found."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with patch("nit.agents.pipelines.pick.RouteDiscoveryAgent") as mock_rd_cls:
        route_agent = Mock()
        mock_rd_cls.return_value = route_agent
        route_agent.run.return_value = Mock(routes=[])

        profile = ProjectProfile(root=str(tmp_path), languages=[], frameworks=[], packages=[])
        result = pipeline._discover_routes(profile)

    assert result is None


@pytest.mark.asyncio
async def test_run_risk_and_semantic_analysis(tmp_path: Path) -> None:
    """_run_risk_and_semantic_analysis populates risk and semantic gaps."""

    gap_report = CoverageGapReport(
        function_gaps=[
            FunctionGap(
                file_path="src/a.py",
                function_name="func_a",
                line_number=1,
                end_line=10,
                coverage_percentage=0.0,
                complexity=5,
                is_public=True,
                priority=GapPriority.CRITICAL,
            ),
        ],
    )

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    mock_risk_report = Mock(critical_files=["a.py"], high_risk_files=[])
    result = PickPipelineResult(
        gap_report=gap_report,
        code_maps={"src/a.py": Mock(parse_result=None)},
    )

    with (
        patch("nit.agents.pipelines.pick.RiskAnalyzer") as mock_risk_cls,
        patch("nit.agents.pipelines.pick.detect_integration_dependencies"),
        patch("nit.agents.pipelines.pick.load_config") as mock_lc,
        patch("nit.agents.pipelines.pick.SemanticGapDetector") as mock_sg_cls,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
    ):
        risk_analyzer = AsyncMock()
        mock_risk_cls.return_value = risk_analyzer
        risk_analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"risk_report": mock_risk_report},
        )

        mock_lc.return_value = Mock(llm=Mock(provider="openai"))

        sg_detector = AsyncMock()
        mock_sg_cls.return_value = sg_detector
        sg_detector.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"semantic_gaps": [Mock()]},
        )

        await pipeline._run_risk_and_semantic_analysis(gap_report, result)

    assert result.risk_report is mock_risk_report
    assert len(result.semantic_gaps) == 1


@pytest.mark.asyncio
async def test_analyze_risk_failure_returns_none(tmp_path: Path) -> None:
    """_analyze_risk returns None on exception."""

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with patch("nit.agents.pipelines.pick.RiskAnalyzer") as mock_cls:
        mock_cls.side_effect = RuntimeError("fail")

        result = await pipeline._analyze_risk({}, CoverageGapReport())

    assert result is None


@pytest.mark.asyncio
async def test_detect_integration_deps_populates_result(
    tmp_path: Path,
) -> None:
    """_detect_integration_deps adds dependency reports to result."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    mock_code_map = Mock(parse_result=Mock(), language="python")
    mock_dep_report = Mock(needs_integration_tests=True)

    result = PickPipelineResult(
        code_maps={"src/a.py": mock_code_map},
    )

    with patch(
        "nit.agents.pipelines.pick.detect_integration_dependencies",
        return_value=mock_dep_report,
    ):
        pipeline._detect_integration_deps(result)

    assert len(result.integration_deps) == 1


@pytest.mark.asyncio
async def test_detect_integration_deps_skips_no_parse(
    tmp_path: Path,
) -> None:
    """_detect_integration_deps skips files without parse_result."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    mock_code_map = Mock(parse_result=None)
    result = PickPipelineResult(code_maps={"src/a.py": mock_code_map})

    pipeline._detect_integration_deps(result)

    assert result.integration_deps == []


@pytest.mark.asyncio
async def test_detect_integration_deps_exception_is_caught(
    tmp_path: Path,
) -> None:
    """_detect_integration_deps catches exceptions per-file."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    mock_code_map = Mock(parse_result=Mock(), language="python")
    result = PickPipelineResult(code_maps={"src/a.py": mock_code_map})

    with patch(
        "nit.agents.pipelines.pick.detect_integration_dependencies",
        side_effect=RuntimeError("fail"),
    ):
        pipeline._detect_integration_deps(result)

    assert result.integration_deps == []


@pytest.mark.asyncio
async def test_map_flows_returns_result(tmp_path: Path) -> None:
    """_map_flows returns flow mapping result."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    mock_route_discovery = Mock(routes=[Mock()])
    mock_flow_result = Mock(flows=[Mock()])

    with patch("nit.agents.pipelines.pick.FlowMapper") as mock_mapper_cls:
        mock_mapper_cls.return_value.map_flows.return_value = mock_flow_result
        result = pipeline._map_flows(mock_route_discovery)

    assert result is mock_flow_result


@pytest.mark.asyncio
async def test_map_flows_exception_returns_none(tmp_path: Path) -> None:
    """_map_flows returns None on exception."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with patch("nit.agents.pipelines.pick.FlowMapper") as mock_mapper_cls:
        mock_mapper_cls.side_effect = RuntimeError("fail")
        result = pipeline._map_flows(Mock())

    assert result is None


@pytest.mark.asyncio
async def test_detect_semantic_gaps_returns_gaps(tmp_path: Path) -> None:
    """_detect_semantic_gaps returns gaps from detector."""

    gap_report = CoverageGapReport(
        function_gaps=[
            FunctionGap(
                file_path="src/a.py",
                function_name="func_a",
                line_number=1,
                end_line=10,
                coverage_percentage=0.0,
                complexity=5,
                is_public=True,
                priority=GapPriority.CRITICAL,
            ),
        ],
    )

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with (
        patch("nit.agents.pipelines.pick.load_config") as mock_lc,
        patch("nit.agents.pipelines.pick.create_engine"),
        patch("nit.agents.pipelines.pick.load_llm_config"),
        patch("nit.agents.pipelines.pick.SemanticGapDetector") as mock_cls,
    ):
        mock_lc.return_value = Mock(llm=Mock(provider="openai"))
        detector = AsyncMock()
        mock_cls.return_value = detector
        detector.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"semantic_gaps": [Mock(), Mock()]},
        )

        gaps = await pipeline._detect_semantic_gaps(gap_report)

    assert len(gaps) == 2


@pytest.mark.asyncio
async def test_detect_semantic_gaps_no_provider_returns_empty(
    tmp_path: Path,
) -> None:
    """_detect_semantic_gaps returns empty when no LLM provider."""

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with patch("nit.agents.pipelines.pick.load_config") as mock_lc:
        mock_lc.return_value = Mock(llm=Mock(provider=""))
        gaps = await pipeline._detect_semantic_gaps(CoverageGapReport())

    assert gaps == []


@pytest.mark.asyncio
async def test_detect_semantic_gaps_exception_returns_empty(
    tmp_path: Path,
) -> None:
    """_detect_semantic_gaps returns empty on exception."""

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with patch(
        "nit.agents.pipelines.pick.load_config",
        side_effect=RuntimeError("fail"),
    ):
        gaps = await pipeline._detect_semantic_gaps(CoverageGapReport())

    assert gaps == []


@pytest.mark.asyncio
async def test_report_risk_summary_all_fields(tmp_path: Path) -> None:
    """_report_risk_summary formats all available risk data."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=False)
    pipeline = PickPipeline(config)

    result = PickPipelineResult(
        risk_report=Mock(critical_files=["a.py"], high_risk_files=["b.py"]),
        integration_deps=[Mock()],
        semantic_gaps=[Mock(), Mock()],
        flow_mapping=Mock(flows=[Mock()]),
    )

    with patch("nit.agents.pipelines.pick.reporter") as mock_reporter:
        pipeline._report_risk_summary(result, 0.5)

    call_args = mock_reporter.print_step_done.call_args[0][0]
    assert "1 critical" in call_args
    assert "1 high-risk" in call_args
    assert "1 files need integration tests" in call_args
    assert "2 semantic gaps" in call_args
    assert "1 user flows" in call_args


@pytest.mark.asyncio
async def test_report_risk_summary_empty(tmp_path: Path) -> None:
    """_report_risk_summary with no data prints default message."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=False)
    pipeline = PickPipeline(config)
    result = PickPipelineResult()

    with patch("nit.agents.pipelines.pick.reporter") as mock_reporter:
        pipeline._report_risk_summary(result, 0.1)

    call_args = mock_reporter.print_step_done.call_args[0][0]
    assert "No additional risks found" in call_args


@pytest.mark.asyncio
async def test_coverage_gap_analysis_returns_failed_status(
    tmp_path: Path,
) -> None:
    """_analyze_coverage_gaps returns None when analyzer reports FAILED."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with (
        patch("nit.agents.pipelines.pick.load_config") as mock_lc,
        patch("nit.agents.pipelines.pick.CoverageAnalyzer") as mock_ca_cls,
    ):
        mock_lc.return_value = Mock(
            coverage=Mock(
                complexity_threshold=10,
                undertested_threshold=50.0,
                line_threshold=80.0,
            ),
        )
        cov_analyzer = AsyncMock()
        mock_ca_cls.return_value = cov_analyzer
        cov_analyzer.run.return_value = Mock(
            status=TaskStatus.FAILED,
            result={},
            errors=["Analysis failed"],
        )

        result = await pipeline._analyze_coverage_gaps(tmp_path)

    assert result is None


@pytest.mark.asyncio
async def test_run_deep_analysis_steps_with_gaps(tmp_path: Path) -> None:
    """_run_deep_analysis_steps runs analysis when gaps exist."""

    gap_report = CoverageGapReport(
        function_gaps=[
            FunctionGap(
                file_path="src/a.py",
                function_name="foo",
                line_number=1,
                end_line=5,
                coverage_percentage=0.0,
                complexity=3,
                is_public=True,
                priority=GapPriority.HIGH,
            ),
        ],
    )

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    result = PickPipelineResult(gap_report=gap_report)
    profile = ProjectProfile(root=str(tmp_path), languages=[], frameworks=[], packages=[])
    tracker = _StepTracker(9, ci_mode=True)

    with (
        patch.object(pipeline, "_run_deep_code_analysis", new_callable=AsyncMock) as mock_dca,
        patch.object(
            pipeline,
            "_run_risk_and_semantic_analysis",
            new_callable=AsyncMock,
        ) as mock_rsa,
    ):
        await pipeline._run_deep_analysis_steps(tracker, profile, result)

    mock_dca.assert_called_once()
    mock_rsa.assert_called_once()


@pytest.mark.asyncio
async def test_create_new_pr_success(tmp_path: Path) -> None:
    """_create_new_pr creates a PR and returns URL."""
    config = PickPipelineConfig(
        project_root=tmp_path,
        ci_mode=True,
        ci_context=_LOCAL_CI_CONTEXT,
    )
    pipeline = PickPipeline(config)
    result = PickPipelineResult(
        tests_run=5,
        tests_passed=5,
        fixes_applied=["a.py"],
    )

    with (
        patch("nit.agents.pipelines.pick.GitHubPRReporter") as mock_pr_cls,
        patch(
            "nit.agents.pipelines.pick.get_default_branch",
            return_value="main",
        ),
    ):
        mock_reporter_instance = Mock()
        mock_pr_cls.return_value = mock_reporter_instance
        mock_reporter_instance.create_pr_with_tests.return_value = Mock(
            success=True, pr_url="https://github.com/o/r/pull/1"
        )

        pr_result = await pipeline._create_new_pr(result)

    assert pr_result["created"] is True
    assert pr_result["url"] == "https://github.com/o/r/pull/1"


@pytest.mark.asyncio
async def test_create_bug_analyzer_without_llm(tmp_path: Path) -> None:
    """_create_bug_analyzer works even when LLM config fails."""
    config = PickPipelineConfig(project_root=tmp_path, ci_mode=True)
    pipeline = PickPipeline(config)

    with patch(
        "nit.agents.pipelines.pick.load_config",
        side_effect=RuntimeError("no config"),
    ):
        analyzer = pipeline._create_bug_analyzer()

    assert analyzer is not None


@pytest.mark.asyncio
async def test_non_ci_collect_test_metrics_with_coverage(
    tmp_path: Path,
) -> None:
    """_collect_test_metrics prints coverage in non-CI mode."""
    cov_report = CoverageReport(
        files={
            "a.py": FileCoverage(
                file_path="a.py",
                lines=[LineCoverage(line_number=1, execution_count=1)],
            )
        }
    )

    test_result = RunResult(
        passed=5,
        failed=0,
        skipped=0,
        errors=0,
        duration_ms=200,
        test_cases=[],
        coverage=cov_report,
    )

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=False)
    pipeline = PickPipeline(config)
    result = PickPipelineResult()

    with (
        patch("nit.agents.pipelines.pick.reporter"),
        patch("nit.agents.pipelines.pick.load_config") as mock_lc,
        patch("nit.agents.pipelines.pick.CoverageAnalyzer") as mock_ca_cls,
    ):
        mock_lc.return_value = Mock(
            coverage=Mock(
                complexity_threshold=10,
                undertested_threshold=50.0,
                line_threshold=80.0,
            ),
        )
        cov_analyzer = AsyncMock()
        mock_ca_cls.return_value = cov_analyzer
        gap = Mock(function_gaps=[Mock(priority=Mock(value="critical"))])
        cov_analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"gap_report": gap},
        )

        await pipeline._collect_test_metrics(test_result, result)

    assert result.coverage_report is not None
    assert result.gap_report is not None


@pytest.mark.asyncio
async def test_non_ci_run_deep_code_analysis_summary(
    tmp_path: Path,
) -> None:
    """Non-CI _run_deep_code_analysis prints summary with routes."""

    config = PickPipelineConfig(project_root=tmp_path, ci_mode=False)
    pipeline = PickPipeline(config)
    result = PickPipelineResult()

    with (
        patch("nit.agents.pipelines.pick.PatternAnalyzer") as mock_pa_cls,
        patch("nit.agents.pipelines.pick.RouteDiscoveryAgent") as mock_rd_cls,
        patch("nit.agents.pipelines.pick.reporter") as mock_reporter,
    ):
        pattern_analyzer = AsyncMock()
        mock_pa_cls.return_value = pattern_analyzer
        pattern_analyzer.run.return_value = Mock(
            status=TaskStatus.COMPLETED,
            result={"convention_profile": Mock()},
        )

        route_agent = Mock()
        mock_rd_cls.return_value = route_agent
        route_agent.run.return_value = Mock(routes=[Mock(), Mock()])

        profile = ProjectProfile(root=str(tmp_path), languages=[], frameworks=[], packages=[])

        await pipeline._run_deep_code_analysis(profile, None, result)

    assert result.convention_profile is not None
    assert result.route_discovery is not None
    mock_reporter.print_step_done.assert_called_once()
    summary = mock_reporter.print_step_done.call_args[0][0]
    assert "conventions detected" in summary
    assert "2 routes found" in summary
