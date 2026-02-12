"""Tests for DriftWatcher agent (task 3.11.1, 3.11.10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.agents.base import TaskInput, TaskStatus
from nit.agents.watchers.drift import DriftWatcher
from nit.agents.watchers.drift_comparator import ComparisonType, DriftComparator
from nit.agents.watchers.drift_test import DriftTestSpec


@pytest.fixture
def drift_watcher(tmp_path: Path) -> DriftWatcher:
    """Create a drift watcher instance with temporary storage."""
    return DriftWatcher(tmp_path)


@pytest.fixture
def drift_tests_file(tmp_path: Path) -> Path:
    """Create a drift tests YAML file."""
    yaml_content = """
tests:
  - id: test_echo
    name: "Echo test"
    endpoint_type: cli
    comparison_type: exact
    endpoint_config:
      command: ["echo", "hello drift"]

  - id: test_str_convert
    name: "String conversion test"
    endpoint_type: function
    comparison_type: semantic
    endpoint_config:
      module: builtins
      function: str
      args: [123]
    comparison_config:
      threshold: 0.8
"""

    yaml_file = tmp_path / ".nit" / "drift-tests.yml"
    yaml_file.parent.mkdir(parents=True, exist_ok=True)
    yaml_file.write_text(yaml_content, encoding="utf-8")
    return yaml_file


@pytest.mark.asyncio
async def test_run_drift_tests_no_baseline(
    drift_watcher: DriftWatcher, drift_tests_file: Path
) -> None:
    """Test running drift tests when no baseline exists."""
    report = await drift_watcher.run_drift_tests(drift_tests_file)

    assert report.total_tests == 2
    assert report.passed_tests == 0  # No baselines exist
    assert report.skipped_tests == 2  # Can't compare without baselines
    assert not report.drift_detected


@pytest.mark.asyncio
async def test_update_baselines(drift_watcher: DriftWatcher, drift_tests_file: Path) -> None:
    """Test updating baselines from test outputs."""
    report = await drift_watcher.update_baselines(drift_tests_file)

    assert report.total_tests == 2
    assert report.passed_tests == 2  # Both baselines created successfully
    assert report.skipped_tests == 0

    # Verify baselines were created
    baseline1 = drift_watcher._baselines.get_baseline("test_echo")
    assert baseline1 is not None
    assert "hello drift" in baseline1.output

    baseline2 = drift_watcher._baselines.get_baseline("test_str_convert")
    assert baseline2 is not None
    assert baseline2.output == "123"
    assert baseline2.embedding is not None  # Should have embedding for semantic


@pytest.mark.asyncio
async def test_run_drift_tests_with_baseline_no_drift(
    drift_watcher: DriftWatcher, drift_tests_file: Path
) -> None:
    """Test running drift tests with baseline and no drift."""
    # First, create baselines
    await drift_watcher.update_baselines(drift_tests_file)

    # Now run tests (outputs should match baselines)
    report = await drift_watcher.run_drift_tests(drift_tests_file)

    assert report.total_tests == 2
    assert report.passed_tests == 2  # All tests pass
    assert report.failed_tests == 0
    assert not report.drift_detected

    # Check individual results
    for result in report.results:
        assert result.passed
        assert result.baseline_exists
        assert result.error is None


@pytest.mark.asyncio
async def test_run_drift_tests_with_drift(drift_watcher: DriftWatcher, tmp_path: Path) -> None:
    """Test running drift tests when drift is detected."""
    # Create a test that will have drift
    yaml_content = """
tests:
  - id: test_counter
    name: "Counter test"
    endpoint_type: function
    comparison_type: exact
    endpoint_config:
      module: builtins
      function: str
      args: [100]
"""

    yaml_file = tmp_path / "drift-tests.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    # Create baseline with different output
    drift_watcher._baselines.set_baseline("test_counter", "200")

    # Run tests (will output "100" but baseline is "200")
    report = await drift_watcher.run_drift_tests(yaml_file)

    assert report.total_tests == 1
    assert report.passed_tests == 0
    assert report.failed_tests == 1
    assert report.drift_detected

    result = report.results[0]
    assert not result.passed
    assert result.baseline_exists
    assert result.output == "100"


@pytest.mark.asyncio
async def test_run_drift_tests_empty_file(drift_watcher: DriftWatcher, tmp_path: Path) -> None:
    """Test running drift tests with empty file."""
    empty_file = tmp_path / "empty.yml"
    empty_file.write_text("", encoding="utf-8")

    report = await drift_watcher.run_drift_tests(empty_file)

    assert report.total_tests == 0
    assert report.passed_tests == 0
    assert report.failed_tests == 0
    assert not report.drift_detected


@pytest.mark.asyncio
async def test_run_drift_tests_nonexistent_file(
    drift_watcher: DriftWatcher, tmp_path: Path
) -> None:
    """Test running drift tests with nonexistent file."""
    nonexistent = tmp_path / "nonexistent.yml"

    report = await drift_watcher.run_drift_tests(nonexistent)

    assert report.total_tests == 0


@pytest.mark.asyncio
async def test_run_drift_tests_with_test_error(drift_watcher: DriftWatcher, tmp_path: Path) -> None:
    """Test handling of test execution errors."""
    # Create a test that will fail
    yaml_content = """
tests:
  - id: test_fail
    name: "Failing test"
    endpoint_type: function
    comparison_type: exact
    endpoint_config:
      module: nonexistent_module
      function: nonexistent_function
"""

    yaml_file = tmp_path / "drift-tests.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    # Create baseline
    drift_watcher._baselines.set_baseline("test_fail", "some output")

    # Run tests
    report = await drift_watcher.run_drift_tests(yaml_file)

    assert report.total_tests == 1
    assert report.skipped_tests == 1  # Error counts as skipped

    result = report.results[0]
    assert not result.passed
    assert result.error is not None


@pytest.mark.asyncio
async def test_semantic_drift_detection(drift_watcher: DriftWatcher, tmp_path: Path) -> None:
    """Test semantic drift detection."""
    # Create a semantic test
    yaml_content = """
tests:
  - id: test_semantic
    name: "Semantic test"
    endpoint_type: cli
    comparison_type: semantic
    endpoint_config:
      command: ["echo", "The quick brown fox"]
    comparison_config:
      threshold: 0.7
"""

    yaml_file = tmp_path / "drift-tests.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    # Create baseline with similar text
    comparator = DriftComparator()
    baseline_text = "A fast brown fox"
    baseline_embedding = comparator.embed_text(baseline_text)

    drift_watcher._baselines.set_baseline(
        "test_semantic",
        baseline_text,
        embedding=baseline_embedding,
    )

    # Run tests
    report = await drift_watcher.run_drift_tests(yaml_file)

    assert report.total_tests == 1

    result = report.results[0]
    assert result.similarity_score is not None
    # Should pass due to semantic similarity, even though text differs
    assert result.passed


@pytest.mark.asyncio
async def test_regex_comparison(drift_watcher: DriftWatcher, tmp_path: Path) -> None:
    """Test regex-based drift detection."""
    yaml_content = r"""
tests:
  - id: test_regex
    name: "Regex test"
    endpoint_type: cli
    comparison_type: regex
    endpoint_config:
      command: ["echo", "version 1.2.3"]
    comparison_config:
      pattern: 'version [0-9]+\.[0-9]+\.[0-9]+'
"""

    yaml_file = tmp_path / "drift-tests.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    # Create a baseline (required even though pattern is used for comparison)
    drift_watcher._baselines.set_baseline("test_regex", "version 1.2.3\n")

    # Run tests
    report = await drift_watcher.run_drift_tests(yaml_file)

    assert report.total_tests == 1

    result = report.results[0]
    assert result.passed  # Pattern should match


@pytest.mark.asyncio
async def test_schema_comparison(drift_watcher: DriftWatcher, tmp_path: Path) -> None:
    """Test schema-based drift detection."""
    yaml_content = """
tests:
  - id: test_schema
    name: "Schema test"
    endpoint_type: cli
    comparison_type: schema
    endpoint_config:
      command: ["echo", '{"name": "Alice", "age": 30}']
    comparison_config:
      schema:
        type: object
        properties:
          name:
            type: string
          age:
            type: number
        required: ["name"]
"""

    yaml_file = tmp_path / "drift-tests.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    # Create a baseline (required even though schema is used for validation)
    drift_watcher._baselines.set_baseline("test_schema", '{"name": "Alice", "age": 30}\n')

    # Run tests
    report = await drift_watcher.run_drift_tests(yaml_file)

    assert report.total_tests == 1

    result = report.results[0]
    assert result.passed  # Schema should validate


# ── Coverage: DriftWatcher Agent interface ────────────────────────


class TestDriftWatcherAgent:
    def test_name(self, drift_watcher: DriftWatcher) -> None:
        assert drift_watcher.name == "drift_watcher"

    def test_description(self, drift_watcher: DriftWatcher) -> None:
        assert "drift" in drift_watcher.description.lower()


# ── Coverage: run() method via TaskInput ──────────────────────────


@pytest.mark.asyncio
async def test_run_test_mode(drift_watcher: DriftWatcher, drift_tests_file: Path) -> None:
    """Test running drift watcher via run() in test mode."""
    task = TaskInput(
        task_type="drift",
        target=str(drift_tests_file.parent.parent),
        context={"mode": "test", "tests_file": str(drift_tests_file)},
    )
    output = await drift_watcher.run(task)
    assert output.status == TaskStatus.COMPLETED
    assert "report" in output.result
    assert "results" in output.result


@pytest.mark.asyncio
async def test_run_baseline_mode(drift_watcher: DriftWatcher, drift_tests_file: Path) -> None:
    """Test running drift watcher via run() in baseline mode."""
    task = TaskInput(
        task_type="drift",
        target=str(drift_tests_file.parent.parent),
        context={"mode": "baseline", "tests_file": str(drift_tests_file)},
    )
    output = await drift_watcher.run(task)
    assert output.status == TaskStatus.COMPLETED
    report = output.result["report"]
    assert report["total_tests"] == 2


@pytest.mark.asyncio
async def test_run_exception_handling(tmp_path: Path) -> None:
    """Test run() handles exceptions gracefully."""
    watcher = DriftWatcher(tmp_path)
    task = TaskInput(
        task_type="drift",
        target=str(tmp_path),
        context={
            "mode": "test",
            "tests_file": str(tmp_path / "nonexistent.yml"),
        },
    )
    output = await watcher.run(task)
    # Should complete successfully with 0 tests (no file found)
    assert output.status == TaskStatus.COMPLETED


# ── Coverage: update_baselines with empty file ────────────────────


@pytest.mark.asyncio
async def test_update_baselines_empty_file(drift_watcher: DriftWatcher, tmp_path: Path) -> None:
    """Update baselines with empty YAML."""
    empty_file = tmp_path / "empty.yml"
    empty_file.write_text("", encoding="utf-8")
    report = await drift_watcher.update_baselines(empty_file)
    assert report.total_tests == 0


# ── Coverage: _execute_and_update_baseline error ──────────────────


@pytest.mark.asyncio
async def test_update_baselines_with_error(drift_watcher: DriftWatcher, tmp_path: Path) -> None:
    """Test baseline update with execution error."""
    yaml_content = """
tests:
  - id: test_bad_baseline
    name: "Bad baseline"
    endpoint_type: function
    comparison_type: exact
    endpoint_config:
      module: nonexistent_module_xyz
      function: nonexistent_function
"""
    yaml_file = tmp_path / "bad.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")
    report = await drift_watcher.update_baselines(yaml_file)
    assert report.total_tests == 1
    assert report.skipped_tests == 1  # Error
    assert report.results[0].error is not None


# ── Coverage: prompt optimization suggestions ─────────────────────


@pytest.mark.asyncio
async def test_drift_with_prompt_optimization(drift_watcher: DriftWatcher, tmp_path: Path) -> None:
    """Test that prompt optimization is generated on drift."""
    yaml_content = """
tests:
  - id: test_opt
    name: "Optimization test"
    endpoint_type: function
    comparison_type: exact
    endpoint_config:
      module: builtins
      function: str
      args: [100]
"""
    yaml_file = tmp_path / "opt.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    # Set a very different baseline to trigger drift
    drift_watcher._baselines.set_baseline("test_opt", "completely different text")

    report = await drift_watcher.run_drift_tests(yaml_file)
    assert report.drift_detected
    result = report.results[0]
    assert not result.passed
    # Should have prompt optimization suggestions
    assert result.prompt_optimization.get("suggestions") is not None


@pytest.mark.asyncio
async def test_drift_no_prompt_optimization_disabled(tmp_path: Path) -> None:
    """Test that prompt optimization is skipped when disabled."""
    watcher = DriftWatcher(tmp_path, enable_prompt_optimization=False)

    yaml_content = """
tests:
  - id: test_no_opt
    name: "No optimization"
    endpoint_type: function
    comparison_type: exact
    endpoint_config:
      module: builtins
      function: str
      args: [42]
"""
    yaml_file = tmp_path / "noopt.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    watcher._baselines.set_baseline("test_no_opt", "different value")
    report = await watcher.run_drift_tests(yaml_file)
    result = report.results[0]
    assert result.prompt_optimization == {}


# ── Coverage: _generate_optimization_suggestions edge cases ───────


class TestOptimizationSuggestions:
    def test_critical_similarity(self, drift_watcher: DriftWatcher) -> None:
        """Test suggestions for critical similarity score."""
        spec = DriftTestSpec(
            id="t",
            name="t",
            endpoint_type=None,  # type: ignore[arg-type]
            comparison_type=ComparisonType.EXACT,
        )
        result = drift_watcher._generate_optimization_suggestions(spec, "baseline", "current", 0.3)
        assert result["drift_severity"] == "critical"
        assert any("CRITICAL" in s for s in result["suggestions"])

    def test_moderate_similarity(self, drift_watcher: DriftWatcher) -> None:
        spec = DriftTestSpec(
            id="t",
            name="t",
            endpoint_type=None,  # type: ignore[arg-type]
            comparison_type=ComparisonType.EXACT,
        )
        result = drift_watcher._generate_optimization_suggestions(spec, "baseline", "current", 0.65)
        assert result["drift_severity"] == "moderate"
        assert any("MODERATE" in s for s in result["suggestions"])

    def test_minor_severity(self, drift_watcher: DriftWatcher) -> None:
        spec = DriftTestSpec(
            id="t",
            name="t",
            endpoint_type=None,  # type: ignore[arg-type]
            comparison_type=ComparisonType.EXACT,
        )
        result = drift_watcher._generate_optimization_suggestions(spec, "a b c", "a b c d", 0.85)
        assert result["drift_severity"] == "minor"

    def test_unknown_severity_no_score(self, drift_watcher: DriftWatcher) -> None:
        spec = DriftTestSpec(
            id="t",
            name="t",
            endpoint_type=None,  # type: ignore[arg-type]
            comparison_type=ComparisonType.EXACT,
        )
        result = drift_watcher._generate_optimization_suggestions(spec, "base", "curr", None)
        assert result["drift_severity"] == "unknown"

    def test_length_diff_suggestion(self, drift_watcher: DriftWatcher) -> None:
        spec = DriftTestSpec(
            id="t",
            name="t",
            endpoint_type=None,  # type: ignore[arg-type]
            comparison_type=ComparisonType.EXACT,
        )
        # Very different lengths
        baseline = "word " * 100
        current = "word " * 10
        result = drift_watcher._generate_optimization_suggestions(spec, baseline, current, 0.6)
        assert any("length" in s.lower() for s in result["suggestions"])

    def test_format_change_suggestion(self, drift_watcher: DriftWatcher) -> None:
        spec = DriftTestSpec(
            id="t",
            name="t",
            endpoint_type=None,  # type: ignore[arg-type]
            comparison_type=ComparisonType.EXACT,
        )
        # Baseline has JSON, current doesn't
        result = drift_watcher._generate_optimization_suggestions(
            spec, '{"key": "value"}', "plain text output", 0.4
        )
        assert any("format" in s.lower() for s in result["suggestions"])
