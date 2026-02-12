"""Merge shard results into a combined report."""

from __future__ import annotations

from nit.adapters.base import RunResult
from nit.adapters.coverage.base import (
    BranchCoverage,
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    LineCoverage,
)


def merge_run_results(results: list[RunResult]) -> RunResult:
    """Merge multiple RunResults into one aggregate.

    Counts are summed, test_cases are concatenated, and duration uses
    max (wall-clock time since shards run in parallel).
    """
    if not results:
        return RunResult()

    aggregate = RunResult()
    for r in results:
        aggregate.passed += r.passed
        aggregate.failed += r.failed
        aggregate.skipped += r.skipped
        aggregate.errors += r.errors
        aggregate.duration_ms = max(aggregate.duration_ms, r.duration_ms)
        aggregate.test_cases.extend(r.test_cases)

    aggregate.success = aggregate.failed == 0 and aggregate.errors == 0 and aggregate.total > 0
    aggregate.coverage = merge_coverage_reports(
        [r.coverage for r in results if r.coverage is not None]
    )
    return aggregate


def merge_coverage_reports(
    reports: list[CoverageReport],
) -> CoverageReport | None:
    """Merge multiple CoverageReports at the unified model level.

    For each file, line/function execution counts use max() so that a
    line covered by any shard counts as covered.  Branch taken_count
    values are summed.
    """
    if not reports:
        return None

    merged_files: dict[str, FileCoverage] = {}

    for report in reports:
        for file_path, file_cov in report.files.items():
            if file_path not in merged_files:
                merged_files[file_path] = FileCoverage(
                    file_path=file_cov.file_path,
                    lines=list(file_cov.lines),
                    functions=list(file_cov.functions),
                    branches=list(file_cov.branches),
                )
            else:
                merged_files[file_path] = _merge_file_coverage(merged_files[file_path], file_cov)

    return CoverageReport(files=merged_files)


def _merge_file_coverage(a: FileCoverage, b: FileCoverage) -> FileCoverage:
    """Merge two FileCoverage objects for the same file."""
    return FileCoverage(
        file_path=a.file_path,
        lines=_merge_lines(a.lines, b.lines),
        functions=_merge_functions(a.functions, b.functions),
        branches=_merge_branches(a.branches, b.branches),
    )


def _merge_lines(a: list[LineCoverage], b: list[LineCoverage]) -> list[LineCoverage]:
    """Merge line coverage using max execution count per line."""
    by_line: dict[int, int] = {}
    for lc in a:
        by_line[lc.line_number] = lc.execution_count
    for lc in b:
        by_line[lc.line_number] = max(by_line.get(lc.line_number, 0), lc.execution_count)
    return [LineCoverage(line_number=ln, execution_count=ec) for ln, ec in sorted(by_line.items())]


def _merge_functions(
    a: list[FunctionCoverage], b: list[FunctionCoverage]
) -> list[FunctionCoverage]:
    """Merge function coverage using max execution count per function."""
    by_key: dict[tuple[str, int], int] = {}
    for fc in a:
        by_key[(fc.name, fc.line_number)] = fc.execution_count
    for fc in b:
        key = (fc.name, fc.line_number)
        by_key[key] = max(by_key.get(key, 0), fc.execution_count)
    return [
        FunctionCoverage(name=name, line_number=line, execution_count=ec)
        for (name, line), ec in sorted(by_key.items())
    ]


def _merge_branches(a: list[BranchCoverage], b: list[BranchCoverage]) -> list[BranchCoverage]:
    """Merge branch coverage by summing taken_count and taking max total_count."""
    by_key: dict[tuple[int, int], tuple[int, int]] = {}
    for bc in a:
        by_key[(bc.line_number, bc.branch_id)] = (bc.taken_count, bc.total_count)
    for bc in b:
        key = (bc.line_number, bc.branch_id)
        prev_taken, prev_total = by_key.get(key, (0, 0))
        by_key[key] = (prev_taken + bc.taken_count, max(prev_total, bc.total_count))
    return [
        BranchCoverage(
            line_number=line,
            branch_id=branch_id,
            taken_count=taken,
            total_count=total,
        )
        for (line, branch_id), (taken, total) in sorted(by_key.items())
    ]
