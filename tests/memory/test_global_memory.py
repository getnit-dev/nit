"""Tests for GlobalMemory."""

from pathlib import Path

import pytest

from nit.memory.global_memory import GlobalMemory


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    return tmp_path


@pytest.fixture
def memory(temp_project: Path) -> GlobalMemory:
    """Create a GlobalMemory instance."""
    return GlobalMemory(temp_project)


def test_global_memory_init(memory: GlobalMemory) -> None:
    """Test GlobalMemory initialization."""
    conventions = memory.get_conventions()
    assert conventions == {}

    stats = memory.get_stats()
    assert stats["total_runs"] == 0
    assert stats["successful_generations"] == 0


def test_set_and_get_conventions(memory: GlobalMemory) -> None:
    """Test setting and getting conventions."""
    conventions = {
        "language": "python",
        "naming_style": "function",
        "assertion_style": "assert",
    }
    memory.set_conventions(conventions)

    loaded = memory.get_conventions()
    assert loaded == conventions


def test_add_known_pattern(memory: GlobalMemory) -> None:
    """Test adding known patterns."""
    memory.add_known_pattern("test_function_style", context={"language": "python"})

    patterns = memory.get_known_patterns()
    assert len(patterns) == 1
    assert patterns[0]["pattern"] == "test_function_style"
    assert patterns[0]["success_count"] == 1
    assert patterns[0]["context"]["language"] == "python"


def test_add_known_pattern_duplicate(memory: GlobalMemory) -> None:
    """Test adding the same pattern multiple times increments count."""
    memory.add_known_pattern("test_function_style")
    memory.add_known_pattern("test_function_style")

    patterns = memory.get_known_patterns()
    assert len(patterns) == 1
    assert patterns[0]["success_count"] == 2


def test_add_failed_pattern(memory: GlobalMemory) -> None:
    """Test adding failed patterns."""
    memory.add_failed_pattern(
        "broken_mock_pattern",
        reason="ImportError: module not found",
        context={"framework": "pytest"},
    )

    patterns = memory.get_failed_patterns()
    assert len(patterns) == 1
    assert patterns[0]["pattern"] == "broken_mock_pattern"
    assert "ImportError" in patterns[0]["reason"]


def test_update_stats(memory: GlobalMemory) -> None:
    """Test updating generation statistics."""
    memory.update_stats(successful=True, tests_generated=5, tests_passing=4)

    stats = memory.get_stats()
    assert stats["total_runs"] == 1
    assert stats["successful_generations"] == 1
    assert stats["failed_generations"] == 0
    assert stats["total_tests_generated"] == 5
    assert stats["total_tests_passing"] == 4

    # Add a failed run
    memory.update_stats(successful=False, tests_generated=0, tests_passing=0)

    stats = memory.get_stats()
    assert stats["total_runs"] == 2
    assert stats["successful_generations"] == 1
    assert stats["failed_generations"] == 1


def test_clear_memory(memory: GlobalMemory) -> None:
    """Test clearing all memory."""
    # Add some data
    memory.set_conventions({"language": "python"})
    memory.add_known_pattern("pattern1")
    memory.update_stats(successful=True)

    # Clear it
    memory.clear()

    # Should be reset
    assert memory.get_conventions() == {}
    assert memory.get_known_patterns() == []
    assert memory.get_stats()["total_runs"] == 0


def test_memory_persistence(temp_project: Path) -> None:
    """Test that memory persists across instances."""
    # Create first instance and add data
    memory1 = GlobalMemory(temp_project)
    memory1.set_conventions({"language": "python"})
    memory1.add_known_pattern("pattern1")

    # Create second instance - should load existing data
    memory2 = GlobalMemory(temp_project)
    assert memory2.get_conventions()["language"] == "python"
    assert len(memory2.get_known_patterns()) == 1
