"""Baseline management for drift detection (task 3.11.6).

This module stores and manages baseline outputs and embeddings for drift tests.
Baselines are stored in `.nit/memory/drift_baselines.json`.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from nit.memory.store import MemoryStore

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DriftBaseline:
    """Baseline for a single drift test."""

    test_id: str
    output: str
    embedding: list[float] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


class DriftBaselinesManager:
    """Manage drift test baselines.

    Stores baseline outputs and embeddings for drift tests in memory.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the drift baselines manager.

        Args:
            project_root: Root directory of the project.
        """
        self._store = MemoryStore[dict[str, Any]](project_root, "drift_baselines.json")
        self._baselines: dict[str, DriftBaseline] = {}
        self._load()

    def _load(self) -> None:
        """Load baselines from disk."""
        data = self._store.load()
        if not data:
            return

        baselines_data = data.get("baselines", {})
        for test_id, baseline_dict in baselines_data.items():
            self._baselines[test_id] = DriftBaseline(**baseline_dict)

    def _save(self) -> None:
        """Save baselines to disk."""
        data = {
            "baselines": {
                test_id: asdict(baseline) for test_id, baseline in self._baselines.items()
            },
            "last_updated": datetime.now(UTC).isoformat(),
        }
        self._store.save(data)

    def get_baseline(self, test_id: str) -> DriftBaseline | None:
        """Get baseline for a specific test.

        Args:
            test_id: ID of the drift test.

        Returns:
            The baseline if it exists, None otherwise.
        """
        return self._baselines.get(test_id)

    def set_baseline(
        self,
        test_id: str,
        output: str,
        embedding: list[float] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set or update baseline for a test.

        Args:
            test_id: ID of the drift test.
            output: Baseline output string.
            embedding: Optional embedding vector for semantic comparison.
            metadata: Optional metadata for the baseline.
        """
        now = datetime.now(UTC).isoformat()

        if test_id in self._baselines:
            # Update existing baseline
            baseline = self._baselines[test_id]
            baseline.output = output
            baseline.embedding = embedding
            baseline.updated_at = now
            if metadata:
                baseline.metadata.update(metadata)
        else:
            # Create new baseline
            self._baselines[test_id] = DriftBaseline(
                test_id=test_id,
                output=output,
                embedding=embedding,
                created_at=now,
                updated_at=now,
                metadata=metadata or {},
            )

        self._save()
        logger.info("Updated baseline for test: %s", test_id)

    def delete_baseline(self, test_id: str) -> bool:
        """Delete baseline for a test.

        Args:
            test_id: ID of the drift test.

        Returns:
            True if baseline was deleted, False if it didn't exist.
        """
        if test_id in self._baselines:
            del self._baselines[test_id]
            self._save()
            logger.info("Deleted baseline for test: %s", test_id)
            return True
        return False

    def list_baselines(self) -> list[str]:
        """List all baseline test IDs.

        Returns:
            List of test IDs that have baselines.
        """
        return list(self._baselines.keys())

    def clear_all(self) -> None:
        """Clear all baselines."""
        self._baselines.clear()
        self._save()
        logger.info("Cleared all drift baselines")
