"""DriftWatcher agent for monitoring LLM output drift (task 3.11.1).

Executes drift tests, compares results against baselines, and reports drift.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.agents.watchers.drift_comparator import CompareConfig, ComparisonType, DriftComparator
from nit.agents.watchers.drift_test import DriftTestExecutor, DriftTestParser, DriftTestSpec
from nit.llm.prompt_analysis import PromptOptimizer
from nit.memory.analytics_collector import get_analytics_collector
from nit.memory.drift_baselines import DriftBaselinesManager

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Drift severity thresholds (task 3.12.4)
_CRITICAL_SIMILARITY_THRESHOLD = 0.5
_MODERATE_SIMILARITY_THRESHOLD = 0.7
_STABLE_SIMILARITY_THRESHOLD = 0.8
_SIGNIFICANT_LENGTH_DIFF_THRESHOLD = 0.5


@dataclass
class DriftTestResult:
    """Result of a single drift test execution."""

    test_id: str
    test_name: str
    passed: bool
    output: str
    similarity_score: float | None = None
    error: str | None = None
    baseline_exists: bool = False
    executed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    details: dict[str, Any] = field(default_factory=dict)
    prompt_optimization: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftReport:
    """Report of all drift test results."""

    total_tests: int
    passed_tests: int
    failed_tests: int
    skipped_tests: int
    drift_detected: bool
    results: list[DriftTestResult] = field(default_factory=list)
    executed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class DriftWatcher(BaseAgent):
    """Agent for monitoring LLM output drift over time (task 3.11.1).

    Loads drift test definitions from `.nit/drift-tests.yml`, executes tests,
    compares against baselines, and reports drift.
    """

    def __init__(self, project_root: Path, *, enable_prompt_optimization: bool = True) -> None:
        """Initialize the drift watcher.

        Args:
            project_root: Root directory of the project.
            enable_prompt_optimization: Whether to include prompt optimization
                suggestions (task 3.12.4).
        """
        self._project_root = project_root
        self._baselines = DriftBaselinesManager(project_root)
        self._comparator = DriftComparator()
        self._executor = DriftTestExecutor()
        self._enable_prompt_optimization = enable_prompt_optimization
        self._prompt_optimizer = PromptOptimizer() if enable_prompt_optimization else None

    @property
    def name(self) -> str:
        """Agent identifier."""
        return "drift_watcher"

    @property
    def description(self) -> str:
        """Human-readable description."""
        return "Monitors LLM output drift over time by comparing test results against baselines"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute drift monitoring task.

        Task context can include:
        - mode: "test" | "baseline" (default: "test")
        - tests_file: path to drift-tests.yml (default: .nit/drift-tests.yml)

        Args:
            task: The drift monitoring task.

        Returns:
            Task output with drift report.
        """
        mode = task.context.get("mode", "test")
        tests_file = task.context.get("tests_file", ".nit/drift-tests.yml")

        try:
            if mode == "baseline":
                report = await self.update_baselines(tests_file)
            else:
                report = await self.run_drift_tests(tests_file)

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "report": {
                        "total_tests": report.total_tests,
                        "passed_tests": report.passed_tests,
                        "failed_tests": report.failed_tests,
                        "skipped_tests": report.skipped_tests,
                        "drift_detected": report.drift_detected,
                        "executed_at": report.executed_at,
                    },
                    "results": [
                        {
                            "test_id": r.test_id,
                            "test_name": r.test_name,
                            "passed": r.passed,
                            "similarity_score": r.similarity_score,
                            "error": r.error,
                            "baseline_exists": r.baseline_exists,
                            "prompt_optimization": r.prompt_optimization,
                        }
                        for r in report.results
                    ],
                },
            )

        except Exception as e:
            logger.error("Drift monitoring failed: %s", e)
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[str(e)],
            )

    async def run_drift_tests(self, tests_file: str | Path) -> DriftReport:
        """Run all drift tests and compare against baselines (task 3.11.1).

        Args:
            tests_file: Path to drift-tests.yml file.

        Returns:
            Drift report with all test results.
        """
        # Parse test specs
        tests_path = self._project_root / tests_file if isinstance(tests_file, str) else tests_file
        specs = DriftTestParser.parse_file(tests_path)

        if not specs:
            logger.warning("No drift tests found")
            return DriftReport(
                total_tests=0,
                passed_tests=0,
                failed_tests=0,
                skipped_tests=0,
                drift_detected=False,
            )

        # Execute tests and compare
        results = []
        for spec in specs:
            result = await self._execute_and_compare_test(spec)
            results.append(result)

            # Record drift test result to analytics
            if result.similarity_score is not None:
                try:
                    collector = get_analytics_collector(self._project_root)
                    collector.record_drift_test(
                        test_id=result.test_id,
                        test_name=result.test_name,
                        similarity_score=result.similarity_score,
                        passed=result.passed,
                        drift_detected=not result.passed,
                    )
                except Exception:
                    logger.exception("Failed to record drift test to analytics")

        # Generate report
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed and r.error is None)
        skipped = sum(1 for r in results if r.error is not None)

        return DriftReport(
            total_tests=len(results),
            passed_tests=passed,
            failed_tests=failed,
            skipped_tests=skipped,
            drift_detected=failed > 0,
            results=results,
        )

    async def update_baselines(self, tests_file: str | Path) -> DriftReport:
        """Update baselines by executing all tests and storing outputs (task 3.11.8).

        Args:
            tests_file: Path to drift-tests.yml file.

        Returns:
            Report of baseline updates.
        """
        # Parse test specs
        tests_path = self._project_root / tests_file if isinstance(tests_file, str) else tests_file
        specs = DriftTestParser.parse_file(tests_path)

        if not specs:
            logger.warning("No drift tests found")
            return DriftReport(
                total_tests=0,
                passed_tests=0,
                failed_tests=0,
                skipped_tests=0,
                drift_detected=False,
            )

        # Execute tests and update baselines
        results = []
        for spec in specs:
            result = await self._execute_and_update_baseline(spec)
            results.append(result)

        # Generate report
        successful = sum(1 for r in results if r.error is None)
        failed = sum(1 for r in results if r.error is not None)

        return DriftReport(
            total_tests=len(results),
            passed_tests=successful,
            failed_tests=0,
            skipped_tests=failed,
            drift_detected=False,
            results=results,
        )

    async def _execute_and_compare_test(self, spec: DriftTestSpec) -> DriftTestResult:
        """Execute a test and compare against baseline.

        Args:
            spec: Test specification.

        Returns:
            Test result.
        """
        try:
            # Execute test
            output = await self._executor.execute_test(spec)

            # Get baseline
            baseline = self._baselines.get_baseline(spec.id)

            if baseline is None:
                # No baseline exists - can't compare
                logger.warning("No baseline for test %s, skipping comparison", spec.id)
                return DriftTestResult(
                    test_id=spec.id,
                    test_name=spec.name,
                    passed=False,
                    output=output,
                    baseline_exists=False,
                    error="No baseline exists for this test",
                )

            # Compare with baseline
            threshold = spec.comparison_config.get("threshold", 0.8)
            pattern = spec.comparison_config.get("pattern")
            schema = spec.comparison_config.get("schema")

            comparison_result = self._comparator.compare(
                CompareConfig(
                    comparison_type=spec.comparison_type,
                    baseline=baseline.output,
                    current=output,
                    baseline_embedding=baseline.embedding,
                    threshold=threshold,
                    pattern=pattern,
                    schema=schema,
                )
            )

            # Generate prompt optimization suggestions if drift detected (task 3.12.4)
            prompt_optimization = {}
            if not comparison_result.passed and self._enable_prompt_optimization:
                prompt_optimization = self._generate_optimization_suggestions(
                    spec, baseline.output, output, comparison_result.similarity_score
                )

            return DriftTestResult(
                test_id=spec.id,
                test_name=spec.name,
                passed=comparison_result.passed,
                output=output,
                similarity_score=comparison_result.similarity_score,
                error=comparison_result.error,
                baseline_exists=True,
                details=comparison_result.details or {},
                prompt_optimization=prompt_optimization,
            )

        except Exception as e:
            logger.error("Test execution failed for %s: %s", spec.id, e)
            return DriftTestResult(
                test_id=spec.id,
                test_name=spec.name,
                passed=False,
                output="",
                error=str(e),
            )

    async def _execute_and_update_baseline(self, spec: DriftTestSpec) -> DriftTestResult:
        """Execute a test and update its baseline.

        Args:
            spec: Test specification.

        Returns:
            Test result.
        """
        try:
            # Execute test
            output = await self._executor.execute_test(spec)

            # Generate embedding if using semantic comparison
            embedding = None
            if spec.comparison_type == ComparisonType.SEMANTIC:
                try:
                    embedding = self._comparator.embed_text(output)
                except Exception as e:
                    logger.warning("Failed to generate embedding for test %s: %s", spec.id, e)

            # Update baseline
            self._baselines.set_baseline(
                test_id=spec.id,
                output=output,
                embedding=embedding,
                metadata={
                    "test_name": spec.name,
                    "comparison_type": spec.comparison_type.value,
                },
            )

            logger.info("Updated baseline for test: %s", spec.id)

            return DriftTestResult(
                test_id=spec.id,
                test_name=spec.name,
                passed=True,
                output=output,
                baseline_exists=True,
            )

        except Exception as e:
            logger.error("Baseline update failed for %s: %s", spec.id, e)
            return DriftTestResult(
                test_id=spec.id,
                test_name=spec.name,
                passed=False,
                output="",
                error=str(e),
            )

    def _generate_optimization_suggestions(
        self,
        _spec: DriftTestSpec,
        baseline_output: str,
        current_output: str,
        similarity_score: float | None,
    ) -> dict[str, Any]:
        """Generate prompt optimization suggestions when drift is detected (task 3.12.4).

        Args:
            _spec: The drift test specification (unused).
            baseline_output: The baseline output.
            current_output: The current (drifted) output.
            similarity_score: Similarity score between outputs.

        Returns:
            Dictionary with optimization suggestions.
        """
        if not self._prompt_optimizer:
            return {}

        suggestions = []

        # Analyze drift severity
        if similarity_score is not None:
            if similarity_score < _CRITICAL_SIMILARITY_THRESHOLD:
                suggestions.append(
                    "CRITICAL: Low similarity score. Consider adding explicit output "
                    "format constraints (e.g., 'Return ONLY valid JSON' or 'Use "
                    "exactly this format:')."
                )
            elif similarity_score < _MODERATE_SIMILARITY_THRESHOLD:
                suggestions.append(
                    "MODERATE: Moderate drift detected. Add few-shot examples "
                    "demonstrating the exact expected output format."
                )

        # Check for length differences
        baseline_len = len(baseline_output.split())
        current_len = len(current_output.split())
        len_diff_ratio = abs(baseline_len - current_len) / max(baseline_len, 1)

        if len_diff_ratio > _SIGNIFICANT_LENGTH_DIFF_THRESHOLD:
            suggestions.append(
                f"Output length changed significantly ({baseline_len} → "
                f"{current_len} words). Add explicit length constraints "
                "(e.g., 'Keep response under 100 words')."
            )

        # Check for format differences (JSON, structured output)
        baseline_has_json = "{" in baseline_output and "}" in baseline_output
        current_has_json = "{" in current_output and "}" in current_output

        if baseline_has_json != current_has_json:
            suggestions.append(
                "Output format changed between structured and unstructured. "
                "Add JSON schema or explicit format requirements."
            )

        # Temperature recommendations
        if similarity_score is not None and similarity_score < _STABLE_SIMILARITY_THRESHOLD:
            suggestions.append(
                "Consider lowering temperature (0.0-0.2) for more deterministic "
                "outputs if consistency is critical."
            )

        # General prompt improvement suggestions
        suggestions.append(
            "Add output validation constraints: specify exact format, required fields, "
            "and forbidden content."
        )

        # Determine severity
        if similarity_score is not None:
            if similarity_score < _CRITICAL_SIMILARITY_THRESHOLD:
                severity = "critical"
            elif similarity_score < _MODERATE_SIMILARITY_THRESHOLD:
                severity = "moderate"
            else:
                severity = "minor"
        else:
            severity = "unknown"

        return {
            "similarity_score": similarity_score,
            "drift_severity": severity,
            "suggestions": suggestions,
            "recommended_actions": [
                "Review and tighten prompt instructions",
                "Add few-shot examples showing expected output",
                "Consider lowering temperature for consistency",
                "Add explicit format validation (JSON schema, regex patterns)",
            ],
        }
