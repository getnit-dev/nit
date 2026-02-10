"""Tests for PackageMemory."""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from nit.memory.package_memory import PackageMemory


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    return tmp_path


@pytest.fixture
def memory(temp_project: Path) -> PackageMemory:
    """Create a PackageMemory instance."""
    return PackageMemory(temp_project, "my-package")


def test_package_memory_init(memory: PackageMemory) -> None:
    """Test PackageMemory initialization."""
    patterns = memory.get_test_patterns()
    assert patterns == {}

    issues = memory.get_known_issues()
    assert issues == []

    history = memory.get_coverage_history()
    assert history == []


def test_set_and_get_test_patterns(memory: PackageMemory) -> None:
    """Test setting and getting test patterns."""
    patterns = {
        "naming": "describe/it",
        "mocking": "vi.mock",
    }
    memory.set_test_patterns(patterns)

    loaded = memory.get_test_patterns()
    assert loaded == patterns


def test_add_known_issue(memory: PackageMemory) -> None:
    """Test adding known issues."""
    memory.add_known_issue(
        "Tests fail with async imports",
        workaround="Use dynamic imports instead",
        context={"file": "api.test.ts"},
    )

    issues = memory.get_known_issues()
    assert len(issues) == 1
    assert issues[0]["issue"] == "Tests fail with async imports"
    assert issues[0]["workaround"] == "Use dynamic imports instead"
    assert "timestamp" in issues[0]


def test_add_multiple_known_issues(memory: PackageMemory) -> None:
    """Test adding multiple known issues."""
    memory.add_known_issue("Issue 1", workaround="Fix 1")
    memory.add_known_issue("Issue 2")

    issues = memory.get_known_issues()
    assert len(issues) == 2


def test_add_coverage_snapshot(memory: PackageMemory) -> None:
    """Test adding coverage snapshots."""
    memory.add_coverage_snapshot(
        coverage_percent=85.5,
        line_coverage={"total": 100, "covered": 85},
        branch_coverage={"total": 50, "covered": 40},
    )

    history = memory.get_coverage_history()
    assert len(history) == 1
    assert history[0]["coverage_percent"] == 85.5
    assert "timestamp" in history[0]


def test_get_latest_coverage(memory: PackageMemory) -> None:
    """Test getting latest coverage snapshot."""
    # Initially None
    assert memory.get_latest_coverage() is None

    # Add some snapshots
    memory.add_coverage_snapshot(coverage_percent=80.0)
    memory.add_coverage_snapshot(coverage_percent=85.0)
    memory.add_coverage_snapshot(coverage_percent=90.0)

    # Should return the last one
    latest = memory.get_latest_coverage()
    assert latest is not None
    assert latest["coverage_percent"] == 90.0


def test_add_llm_feedback(memory: PackageMemory) -> None:
    """Test adding LLM feedback."""
    memory.add_llm_feedback(
        "improvement",
        "Consider using more specific test names",
        metadata={"model": "gpt-4"},
    )

    feedback = memory.get_llm_feedback()
    assert len(feedback) == 1
    assert feedback[0]["type"] == "improvement"
    assert "specific test names" in feedback[0]["content"]
    assert feedback[0]["metadata"]["model"] == "gpt-4"


def test_clear_package_memory(memory: PackageMemory) -> None:
    """Test clearing package memory."""
    # Add some data
    memory.set_test_patterns({"naming": "function"})
    memory.add_known_issue("Issue 1")
    memory.add_coverage_snapshot(coverage_percent=80.0)
    memory.add_llm_feedback("error", "Test failed")

    # Clear it
    memory.clear()

    # Should be reset
    assert memory.get_test_patterns() == {}
    assert memory.get_known_issues() == []
    assert memory.get_coverage_history() == []
    assert memory.get_llm_feedback() == []


def test_package_name_sanitization(temp_project: Path) -> None:
    """Test that package names with slashes are sanitized."""
    memory1 = PackageMemory(temp_project, "packages/web")
    memory2 = PackageMemory(temp_project, "packages\\mobile")

    # Add data to each
    memory1.set_test_patterns({"web": True})
    memory2.set_test_patterns({"mobile": True})

    # Should have different files
    assert memory1.get_test_patterns() == {"web": True}
    assert memory2.get_test_patterns() == {"mobile": True}


def test_package_memory_persistence(temp_project: Path) -> None:
    """Test that package memory persists across instances."""
    # Create first instance and add data
    memory1 = PackageMemory(temp_project, "my-package")
    memory1.set_test_patterns({"naming": "function"})
    memory1.add_known_issue("Known issue")

    # Create second instance - should load existing data
    memory2 = PackageMemory(temp_project, "my-package")
    assert memory2.get_test_patterns()["naming"] == "function"
    assert len(memory2.get_known_issues()) == 1
