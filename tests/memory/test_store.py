"""Tests for MemoryStore base class."""

from pathlib import Path
from typing import Any

import pytest

from nit.memory.store import MemoryStore


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    return tmp_path


def test_memory_store_save_and_load(temp_project: Path) -> None:
    """Test saving and loading data from memory store."""
    store: MemoryStore[dict[str, Any]] = MemoryStore(temp_project, "test.json")

    # Save data
    data = {"key": "value", "nested": {"foo": "bar"}}
    store.save(data)

    # Load data
    loaded = store.load()
    assert loaded == data


def test_memory_store_load_nonexistent(temp_project: Path) -> None:
    """Test loading from nonexistent file returns None."""
    store: MemoryStore[dict[str, Any]] = MemoryStore(temp_project, "nonexistent.json")
    assert store.load() is None


def test_memory_store_exists(temp_project: Path) -> None:
    """Test exists() method."""
    store: MemoryStore[dict[str, Any]] = MemoryStore(temp_project, "test.json")

    # Initially doesn't exist
    assert not store.exists()

    # After saving, exists
    store.save({"data": "test"})
    assert store.exists()


def test_memory_store_clear(temp_project: Path) -> None:
    """Test clearing memory store."""
    store: MemoryStore[dict[str, Any]] = MemoryStore(temp_project, "test.json")

    # Save some data
    store.save({"data": "test"})
    assert store.exists()

    # Clear it
    store.clear()
    assert not store.exists()
    assert store.load() is None


def test_memory_store_update(temp_project: Path) -> None:
    """Test updating memory store."""
    store: MemoryStore[dict[str, Any]] = MemoryStore(temp_project, "test.json")

    # Save initial data
    store.save({"key1": "value1", "key2": "value2"})

    # Update with new data
    store.update({"key2": "updated", "key3": "new"})

    # Load and verify
    loaded = store.load()
    assert loaded == {"key1": "value1", "key2": "updated", "key3": "new"}


def test_memory_store_update_empty(temp_project: Path) -> None:
    """Test updating when no existing data."""
    store: MemoryStore[dict[str, Any]] = MemoryStore(temp_project, "test.json")

    # Update without existing data
    store.update({"key": "value"})

    # Should create new data
    loaded = store.load()
    assert loaded == {"key": "value"}


def test_memory_store_file_path(temp_project: Path) -> None:
    """Test file_path property."""
    store: MemoryStore[dict[str, Any]] = MemoryStore(temp_project, "test.json")
    expected = temp_project / ".nit" / "memory" / "test.json"
    assert store.file_path == expected
