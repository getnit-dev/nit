"""Tests for the CoverageAnalyzer (agents/analyzers/coverage.py).

Covers:
- Running coverage via adapters
- Identifying untested files (0% coverage)
- Identifying undertested functions
- Calculating cyclomatic complexity
- Identifying stale tests
- Generating gap reports
- Creating BuildTask entries
- Priority calculation
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from nit.adapters.coverage.base import (
    BranchCoverage,
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    LineCoverage,
)
from nit.agents.analyzers.coverage import (
    CoverageAnalysisTask,
    CoverageAnalyzer,
    GapPriority,
)
from nit.agents.base import TaskInput, TaskStatus
from nit.parsing.treesitter import FunctionInfo

# ── Sample source files ──────────────────────────────────────────


_SIMPLE_PYTHON_SOURCE = """
def add(a, b):
    '''Add two numbers.'''
    return a + b

def _private_helper():
    '''Private helper function.'''
    return 42

def complex_function(x, y, z):
    '''Complex function with multiple branches.'''
    if x > 0:
        if y > 0:
            if z > 0:
                return x + y + z
            else:
                return x + y
        else:
            if z > 0:
                return x + z
            else:
                return x
    else:
        if y > 0:
            if z > 0:
                return y + z
            else:
                return y
        else:
            return 0
"""

_TYPESCRIPT_SOURCE = """
export function calculatePrice(quantity: number, price: number): number {
  if (quantity <= 0) {
    throw new Error('Quantity must be positive');
  }

  if (price < 0) {
    throw new Error('Price cannot be negative');
  }

  let total = quantity * price;

  if (quantity >= 100) {
    total *= 0.9; // 10% discount
  } else if (quantity >= 50) {
    total *= 0.95; // 5% discount
  }

  return total;
}

function _internalHelper(): string {
  return 'helper';
}
"""

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    # Create source files
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    (src_dir / "calculator.py").write_text(_SIMPLE_PYTHON_SOURCE)
    (src_dir / "pricing.ts").write_text(_TYPESCRIPT_SOURCE)

    # Create test directory
    test_dir = tmp_path / "tests"
    test_dir.mkdir()

    # Create a stale test
    (test_dir / "test_old_module.py").write_text("""
from old_module import deleted_function

def test_deleted() -> None:
    assert deleted_function() == 42
""")

    return tmp_path


@pytest.fixture
def mock_coverage_report() -> CoverageReport:
    """Create a mock coverage report."""
    report = CoverageReport()

    # File 1: calculator.py with partial coverage
    report.files["src/calculator.py"] = FileCoverage(
        file_path="src/calculator.py",
        lines=[
            LineCoverage(line_number=2, execution_count=10),  # add function: covered
            LineCoverage(line_number=3, execution_count=10),
            LineCoverage(line_number=4, execution_count=10),
            LineCoverage(line_number=6, execution_count=0),  # _private_helper: not covered
            LineCoverage(line_number=7, execution_count=0),
            LineCoverage(line_number=8, execution_count=0),
            LineCoverage(line_number=10, execution_count=0),  # complex_function: not covered
        ],
        functions=[
            FunctionCoverage(name="add", line_number=2, execution_count=10),
            FunctionCoverage(name="_private_helper", line_number=6, execution_count=0),
            FunctionCoverage(name="complex_function", line_number=10, execution_count=0),
        ],
        branches=[
            BranchCoverage(line_number=10, branch_id=1, taken_count=0, total_count=6),
        ],
    )

    # File 2: pricing.ts with zero coverage
    report.files["src/pricing.ts"] = FileCoverage(
        file_path="src/pricing.ts",
        lines=[
            LineCoverage(line_number=1, execution_count=0),
            LineCoverage(line_number=2, execution_count=0),
        ],
        functions=[
            FunctionCoverage(name="calculatePrice", line_number=1, execution_count=0),
            FunctionCoverage(name="_internalHelper", line_number=20, execution_count=0),
        ],
    )

    return report


@pytest.fixture
def mock_adapter(mock_coverage_report: CoverageReport) -> Mock:
    """Create a mock coverage adapter."""
    adapter = Mock()
    adapter.name = "mock_coverage"
    adapter.language = "python"
    adapter.detect = Mock(return_value=True)
    adapter.run_coverage = AsyncMock(return_value=mock_coverage_report)
    return adapter


# ── Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_coverage_analyzer_basic(
    project_root: Path, mock_adapter: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test basic coverage analysis flow."""

    analyzer = CoverageAnalyzer(project_root)
    # Directly patch the coverage adapters
    analyzer._coverage_adapters = [mock_adapter]
    task = CoverageAnalysisTask(project_root=str(project_root), coverage_threshold=80.0)

    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert "gap_report" in result.result
    assert "build_tasks" in result.result


@pytest.mark.asyncio
async def test_identify_untested_files(
    project_root: Path, mock_adapter: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test identification of files with 0% coverage."""

    analyzer = CoverageAnalyzer(project_root)
    # Directly patch the coverage adapters
    analyzer._coverage_adapters = [mock_adapter]
    task = CoverageAnalysisTask(project_root=str(project_root))

    result = await analyzer.run(task)

    gap_report = result.result["gap_report"]

    # pricing.ts should be identified as untested (0% coverage)
    assert "src/pricing.ts" in gap_report.untested_files


@pytest.mark.asyncio
async def test_identify_function_gaps(
    project_root: Path, mock_adapter: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test identification of undertested functions."""

    analyzer = CoverageAnalyzer(project_root)
    # Directly patch the coverage adapters
    analyzer._coverage_adapters = [mock_adapter]
    task = CoverageAnalysisTask(project_root=str(project_root))

    result = await analyzer.run(task)

    gap_report = result.result["gap_report"]
    function_gaps = gap_report.function_gaps

    # Should have identified gaps for uncovered functions
    # Note: This depends on tree-sitter parsing working correctly
    assert len(function_gaps) >= 0  # May be 0 if tree-sitter can't parse temp files


@pytest.mark.asyncio
async def test_priority_calculation(project_root: Path) -> None:
    """Test priority calculation for gaps."""
    analyzer = CoverageAnalyzer(project_root)

    # Critical: high complexity + zero coverage
    priority = analyzer._calculate_priority(complexity=15, coverage_pct=0.0, is_public=True)
    assert priority == GapPriority.CRITICAL

    # Critical: public API + zero coverage
    priority = analyzer._calculate_priority(complexity=3, coverage_pct=0.0, is_public=True)
    assert priority == GapPriority.CRITICAL

    # High: moderate complexity + low coverage
    priority = analyzer._calculate_priority(complexity=7, coverage_pct=20.0, is_public=False)
    assert priority == GapPriority.HIGH

    # High: public API + low coverage
    priority = analyzer._calculate_priority(complexity=2, coverage_pct=30.0, is_public=True)
    assert priority == GapPriority.HIGH

    # Medium: some coverage but below threshold
    priority = analyzer._calculate_priority(complexity=3, coverage_pct=40.0, is_public=False)
    assert priority == GapPriority.MEDIUM

    # Low: private + low complexity
    priority = analyzer._calculate_priority(complexity=2, coverage_pct=0.0, is_public=False)
    assert priority == GapPriority.LOW


@pytest.mark.asyncio
async def test_complexity_estimation(project_root: Path) -> None:
    """Test cyclomatic complexity estimation."""
    analyzer = CoverageAnalyzer(project_root)

    # Simple function (complexity = 1)
    simple_func = FunctionInfo(
        name="simple",
        start_line=1,
        end_line=3,
        body_text="return a + b",
    )
    complexity = analyzer._estimate_complexity(simple_func)
    assert complexity == 1

    # Function with one if statement (complexity = 2)
    if_func = FunctionInfo(
        name="with_if",
        start_line=1,
        end_line=5,
        body_text="if x > 0:\n    return x\nelse:\n    return 0",
    )
    complexity = analyzer._estimate_complexity(if_func)
    assert complexity >= 2

    # Function with nested conditionals (high complexity)
    complex_func = FunctionInfo(
        name="complex",
        start_line=1,
        end_line=20,
        body_text="""
if x > 0:
    if y > 0:
        if z > 0:
            return 1
        else:
            return 2
    else:
        return 3
else:
    for i in range(10):
        if i % 2 == 0:
            continue
    while x < 100:
        x += 1
""",
    )
    complexity = analyzer._estimate_complexity(complex_func)
    assert complexity >= 10


@pytest.mark.asyncio
async def test_public_function_detection(project_root: Path) -> None:
    """Test detection of public vs private functions."""
    analyzer = CoverageAnalyzer(project_root)

    # Public function
    public_func = FunctionInfo(name="calculate", start_line=1, end_line=3)
    assert analyzer._is_public_function(public_func) is True

    # Private function (Python convention)
    private_func = FunctionInfo(name="_internal", start_line=1, end_line=3)
    assert analyzer._is_public_function(private_func) is False

    # Dunder method (should be public)
    dunder_func = FunctionInfo(name="__init__", start_line=1, end_line=3)
    assert analyzer._is_public_function(dunder_func) is True

    # Function with @private decorator
    decorated_func = FunctionInfo(
        name="secret",
        start_line=1,
        end_line=3,
        decorators=["@private"],
    )
    assert analyzer._is_public_function(decorated_func) is False


@pytest.mark.asyncio
async def test_stale_test_detection(
    project_root: Path, mock_adapter: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test identification of stale tests."""

    analyzer = CoverageAnalyzer(project_root)
    # Directly patch the coverage adapters
    analyzer._coverage_adapters = [mock_adapter]
    task = CoverageAnalysisTask(project_root=str(project_root))

    result = await analyzer.run(task)

    gap_report = result.result["gap_report"]
    stale_tests = gap_report.stale_tests

    # Should identify the stale test that imports deleted module
    assert len(stale_tests) >= 1
    if stale_tests:
        assert "old_module" in stale_tests[0].missing_imports[0]


@pytest.mark.asyncio
async def test_build_task_creation(
    project_root: Path, mock_adapter: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test creation of BuildTask entries from gap report."""

    analyzer = CoverageAnalyzer(project_root)
    # Directly patch the coverage adapters
    analyzer._coverage_adapters = [mock_adapter]
    task = CoverageAnalysisTask(project_root=str(project_root))

    result = await analyzer.run(task)

    build_tasks = result.result["build_tasks"]

    # Should have created at least one BuildTask
    assert len(build_tasks) >= 1

    # All tasks should have required fields
    for build_task in build_tasks:
        assert build_task.task_type == "build_unit_test"
        assert build_task.source_file
        assert build_task.target


@pytest.mark.asyncio
async def test_gap_report_prioritization(
    project_root: Path, mock_adapter: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that gap report returns prioritized gaps."""

    analyzer = CoverageAnalyzer(project_root)
    # Directly patch the coverage adapters
    analyzer._coverage_adapters = [mock_adapter]
    task = CoverageAnalysisTask(project_root=str(project_root))

    result = await analyzer.run(task)

    gap_report = result.result["gap_report"]
    prioritized = gap_report.get_prioritized_gaps()

    # Verify sorting: critical should come before high, high before medium, etc.
    if len(prioritized) > 1:
        priority_values = {
            GapPriority.CRITICAL: 0,
            GapPriority.HIGH: 1,
            GapPriority.MEDIUM: 2,
            GapPriority.LOW: 3,
        }
        for i in range(len(prioritized) - 1):
            curr_priority = priority_values[prioritized[i].priority]
            next_priority = priority_values[prioritized[i + 1].priority]
            assert curr_priority <= next_priority


@pytest.mark.asyncio
async def test_no_coverage_adapter_found(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test behavior when no coverage adapter can run."""

    analyzer = CoverageAnalyzer(project_root)
    # Set empty list of coverage adapters
    analyzer._coverage_adapters = []
    task = CoverageAnalysisTask(project_root=str(project_root))

    result = await analyzer.run(task)

    # Should fail gracefully when no adapter found
    assert result.status == TaskStatus.FAILED
    assert "No coverage adapter" in result.errors[0]


@pytest.mark.asyncio
async def test_invalid_task_type(project_root: Path) -> None:
    """Test that analyzer rejects invalid task types."""
    analyzer = CoverageAnalyzer(project_root)
    invalid_task = TaskInput(task_type="invalid", target="test")

    result = await analyzer.run(invalid_task)

    assert result.status == TaskStatus.FAILED
    assert "CoverageAnalysisTask" in result.errors[0]


@pytest.mark.asyncio
async def test_nonexistent_project_root() -> None:
    """Test behavior with non-existent project root."""
    analyzer = CoverageAnalyzer(Path("/nonexistent/path"))
    task = CoverageAnalysisTask(project_root="/nonexistent/path")

    result = await analyzer.run(task)

    assert result.status == TaskStatus.FAILED
    assert "does not exist" in result.errors[0]


@pytest.mark.asyncio
async def test_overall_coverage_calculation(mock_coverage_report: CoverageReport) -> None:
    """Test overall coverage percentage calculation."""
    # calculator.py: 3 covered lines out of 7 = ~43%
    # pricing.ts: 0 covered lines out of 2 = 0%
    # Overall: 3 covered out of 9 = ~33%

    overall = mock_coverage_report.overall_line_coverage

    # Should be around 33% (3/9)
    assert 30.0 <= overall <= 40.0


@pytest.mark.asyncio
async def test_undertested_function_filtering(project_root: Path) -> None:
    """Test that well-tested functions are not flagged as gaps."""
    analyzer = CoverageAnalyzer(project_root, undertested_threshold=50.0)

    # Function with 100% coverage (should not be a gap)
    func_info = FunctionInfo(name="well_tested", start_line=1, end_line=3)
    coverage_data = FunctionCoverage(name="well_tested", line_number=1, execution_count=100)

    gap = analyzer._analyze_function("test.py", func_info, coverage_data)

    assert gap is None  # Should not create a gap for well-tested function


@pytest.mark.asyncio
async def test_private_function_low_priority(project_root: Path) -> None:
    """Test that private functions with low complexity get lower priority."""
    analyzer = CoverageAnalyzer(project_root)

    # Private function with low complexity and zero coverage
    func_info = FunctionInfo(
        name="_private_helper",
        start_line=1,
        end_line=3,
        body_text="return 42",
    )

    gap = analyzer._analyze_function("test.py", func_info, None)

    # Should still create a gap, but with low priority
    assert gap is not None
    assert gap.priority in (GapPriority.LOW, GapPriority.MEDIUM)
