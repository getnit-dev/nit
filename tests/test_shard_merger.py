"""Tests for nit.sharding.merger."""

from __future__ import annotations

from nit.adapters.base import CaseResult, CaseStatus, RunResult
from nit.adapters.coverage.base import (
    BranchCoverage,
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    LineCoverage,
)
from nit.sharding.merger import merge_coverage_reports, merge_run_results


class TestMergeRunResults:
    def test_empty_list(self) -> None:
        result = merge_run_results([])
        assert result.passed == 0
        assert result.total == 0

    def test_single_result(self) -> None:
        r = RunResult(passed=5, failed=1, skipped=2, errors=0, duration_ms=1000.0)
        r.success = False
        merged = merge_run_results([r])
        assert merged.passed == 5
        assert merged.failed == 1
        assert merged.skipped == 2
        assert merged.duration_ms == 1000.0
        assert not merged.success

    def test_sums_counts(self) -> None:
        r1 = RunResult(passed=3, failed=0, skipped=1, errors=0, duration_ms=500.0)
        r2 = RunResult(passed=2, failed=1, skipped=0, errors=0, duration_ms=800.0)
        merged = merge_run_results([r1, r2])
        assert merged.passed == 5
        assert merged.failed == 1
        assert merged.skipped == 1
        assert merged.errors == 0

    def test_duration_uses_max(self) -> None:
        r1 = RunResult(passed=1, duration_ms=500.0)
        r2 = RunResult(passed=1, duration_ms=1200.0)
        r3 = RunResult(passed=1, duration_ms=800.0)
        merged = merge_run_results([r1, r2, r3])
        assert merged.duration_ms == 1200.0

    def test_concatenates_test_cases(self) -> None:
        tc1 = CaseResult(name="test_a", status=CaseStatus.PASSED)
        tc2 = CaseResult(name="test_b", status=CaseStatus.FAILED)
        tc3 = CaseResult(name="test_c", status=CaseStatus.PASSED)
        r1 = RunResult(passed=1, test_cases=[tc1])
        r2 = RunResult(passed=1, failed=1, test_cases=[tc2, tc3])
        merged = merge_run_results([r1, r2])
        assert len(merged.test_cases) == 3
        assert [tc.name for tc in merged.test_cases] == ["test_a", "test_b", "test_c"]

    def test_success_when_no_failures(self) -> None:
        r1 = RunResult(passed=3, failed=0, errors=0)
        r2 = RunResult(passed=2, failed=0, errors=0)
        merged = merge_run_results([r1, r2])
        assert merged.success is True

    def test_not_success_when_failures(self) -> None:
        r1 = RunResult(passed=3, failed=0, errors=0)
        r2 = RunResult(passed=2, failed=1, errors=0)
        merged = merge_run_results([r1, r2])
        assert merged.success is False

    def test_not_success_when_errors(self) -> None:
        r1 = RunResult(passed=3, failed=0, errors=1)
        r2 = RunResult(passed=2, failed=0, errors=0)
        merged = merge_run_results([r1, r2])
        assert merged.success is False

    def test_merges_coverage_from_results(self) -> None:
        cov1 = CoverageReport(
            files={
                "a.py": FileCoverage(
                    file_path="a.py",
                    lines=[LineCoverage(line_number=1, execution_count=1)],
                )
            }
        )
        cov2 = CoverageReport(
            files={
                "b.py": FileCoverage(
                    file_path="b.py",
                    lines=[LineCoverage(line_number=1, execution_count=2)],
                )
            }
        )
        r1 = RunResult(passed=1, coverage=cov1)
        r2 = RunResult(passed=1, coverage=cov2)
        merged = merge_run_results([r1, r2])
        assert merged.coverage is not None
        assert "a.py" in merged.coverage.files
        assert "b.py" in merged.coverage.files

    def test_skips_none_coverage(self) -> None:
        cov = CoverageReport(
            files={
                "a.py": FileCoverage(
                    file_path="a.py",
                    lines=[LineCoverage(line_number=1, execution_count=1)],
                )
            }
        )
        r1 = RunResult(passed=1, coverage=cov)
        r2 = RunResult(passed=1, coverage=None)
        merged = merge_run_results([r1, r2])
        assert merged.coverage is not None
        assert len(merged.coverage.files) == 1


class TestMergeCoverageReports:
    def test_empty_list(self) -> None:
        assert merge_coverage_reports([]) is None

    def test_single_report(self) -> None:
        report = CoverageReport(
            files={
                "a.py": FileCoverage(
                    file_path="a.py",
                    lines=[LineCoverage(line_number=1, execution_count=5)],
                )
            }
        )
        merged = merge_coverage_reports([report])
        assert merged is not None
        assert merged.files["a.py"].lines[0].execution_count == 5

    def test_disjoint_files(self) -> None:
        r1 = CoverageReport(
            files={
                "a.py": FileCoverage(
                    file_path="a.py",
                    lines=[LineCoverage(line_number=1, execution_count=1)],
                )
            }
        )
        r2 = CoverageReport(
            files={
                "b.py": FileCoverage(
                    file_path="b.py",
                    lines=[LineCoverage(line_number=1, execution_count=2)],
                )
            }
        )
        merged = merge_coverage_reports([r1, r2])
        assert merged is not None
        assert "a.py" in merged.files
        assert "b.py" in merged.files

    def test_overlapping_lines_uses_max(self) -> None:
        r1 = CoverageReport(
            files={
                "a.py": FileCoverage(
                    file_path="a.py",
                    lines=[
                        LineCoverage(line_number=1, execution_count=2),
                        LineCoverage(line_number=2, execution_count=0),
                    ],
                )
            }
        )
        r2 = CoverageReport(
            files={
                "a.py": FileCoverage(
                    file_path="a.py",
                    lines=[
                        LineCoverage(line_number=1, execution_count=1),
                        LineCoverage(line_number=2, execution_count=3),
                    ],
                )
            }
        )
        merged = merge_coverage_reports([r1, r2])
        assert merged is not None
        lines = {lc.line_number: lc.execution_count for lc in merged.files["a.py"].lines}
        assert lines[1] == 2  # max(2, 1)
        assert lines[2] == 3  # max(0, 3)

    def test_overlapping_functions_uses_max(self) -> None:
        r1 = CoverageReport(
            files={
                "a.py": FileCoverage(
                    file_path="a.py",
                    functions=[
                        FunctionCoverage(name="foo", line_number=1, execution_count=0),
                    ],
                )
            }
        )
        r2 = CoverageReport(
            files={
                "a.py": FileCoverage(
                    file_path="a.py",
                    functions=[
                        FunctionCoverage(name="foo", line_number=1, execution_count=3),
                    ],
                )
            }
        )
        merged = merge_coverage_reports([r1, r2])
        assert merged is not None
        assert merged.files["a.py"].functions[0].execution_count == 3

    def test_overlapping_branches_sums_taken(self) -> None:
        r1 = CoverageReport(
            files={
                "a.py": FileCoverage(
                    file_path="a.py",
                    branches=[
                        BranchCoverage(line_number=10, branch_id=0, taken_count=1, total_count=2),
                    ],
                )
            }
        )
        r2 = CoverageReport(
            files={
                "a.py": FileCoverage(
                    file_path="a.py",
                    branches=[
                        BranchCoverage(line_number=10, branch_id=0, taken_count=2, total_count=2),
                    ],
                )
            }
        )
        merged = merge_coverage_reports([r1, r2])
        assert merged is not None
        branch = merged.files["a.py"].branches[0]
        assert branch.taken_count == 3  # sum(1, 2)
        assert branch.total_count == 2  # max(2, 2)

    def test_three_reports_merge(self) -> None:
        reports = [
            CoverageReport(
                files={
                    "a.py": FileCoverage(
                        file_path="a.py",
                        lines=[LineCoverage(line_number=1, execution_count=i)],
                    )
                }
            )
            for i in [2, 5, 3]
        ]
        merged = merge_coverage_reports(reports)
        assert merged is not None
        assert merged.files["a.py"].lines[0].execution_count == 5  # max(2, 5, 3)
