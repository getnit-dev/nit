"""SARIF reporter — generates Static Analysis Results Interchange Format output.

Produces SARIF v2.1.0 JSON from nit's ``SecurityReport``, enabling
integration with GitHub Code Scanning, VS Code, and other SARIF consumers.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from nit.agents.analyzers.security_types import SecuritySeverity

if TYPE_CHECKING:
    from pathlib import Path

    from nit.agents.analyzers.security import SecurityFinding, SecurityReport

logger = logging.getLogger(__name__)

_SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json"
_SARIF_VERSION = "2.1.0"
_TOOL_NAME = "nit"
_TOOL_INFO_URI = "https://getnit.dev"


class SARIFReporter:
    """Generate SARIF v2.1.0 reports from security analysis results."""

    def generate(self, report: SecurityReport, output_path: Path) -> Path:
        """Write a SARIF JSON report file.

        Args:
            report: Security analysis report with findings.
            output_path: Path to write the SARIF JSON file.

        Returns:
            The path to the generated SARIF file.
        """
        sarif = _build_sarif(report)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(sarif, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("SARIF report written to %s", output_path)
        return output_path

    def generate_string(self, report: SecurityReport) -> str:
        """Return SARIF JSON as a string.

        Args:
            report: Security analysis report with findings.

        Returns:
            SARIF JSON content as a string.
        """
        sarif = _build_sarif(report)
        return json.dumps(sarif, indent=2, ensure_ascii=False)


def _build_sarif(report: SecurityReport) -> dict[str, Any]:
    """Build a SARIF v2.1.0 document from a ``SecurityReport``."""
    # Collect unique rules from findings
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []

    for finding in report.findings:
        rule_id = finding.vulnerability_type.value
        if rule_id not in rules:
            rules[rule_id] = _build_rule(finding)
        results.append(_build_result(finding))

    return {
        "$schema": _SARIF_SCHEMA,
        "version": _SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": _TOOL_NAME,
                        "informationUri": _TOOL_INFO_URI,
                        "rules": list(rules.values()),
                    },
                },
                "results": results,
            },
        ],
    }


def _build_rule(finding: SecurityFinding) -> dict[str, Any]:
    """Build a SARIF ``reportingDescriptor`` (rule) from a finding."""
    rule: dict[str, Any] = {
        "id": finding.vulnerability_type.value,
        "shortDescription": {"text": finding.vulnerability_type.value.replace("_", " ").title()},
        "helpUri": _TOOL_INFO_URI,
    }
    if finding.cwe_id:
        rule["properties"] = {"tags": [finding.cwe_id]}
    return rule


def _build_result(finding: SecurityFinding) -> dict[str, Any]:
    """Build a SARIF ``result`` from a ``SecurityFinding``."""
    result: dict[str, Any] = {
        "ruleId": finding.vulnerability_type.value,
        "level": _map_severity(finding.severity),
        "message": {
            "text": f"{finding.title}: {finding.description}",
        },
    }

    # Location
    location: dict[str, Any] = {
        "physicalLocation": {
            "artifactLocation": {"uri": finding.file_path},
        },
    }
    if finding.line_number is not None:
        location["physicalLocation"]["region"] = {
            "startLine": finding.line_number,
        }
        if finding.evidence:
            location["physicalLocation"]["region"]["snippet"] = {
                "text": finding.evidence,
            }
    result["locations"] = [location]

    # Properties
    props: dict[str, Any] = {
        "confidence": finding.confidence,
        "detectionMethod": finding.detection_method,
    }
    if finding.remediation:
        props["remediation"] = finding.remediation
    if finding.cwe_id:
        props["cweId"] = finding.cwe_id
    if finding.function_name:
        props["functionName"] = finding.function_name
    result["properties"] = props

    return result


def _map_severity(severity: SecuritySeverity) -> str:
    """Map ``SecuritySeverity`` to SARIF level string."""
    mapping: dict[SecuritySeverity, str] = {
        SecuritySeverity.CRITICAL: "error",
        SecuritySeverity.HIGH: "error",
        SecuritySeverity.MEDIUM: "warning",
        SecuritySeverity.LOW: "note",
        SecuritySeverity.INFO: "note",
    }
    return mapping.get(severity, "warning")
