"""Global memory storage for project-wide patterns and conventions.

Stores project-wide conventions, known patterns, failed patterns,
and generation statistics across all test generation runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

from nit.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# Global memory filename
_GLOBAL_MEMORY_FILE = "global.json"

# Display constants for markdown export
_MAX_COVERAGE_SNAPSHOTS = 5


@dataclass
class FailedPattern:
    """A pattern that failed during test generation."""

    pattern: str
    reason: str
    timestamp: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class KnownPattern:
    """A pattern that successfully worked during test generation."""

    pattern: str
    success_count: int = 0
    last_used: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationStats:
    """Statistics about test generation runs."""

    total_runs: int = 0
    successful_generations: int = 0
    failed_generations: int = 0
    total_tests_generated: int = 0
    total_tests_passing: int = 0
    last_run: str = ""


class GlobalMemory:
    """Project-wide memory for conventions, patterns, and statistics.

    Stores:
    - Project-wide conventions (naming, assertion styles, etc.)
    - Known patterns that work well
    - Failed patterns to avoid
    - Generation statistics
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize global memory.

        Args:
            project_root: Root directory of the project.
        """
        self._store: MemoryStore[dict[str, Any]] = MemoryStore(project_root, _GLOBAL_MEMORY_FILE)
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load data from disk into memory."""
        data = self._store.load()
        if data:
            self._data = data
        else:
            # Initialize with empty structure
            self._data = {
                "conventions": {},
                "known_patterns": [],
                "failed_patterns": [],
                "generation_stats": {
                    "total_runs": 0,
                    "successful_generations": 0,
                    "failed_generations": 0,
                    "total_tests_generated": 0,
                    "total_tests_passing": 0,
                    "last_run": "",
                },
            }

    def _save(self) -> None:
        """Save current data to disk."""
        self._store.save(self._data)

    def get_conventions(self) -> dict[str, Any]:
        """Get project-wide conventions.

        Returns:
            Dictionary of conventions.
        """
        return cast("dict[str, Any]", self._data.get("conventions", {}))

    def set_conventions(self, conventions: dict[str, Any]) -> None:
        """Set project-wide conventions.

        Args:
            conventions: Dictionary of conventions to store.
        """
        self._data["conventions"] = conventions
        self._save()

    def add_known_pattern(self, pattern: str, context: dict[str, Any] | None = None) -> None:
        """Add or update a known successful pattern.

        If pattern already exists, increments success count and updates timestamp.

        Args:
            pattern: The pattern that worked.
            context: Additional context about the pattern.
        """
        known_patterns = self._data.get("known_patterns", [])

        # Check if pattern already exists
        for p in known_patterns:
            if p.get("pattern") == pattern:
                p["success_count"] = p.get("success_count", 0) + 1
                p["last_used"] = datetime.now(UTC).isoformat()
                if context:
                    p["context"] = context
                self._save()
                return

        # Add new pattern
        new_pattern = {
            "pattern": pattern,
            "success_count": 1,
            "last_used": datetime.now(UTC).isoformat(),
            "context": context or {},
        }
        known_patterns.append(new_pattern)
        self._data["known_patterns"] = known_patterns
        self._save()

    def add_failed_pattern(
        self, pattern: str, reason: str, context: dict[str, Any] | None = None
    ) -> None:
        """Add a failed pattern to avoid in the future.

        Args:
            pattern: The pattern that failed.
            reason: Why it failed.
            context: Additional context about the failure.
        """
        failed_patterns = self._data.get("failed_patterns", [])

        failed_pattern = {
            "pattern": pattern,
            "reason": reason,
            "timestamp": datetime.now(UTC).isoformat(),
            "context": context or {},
        }
        failed_patterns.append(failed_pattern)
        self._data["failed_patterns"] = failed_patterns
        self._save()

    def get_known_patterns(self) -> list[dict[str, Any]]:
        """Get all known successful patterns.

        Returns:
            List of known pattern dictionaries.
        """
        return cast("list[dict[str, Any]]", self._data.get("known_patterns", []))

    def get_failed_patterns(self) -> list[dict[str, Any]]:
        """Get all failed patterns.

        Returns:
            List of failed pattern dictionaries.
        """
        return cast("list[dict[str, Any]]", self._data.get("failed_patterns", []))

    def update_stats(
        self,
        *,
        successful: bool = False,
        tests_generated: int = 0,
        tests_passing: int = 0,
    ) -> None:
        """Update generation statistics.

        Args:
            successful: Whether the generation was successful.
            tests_generated: Number of tests generated.
            tests_passing: Number of tests passing.
        """
        stats = self._data.get("generation_stats", {})

        stats["total_runs"] = stats.get("total_runs", 0) + 1
        if successful:
            stats["successful_generations"] = stats.get("successful_generations", 0) + 1
        else:
            stats["failed_generations"] = stats.get("failed_generations", 0) + 1

        stats["total_tests_generated"] = stats.get("total_tests_generated", 0) + tests_generated
        stats["total_tests_passing"] = stats.get("total_tests_passing", 0) + tests_passing
        stats["last_run"] = datetime.now(UTC).isoformat()

        self._data["generation_stats"] = stats
        self._save()

    def get_stats(self) -> dict[str, Any]:
        """Get generation statistics.

        Returns:
            Dictionary of statistics.
        """
        return cast("dict[str, Any]", self._data.get("generation_stats", {}))

    def clear(self) -> None:
        """Clear all global memory."""
        self._store.clear()
        self._load()

    def to_dict(self) -> dict[str, Any]:
        """Export memory as a dictionary for display or serialization.

        Returns:
            Dictionary containing all memory data.
        """
        return self._data.copy()

    def to_markdown(self) -> str:
        """Export memory as a human-readable markdown report.

        Returns:
            Markdown-formatted string containing all memory data.
        """
        sections = [
            "# Global Memory Report",
            "",
            *self._format_conventions_section(),
            *self._format_known_patterns_section(),
            *self._format_failed_patterns_section(),
            *self._format_statistics_section(),
        ]
        return "\n".join(sections)

    def _format_conventions_section(self) -> list[str]:
        """Format conventions section for markdown export."""
        lines = ["## Conventions", ""]
        conventions = self.get_conventions()
        if conventions:
            lines.extend(f"- **{key}**: {value}" for key, value in conventions.items())
        else:
            lines.append("*No conventions recorded*")
        lines.append("")
        return lines

    def _format_known_patterns_section(self) -> list[str]:
        """Format known patterns section for markdown export."""
        lines = ["## Known Patterns", ""]
        known_patterns = self.get_known_patterns()
        if not known_patterns:
            lines.extend(["*No known patterns recorded*", ""])
            return lines

        for idx, pattern in enumerate(known_patterns, start=1):
            lines.append(f"### Pattern {idx}")
            lines.append(f"- **Pattern**: `{pattern.get('pattern', 'N/A')}`")
            lines.append(f"- **Success Count**: {pattern.get('success_count', 0)}")
            lines.append(f"- **Last Used**: {pattern.get('last_used', 'Never')}")
            if pattern.get("context"):
                lines.append(f"- **Context**: {pattern['context']}")
            lines.append("")
        return lines

    def _format_failed_patterns_section(self) -> list[str]:
        """Format failed patterns section for markdown export."""
        lines = ["## Failed Patterns", ""]
        failed_patterns = self.get_failed_patterns()
        if not failed_patterns:
            lines.extend(["*No failed patterns recorded*", ""])
            return lines

        for idx, pattern in enumerate(failed_patterns, start=1):
            lines.append(f"### Failed Pattern {idx}")
            lines.append(f"- **Pattern**: `{pattern.get('pattern', 'N/A')}`")
            lines.append(f"- **Reason**: {pattern.get('reason', 'Unknown')}")
            lines.append(f"- **Timestamp**: {pattern.get('timestamp', 'Unknown')}")
            if pattern.get("context"):
                lines.append(f"- **Context**: {pattern['context']}")
            lines.append("")
        return lines

    def _format_statistics_section(self) -> list[str]:
        """Format statistics section for markdown export."""
        lines = ["## Generation Statistics", ""]
        stats = self.get_stats()
        if stats:
            lines.extend(
                [
                    f"- **Total Runs**: {stats.get('total_runs', 0)}",
                    f"- **Successful Generations**: {stats.get('successful_generations', 0)}",
                    f"- **Failed Generations**: {stats.get('failed_generations', 0)}",
                    f"- **Total Tests Generated**: {stats.get('total_tests_generated', 0)}",
                    f"- **Total Tests Passing**: {stats.get('total_tests_passing', 0)}",
                    f"- **Last Run**: {stats.get('last_run', 'Never')}",
                ]
            )
        else:
            lines.append("*No statistics available*")
        lines.append("")
        return lines
