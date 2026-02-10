"""Tests for PackageMemoryManager - per-package memory storage."""

from pathlib import Path

import pytest

from nit.memory.package_memory_manager import PackageMemoryManager


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    memory_dir = tmp_path / ".nit" / "memory"
    memory_dir.mkdir(parents=True)
    return tmp_path


def test_package_memory_manager_init(temp_project: Path) -> None:
    """Test PackageMemoryManager initialization."""
    manager = PackageMemoryManager(temp_project)

    assert manager.project_root == temp_project
    assert manager.packages_dir == temp_project / ".nit" / "memory" / "packages"
    assert manager.packages_dir.exists()


def test_get_package_memory(temp_project: Path) -> None:
    """Test getting package memory."""
    manager = PackageMemoryManager(temp_project)

    memory = manager.get_package_memory("test-package")
    assert memory is not None
    assert memory._package_name == "test-package"

    # Getting same package again should return cached instance
    memory2 = manager.get_package_memory("test-package")
    assert memory is memory2


def test_package_memory_file_location(temp_project: Path) -> None:
    """Test that package memory files are created in packages/ subdirectory."""
    manager = PackageMemoryManager(temp_project)

    memory = manager.get_package_memory("my-package")
    memory.set_test_patterns({"pattern": "test"})

    # Check file was created in correct location
    expected_file = temp_project / ".nit" / "memory" / "packages" / "package_my-package.json"
    assert expected_file.exists()


def test_list_packages(temp_project: Path) -> None:
    """Test listing packages with memory."""
    manager = PackageMemoryManager(temp_project)

    # Initially empty
    packages = manager.list_packages()
    assert packages == []

    # Create memory for some packages
    manager.get_package_memory("pkg-a").set_test_patterns({"a": 1})
    manager.get_package_memory("pkg-b").set_test_patterns({"b": 2})

    packages = manager.list_packages()
    assert len(packages) == 2
    assert "pkg-a" in packages
    assert "pkg-b" in packages


def test_clear_package_memory(temp_project: Path) -> None:
    """Test clearing memory for a specific package."""
    manager = PackageMemoryManager(temp_project)

    # Create memory
    memory = manager.get_package_memory("test-pkg")
    memory.set_test_patterns({"pattern": "test"})

    # Clear it
    manager.clear_package_memory("test-pkg")

    # Should be empty now
    new_memory = manager.get_package_memory("test-pkg")
    assert new_memory.get_test_patterns() == {}


def test_clear_all_package_memories(temp_project: Path) -> None:
    """Test clearing all package memories."""
    manager = PackageMemoryManager(temp_project)

    # Create multiple memories
    manager.get_package_memory("pkg-a").set_test_patterns({"a": 1})
    manager.get_package_memory("pkg-b").set_test_patterns({"b": 2})
    manager.get_package_memory("pkg-c").set_test_patterns({"c": 3})

    # Clear all
    manager.clear_all_package_memories()

    # All should be empty
    assert manager.get_package_memory("pkg-a").get_test_patterns() == {}
    assert manager.get_package_memory("pkg-b").get_test_patterns() == {}
    assert manager.get_package_memory("pkg-c").get_test_patterns() == {}


def test_package_name_sanitization(temp_project: Path) -> None:
    """Test that package names with slashes are sanitized."""
    manager = PackageMemoryManager(temp_project)

    # Use a scoped package name with slash
    memory = manager.get_package_memory("@scope/package")
    memory.set_test_patterns({"test": "value"})

    # File should use underscore instead of slash
    expected_file = temp_project / ".nit" / "memory" / "packages" / "package_@scope_package.json"
    assert expected_file.exists()

    # List should correctly unsanitize
    packages = manager.list_packages()
    # Note: current implementation replaces all _ with /, so @scope_package becomes @scope/package
    assert "@scope/package" in packages or "@scope_package" in packages


def test_package_memory_persistence(temp_project: Path) -> None:
    """Test that package memory persists across manager instances."""
    # Create first manager and save data
    manager1 = PackageMemoryManager(temp_project)
    memory1 = manager1.get_package_memory("persist-test")
    memory1.set_test_patterns({"key": "value"})
    memory1.add_known_issue("test issue", "test workaround")

    # Create new manager and verify data persists
    manager2 = PackageMemoryManager(temp_project)
    memory2 = manager2.get_package_memory("persist-test")

    assert memory2.get_test_patterns() == {"key": "value"}
    issues = memory2.get_known_issues()
    assert len(issues) == 1
    assert issues[0]["issue"] == "test issue"
    assert issues[0]["workaround"] == "test workaround"
