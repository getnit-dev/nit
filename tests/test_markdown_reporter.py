"""Tests for the Markdown reporter."""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.adapters.base import CaseResult, CaseStatus, RunResult
from nit.agents.reporters.markdown_reporter import MarkdownReporter


@pytest.fixture
def reporter() -> MarkdownReporter:
    return MarkdownReporter()


@pytest.fixture
def passing_result() -> RunResult:
    return RunResult(
        passed=2,
        failed=0,
        skipped=0,
        errors=0,
        duration_ms=500.0,
        success=True,
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
        ],
    )


@pytest.fixture
def mixed_result() -> RunResult:
    return RunResult(
        passed=1,
        failed=1,
        skipped=1,
        errors=0,
        duration_ms=1000.0,
        success=False,
        test_cases=[
            CaseResult(name="test_pass", status=CaseStatus.PASSED, duration_ms=200.0),
            CaseResult(
                name="test_fail",
                status=CaseStatus.FAILED,
                duration_ms=500.0,
                failure_message="AssertionError: expected 1 got 2",
                file_path="test_b.py",
            ),
            CaseResult(name="test_skip", status=CaseStatus.SKIPPED, duration_ms=0.0),
        ],
    )


def test_generate_file(
    reporter: MarkdownReporter, passing_result: RunResult, tmp_path: Path
) -> None:
    output = tmp_path / "report.md"
    result_path = reporter.generate(output, test_result=passing_result)
    assert result_path == output
    assert output.exists()
    content = output.read_text()
    assert "# nit Test Report" in content


def test_generate_string(reporter: MarkdownReporter, passing_result: RunResult) -> None:
    md = reporter.generate_string(test_result=passing_result)
    assert "# nit Test Report" in md
    assert "PASS" in md


def test_summary_table(reporter: MarkdownReporter, passing_result: RunResult) -> None:
    md = reporter.generate_string(test_result=passing_result)
    assert "| Total | 2 |" in md
    assert "| Passed | 2 |" in md
    assert "| Failed | 0 |" in md


def test_failure_section(reporter: MarkdownReporter, mixed_result: RunResult) -> None:
    md = reporter.generate_string(test_result=mixed_result)
    assert "### Failures" in md
    assert "test_fail" in md
    assert "AssertionError" in md


def test_status_in_table(reporter: MarkdownReporter, mixed_result: RunResult) -> None:
    md = reporter.generate_string(test_result=mixed_result)
    assert "FAIL" in md
    assert "SKIP" in md


def test_extra_data(reporter: MarkdownReporter) -> None:
    md = reporter.generate_string(extra={"coverage": {"line": 85.5}})
    assert "Coverage" in md


def test_empty_report(reporter: MarkdownReporter) -> None:
    md = reporter.generate_string()
    assert "# nit Test Report" in md


def test_creates_parent_dirs(
    reporter: MarkdownReporter, passing_result: RunResult, tmp_path: Path
) -> None:
    output = tmp_path / "deep" / "nested" / "report.md"
    reporter.generate(output, test_result=passing_result)
    assert output.exists()
