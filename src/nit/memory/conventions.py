"""Convention profile storage for the PatternAnalyzer.

Stores and retrieves convention profiles extracted from test files.
This is a simple JSON-based store that will be expanded in Phase 1.15.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING

from nit.agents.analyzers.pattern import ConventionProfile

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Default memory directory relative to project root
_DEFAULT_MEMORY_DIR = ".nit/memory"
_CONVENTIONS_FILE = "conventions.json"


class ConventionStore:
    """Simple JSON-based storage for convention profiles.

    Stores convention profiles in .nit/memory/conventions.json
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the convention store.

        Args:
            project_root: Root directory of the project.
        """
        self._root = project_root
        self._memory_dir = project_root / _DEFAULT_MEMORY_DIR
        self._conventions_file = self._memory_dir / _CONVENTIONS_FILE

    def save(self, profile: ConventionProfile) -> None:
        """Save a convention profile to disk.

        Args:
            profile: The convention profile to save.
        """
        # Ensure memory directory exists
        self._memory_dir.mkdir(parents=True, exist_ok=True)

        # Convert profile to dict
        data = asdict(profile)

        # Write to file
        self._conventions_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved convention profile to %s", self._conventions_file)

    def load(self) -> ConventionProfile | None:
        """Load the convention profile from disk.

        Returns:
            The loaded convention profile, or None if not found.
        """
        if not self._conventions_file.exists():
            logger.debug("No convention profile found at %s", self._conventions_file)
            return None

        try:
            data = json.loads(self._conventions_file.read_text(encoding="utf-8"))

            # Reconstruct the ConventionProfile
            profile = ConventionProfile(**data)
            logger.info("Loaded convention profile from %s", self._conventions_file)
            return profile

        except Exception as exc:
            logger.error("Failed to load convention profile: %s", exc)
            return None

    def exists(self) -> bool:
        """Check if a convention profile exists.

        Returns:
            True if a convention profile is stored, False otherwise.
        """
        return self._conventions_file.exists()

    def clear(self) -> None:
        """Delete the stored convention profile."""
        if self._conventions_file.exists():
            self._conventions_file.unlink()
            logger.info("Cleared convention profile at %s", self._conventions_file)
