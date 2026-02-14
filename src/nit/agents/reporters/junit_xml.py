"""JUnit XML reporter — generates standard JUnit XML test reports.

Produces XML consumable by CI systems (Jenkins, GitLab, Azure DevOps,
CircleCI, etc.) from nit's ``RunResult`` data.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.base import CaseStatus, RunResult

logger = logging.getLogger(__name__)


class JUnitXMLReporter:
    """Generate JUnit XML reports from test results.

    Produces standard JUnit XML format with ``<testsuites>`` root,
    containing ``<testsuite>`` and ``<testcase>`` elements.
    """

    def generate(self, result: RunResult, output_path: Path) -> Path:
        """Write a JUnit XML report file.

        Args:
            result: Aggregated test run result.
            output_path: Path to write the XML file.

        Returns:
            The path to the generated XML file.
        """
        root = _build_xml(result)
        tree = ET.ElementTree(root)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ET.indent(tree, space="  ")
        tree.write(str(output_path), encoding="unicode", xml_declaration=True)
        logger.info("JUnit XML report written to %s", output_path)
        return output_path

    def generate_string(self, result: RunResult) -> str:
        """Return JUnit XML as a string.

        Args:
            result: Aggregated test run result.

        Returns:
            JUnit XML content as a string.
        """
        root = _build_xml(result)
        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _build_xml(result: RunResult) -> ET.Element:
    """Build the JUnit XML element tree from a ``RunResult``."""
    testsuites = ET.Element("testsuites")
    testsuites.set("tests", str(result.total))
    testsuites.set("failures", str(result.failed))
    testsuites.set("errors", str(result.errors))
    testsuites.set("skipped", str(result.skipped))
    testsuites.set("time", f"{result.duration_ms / 1000:.3f}")

    # Group test cases by file path into suites
    suites: dict[str, list[int]] = {}
    for idx, tc in enumerate(result.test_cases):
        key = tc.file_path or "default"
        suites.setdefault(key, []).append(idx)

    # If no test cases, create a single suite with summary counts
    if not result.test_cases:
        suite_elem = ET.SubElement(testsuites, "testsuite")
        suite_elem.set("name", "nit")
        suite_elem.set("tests", str(result.total))
        suite_elem.set("failures", str(result.failed))
        suite_elem.set("errors", str(result.errors))
        suite_elem.set("skipped", str(result.skipped))
        suite_elem.set("time", f"{result.duration_ms / 1000:.3f}")
        return testsuites

    for suite_name, indices in suites.items():
        cases = [result.test_cases[i] for i in indices]
        suite_elem = ET.SubElement(testsuites, "testsuite")
        suite_elem.set("name", suite_name)
        suite_elem.set("tests", str(len(cases)))

        suite_failures = sum(1 for c in cases if c.status == CaseStatus.FAILED)
        suite_errors = sum(1 for c in cases if c.status == CaseStatus.ERROR)
        suite_skipped = sum(1 for c in cases if c.status == CaseStatus.SKIPPED)
        suite_time = sum(c.duration_ms for c in cases)

        suite_elem.set("failures", str(suite_failures))
        suite_elem.set("errors", str(suite_errors))
        suite_elem.set("skipped", str(suite_skipped))
        suite_elem.set("time", f"{suite_time / 1000:.3f}")

        for tc in cases:
            tc_elem = ET.SubElement(suite_elem, "testcase")
            tc_elem.set("name", tc.name)
            tc_elem.set("classname", suite_name)
            tc_elem.set("time", f"{tc.duration_ms / 1000:.3f}")

            if tc.status == CaseStatus.FAILED:
                failure = ET.SubElement(tc_elem, "failure")
                failure.set("message", tc.failure_message or "Test failed")
                failure.text = tc.failure_message
            elif tc.status == CaseStatus.ERROR:
                error = ET.SubElement(tc_elem, "error")
                error.set("message", tc.failure_message or "Test error")
                error.text = tc.failure_message
            elif tc.status == CaseStatus.SKIPPED:
                ET.SubElement(tc_elem, "skipped")

    return testsuites
