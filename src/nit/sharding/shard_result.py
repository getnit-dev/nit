"""Shard result serialization for inter-job artifact exchange."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nit.adapters.base import CaseResult, CaseStatus, RunResult
from nit.adapters.coverage.base import (
    BranchCoverage,
    CoverageReport,
    FileCoverage,
    FunctionCoverage,
    LineCoverage,
)

if TYPE_CHECKING:
    from pathlib import Path


def write_shard_result(
    result: RunResult,
    output_path: Path,
    shard_index: int,
    shard_count: int,
    adapter_name: str,
) -> None:
    """Serialize and write shard result to a JSON file."""
    data = _serialize_shard_result(result, shard_index, shard_count, adapter_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_shard_result(path: Path) -> tuple[RunResult, dict[str, Any]]:
    """Read a shard result JSON file.

    Returns:
        A tuple of (RunResult, metadata) where metadata includes
        shard_index, shard_count, and adapter_name.
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    test_cases = [
        CaseResult(
            name=tc["name"],
            status=CaseStatus(tc["status"]),
            duration_ms=tc["duration_ms"],
            failure_message=tc.get("failure_message", ""),
            file_path=tc.get("file_path", ""),
        )
        for tc in data.get("test_cases", [])
    ]

    coverage: CoverageReport | None = None
    if data.get("coverage") is not None:
        coverage = _deserialize_coverage(data["coverage"])

    run_result = RunResult(
        passed=data["passed"],
        failed=data["failed"],
        skipped=data["skipped"],
        errors=data["errors"],
        duration_ms=data["duration_ms"],
        test_cases=test_cases,
        raw_output="",
        success=data["success"],
        coverage=coverage,
    )

    metadata = {
        "shard_index": data["shard_index"],
        "shard_count": data["shard_count"],
        "adapter_name": data["adapter_name"],
    }

    return run_result, metadata


def _serialize_shard_result(
    result: RunResult,
    shard_index: int,
    shard_count: int,
    adapter_name: str,
) -> dict[str, Any]:
    """Convert a RunResult to a JSON-serializable dict."""
    payload: dict[str, Any] = {
        "shard_index": shard_index,
        "shard_count": shard_count,
        "adapter_name": adapter_name,
        "passed": result.passed,
        "failed": result.failed,
        "skipped": result.skipped,
        "errors": result.errors,
        "duration_ms": result.duration_ms,
        "success": result.success,
        "test_cases": [
            {
                "name": tc.name,
                "status": tc.status.value,
                "duration_ms": tc.duration_ms,
                "failure_message": tc.failure_message,
                "file_path": tc.file_path,
            }
            for tc in result.test_cases
        ],
        "coverage": _serialize_coverage(result.coverage) if result.coverage else None,
    }
    return payload


def _serialize_coverage(report: CoverageReport) -> dict[str, Any]:
    """Serialize a CoverageReport to a JSON-serializable dict."""
    files: dict[str, Any] = {}
    for file_path, file_cov in report.files.items():
        files[file_path] = {
            "file_path": file_cov.file_path,
            "lines": [
                {"line_number": lc.line_number, "execution_count": lc.execution_count}
                for lc in file_cov.lines
            ],
            "functions": [
                {
                    "name": fc.name,
                    "line_number": fc.line_number,
                    "execution_count": fc.execution_count,
                }
                for fc in file_cov.functions
            ],
            "branches": [
                {
                    "line_number": bc.line_number,
                    "branch_id": bc.branch_id,
                    "taken_count": bc.taken_count,
                    "total_count": bc.total_count,
                }
                for bc in file_cov.branches
            ],
        }
    return {"files": files}


def _deserialize_coverage(data: dict[str, Any]) -> CoverageReport:
    """Deserialize a CoverageReport from a dict."""
    files: dict[str, FileCoverage] = {}
    for file_path, file_data in data.get("files", {}).items():
        files[file_path] = FileCoverage(
            file_path=file_data["file_path"],
            lines=[
                LineCoverage(
                    line_number=lc["line_number"],
                    execution_count=lc["execution_count"],
                )
                for lc in file_data.get("lines", [])
            ],
            functions=[
                FunctionCoverage(
                    name=fc["name"],
                    line_number=fc["line_number"],
                    execution_count=fc["execution_count"],
                )
                for fc in file_data.get("functions", [])
            ],
            branches=[
                BranchCoverage(
                    line_number=bc["line_number"],
                    branch_id=bc["branch_id"],
                    taken_count=bc["taken_count"],
                    total_count=bc["total_count"],
                )
                for bc in file_data.get("branches", [])
            ],
        )
    return CoverageReport(files=files)
