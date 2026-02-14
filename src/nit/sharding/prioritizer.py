"""Risk-based test prioritization and shard distribution.

Sorts test files by risk score (derived from source-file risk reports and
test-to-source mappings) and distributes the sorted list across shards so
that each shard receives a balanced mix of high/medium/low risk tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nit.agents.analyzers.test_mapper import TestMapper

# ── Constants ─────────────────────────────────────────────────────

DEFAULT_RISK_SCORE = 0.5
"""Score assigned to test files that cannot be mapped to any source file."""

# ── Data models ───────────────────────────────────────────────────


@dataclass
class RiskScore:
    """Risk score for a single test file."""

    file_path: str
    """Path to the test file."""

    score: float = 0.0
    """Composite risk score (0.0-1.0)."""

    reasons: list[str] = field(default_factory=list)
    """Human-readable explanations for the score."""


@dataclass
class PrioritizedTestPlan:
    """Sorted test plan produced by the prioritizer."""

    test_files: list[Path] = field(default_factory=list)
    """Test files sorted by risk score (highest first)."""

    risk_scores: list[RiskScore] = field(default_factory=list)
    """Corresponding risk scores, same order as test_files."""


# ── Public API ────────────────────────────────────────────────────


def prioritize_test_files_by_risk(
    test_files: list[Path],
    risk_report: dict[str, float] | None = None,
    test_mapper: TestMapper | None = None,
) -> PrioritizedTestPlan:
    """Sort test files by descending risk score.

    1. If *test_mapper* is provided, map each test to its source files.
    2. If *risk_report* is provided (source_file -> score), look up the max
       risk score across each test's source files.
    3. Unmapped tests receive ``DEFAULT_RISK_SCORE``.
    4. Return a ``PrioritizedTestPlan`` sorted highest-risk first.

    Args:
        test_files: Test files to prioritize.
        risk_report: Mapping of source file path to risk score (0.0-1.0).
        test_mapper: Optional TestMapper for resolving test-to-source links.

    Returns:
        PrioritizedTestPlan with sorted files and scores.
    """
    scored: list[RiskScore] = []
    risk_map = risk_report or {}

    for tf in test_files:
        tf_str = str(tf)
        source_files: list[str] = []

        # Step 1: resolve test -> source mappings
        if test_mapper is not None:
            mapping = test_mapper.map_test_to_sources(tf)
            source_files = mapping.source_files

        # Step 2: look up risk for mapped sources
        source_scores = [risk_map[sf] for sf in source_files if sf in risk_map]

        if source_scores:
            max_score = max(source_scores)
            reasons = [f"source {sf}: {risk_map[sf]:.2f}" for sf in source_files if sf in risk_map]
            scored.append(RiskScore(file_path=tf_str, score=max_score, reasons=reasons))
        else:
            scored.append(
                RiskScore(
                    file_path=tf_str,
                    score=DEFAULT_RISK_SCORE,
                    reasons=["no source mapping -- default score"],
                )
            )

    # Step 4: sort descending by score (stable sort keeps original order for ties)
    scored.sort(key=lambda rs: rs.score, reverse=True)

    return PrioritizedTestPlan(
        test_files=[Path(rs.file_path) for rs in scored],
        risk_scores=scored,
    )


def distribute_prioritized_shards(
    plan: PrioritizedTestPlan,
    shard_index: int,
    shard_count: int,
) -> list[Path]:
    """Round-robin distribute the *sorted* test plan across shards.

    Because the plan is sorted highest-risk first, round-robin ensures that
    each shard receives a balanced mix of high/medium/low risk tests rather
    than concentrating all high-risk tests in shard 0.

    Uses the same round-robin logic as ``split_into_shards``.

    Args:
        plan: Prioritized test plan (pre-sorted by risk).
        shard_index: Zero-based index of this shard.
        shard_count: Total number of shards.

    Returns:
        Subset of test files assigned to this shard.

    Raises:
        ValueError: If shard_index or shard_count is invalid.
    """
    if shard_count < 1:
        msg = f"shard_count must be >= 1, got {shard_count}"
        raise ValueError(msg)
    if shard_index < 0 or shard_index >= shard_count:
        msg = f"shard_index must be in [0, {shard_count}), got {shard_index}"
        raise ValueError(msg)

    return [f for i, f in enumerate(plan.test_files) if i % shard_count == shard_index]
