"""Tests for the SARIF reporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nit.agents.analyzers.security import SecurityFinding, SecurityReport
from nit.agents.analyzers.security_types import SecuritySeverity, VulnerabilityType
from nit.agents.reporters.sarif import SARIFReporter


@pytest.fixture
def reporter() -> SARIFReporter:
    return SARIFReporter()


@pytest.fixture
def sample_report() -> SecurityReport:
    return SecurityReport(
        findings=[
            SecurityFinding(
                vulnerability_type=VulnerabilityType.SQL_INJECTION,
                severity=SecuritySeverity.CRITICAL,
                file_path="src/db.py",
                line_number=42,
                function_name="query_user",
                title="SQL Injection",
                description="User input directly in SQL query",
                remediation="Use parameterized queries",
                confidence=0.95,
                cwe_id="CWE-89",
                evidence="cursor.execute(f'SELECT * FROM users WHERE id={user_id}')",
                detection_method="heuristic",
            ),
            SecurityFinding(
                vulnerability_type=VulnerabilityType.XSS,
                severity=SecuritySeverity.HIGH,
                file_path="src/views.py",
                line_number=100,
                function_name="render_comment",
                title="Cross-Site Scripting",
                description="Unescaped user input in HTML output",
                remediation="Use HTML escaping",
                confidence=0.8,
                cwe_id="CWE-79",
            ),
        ],
        files_scanned=10,
    )


@pytest.fixture
def empty_report() -> SecurityReport:
    return SecurityReport(findings=[], files_scanned=5)


def test_generate_file(
    reporter: SARIFReporter, sample_report: SecurityReport, tmp_path: Path
) -> None:
    output = tmp_path / "report.sarif"
    result_path = reporter.generate(sample_report, output)
    assert result_path == output
    assert output.exists()

    data = json.loads(output.read_text())
    assert data["version"] == "2.1.0"
    assert "$schema" in data


def test_generate_string(reporter: SARIFReporter, sample_report: SecurityReport) -> None:
    sarif_str = reporter.generate_string(sample_report)
    data = json.loads(sarif_str)
    assert data["version"] == "2.1.0"


def test_sarif_structure(reporter: SARIFReporter, sample_report: SecurityReport) -> None:
    sarif_str = reporter.generate_string(sample_report)
    data = json.loads(sarif_str)

    assert len(data["runs"]) == 1
    run = data["runs"][0]

    # Tool info
    assert run["tool"]["driver"]["name"] == "nit"
    assert len(run["tool"]["driver"]["rules"]) == 2

    # Results
    assert len(run["results"]) == 2


def test_severity_mapping(reporter: SARIFReporter, sample_report: SecurityReport) -> None:
    sarif_str = reporter.generate_string(sample_report)
    data = json.loads(sarif_str)
    results = data["runs"][0]["results"]

    # CRITICAL -> error
    assert results[0]["level"] == "error"
    # HIGH -> error
    assert results[1]["level"] == "error"


def test_location_info(reporter: SARIFReporter, sample_report: SecurityReport) -> None:
    sarif_str = reporter.generate_string(sample_report)
    data = json.loads(sarif_str)
    result = data["runs"][0]["results"][0]

    location = result["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == "src/db.py"
    assert location["region"]["startLine"] == 42


def test_cwe_in_properties(reporter: SARIFReporter, sample_report: SecurityReport) -> None:
    sarif_str = reporter.generate_string(sample_report)
    data = json.loads(sarif_str)
    result = data["runs"][0]["results"][0]
    assert result["properties"]["cweId"] == "CWE-89"


def test_empty_report(reporter: SARIFReporter, empty_report: SecurityReport) -> None:
    sarif_str = reporter.generate_string(empty_report)
    data = json.loads(sarif_str)
    assert len(data["runs"][0]["results"]) == 0
    assert len(data["runs"][0]["tool"]["driver"]["rules"]) == 0


def test_creates_parent_dirs(
    reporter: SARIFReporter, sample_report: SecurityReport, tmp_path: Path
) -> None:
    output = tmp_path / "deep" / "nested" / "report.sarif"
    reporter.generate(sample_report, output)
    assert output.exists()
