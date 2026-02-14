"""Tests for the JUnit XML reporter."""

from __future__ import annotations

from pathlib import Path

import pytest
from defusedxml import ElementTree

from nit.adapters.base import CaseResult, CaseStatus, RunResult
from nit.agents.reporters.junit_xml import JUnitXMLReporter


@pytest.fixture
def reporter() -> JUnitXMLReporter:
    return JUnitXMLReporter()


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
            CaseResult(
                name="test_pass", status=CaseStatus.PASSED, duration_ms=200.0, file_path="test_a.py"
            ),
            CaseResult(
                name="test_fail",
                status=CaseStatus.FAILED,
                duration_ms=500.0,
                failure_message="AssertionError: expected 1 got 2",
                file_path="test_b.py",
            ),
            CaseResult(
                name="test_skip", status=CaseStatus.SKIPPED, duration_ms=0.0, file_path="test_a.py"
            ),
        ],
    )


def test_generate_file(
    reporter: JUnitXMLReporter, passing_result: RunResult, tmp_path: Path
) -> None:
    output = tmp_path / "junit.xml"
    result_path = reporter.generate(passing_result, output)
    assert result_path == output
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "<?xml" in content
    assert "<testsuites" in content


def test_generate_string(reporter: JUnitXMLReporter, passing_result: RunResult) -> None:
    xml_str = reporter.generate_string(passing_result)
    assert "<?xml" in xml_str
    assert "<testsuites" in xml_str


def test_xml_structure_passing(reporter: JUnitXMLReporter, passing_result: RunResult) -> None:
    xml_str = reporter.generate_string(passing_result)
    root = ElementTree.fromstring(xml_str)
    assert root.tag == "testsuites"
    assert root.get("tests") == "2"
    assert root.get("failures") == "0"

    suites = root.findall("testsuite")
    assert len(suites) >= 1

    cases = root.findall(".//testcase")
    assert len(cases) == 2


def test_xml_structure_mixed(reporter: JUnitXMLReporter, mixed_result: RunResult) -> None:
    xml_str = reporter.generate_string(mixed_result)
    root = ElementTree.fromstring(xml_str)
    assert root.get("tests") == "3"
    assert root.get("failures") == "1"

    failures = root.findall(".//failure")
    assert len(failures) == 1
    assert "AssertionError" in (failures[0].get("message") or "")

    skipped = root.findall(".//skipped")
    assert len(skipped) == 1


def test_empty_result(reporter: JUnitXMLReporter) -> None:
    result = RunResult(success=True)
    xml_str = reporter.generate_string(result)
    root = ElementTree.fromstring(xml_str)
    assert root.get("tests") == "0"


def test_creates_parent_dirs(
    reporter: JUnitXMLReporter, passing_result: RunResult, tmp_path: Path
) -> None:
    output = tmp_path / "deep" / "nested" / "junit.xml"
    reporter.generate(passing_result, output)
    assert output.exists()
