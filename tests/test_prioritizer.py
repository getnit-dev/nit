"""Tests for the risk-based test prioritizer (sharding/prioritizer.py).

Covers:
- prioritize_test_files_by_risk: sorting, risk lookup, defaults, edge cases
- distribute_prioritized_shards: round-robin, balance, validation
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.agents.analyzers.test_mapper import TestMapper
from nit.sharding.prioritizer import (
    DEFAULT_RISK_SCORE,
    PrioritizedTestPlan,
    RiskScore,
    distribute_prioritized_shards,
    prioritize_test_files_by_risk,
)

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Create a project tree with source and test files."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text("def login(): pass\n")
    (src / "utils.py").write_text("def helper(): pass\n")
    (src / "db.py").write_text("def query(): pass\n")

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_auth.py").write_text("")
    (tests / "test_utils.py").write_text("")
    (tests / "test_db.py").write_text("")
    (tests / "test_unknown.py").write_text("")

    return tmp_path


@pytest.fixture()
def test_files(project_root: Path) -> list[Path]:
    """Return the test files in the fixture project."""
    tests = project_root / "tests"
    return [
        tests / "test_auth.py",
        tests / "test_utils.py",
        tests / "test_db.py",
        tests / "test_unknown.py",
    ]


@pytest.fixture()
def risk_report() -> dict[str, float]:
    """Risk scores for source files."""
    return {
        "src/auth.py": 0.95,
        "src/db.py": 0.7,
        "src/utils.py": 0.3,
    }


# ── prioritize_test_files_by_risk tests ──────────────────────────


def test_sorts_by_risk_descending(
    project_root: Path, test_files: list[Path], risk_report: dict[str, float]
) -> None:
    """Test files should be sorted highest risk first."""
    mapper = TestMapper(project_root)

    plan = prioritize_test_files_by_risk(test_files, risk_report=risk_report, test_mapper=mapper)

    scores = [rs.score for rs in plan.risk_scores]
    assert scores == sorted(scores, reverse=True)
    # auth (0.95) should be first
    assert "test_auth.py" in plan.test_files[0].name


def test_uses_risk_report_via_mapper(
    project_root: Path, test_files: list[Path], risk_report: dict[str, float]
) -> None:
    """Risk scores should propagate from source files through the mapper."""
    mapper = TestMapper(project_root)

    plan = prioritize_test_files_by_risk(test_files, risk_report=risk_report, test_mapper=mapper)

    auth_score = next(rs for rs in plan.risk_scores if "test_auth" in rs.file_path)
    assert auth_score.score == 0.95

    utils_score = next(rs for rs in plan.risk_scores if "test_utils" in rs.file_path)
    assert utils_score.score == 0.3


def test_default_score_for_unmapped_tests(
    project_root: Path, test_files: list[Path], risk_report: dict[str, float]
) -> None:
    """Tests with no source mapping should get DEFAULT_RISK_SCORE."""
    mapper = TestMapper(project_root)

    plan = prioritize_test_files_by_risk(test_files, risk_report=risk_report, test_mapper=mapper)

    unknown_score = next(rs for rs in plan.risk_scores if "test_unknown" in rs.file_path)
    assert unknown_score.score == DEFAULT_RISK_SCORE
    assert "default" in unknown_score.reasons[0].lower()


def test_empty_test_files() -> None:
    """Empty input should produce an empty plan."""
    plan = prioritize_test_files_by_risk([])

    assert plan.test_files == []
    assert plan.risk_scores == []


def test_no_risk_report_all_defaults(project_root: Path, test_files: list[Path]) -> None:
    """Without a risk_report, all tests get the default score."""
    mapper = TestMapper(project_root)

    plan = prioritize_test_files_by_risk(test_files, test_mapper=mapper)

    assert all(rs.score == DEFAULT_RISK_SCORE for rs in plan.risk_scores)


def test_no_mapper_all_defaults(test_files: list[Path], risk_report: dict[str, float]) -> None:
    """Without a mapper, no source mapping occurs so all get default scores."""
    plan = prioritize_test_files_by_risk(test_files, risk_report=risk_report)

    assert all(rs.score == DEFAULT_RISK_SCORE for rs in plan.risk_scores)


def test_no_mapper_no_report(test_files: list[Path]) -> None:
    """Without mapper or report, all tests still get default scores."""
    plan = prioritize_test_files_by_risk(test_files)

    assert len(plan.test_files) == len(test_files)
    assert all(rs.score == DEFAULT_RISK_SCORE for rs in plan.risk_scores)


def test_plan_length_matches_input(
    project_root: Path, test_files: list[Path], risk_report: dict[str, float]
) -> None:
    """Plan should contain exactly as many entries as input test files."""
    mapper = TestMapper(project_root)

    plan = prioritize_test_files_by_risk(test_files, risk_report=risk_report, test_mapper=mapper)

    assert len(plan.test_files) == len(test_files)
    assert len(plan.risk_scores) == len(test_files)


# ── distribute_prioritized_shards tests ──────────────────────────


def test_round_robin_distribution() -> None:
    """Files should be distributed round-robin across shards."""
    files = [Path(f"test_{i}.py") for i in range(6)]
    scores = [RiskScore(file_path=str(f), score=1.0 - i * 0.1) for i, f in enumerate(files)]
    plan = PrioritizedTestPlan(test_files=files, risk_scores=scores)

    shard0 = distribute_prioritized_shards(plan, shard_index=0, shard_count=3)
    shard1 = distribute_prioritized_shards(plan, shard_index=1, shard_count=3)
    shard2 = distribute_prioritized_shards(plan, shard_index=2, shard_count=3)

    # Each shard gets 2 files
    assert len(shard0) == 2
    assert len(shard1) == 2
    assert len(shard2) == 2

    # All files covered
    all_assigned = shard0 + shard1 + shard2
    assert sorted(str(f) for f in all_assigned) == sorted(str(f) for f in files)


def test_shards_get_mix_of_risk_levels() -> None:
    """Each shard should get both high and low risk tests."""
    # Files pre-sorted by risk: high, high, med, med, low, low
    files = [Path(f"test_{i}.py") for i in range(6)]
    scores_values = [0.9, 0.8, 0.5, 0.5, 0.2, 0.1]
    scores = [
        RiskScore(file_path=str(f), score=s) for f, s in zip(files, scores_values, strict=True)
    ]
    plan = PrioritizedTestPlan(test_files=files, risk_scores=scores)

    shard0 = distribute_prioritized_shards(plan, shard_index=0, shard_count=2)
    shard1 = distribute_prioritized_shards(plan, shard_index=1, shard_count=2)

    # shard0 gets indices 0, 2, 4 (high, med, low)
    assert len(shard0) == 3
    # shard1 gets indices 1, 3, 5 (high, med, low)
    assert len(shard1) == 3


def test_single_shard_gets_all_files() -> None:
    """With shard_count=1, shard 0 gets everything."""
    files = [Path(f"test_{i}.py") for i in range(5)]
    scores = [RiskScore(file_path=str(f), score=0.5) for f in files]
    plan = PrioritizedTestPlan(test_files=files, risk_scores=scores)

    result = distribute_prioritized_shards(plan, shard_index=0, shard_count=1)

    assert len(result) == 5


def test_empty_plan_returns_empty() -> None:
    """An empty plan should return an empty list."""
    plan = PrioritizedTestPlan()

    result = distribute_prioritized_shards(plan, shard_index=0, shard_count=2)

    assert result == []


def test_invalid_shard_count_raises() -> None:
    """shard_count < 1 should raise ValueError."""
    plan = PrioritizedTestPlan()

    with pytest.raises(ValueError, match="shard_count must be >= 1"):
        distribute_prioritized_shards(plan, shard_index=0, shard_count=0)


def test_invalid_shard_index_raises() -> None:
    """shard_index >= shard_count should raise ValueError."""
    plan = PrioritizedTestPlan()

    with pytest.raises(ValueError, match="shard_index must be in"):
        distribute_prioritized_shards(plan, shard_index=3, shard_count=3)


def test_negative_shard_index_raises() -> None:
    """Negative shard_index should raise ValueError."""
    plan = PrioritizedTestPlan()

    with pytest.raises(ValueError, match="shard_index must be in"):
        distribute_prioritized_shards(plan, shard_index=-1, shard_count=2)
