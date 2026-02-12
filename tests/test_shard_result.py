"""Tests for nit.sharding.shard_result."""

from __future__ import annotations

from pathlib import Path

from nit.adapters.base import CaseResult, CaseStatus, RunResult
from nit.adapters.coverage.base import (
    BranchCoverage,
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    LineCoverage,
)
from nit.sharding.shard_result import read_shard_result, write_shard_result


def _make_run_result(*, with_coverage: bool = False) -> RunResult:
    """Build a sample RunResult for testing."""
    coverage = None
    if with_coverage:
        coverage = CoverageReport(
            files={
                "src/main.py": FileCoverage(
                    file_path="src/main.py",
                    lines=[
                        LineCoverage(line_number=1, execution_count=3),
                        LineCoverage(line_number=2, execution_count=0),
                    ],
                    functions=[
                        FunctionCoverage(name="main", line_number=1, execution_count=1),
                    ],
                    branches=[
                        BranchCoverage(line_number=5, branch_id=0, taken_count=2, total_count=3),
                    ],
                ),
            }
        )
    return RunResult(
        passed=3,
        failed=1,
        skipped=0,
        errors=0,
        duration_ms=1234.5,
        test_cases=[
            CaseResult(
                name="test_foo",
                status=CaseStatus.PASSED,
                duration_ms=100.0,
                failure_message="",
                file_path="tests/test_main.py",
            ),
            CaseResult(
                name="test_bar",
                status=CaseStatus.FAILED,
                duration_ms=200.0,
                failure_message="AssertionError: 1 != 2",
                file_path="tests/test_main.py",
            ),
        ],
        success=False,
        coverage=coverage,
    )


class TestRoundTrip:
    def test_roundtrip_without_coverage(self, tmp_path: Path) -> None:
        original = _make_run_result(with_coverage=False)
        output = tmp_path / "shard-0.json"

        write_shard_result(original, output, shard_index=0, shard_count=4, adapter_name="pytest")
        restored, metadata = read_shard_result(output)

        assert metadata["shard_index"] == 0
        assert metadata["shard_count"] == 4
        assert metadata["adapter_name"] == "pytest"
        assert restored.passed == original.passed
        assert restored.failed == original.failed
        assert restored.skipped == original.skipped
        assert restored.errors == original.errors
        assert restored.duration_ms == original.duration_ms
        assert restored.success == original.success
        assert restored.coverage is None
        assert len(restored.test_cases) == 2
        assert restored.test_cases[0].name == "test_foo"
        assert restored.test_cases[0].status == CaseStatus.PASSED
        assert restored.test_cases[1].name == "test_bar"
        assert restored.test_cases[1].status == CaseStatus.FAILED
        assert restored.test_cases[1].failure_message == "AssertionError: 1 != 2"

    def test_roundtrip_with_coverage(self, tmp_path: Path) -> None:
        original = _make_run_result(with_coverage=True)
        output = tmp_path / "shard-1.json"

        write_shard_result(original, output, shard_index=1, shard_count=2, adapter_name="vitest")
        restored, metadata = read_shard_result(output)

        assert metadata["adapter_name"] == "vitest"
        assert restored.coverage is not None

        cov = restored.coverage
        assert "src/main.py" in cov.files
        fc = cov.files["src/main.py"]
        assert len(fc.lines) == 2
        assert fc.lines[0].line_number == 1
        assert fc.lines[0].execution_count == 3
        assert fc.lines[1].execution_count == 0
        assert len(fc.functions) == 1
        assert fc.functions[0].name == "main"
        assert len(fc.branches) == 1
        assert fc.branches[0].taken_count == 2
        assert fc.branches[0].total_count == 3

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        output = tmp_path / "nested" / "dir" / "shard.json"
        write_shard_result(RunResult(), output, shard_index=0, shard_count=1, adapter_name="pytest")
        assert output.exists()
