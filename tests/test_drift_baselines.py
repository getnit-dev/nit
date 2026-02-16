"""Tests for drift baseline management (task 3.11.6)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from nit.memory.drift_baselines import DriftBaselinesManager


@pytest.fixture
def baselines_manager(tmp_path: Path) -> DriftBaselinesManager:
    """Create a drift baselines manager with temporary storage."""
    return DriftBaselinesManager(tmp_path)


def test_get_baseline_not_exists(baselines_manager: DriftBaselinesManager) -> None:
    """Test getting a baseline that doesn't exist."""
    baseline = baselines_manager.get_baseline("test_id")

    assert baseline is None


def test_set_and_get_baseline(baselines_manager: DriftBaselinesManager) -> None:
    """Test setting and retrieving a baseline."""
    baselines_manager.set_baseline(
        test_id="test_1",
        output="Hello world",
        metadata={"framework": "test"},
    )

    baseline = baselines_manager.get_baseline("test_1")

    assert baseline is not None
    assert baseline.test_id == "test_1"
    assert baseline.output == "Hello world"
    assert baseline.embedding is None
    assert baseline.metadata["framework"] == "test"


def test_set_baseline_with_embedding(baselines_manager: DriftBaselinesManager) -> None:
    """Test setting a baseline with embedding."""
    embedding = [0.1, 0.2, 0.3, 0.4]

    baselines_manager.set_baseline(
        test_id="test_1",
        output="Hello world",
        embedding=embedding,
    )

    baseline = baselines_manager.get_baseline("test_1")

    assert baseline is not None
    assert baseline.embedding == embedding


def test_update_existing_baseline(baselines_manager: DriftBaselinesManager) -> None:
    """Test updating an existing baseline."""
    # Set initial baseline
    baselines_manager.set_baseline(
        test_id="test_1",
        output="Initial output",
    )

    # Ensure timestamps differ across calls
    time.sleep(0.01)

    # Update it
    baselines_manager.set_baseline(
        test_id="test_1",
        output="Updated output",
        embedding=[1.0, 2.0],
    )

    baseline = baselines_manager.get_baseline("test_1")

    assert baseline is not None
    assert baseline.output == "Updated output"
    assert baseline.embedding == [1.0, 2.0]
    assert baseline.created_at != baseline.updated_at


def test_delete_baseline(baselines_manager: DriftBaselinesManager) -> None:
    """Test deleting a baseline."""
    baselines_manager.set_baseline(
        test_id="test_1",
        output="Hello world",
    )

    # Verify it exists
    assert baselines_manager.get_baseline("test_1") is not None

    # Delete it
    deleted = baselines_manager.delete_baseline("test_1")

    assert deleted
    assert baselines_manager.get_baseline("test_1") is None


def test_delete_nonexistent_baseline(baselines_manager: DriftBaselinesManager) -> None:
    """Test deleting a baseline that doesn't exist."""
    deleted = baselines_manager.delete_baseline("nonexistent")

    assert not deleted


def test_list_baselines(baselines_manager: DriftBaselinesManager) -> None:
    """Test listing all baseline IDs."""
    assert baselines_manager.list_baselines() == []

    baselines_manager.set_baseline("test_1", "output 1")
    baselines_manager.set_baseline("test_2", "output 2")
    baselines_manager.set_baseline("test_3", "output 3")

    baseline_ids = baselines_manager.list_baselines()

    assert len(baseline_ids) == 3
    assert "test_1" in baseline_ids
    assert "test_2" in baseline_ids
    assert "test_3" in baseline_ids


def test_clear_all_baselines(baselines_manager: DriftBaselinesManager) -> None:
    """Test clearing all baselines."""
    baselines_manager.set_baseline("test_1", "output 1")
    baselines_manager.set_baseline("test_2", "output 2")

    assert len(baselines_manager.list_baselines()) == 2

    baselines_manager.clear_all()

    assert baselines_manager.list_baselines() == []


def test_persistence(tmp_path: Path) -> None:
    """Test that baselines persist across manager instances."""
    # Create first manager and set baseline
    manager1 = DriftBaselinesManager(tmp_path)
    manager1.set_baseline("test_1", "Persistent output", embedding=[1.0, 2.0])

    # Create second manager (simulating restart)
    manager2 = DriftBaselinesManager(tmp_path)

    # Verify baseline is still there
    baseline = manager2.get_baseline("test_1")

    assert baseline is not None
    assert baseline.output == "Persistent output"
    assert baseline.embedding == [1.0, 2.0]
