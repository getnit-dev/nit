"""Tests for the JSON reporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nit.adapters.base import CaseResult, CaseStatus, RunResult
from nit.agents.reporters.json_reporter import JSONReporter


@pytest.fixture
def reporter() -> JSONReporter:
    return JSONReporter()


@pytest.fixture
def sample_result() -> RunResult:
    return RunResult(
        passed=2,
        failed=1,
        skipped=0,
        errors=0,
        duration_ms=1500.0,
        success=False,
        test_cases=[
            CaseResult(
                name="test_add",
                status=CaseStatus.PASSED,
                duration_ms=200.0,
                file_path="test_math.py",
            ),
            CaseResult(
                name="test_sub",
                status=CaseStatus.PASSED,
                duration_ms=300.0,
                file_path="test_math.py",
            ),
            CaseResult(
                name="test_div",
                status=CaseStatus.FAILED,
                duration_ms=100.0,
                failure_message="ZeroDivisionError",
                file_path="test_math.py",
            ),
        ],
    )


def test_generate_file(reporter: JSONReporter, sample_result: RunResult, tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    result_path = reporter.generate(output, test_result=sample_result)
    assert result_path == output
    assert output.exists()

    data = json.loads(output.read_text())
    assert data["tool"] == "nit"
    assert "timestamp" in data


def test_generate_string(reporter: JSONReporter, sample_result: RunResult) -> None:
    json_str = reporter.generate_string(test_result=sample_result)
    data = json.loads(json_str)
    assert data["tool"] == "nit"


def test_test_results_structure(reporter: JSONReporter, sample_result: RunResult) -> None:
    json_str = reporter.generate_string(test_result=sample_result)
    data = json.loads(json_str)

    results = data["test_results"]
    assert results["summary"]["total"] == 3
    assert results["summary"]["passed"] == 2
    assert results["summary"]["failed"] == 1
    assert results["summary"]["success"] is False
    assert len(results["test_cases"]) == 3


def test_extra_data(reporter: JSONReporter) -> None:
    json_str = reporter.generate_string(extra={"coverage": {"line": 85.5}})
    data = json.loads(json_str)
    assert data["coverage"]["line"] == 85.5


def test_empty_report(reporter: JSONReporter) -> None:
    json_str = reporter.generate_string()
    data = json.loads(json_str)
    assert data["tool"] == "nit"
    assert "test_results" not in data


def test_creates_parent_dirs(
    reporter: JSONReporter, sample_result: RunResult, tmp_path: Path
) -> None:
    output = tmp_path / "deep" / "nested" / "report.json"
    reporter.generate(output, test_result=sample_result)
    assert output.exists()
