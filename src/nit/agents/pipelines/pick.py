"""Pick pipeline - bug detection, fixing, and reporting."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nit.adapters.base import CaseResult, CaseStatus, TestFrameworkAdapter
from nit.adapters.registry import get_registry
from nit.agents.analyzers.bug import BugAnalysisTask, BugAnalyzer, BugReport
from nit.agents.analyzers.code import CodeAnalysisTask, CodeAnalyzer
from nit.agents.analyzers.coverage import (
    CoverageAnalysisTask,
    CoverageAnalyzer,
    CoverageGapReport,
)
from nit.agents.analyzers.flow_mapping import FlowMapper
from nit.agents.analyzers.integration_deps import detect_integration_dependencies
from nit.agents.analyzers.pattern import PatternAnalysisTask, PatternAnalyzer
from nit.agents.analyzers.risk import RiskAnalysisTask, RiskAnalyzer
from nit.agents.analyzers.route_discovery import RouteDiscoveryAgent
from nit.agents.analyzers.security import SecurityAnalysisTask, SecurityAnalyzer
from nit.agents.analyzers.semantic_gap import SemanticGapDetector, SemanticGapTask
from nit.agents.base import TaskInput, TaskStatus
from nit.agents.debuggers import (
    BugVerificationTask,
    BugVerifier,
    FixGenerationTask,
    FixGenerator,
    FixVerificationTask,
    FixVerifier,
    GeneratedFix,
    RootCause,
    RootCauseAnalysisTask,
    RootCauseAnalyzer,
    VerificationResult,
)
from nit.agents.detectors.dependency import detect_dependencies
from nit.agents.detectors.framework import detect_frameworks
from nit.agents.detectors.infra import detect_infra
from nit.agents.detectors.llm_usage import LLMUsageDetector, LLMUsageProfile
from nit.agents.detectors.stack import detect_languages
from nit.agents.detectors.workspace import detect_workspace
from nit.agents.reporters import GenerationSummary, GitHubPRReporter
from nit.agents.reporters.github_issue import BugIssueData, GitHubIssueReporter
from nit.agents.reporters.terminal import reporter
from nit.cli_helpers import check_and_install_prerequisites
from nit.config import load_config
from nit.llm.config import load_llm_config
from nit.llm.factory import create_engine
from nit.llm.usage_callback import get_session_usage_stats
from nit.memory.analytics_collector import get_analytics_collector
from nit.models.analytics import BugSnapshot, TestExecutionSnapshot
from nit.models.profile import ProjectProfile
from nit.models.store import is_profile_stale, load_profile, save_profile
from nit.sharding.parallel_runner import ParallelRunConfig, run_tests_parallel
from nit.telemetry.sentry_integration import (
    record_metric_count,
    record_metric_distribution,
    start_span,
)
from nit.utils.ci_context import CIContext, detect_ci_context, should_create_pr
from nit.utils.git import get_default_branch

if TYPE_CHECKING:
    from nit.adapters.base import RunResult
    from nit.adapters.coverage.base import CoverageReport
    from nit.agents.analyzers.code import CodeMap
    from nit.agents.analyzers.flow_mapping import FlowMappingResult
    from nit.agents.analyzers.integration_deps import IntegrationDependencyReport
    from nit.agents.analyzers.pattern import ConventionProfile
    from nit.agents.analyzers.risk import RiskReport
    from nit.agents.analyzers.security import SecurityReport
    from nit.agents.analyzers.semantic_gap import SemanticGap
    from nit.models.route import RouteDiscoveryResult

logger = logging.getLogger(__name__)

_TOTAL_STEPS = 9


class _StepTracker:
    """Track pipeline step progress for terminal display."""

    def __init__(self, total: int, *, ci_mode: bool) -> None:
        self._total = total
        self._ci_mode = ci_mode
        self._current = 0

    def step(self, description: str) -> None:
        """Advance to the next step and print its header."""
        self._current += 1
        if not self._ci_mode:
            reporter.print_step_header(self._current, self._total, description)

    def skip(self, description: str) -> None:
        """Skip a step and print it as skipped."""
        self._current += 1
        if not self._ci_mode:
            reporter.print_step_skip(description)


@dataclass
class PickPipelineConfig:
    """Configuration for pick pipeline execution."""

    project_root: Path
    """Project root directory."""

    test_type: str = "all"
    """Type of tests to target (unit/e2e/integration/all)."""

    target_file: str | None = None
    """Specific file to target (optional)."""

    coverage_target: int | None = None
    """Target coverage percentage (optional)."""

    fix_enabled: bool = False
    """Whether to generate and apply fixes."""

    create_pr: bool = False
    """Whether to create a GitHub PR."""

    create_issues: bool = False
    """Whether to create GitHub issues for detected bugs."""

    create_fix_prs: bool = False
    """Whether to create separate PRs for bug fixes."""

    commit_changes: bool = True
    """Whether to commit changes (fixes/tests) locally or in PR context."""

    ci_mode: bool = False
    """Whether running in CI mode (minimal output)."""

    ci_context: CIContext | None = None
    """Detected CI/PR context (auto-detected if None)."""

    max_fix_loops: int = 1
    """Maximum fix-rerun iterations (0 = unlimited, 1 = single pass)."""

    token_budget: int = 0
    """Total token budget for LLM usage (0 = unlimited)."""


@dataclass
class PickPipelineResult:
    """Result of pick pipeline execution."""

    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_errors: int = 0

    bugs_found: list[BugReport] = field(default_factory=list)
    fixes_generated: list[tuple[str, GeneratedFix]] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)

    coverage_report: CoverageReport | None = None
    gap_report: CoverageGapReport | None = None

    pr_url: str | None = None
    pr_created: bool = False

    # Track GitHub issue/PR URLs for individual bugs
    created_issues: list[str] = field(default_factory=list)
    created_fix_prs: list[str] = field(default_factory=list)

    iterations_run: int = 1
    """Number of fix-loop iterations completed."""

    # Deep analysis results
    code_maps: dict[str, CodeMap] = field(default_factory=dict)
    """Code analysis results keyed by file path."""

    convention_profile: ConventionProfile | None = None
    """Detected test conventions from existing tests."""

    risk_report: RiskReport | None = None
    """Composite risk scores for files and functions."""

    integration_deps: list[IntegrationDependencyReport] = field(default_factory=list)
    """Files needing integration tests."""

    semantic_gaps: list[SemanticGap] = field(default_factory=list)
    """LLM-identified semantic test gaps."""

    route_discovery: RouteDiscoveryResult | None = None
    """Discovered web routes for E2E testing."""

    flow_mapping: FlowMappingResult | None = None
    """Identified user flows from discovered routes."""

    security_report: SecurityReport | None = None
    """Security vulnerability findings."""

    llm_usage_profile: LLMUsageProfile | None = None
    """Detected LLM/AI SDK usage locations."""

    success: bool = True
    errors: list[str] = field(default_factory=list)


@dataclass
class FixPipelineAgents:
    """Container for fix pipeline agents to reduce parameter count."""

    verifier: BugVerifier
    root_cause_analyzer: RootCauseAnalyzer
    fix_generator: FixGenerator
    fix_verifier: FixVerifier


@dataclass
class FixVerificationContext:
    """Context for fix verification to reduce parameter count."""

    bug_report: BugReport
    source_code: str
    generated_fix: GeneratedFix
    verification_result: VerificationResult


class PickPipeline:
    """Orchestrates the full pick pipeline: test → analyze → fix → report."""

    def __init__(self, config: PickPipelineConfig) -> None:
        """Initialize pick pipeline.

        Args:
            config: Pipeline configuration.
        """
        self.config = config
        self.ci_context = config.ci_context or detect_ci_context()

        # Initialize analytics collector for local tracking
        self._collector = get_analytics_collector(config.project_root)

        # Populated during profile loading when LLM SDK usage is detected
        self._llm_usage_profile: LLMUsageProfile | None = None

    def _token_budget_exceeded(self) -> bool:
        """Check if the session token budget has been exceeded."""
        if self.config.token_budget <= 0:
            return False
        stats = get_session_usage_stats()
        return stats.total_tokens >= self.config.token_budget

    @property
    def _effective_max_loops(self) -> int:
        """Return effective max loops (CI forces 1)."""
        if self.config.ci_mode:
            return 1
        return self.config.max_fix_loops

    async def run(self) -> PickPipelineResult:
        """Execute the full pick pipeline.

        When ``max_fix_loops > 1`` (or 0 for unlimited) and ``fix_enabled``
        is True, the pipeline loops: run tests -> analyse -> fix -> rerun
        until tests are clean, the loop limit is reached, or the token
        budget is exhausted.  CI mode always runs a single pass.

        Returns:
            Pipeline execution result.
        """
        result = PickPipelineResult()
        tracker = _StepTracker(_TOTAL_STEPS, ci_mode=self.config.ci_mode)
        pipeline_start = time.monotonic()

        if not self.config.ci_mode:
            reporter.print_pipeline_header("nit pick")

        record_metric_count("nit.command.invoked", command="pick")

        try:
            await self._run_pipeline_steps(result, tracker, start_span, record_metric_count)
        except Exception as e:
            logger.exception("Pick pipeline failed: %s", e)
            result.success = False
            result.errors.append(str(e))

        duration_ms = (time.monotonic() - pipeline_start) * 1000
        record_metric_distribution("nit.pipeline.duration_ms", duration_ms, unit="millisecond")

        return result

    async def _run_pipeline_steps(
        self,
        result: PickPipelineResult,
        tracker: _StepTracker,
        start_span: Any,
        record_metric_count: Any,
    ) -> None:
        """Execute the core pipeline steps (extracted to stay within statement limits)."""
        # Step 1: Load project profile
        tracker.step("Loading project profile")
        with start_span(op="step.profile", description="Load project profile"):
            profile = await self._load_profile()
            result.llm_usage_profile = self._llm_usage_profile

        # Step 2: Load test framework adapters
        tracker.step("Loading test framework adapters")
        with start_span(op="step.adapters", description="Load test adapters"):
            adapters = self._get_test_adapters(profile)
            primary_adapter = adapters[0]
            record_metric_count("nit.framework.detected", framework=primary_adapter.name)

        # Check prerequisites (part of step 2)
        prereqs_ok = await check_and_install_prerequisites(
            primary_adapter, self.config.project_root, ci_mode=self.config.ci_mode
        )
        if not prereqs_ok:
            error_msg = "Prerequisites not satisfied. Please install required dependencies."
            result.success = False
            result.errors.append(error_msg)
            if not self.config.ci_mode:
                reporter.print_error(error_msg)
            return

        # Step 3: Run tests and analyze coverage
        tracker.step("Running tests and analyzing coverage")
        with start_span(op="step.tests", description="Run tests"):
            test_result = await self._run_tests(primary_adapter)
            await self._collect_test_metrics(test_result, result)

        record_metric_count("nit.tests.passed", value=result.tests_passed)
        record_metric_count("nit.tests.failed", value=result.tests_failed)

        # Step 4: Analyze test failures for bugs
        failed_count = result.tests_failed + result.tests_errors
        tracker.step(f"Analyzing {failed_count} test failures for bugs")
        with start_span(op="step.bugs", description="Analyze bugs"):
            bugs = await self._analyze_bugs(test_result)
            result.bugs_found = bugs

        record_metric_count("nit.bugs.found", value=len(bugs))

        # Steps 5-6: Deep analysis (code patterns, risk, semantic gaps)
        with start_span(op="step.analysis", description="Deep analysis"):
            await self._run_deep_analysis_steps(tracker, profile, result)

        # Steps 7-8: Fix generation and application
        with start_span(op="step.fixes", description="Fix generation"):
            await self._run_fix_steps(tracker, bugs, primary_adapter, result)

        # Step 9: Post-loop actions (issues, PRs, commits)
        if self._should_run_post_loop(result):
            tracker.step("Creating GitHub pull request or commit")
            with start_span(op="step.report", description="Post-loop actions"):
                await self._post_loop(result)
        else:
            tracker.skip("Creating PR/commit")

    # ------------------------------------------------------------------
    # Step groups extracted from run()
    # ------------------------------------------------------------------

    async def _run_deep_analysis_steps(
        self,
        tracker: _StepTracker,
        profile: ProjectProfile,
        result: PickPipelineResult,
    ) -> None:
        """Run steps 5-6: code patterns, conventions, risk, security, and semantic gaps."""
        has_gaps = bool(result.gap_report and result.gap_report.function_gaps)

        if has_gaps:
            tracker.step("Analyzing code patterns and conventions")
            await self._run_deep_code_analysis(profile, result.gap_report, result)
        else:
            tracker.skip("Analyzing code patterns and conventions")

        if has_gaps:
            tracker.step("Analyzing risk, security, and semantic gaps")
            await self._run_risk_and_semantic_analysis(result.gap_report, result)
        else:
            # Security analysis runs even without coverage gaps
            tracker.step("Analyzing security")
            await self._run_security_analysis(result)

    async def _run_fix_steps(
        self,
        tracker: _StepTracker,
        bugs: list[BugReport],
        adapter: TestFrameworkAdapter,
        result: PickPipelineResult,
    ) -> None:
        """Run steps 7-8: fix generation, verification, and application."""
        if self.config.fix_enabled and bugs and not self._token_budget_exceeded():
            tracker.step(f"Generating fixes for {len(bugs)} bugs")
            llm_engine = self._create_llm_engine()
            fixes = await self._generate_fixes(bugs, adapter, llm_engine)
            result.fixes_generated.extend(fixes)
        else:
            tracker.skip("Generating fixes")

        if self.config.fix_enabled and result.fixes_generated:
            tracker.step(f"Applying {len(result.fixes_generated)} verified fixes")
            result.fixes_applied.extend(self._apply_fixes(result.fixes_generated))
            await self._additional_fix_iterations(adapter, result)
        else:
            tracker.skip("Applying fixes")

    # ------------------------------------------------------------------
    # Test metrics and additional fix iterations
    # ------------------------------------------------------------------

    async def _collect_test_metrics(
        self, test_result: RunResult, result: PickPipelineResult
    ) -> None:
        """Process test results: store metrics, coverage, and gap analysis."""
        result.tests_run = test_result.total
        result.tests_passed = test_result.passed
        result.tests_failed = test_result.failed
        result.tests_errors = test_result.errors

        if test_result.coverage:
            result.coverage_report = test_result.coverage
            if not self.config.ci_mode:
                coverage_pct = test_result.coverage.overall_line_coverage
                reporter.print_info(f"Coverage: {coverage_pct:.1f}% line coverage")

        if test_result.coverage and result.coverage_report:
            gap_report = await self._analyze_coverage_gaps(self.config.project_root)
            result.gap_report = gap_report
            if not self.config.ci_mode and gap_report:
                self._report_gap_analysis(gap_report)

    async def _additional_fix_iterations(
        self,
        adapter: TestFrameworkAdapter,
        result: PickPipelineResult,
    ) -> None:
        """Run additional fix-loop iterations when max_fix_loops > 1.

        The first iteration is handled directly in ``run()``.  This method
        handles subsequent re-test → re-analyse → re-fix cycles.
        """
        max_loops = self._effective_max_loops
        if max_loops == 1:
            return

        iteration = 1
        while True:
            iteration += 1

            if self._token_budget_exceeded():
                if not self.config.ci_mode:
                    stats = get_session_usage_stats()
                    reporter.print_warning(
                        f"Token budget exhausted "
                        f"({stats.total_tokens}/{self.config.token_budget}), "
                        f"{len(result.bugs_found)} bug(s) remain"
                    )
                break

            if max_loops > 0 and iteration > max_loops:
                if not self.config.ci_mode:
                    reporter.print_warning(f"Reached max fix loops ({max_loops}), stopping")
                break

            result.iterations_run = iteration

            if not self.config.ci_mode:
                loop_label = "\u221e" if max_loops == 0 else str(max_loops)
                reporter.print_info(f"Fix loop iteration {iteration}/{loop_label}")

            # Re-run tests
            test_result = await self._run_tests(adapter)
            await self._collect_test_metrics(test_result, result)

            # Re-analyze bugs
            bugs = await self._analyze_bugs(test_result)
            result.bugs_found = bugs

            if not bugs:
                if not self.config.ci_mode:
                    reporter.print_success(f"All bugs resolved after {iteration} iteration(s)")
                break

            # Generate and apply more fixes
            llm_engine = self._create_llm_engine()
            fixes = await self._generate_fixes(bugs, adapter, llm_engine)
            result.fixes_generated.extend(fixes)
            result.fixes_applied.extend(self._apply_fixes(fixes))

            if not fixes:
                if not self.config.ci_mode:
                    reporter.print_warning("No fixes generated, stopping fix loop")
                break

    # ------------------------------------------------------------------
    # Post-loop reporting
    # ------------------------------------------------------------------

    async def _post_loop(self, result: PickPipelineResult) -> None:
        """Run post-loop steps: issue creation, PRs, commits."""
        if self.config.create_issues and result.bugs_found:
            result.created_issues = await self._create_bug_issues(result.bugs_found)

        if self.config.create_fix_prs and result.fixes_generated:
            result.created_fix_prs = await self._create_fix_prs(
                result.bugs_found, result.fixes_generated
            )

        pr_result = await self._create_pr_or_commit(result)
        url = pr_result.get("url")
        result.pr_url = url if isinstance(url, str) else None
        created = pr_result.get("created", False)
        result.pr_created = bool(created)

    async def _load_profile(self) -> ProjectProfile:
        """Load or rebuild project profile."""
        t0 = time.monotonic()
        profile = load_profile(str(self.config.project_root))
        if profile is None or is_profile_stale(str(self.config.project_root)):
            if not self.config.ci_mode:
                reporter.print_info("  Profile is stale, re-scanning...")

            root = str(self.config.project_root)
            lang_profile = detect_languages(root)
            fw_profile = detect_frameworks(root)
            ws_profile = detect_workspace(root)
            infra_profile = detect_infra(root)
            dep_profile = detect_dependencies(root, workspace=ws_profile)

            # Detect LLM/AI SDK usage for drift test candidates
            try:
                llm_detector = LLMUsageDetector()
                llm_task = TaskInput(task_type="detect_llm_usage", target=root)
                llm_output = await llm_detector.run(llm_task)
                if llm_output.status == TaskStatus.COMPLETED:
                    llm_profile = llm_output.result.get("profile")
                    if isinstance(llm_profile, LLMUsageProfile) and llm_profile.total_usages:
                        self._llm_usage_profile = llm_profile
                        logger.info(
                            "LLM usage detection: %d usage(s), providers: %s",
                            llm_profile.total_usages,
                            ", ".join(sorted(llm_profile.providers)),
                        )
            except Exception as exc:
                logger.debug("LLM usage detection failed: %s", exc)

            profile = ProjectProfile(
                root=str(self.config.project_root.resolve()),
                languages=lang_profile.languages,
                frameworks=fw_profile.frameworks,
                packages=ws_profile.packages,
                workspace_tool=ws_profile.tool,
                infra_profile=infra_profile,
                dependency_profile=dep_profile,
            )
            save_profile(profile)

        elapsed = time.monotonic() - t0
        if not self.config.ci_mode:
            langs = (
                ", ".join(lang.language for lang in profile.languages)
                if profile.languages
                else "unknown"
            )
            reporter.print_step_done(f"Profile loaded ({langs})", elapsed)

        return profile

    def _get_test_adapters(self, profile: ProjectProfile) -> list[TestFrameworkAdapter]:
        """Get test adapters for the profile."""
        t0 = time.monotonic()
        registry = get_registry()
        adapters_by_package = registry.select_adapters_for_profile(profile)

        all_adapters = []
        for package_adapters in adapters_by_package.values():
            all_adapters.extend(
                [a for a in package_adapters if isinstance(a, TestFrameworkAdapter)]
            )

        if not all_adapters:
            msg = "No unit test framework detected"
            raise RuntimeError(msg)

        elapsed = time.monotonic() - t0
        if not self.config.ci_mode:
            names = ", ".join(a.name for a in all_adapters)
            reporter.print_step_done(f"Adapters ready ({names})", elapsed)

        return all_adapters

    async def _run_tests(self, adapter: TestFrameworkAdapter) -> RunResult:
        """Run tests and capture results, using parallel execution when beneficial."""
        t0 = time.monotonic()
        parallel_config = ParallelRunConfig(timeout=120.0)

        if not self.config.ci_mode:
            with reporter.create_status(f"[bold]Running {adapter.name} tests...[/bold]"):
                result = await run_tests_parallel(
                    adapter, self.config.project_root, config=parallel_config
                )
        else:
            result = await run_tests_parallel(
                adapter, self.config.project_root, config=parallel_config
            )

        elapsed = time.monotonic() - t0
        duration = result.duration_ms if result.duration_ms > 0 else elapsed * 1000

        if not self.config.ci_mode:
            reporter.print_step_done("Tests completed", elapsed)
            reporter.print_test_summary_bar(
                result.passed, result.failed, result.skipped, result.errors, duration
            )

        # Record test execution to analytics
        self._collector.record_test_execution(
            TestExecutionSnapshot(
                timestamp=datetime.now(UTC).isoformat(),
                total_tests=result.total,
                passed_tests=result.passed,
                failed_tests=result.failed,
                skipped_tests=result.skipped,
                total_duration_ms=result.duration_ms if result.duration_ms > 0 else None,
            ),
        )

        return result

    async def _analyze_bugs(self, test_result: RunResult) -> list[BugReport]:
        """Analyze test failures to identify code bugs."""
        failed_tests = [tc for tc in test_result.test_cases if tc.status != CaseStatus.PASSED]

        if not failed_tests:
            if not self.config.ci_mode:
                reporter.print_step_done("No failures to analyze", 0.0)
            return []

        t0 = time.monotonic()
        analyzer = self._create_bug_analyzer()
        bugs = await self._run_bug_analysis(analyzer, failed_tests)

        elapsed = time.monotonic() - t0
        if not self.config.ci_mode:
            label = f"Found {len(bugs)} code bugs" if bugs else "No code bugs detected"
            reporter.print_step_done(label, elapsed)

        return bugs

    def _create_bug_analyzer(self) -> BugAnalyzer:
        """Create a BugAnalyzer with optional LLM support."""
        llm_engine = None
        try:
            config = load_config(self.config.project_root)
            if config.llm.provider:
                llm_engine = self._create_llm_engine()
        except Exception as e:
            logger.debug("LLM not configured for bug analysis: %s", e)

        return BugAnalyzer(
            llm_engine=llm_engine,
            enable_llm_analysis=True,
            project_root=self.config.project_root,
        )

    async def _run_bug_analysis(
        self,
        analyzer: BugAnalyzer,
        failed_tests: list[CaseResult],
    ) -> list[BugReport]:
        """Run bug analysis on failed tests and collect reports (parallelized)."""
        ci_mode = self.config.ci_mode
        collector = self._collector

        async def _analyze_one(i: int, test_case: CaseResult) -> BugReport | None:
            if not ci_mode:
                short_name = test_case.name[:60]
                reporter.print_analysis_progress(
                    i, len(failed_tests), f"Analyzing [bold]{short_name}[/bold]"
                )

            try:
                task = BugAnalysisTask(
                    target=test_case.file_path or "unknown",
                    error_message=test_case.failure_message,
                    stack_trace="",
                    source_file=test_case.file_path or "",
                )

                result = await analyzer.run(task)

                if result.status == TaskStatus.COMPLETED and result.result.get("is_code_bug"):
                    raw_report = result.result.get("bug_report")
                    if isinstance(raw_report, BugReport):
                        if not ci_mode:
                            reporter.print_warning(f"    Bug detected: {raw_report.title}")

                        collector.record_bug(
                            BugSnapshot(
                                timestamp=datetime.now(UTC).isoformat(),
                                bug_type=raw_report.bug_type.value,
                                severity=raw_report.severity.value,
                                status="discovered",
                                file_path=raw_report.location.file_path,
                                line_number=raw_report.location.line_number,
                                title=raw_report.title,
                            ),
                        )
                        return raw_report

            except Exception as e:
                logger.warning("Bug analysis failed for test %s: %s", test_case.name, e)

            return None

        tasks = [_analyze_one(i, tc) for i, tc in enumerate(failed_tests, 1)]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        bugs: list[BugReport] = []
        for item in outcomes:
            if isinstance(item, BaseException):
                logger.warning("Bug analysis raised exception: %s", item)
            elif item is not None:
                bugs.append(item)

        return bugs

    async def _analyze_coverage_gaps(self, project_root: Path) -> CoverageGapReport | None:
        """Analyze coverage gaps using CoverageAnalyzer.

        Args:
            project_root: Project root directory.

        Returns:
            Gap analysis report or None if analysis fails.
        """
        try:
            # Load coverage thresholds from config
            config = load_config(project_root)
            coverage_config = config.coverage

            # Create analyzer with thresholds
            analyzer = CoverageAnalyzer(
                project_root,
                complexity_threshold=coverage_config.complexity_threshold,
                undertested_threshold=coverage_config.undertested_threshold,
            )

            # Create task
            task = CoverageAnalysisTask(
                project_root=str(project_root),
                coverage_threshold=coverage_config.line_threshold,
            )

            # Run analysis
            output = await analyzer.run(task)

            if output.status == TaskStatus.COMPLETED:
                return output.result.get("gap_report")

            logger.warning("Coverage gap analysis failed: %s", output.errors)
            return None

        except Exception as e:
            logger.exception("Coverage gap analysis error: %s", e)
            return None

    def _report_gap_analysis(self, gap_report: CoverageGapReport) -> None:
        """Report gap analysis results to console.

        Args:
            gap_report: Gap analysis report to display.
        """
        gap_count = len(gap_report.function_gaps)
        critical_count = len(
            [g for g in gap_report.function_gaps if g.priority.value == "critical"]
        )
        reporter.print_info(
            f"Gap analysis: {gap_count} function gaps identified ({critical_count} critical)"
        )

    # ------------------------------------------------------------------
    # Deep code analysis (steps 5-6)
    # ------------------------------------------------------------------

    async def _run_deep_code_analysis(
        self,
        profile: ProjectProfile,
        gap_report: CoverageGapReport | None,
        result: PickPipelineResult,
    ) -> None:
        """Run deep code analysis: CodeAnalyzer, PatternAnalyzer, RouteDiscovery.

        Populates ``result.code_maps``, ``result.convention_profile``,
        and ``result.route_discovery``.
        """
        t0 = time.monotonic()

        if gap_report:
            await self._analyze_code_maps(gap_report, result)

        result.convention_profile = await self._analyze_patterns(profile)
        result.route_discovery = self._discover_routes(profile)

        elapsed = time.monotonic() - t0
        if not self.config.ci_mode:
            summary_parts: list[str] = []
            if result.code_maps:
                summary_parts.append(f"{len(result.code_maps)} files analyzed")
            if result.convention_profile:
                summary_parts.append("conventions detected")
            if result.route_discovery:
                summary_parts.append(f"{len(result.route_discovery.routes)} routes found")
            label = ", ".join(summary_parts) if summary_parts else "No analysis targets"
            reporter.print_step_done(label, elapsed)

    async def _analyze_code_maps(
        self,
        gap_report: CoverageGapReport,
        result: PickPipelineResult,
    ) -> None:
        """Run CodeAnalyzer on files from gap report (parallelized)."""
        file_paths = {fg.file_path for fg in gap_report.function_gaps}
        file_paths.update(gap_report.untested_files)

        code_analyzer = CodeAnalyzer(project_root=self.config.project_root)
        ci_mode = self.config.ci_mode

        async def _analyze_one(fp: str) -> tuple[str, Any]:
            full_path = Path(fp)
            if not full_path.is_absolute():
                full_path = self.config.project_root / fp
            if not full_path.exists():
                return fp, None
            try:
                task = CodeAnalysisTask(file_path=str(full_path))
                output = await code_analyzer.run(task)
                if output.status == TaskStatus.COMPLETED:
                    return fp, output.result.get("code_map")
            except Exception as exc:
                logger.warning("Code analysis failed for %s: %s", fp, exc)
                if not ci_mode:
                    reporter.print_warning(f"Could not analyze {fp}: {exc}")
            return fp, None

        tasks = [_analyze_one(fp) for fp in file_paths]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        for item in outcomes:
            if isinstance(item, BaseException):
                logger.warning("Code analysis raised exception: %s", item)
                continue
            fp, code_map = item
            if code_map:
                result.code_maps[fp] = code_map

    async def _analyze_patterns(self, profile: ProjectProfile) -> ConventionProfile | None:
        """Run PatternAnalyzer for project-wide conventions."""
        try:
            primary_lang = profile.languages[0].language if profile.languages else ""
            pattern_analyzer = PatternAnalyzer()
            pattern_task = PatternAnalysisTask(
                project_root=str(self.config.project_root),
                language=primary_lang,
            )
            pattern_output = await pattern_analyzer.run(pattern_task)
            if pattern_output.status == TaskStatus.COMPLETED:
                return pattern_output.result.get("convention_profile")
        except Exception as exc:
            logger.debug("Pattern analysis failed: %s", exc)
        return None

    def _discover_routes(self, profile: ProjectProfile) -> RouteDiscoveryResult | None:
        """Run RouteDiscoveryAgent for project-wide route discovery."""
        try:
            route_agent = RouteDiscoveryAgent()
            route_result = route_agent.run(profile)
            if route_result.routes:
                return route_result
        except Exception as exc:
            logger.debug("Route discovery failed: %s", exc)
        return None

    async def _run_risk_and_semantic_analysis(
        self,
        gap_report: CoverageGapReport | None,
        result: PickPipelineResult,
    ) -> None:
        """Run risk, security, integration deps, flow mapping, and semantic gap analysis.

        Populates ``result.risk_report``, ``result.security_report``,
        ``result.integration_deps``, ``result.flow_mapping``, and
        ``result.semantic_gaps``.
        """
        t0 = time.monotonic()

        if result.code_maps and gap_report:
            result.risk_report = await self._analyze_risk(result.code_maps, gap_report)

        # Security analysis runs on all code maps (not gated on gaps)
        await self._run_security_analysis(result)

        self._detect_integration_deps(result)

        if result.route_discovery and result.route_discovery.routes:
            result.flow_mapping = self._map_flows(result.route_discovery)

        if gap_report and gap_report.function_gaps:
            result.semantic_gaps = await self._detect_semantic_gaps(gap_report)

        elapsed = time.monotonic() - t0
        if not self.config.ci_mode:
            self._report_risk_summary(result, elapsed)

    async def _run_security_analysis(self, result: PickPipelineResult) -> None:
        """Run SecurityAnalyzer on code maps."""
        if not result.code_maps:
            return

        try:
            config = load_config(self.config.project_root)
            if not config.security.enabled:
                return

            llm_engine = None
            if config.security.llm_validation:
                try:
                    llm_engine = self._create_llm_engine()
                except Exception:
                    logger.debug("LLM not available for security validation")

            analyzer = SecurityAnalyzer(
                project_root=self.config.project_root,
                llm_engine=llm_engine,
                enable_llm_validation=config.security.llm_validation,
                confidence_threshold=config.security.confidence_threshold,
            )

            task = SecurityAnalysisTask(
                project_root=str(self.config.project_root),
                code_maps=result.code_maps,
                enable_llm_validation=config.security.llm_validation,
                confidence_threshold=config.security.confidence_threshold,
            )

            output = await analyzer.run(task)
            if output.status == TaskStatus.COMPLETED:
                result.security_report = output.result.get("security_report")
                if not self.config.ci_mode and result.security_report:
                    reporter.print_security_summary(result.security_report)
        except Exception as exc:
            logger.debug("Security analysis error: %s", exc)

    async def _analyze_risk(
        self,
        code_maps: dict[str, CodeMap],
        gap_report: CoverageGapReport,
    ) -> RiskReport | None:
        """Run RiskAnalyzer on code maps and function gaps."""
        try:
            risk_analyzer = RiskAnalyzer(project_root=self.config.project_root)
            risk_task = RiskAnalysisTask(
                project_root=str(self.config.project_root),
                code_maps=code_maps,
                function_gaps=gap_report.function_gaps,
            )
            risk_output = await risk_analyzer.run(risk_task)
            if risk_output.status == TaskStatus.COMPLETED:
                return risk_output.result.get("risk_report")
        except Exception as exc:
            logger.debug("Risk analysis failed: %s", exc)
        return None

    def _detect_integration_deps(self, result: PickPipelineResult) -> None:
        """Detect integration dependencies per file in code maps."""
        for file_path, code_map in result.code_maps.items():
            if code_map.parse_result is None:
                continue
            try:
                source_path = Path(file_path)
                if not source_path.is_absolute():
                    source_path = self.config.project_root / file_path
                dep_report = detect_integration_dependencies(
                    source_path, code_map.parse_result, code_map.language
                )
                if dep_report.needs_integration_tests:
                    result.integration_deps.append(dep_report)
            except Exception as exc:
                logger.debug("Integration deps detection failed for %s: %s", file_path, exc)

    def _map_flows(self, route_discovery: RouteDiscoveryResult) -> FlowMappingResult | None:
        """Map user flows from discovered routes."""
        try:
            mapper = FlowMapper()
            return mapper.map_flows(route_discovery)
        except Exception as exc:
            logger.debug("Flow mapping failed: %s", exc)
        return None

    async def _detect_semantic_gaps(self, gap_report: CoverageGapReport) -> list[SemanticGap]:
        """Detect semantic test gaps using LLM analysis."""
        try:
            config = load_config(self.config.project_root)
            if config.llm.provider:
                llm_engine = self._create_llm_engine()
                detector = SemanticGapDetector(
                    llm_engine=llm_engine,
                    project_root=self.config.project_root,
                )
                sg_task = SemanticGapTask(
                    task_type="semantic_gap_detection",
                    target=str(self.config.project_root),
                    coverage_gap_report=gap_report,
                    function_gaps=gap_report.function_gaps,
                )
                sg_output = await detector.run(sg_task)
                if sg_output.status == TaskStatus.COMPLETED:
                    gaps: list[SemanticGap] = sg_output.result.get("semantic_gaps", [])
                    return gaps
        except Exception as exc:
            logger.debug("Semantic gap detection skipped: %s", exc)
        return []

    def _report_risk_summary(self, result: PickPipelineResult, elapsed: float) -> None:
        """Report risk and semantic analysis summary to console."""
        summary_parts: list[str] = []
        if result.risk_report:
            n_critical = len(result.risk_report.critical_files)
            n_high = len(result.risk_report.high_risk_files)
            summary_parts.append(f"{n_critical} critical, {n_high} high-risk files")
        if result.integration_deps:
            summary_parts.append(f"{len(result.integration_deps)} files need integration tests")
        if result.semantic_gaps:
            summary_parts.append(f"{len(result.semantic_gaps)} semantic gaps")
        if result.flow_mapping and result.flow_mapping.flows:
            summary_parts.append(f"{len(result.flow_mapping.flows)} user flows")
        label = ", ".join(summary_parts) if summary_parts else "No additional risks found"
        reporter.print_step_done(label, elapsed)

    async def _generate_fixes(
        self,
        bugs: list[BugReport],
        adapter: TestFrameworkAdapter,
        llm_engine: Any,  # LLMEngine (Any used due to missing py.typed)
    ) -> list[tuple[str, GeneratedFix]]:
        """Generate and verify fixes for detected bugs (parallelized)."""
        t0 = time.monotonic()
        ci_mode = self.config.ci_mode

        # Create fix pipeline agents once (shared across all tasks)
        agents = FixPipelineAgents(
            verifier=BugVerifier(llm_engine, self.config.project_root),
            root_cause_analyzer=RootCauseAnalyzer(llm_engine, self.config.project_root),
            fix_generator=FixGenerator(llm_engine, self.config.project_root),
            fix_verifier=FixVerifier(self.config.project_root),
        )

        async def _fix_one(
            i: int,
            bug_report: BugReport,
        ) -> tuple[str, GeneratedFix] | None:
            if not ci_mode:
                reporter.print_analysis_progress(
                    i, len(bugs), f"Fixing [bold]{bug_report.title[:50]}[/bold]"
                )
            try:
                fix = await self._generate_single_fix(bug_report, adapter, agents)
                if fix:
                    if not ci_mode:
                        reporter.print_success(f"    Fix verified for: {bug_report.title}")
                    return (bug_report.location.file_path, fix)
            except Exception as e:
                logger.exception("Fix generation failed for bug %s: %s", bug_report.title, e)
            return None

        tasks = [_fix_one(i, br) for i, br in enumerate(bugs, 1)]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        fixes: list[tuple[str, GeneratedFix]] = []
        for item in outcomes:
            if isinstance(item, BaseException):
                logger.warning("Fix generation raised exception: %s", item)
            elif item is not None:
                fixes.append(item)

        elapsed = time.monotonic() - t0
        if not ci_mode:
            reporter.print_step_done(f"Generated {len(fixes)} verified fixes", elapsed)

        return fixes

    async def _generate_single_fix(
        self,
        bug_report: BugReport,
        adapter: TestFrameworkAdapter,
        agents: FixPipelineAgents,
    ) -> GeneratedFix | None:
        """Generate and verify a single fix."""
        bug_id = bug_report.title[:30]
        source_path = Path(bug_report.location.file_path)
        if not source_path.exists():
            logger.warning("Source file not found: %s", source_path)
            return None

        source_code = source_path.read_text(encoding="utf-8")

        # Verify bug with reproduction test
        if not self.config.ci_mode:
            reporter.print_fix_progress(bug_id, "verify", "success", "Reproducing bug")
        verification = await self._verify_bug(bug_report, source_code, adapter, agents.verifier)
        if not verification or not verification.is_confirmed:
            if not self.config.ci_mode:
                reporter.print_fix_progress(bug_id, "verify", "failed", "Could not reproduce")
            return None

        # Analyze root cause
        if not self.config.ci_mode:
            reporter.print_fix_progress(bug_id, "root_cause", "success", "Analyzing root cause")
        root_cause = await self._analyze_root_cause(
            bug_report, source_code, verification.reproduction_test, agents.root_cause_analyzer
        )
        if not root_cause:
            if not self.config.ci_mode:
                reporter.print_fix_progress(bug_id, "root_cause", "failed", "Analysis failed")
            return None

        # Generate fix
        if not self.config.ci_mode:
            reporter.print_fix_progress(bug_id, "generate", "success", "Generating fix code")
        generated_fix = await self._generate_fix_code(
            bug_report,
            source_code,
            root_cause,
            verification.reproduction_test,
            agents.fix_generator,
        )
        if not generated_fix:
            if not self.config.ci_mode:
                reporter.print_fix_progress(bug_id, "generate", "failed", "Generation failed")
            return None

        # Verify fix doesn't cause regressions
        if not self.config.ci_mode:
            reporter.print_fix_progress(bug_id, "verify_fix", "success", "Verifying no regressions")
        ctx = FixVerificationContext(
            bug_report=bug_report,
            source_code=source_code,
            generated_fix=generated_fix,
            verification_result=verification,
        )
        if await self._verify_fix(ctx, adapter, agents.fix_verifier):
            return generated_fix

        return None

    async def _verify_bug(
        self,
        bug_report: BugReport,
        source_code: str,
        adapter: TestFrameworkAdapter,
        verifier: BugVerifier,
    ) -> VerificationResult | None:
        """Verify bug can be reproduced."""
        task = BugVerificationTask(
            target=bug_report.location.file_path,
            bug_report=bug_report,
            source_code=source_code,
            adapter=adapter,
        )

        result = await verifier.run(task)
        if result.status != TaskStatus.COMPLETED:
            logger.warning("Bug verification failed: %s", result.errors)
            return None

        verification: VerificationResult = result.result["verification"]
        if not verification.is_confirmed and not self.config.ci_mode:
            reporter.print_info("Bug could not be reproduced, skipping")

        return verification if verification.is_confirmed else None

    async def _analyze_root_cause(
        self,
        bug_report: BugReport,
        source_code: str,
        reproduction_test: str,
        analyzer: RootCauseAnalyzer,
    ) -> RootCause | None:
        """Analyze root cause of the bug."""
        task = RootCauseAnalysisTask(
            target=bug_report.location.file_path,
            bug_report=bug_report,
            reproduction_test=reproduction_test,
            source_code=source_code,
        )

        result = await analyzer.run(task)
        if result.status != TaskStatus.COMPLETED:
            logger.warning("Root cause analysis failed: %s", result.errors)
            return None

        root_cause = result.result.get("root_cause")
        if not isinstance(root_cause, RootCause):
            return None
        return root_cause

    async def _generate_fix_code(
        self,
        bug_report: BugReport,
        source_code: str,
        root_cause: RootCause,
        reproduction_test: str,
        generator: FixGenerator,
    ) -> GeneratedFix | None:
        """Generate fix code."""
        task = FixGenerationTask(
            target=bug_report.location.file_path,
            bug_report=bug_report,
            root_cause=root_cause,
            source_code=source_code,
            reproduction_test=reproduction_test,
        )

        result = await generator.run(task)
        if result.status != TaskStatus.COMPLETED:
            logger.warning("Fix generation failed: %s", result.errors)
            return None

        fix = result.result.get("fix")
        if not isinstance(fix, GeneratedFix):
            return None
        return fix

    async def _verify_fix(
        self,
        ctx: FixVerificationContext,
        adapter: TestFrameworkAdapter,
        verifier: FixVerifier,
    ) -> bool:
        """Verify fix doesn't cause regressions."""
        # Write reproduction test to temp directory
        repro_test_dir = self.config.project_root / ".nit" / "tmp" / "reproduction"
        repro_test_dir.mkdir(parents=True, exist_ok=True)
        repro_test_path = repro_test_dir / "repro_test.py"
        repro_test_path.write_text(ctx.verification_result.reproduction_test, encoding="utf-8")

        task = FixVerificationTask(
            target=ctx.bug_report.location.file_path,
            fix=ctx.generated_fix,
            original_code=ctx.source_code,
            reproduction_test_file=str(repro_test_path),
            adapter=adapter,
        )

        result = await verifier.run(task)
        if result.status != TaskStatus.COMPLETED:
            logger.warning("Fix verification failed: %s", result.errors)
            return False

        verification_report = result.result.get("verification")
        if verification_report is None or not hasattr(verification_report, "is_verified"):
            return False

        if not verification_report.is_verified and not self.config.ci_mode:
            reporter.print_warning(f"Fix verification failed: {verification_report.notes}")

        return bool(verification_report.is_verified)

    def _create_llm_engine(self) -> Any:  # LLMEngine (Any used due to missing py.typed)
        """Create LLM engine from config."""
        llm_config = load_llm_config(str(self.config.project_root))
        return create_engine(llm_config, project_root=self.config.project_root)

    def _apply_fixes(self, fixes: list[tuple[str, GeneratedFix]]) -> list[str]:
        """Apply verified fixes to source files."""
        if not fixes:
            return []

        t0 = time.monotonic()
        applied = []
        for file_path, generated_fix in fixes:
            try:
                target_path = Path(file_path)
                if not target_path.is_absolute():
                    target_path = self.config.project_root / file_path

                target_path.write_text(generated_fix.fixed_code, encoding="utf-8")
                applied.append(str(target_path))

                if not self.config.ci_mode:
                    reporter.print_success(f"  Applied fix to: {file_path}")

            except Exception as e:
                logger.exception("Failed to apply fix to %s: %s", file_path, e)

        elapsed = time.monotonic() - t0
        if not self.config.ci_mode:
            reporter.print_step_done(f"Applied {len(applied)} fixes", elapsed)

        return applied

    async def _create_bug_issues(self, bugs: list[BugReport]) -> list[str]:
        """Create GitHub issues for detected bugs."""
        if not self.config.ci_mode:
            reporter.print_info(f"Creating GitHub issues for {len(bugs)} bugs...")

        issue_reporter = GitHubIssueReporter(repo_path=self.config.project_root)
        created_issues = []

        for bug in bugs:
            try:
                # Convert BugReport to BugIssueData
                issue_data = BugIssueData(bug_report=bug)
                result = issue_reporter.create_bug_issue(issue_data)
                if result.success and result.issue_url:
                    created_issues.append(result.issue_url)
                    if not self.config.ci_mode:
                        reporter.print_success(
                            f"Created issue for: {bug.title} - {result.issue_url}"
                        )
            except Exception as e:
                logger.exception("Failed to create issue for bug %s: %s", bug.title, e)

        return created_issues

    async def _create_fix_prs(
        self,
        bugs: list[BugReport],
        fixes: list[tuple[str, GeneratedFix]],
    ) -> list[str]:
        """Create individual GitHub PRs for each bug fix.

        Args:
            bugs: List of bugs that were fixed.
            fixes: List of (file_path, fix) tuples.

        Returns:
            List of created PR URLs.
        """
        if not self.config.ci_mode:
            reporter.print_info(f"Creating individual PRs for {len(fixes)} fixes...")

        pr_reporter = GitHubPRReporter(
            repo_path=self.config.project_root,
            base_branch=self._resolve_base_branch(),
        )
        created_prs = []

        # Match each fix with its bug report
        for (file_path, fix), bug in zip(fixes, bugs, strict=True):
            try:
                result = pr_reporter.create_fix_pr(
                    bug_report=bug,
                    fix=fix,
                    file_path=file_path,
                    draft=False,
                )
                if result.success and result.pr_url:
                    created_prs.append(result.pr_url)
                    if not self.config.ci_mode:
                        reporter.print_success(f"Created PR for: {bug.title} - {result.pr_url}")
            except Exception as e:
                logger.exception("Failed to create fix PR for bug %s: %s", bug.title, e)

        return created_prs

    def _resolve_base_branch(self) -> str:
        """Resolve the base branch for PR creation.

        Uses git remote HEAD detection with fallback to ``"main"``.
        """
        try:
            return get_default_branch(self.config.project_root)
        except Exception:
            return "main"

    def _should_create_pr_or_commit(self) -> bool:
        """Determine if we should create PR or add commit."""
        if not self.config.commit_changes:
            return False
        return should_create_pr(self.ci_context, self.config.create_pr)

    def _should_run_post_loop(self, result: PickPipelineResult) -> bool:
        """Determine if any post-loop actions (issues, PRs, commits) are needed."""
        if self._should_create_pr_or_commit():
            return True
        if self.config.create_issues and result.bugs_found:
            return True
        return bool(self.config.create_fix_prs and result.fixes_generated)

    async def _create_pr_or_commit(
        self, result: PickPipelineResult
    ) -> dict[str, str | bool | None]:
        """Create PR or add commit based on context."""
        # If we're in a PR, add commit to existing PR
        if self.ci_context.is_pr:
            return await self._add_commit_to_pr(result)

        # Otherwise create a new PR
        return await self._create_new_pr(result)

    async def _add_commit_to_pr(self, result: PickPipelineResult) -> dict[str, str | bool | None]:
        """Add commit to existing PR (when running in CI within a PR)."""
        if not self.config.ci_mode:
            reporter.print_info(f"Adding commit to existing PR #{self.ci_context.pr_number}...")

        try:
            # Commit changes using git
            committed = self._commit_changes(result)

            return {
                "created": False,
                "url": None,
                "committed": committed,
            }
        except Exception as e:
            logger.exception("Failed to commit changes: %s", e)
            return {
                "created": False,
                "url": None,
                "committed": False,
                "error": str(e),
            }

    def _commit_changes(self, result: PickPipelineResult) -> bool:
        """Commit changes (fixes/tests) to git."""
        try:
            # Stage all changes
            subprocess.run(
                ["git", "add", "."],
                cwd=self.config.project_root,
                check=True,
                capture_output=True,
            )

            # Create commit message
            commit_parts = []
            if result.fixes_applied:
                commit_parts.append(f"Apply {len(result.fixes_applied)} bug fixes")
            if result.bugs_found:
                commit_parts.append(f"Found {len(result.bugs_found)} bugs")

            commit_msg = " | ".join(commit_parts) if commit_parts else "nit pick results"
            commit_msg += "\n\nCo-Authored-By: nit AI <noreply@getnit.dev>"

            # Commit
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=self.config.project_root,
                check=True,
                capture_output=True,
            )

            if not self.config.ci_mode:
                reporter.print_success("Changes committed to git")

            return True

        except subprocess.CalledProcessError as e:
            logger.warning("Git commit failed: %s", e.stderr.decode() if e.stderr else str(e))
            return False

    async def _create_new_pr(self, result: PickPipelineResult) -> dict[str, str | bool | None]:
        """Create a new PR with generated tests/fixes."""
        if not (result.fixes_applied or result.tests_run > 0):
            if not self.config.ci_mode:
                reporter.print_warning("No changes to create PR")
            return {"created": False, "url": None}

        try:
            summary = GenerationSummary(
                tests_generated=result.tests_run,
                tests_passed=result.tests_passed,
                tests_failed=result.tests_failed,
                files_created=list(result.fixes_applied),
                bugs_found=[bug.title for bug in result.bugs_found],
                bugs_fixed=[f"{fp}: {fix.explanation[:100]}" for fp, fix in result.fixes_generated],
            )

            pr_reporter = GitHubPRReporter(
                repo_path=self.config.project_root,
                base_branch=self._resolve_base_branch(),
            )

            pr_result = pr_reporter.create_pr_with_tests(summary, draft=False)

            if pr_result.success and not self.config.ci_mode:
                reporter.print_success(f"Created PR: {pr_result.pr_url}")

            return {
                "created": pr_result.success,
                "url": pr_result.pr_url if pr_result.success else None,
            }

        except Exception as e:
            logger.exception("PR creation failed: %s", e)
            if not self.config.ci_mode:
                reporter.print_error(f"Failed to create PR: {e}")
            return {"created": False, "url": None, "error": str(e)}
