"""Base memory storage interface for nit.

Provides a generic JSON-based storage system for different memory types.
All memory data is stored in `.nit/memory/` directory.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Default memory directory relative to project root
DEFAULT_MEMORY_DIR = ".nit/memory"

T = TypeVar("T")


class MemoryStore[T]:
    """Generic JSON-based storage for memory data.

    Stores and retrieves JSON-serializable data in `.nit/memory/` directory.
    Subclasses should provide serialization/deserialization logic.
    """

    def __init__(self, project_root: Path, filename: str) -> None:
        """Initialize the memory store.

        Args:
            project_root: Root directory of the project.
            filename: Name of the JSON file (e.g., "global.json", "package_foo.json").
        """
        self._root = project_root
        self._memory_dir = project_root / DEFAULT_MEMORY_DIR
        self._file_path = self._memory_dir / filename

    def save(self, data: dict[str, Any]) -> None:
        """Save data to disk as JSON.

        Args:
            data: Dictionary to save.
        """
        # Ensure memory directory and any subdirectories exist
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to file
        self._file_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved memory to %s", self._file_path)

    def load(self) -> dict[str, Any] | None:
        """Load data from disk.

        Returns:
            The loaded data dictionary, or None if file doesn't exist.
        """
        if not self._file_path.exists():
            logger.debug("No memory file found at %s", self._file_path)
            return None

        try:
            data = json.loads(self._file_path.read_text(encoding="utf-8"))
            logger.info("Loaded memory from %s", self._file_path)
            return cast("dict[str, Any]", data)

        except Exception as exc:
            logger.error("Failed to load memory from %s: %s", self._file_path, exc)
            return None

    def exists(self) -> bool:
        """Check if memory file exists.

        Returns:
            True if the memory file exists, False otherwise.
        """
        return self._file_path.exists()

    def clear(self) -> None:
        """Delete the memory file."""
        if self._file_path.exists():
            self._file_path.unlink()
            logger.info("Cleared memory at %s", self._file_path)

    def update(self, updates: dict[str, Any]) -> None:
        """Update existing memory data with new values.

        Loads existing data, merges with updates, and saves.

        Args:
            updates: Dictionary of updates to merge into existing data.
        """
        # Load existing data or start with empty dict
        data = self.load() or {}

        # Merge updates (deep merge for nested dicts)
        data.update(updates)

        # Save back
        self.save(data)

    @property
    def file_path(self) -> Path:
        """Get the file path for this memory store.

        Returns:
            Path to the JSON file.
        """
        return self._file_path
