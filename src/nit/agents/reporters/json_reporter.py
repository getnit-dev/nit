"""JSON reporter — generates structured JSON test reports.

Produces machine-readable JSON output for downstream tooling from
nit's pipeline results.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from nit.adapters.base import RunResult

logger = logging.getLogger(__name__)


class JSONReporter:
    """Generate structured JSON reports from pipeline results.

    Serializes test results, coverage, bugs, security findings,
    and risk scores into a single JSON document.
    """

    def generate(
        self,
        output_path: Path,
        *,
        test_result: RunResult | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Path:
        """Write a JSON report file.

        Args:
            output_path: Path to write the JSON file.
            test_result: Aggregated test run result.
            extra: Additional pipeline data (coverage, bugs, security, risk).

        Returns:
            The path to the generated JSON file.
        """
        report = _build_report(test_result=test_result, extra=extra)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        logger.info("JSON report written to %s", output_path)
        return output_path

    def generate_string(
        self,
        *,
        test_result: RunResult | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Return JSON report as a string.

        Args:
            test_result: Aggregated test run result.
            extra: Additional pipeline data.

        Returns:
            JSON content as a string.
        """
        report = _build_report(test_result=test_result, extra=extra)
        return json.dumps(report, indent=2, ensure_ascii=False, default=str)


def _build_report(
    *,
    test_result: RunResult | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the JSON report structure."""
    report: dict[str, Any] = {
        "tool": "nit",
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }

    if test_result is not None:
        report["test_results"] = _serialize_run_result(test_result)

    if extra:
        report.update(extra)

    return report


def _serialize_run_result(result: RunResult) -> dict[str, Any]:
    """Serialize a ``RunResult`` into a JSON-compatible dict."""
    return {
        "summary": {
            "total": result.total,
            "passed": result.passed,
            "failed": result.failed,
            "skipped": result.skipped,
            "errors": result.errors,
            "duration_ms": result.duration_ms,
            "success": result.success,
        },
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
    }
