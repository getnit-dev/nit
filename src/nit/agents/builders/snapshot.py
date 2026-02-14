"""SnapshotTestBuilder -- generates test plans for snapshot/approval testing.

This builder:
1. Receives a SnapshotAnalysisResult from the snapshot analyzer
2. Generates test cases for stale cleanup, snapshot review, and updates
3. Produces SnapshotTestCase entries for each snapshot concern
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nit.agents.analyzers.snapshot import SnapshotAnalysisResult

logger = logging.getLogger(__name__)


@dataclass
class SnapshotTestCase:
    """A single snapshot test case to be generated."""

    file_path: str
    """Path to the snapshot file this test case targets."""

    test_name: str
    """Generated test function/method name."""

    test_type: str
    """Type of test: 'snapshot_update', 'stale_cleanup', 'new_snapshot', or 'snapshot_review'."""

    description: str
    """Human-readable description of what this test case addresses."""

    framework: str = ""
    """Snapshot framework associated with this test case."""


def _slugify(text: str) -> str:
    """Convert a file path or description into a valid test-name slug.

    Args:
        text: Arbitrary text to slugify.

    Returns:
        Lowercased, underscore-separated slug suitable for a test name.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug or "unnamed"


class SnapshotTestBuilder:
    """Generates test plans from snapshot analysis results.

    For each snapshot concern, the builder creates appropriate test cases:
    - Stale cleanup tests for orphaned snapshot files
    - Snapshot review tests for each active snapshot file
    - A general snapshot update test if snapshots exist
    """

    def generate_test_plan(self, analysis: SnapshotAnalysisResult) -> list[SnapshotTestCase]:
        """Generate a list of snapshot test cases from the analysis result.

        Creates:
        - ``stale_cleanup`` test for each stale snapshot file
        - ``snapshot_review`` test for each snapshot file
        - ``snapshot_update`` test for the project if snapshots exist

        Args:
            analysis: The result from :func:`analyze_snapshots`.

        Returns:
            List of SnapshotTestCase entries ready for code generation.
        """
        test_cases: list[SnapshotTestCase] = []

        for snap_file in analysis.snapshot_files:
            slug = _slugify(snap_file.path)

            # Stale cleanup test for orphaned snapshots
            if snap_file.is_stale:
                test_cases.append(
                    SnapshotTestCase(
                        file_path=snap_file.path,
                        test_name=f"test_stale_cleanup_{slug}",
                        test_type="stale_cleanup",
                        description=(
                            f"Clean up stale snapshot '{snap_file.path}' "
                            f"-- no corresponding test file found"
                        ),
                        framework=snap_file.framework,
                    )
                )

            # Snapshot review test for every snapshot file
            test_cases.append(
                SnapshotTestCase(
                    file_path=snap_file.path,
                    test_name=f"test_snapshot_review_{slug}",
                    test_type="snapshot_review",
                    description=(
                        f"Review snapshot file '{snap_file.path}' "
                        f"({snap_file.snapshot_count} snapshot(s))"
                    ),
                    framework=snap_file.framework,
                )
            )

        # General snapshot update test if there are any snapshots
        if analysis.snapshot_files:
            test_cases.append(
                SnapshotTestCase(
                    file_path="",
                    test_name="test_snapshot_update_all",
                    test_type="snapshot_update",
                    description=(
                        f"Update all snapshots for {analysis.framework} "
                        f"({analysis.total_snapshots} total snapshot(s))"
                    ),
                    framework=analysis.framework,
                )
            )

        logger.info(
            "Generated %d snapshot test cases from %d snapshot files",
            len(test_cases),
            len(analysis.snapshot_files),
        )

        return test_cases
