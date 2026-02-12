"""Analytics history storage using JSONL files.

Manages append-only history files in `.nit/history/` directory.
All analytics events are stored as JSON Lines for efficient streaming and crash-safety.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from nit.models.analytics import AnalyticsEvent as EventClass

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from nit.models.analytics import AnalyticsEvent, EventType

logger = logging.getLogger(__name__)

# History directory relative to project root
DEFAULT_HISTORY_DIR = ".nit/history"

# JSONL filenames for different event types
EVENT_FILES = {
    "all": "events.jsonl",  # Unified chronological log
    "llm_usage": "llm_usage.jsonl",
    "coverage": "coverage.jsonl",
    "test_execution": "test_execution.jsonl",
    "bug": "bugs.jsonl",
    "drift": "drift.jsonl",
    "pr": "prs.jsonl",
    "issue": "issues.jsonl",
}


class AnalyticsHistory:
    """Manages JSONL history files for analytics events.

    All events are appended to files in `.nit/history/` directory.
    The system uses JSONL (JSON Lines) format for:
    - Append-only writes (crash-safe)
    - Streaming reads (memory efficient)
    - Simple parsing (one event per line)
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize analytics history manager.

        Args:
            project_root: Root directory of the project.
        """
        self._root = project_root
        self._history_dir = project_root / DEFAULT_HISTORY_DIR
        self._history_dir.mkdir(parents=True, exist_ok=True)

    def append_event(
        self,
        event: AnalyticsEvent,
        specialized_file: str | None = None,
    ) -> None:
        """Append an event to history files.

        The event is always written to the unified events.jsonl file.
        Optionally, it can also be written to a specialized file for efficient queries.

        Args:
            event: The analytics event to record.
            specialized_file: Optional specialized file key (e.g., "llm_usage", "coverage").
        """
        # Convert event to JSON string
        event_json = json.dumps(event.to_dict(), ensure_ascii=False)

        # Write to unified log
        self._append_to_file(EVENT_FILES["all"], event_json)

        # Write to specialized file if specified
        if specialized_file and specialized_file in EVENT_FILES:
            self._append_to_file(EVENT_FILES[specialized_file], event_json)

    def _append_to_file(self, filename: str, json_line: str) -> None:
        """Append a JSON line to a file.

        Args:
            filename: Name of the file in history directory.
            json_line: JSON string to append (without newline).
        """
        file_path = self._history_dir / filename

        try:
            # Atomic append: open in append mode, write line with newline
            with file_path.open("a", encoding="utf-8") as f:
                f.write(json_line)
                f.write("\n")

        except OSError as exc:
            logger.error("Failed to append to %s: %s", file_path, exc)

    def read_events(
        self,
        event_type: EventType | None = None,
        since: str | None = None,
        limit: int = 0,
        from_file: str = "all",
    ) -> Iterator[AnalyticsEvent]:
        """Read events from history files.

        Streams events from JSONL files without loading everything into memory.

        Args:
            event_type: Filter by event type (None = all types).
            since: Filter events after this ISO timestamp (None = all events).
            limit: Maximum number of events to return (0 = unlimited).
            from_file: Which file to read from ("all", "llm_usage", "coverage", etc.).

        Yields:
            AnalyticsEvent instances matching the filters.
        """
        filename = EVENT_FILES.get(from_file, EVENT_FILES["all"])
        file_path = self._history_dir / filename

        if not file_path.exists():
            logger.debug("History file does not exist: %s", file_path)
            return

        count = 0

        try:
            with file_path.open("r", encoding="utf-8") as f:
                for line_num, raw_line in enumerate(f, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue

                    try:
                        # Parse JSON line
                        data = json.loads(line)
                        event = EventClass.from_dict(data)

                        # Apply filters
                        if event_type and event.event_type != event_type:
                            continue

                        if since and event.timestamp < since:
                            continue

                        # Yield event
                        yield event

                        # Check limit
                        count += 1
                        if limit > 0 and count >= limit:
                            break

                    except (json.JSONDecodeError, KeyError, ValueError) as exc:
                        logger.warning(
                            "Skipping malformed line %d in %s: %s",
                            line_num,
                            filename,
                            exc,
                        )
                        continue

        except OSError as exc:
            logger.error("Failed to read from %s: %s", file_path, exc)

    def get_events_since(
        self,
        days: int = 30,
        from_file: str = "all",
    ) -> Iterator[AnalyticsEvent]:
        """Get events from the last N days.

        Args:
            days: Number of days to look back.
            from_file: Which file to read from.

        Yields:
            AnalyticsEvent instances from the specified time window.
        """
        since_timestamp = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        yield from self.read_events(since=since_timestamp, from_file=from_file)

    def prune_old_events(self, older_than_days: int, from_file: str = "all") -> int:
        """Delete events older than specified days.

        Creates a new file with only recent events and replaces the old file.

        Args:
            older_than_days: Delete events older than this many days.
            from_file: Which file to prune ("all" prunes all files).

        Returns:
            Number of events deleted.
        """
        cutoff_timestamp = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()

        files_to_prune = [from_file] if from_file != "all" else list(EVENT_FILES.keys())
        total_deleted = 0

        for file_key in files_to_prune:
            if file_key == "all":
                continue  # Handle unified log last

            filename = EVENT_FILES[file_key]
            file_path = self._history_dir / filename

            if not file_path.exists():
                continue

            deleted = self._prune_file(file_path, cutoff_timestamp)
            total_deleted += deleted
            logger.info("Pruned %d events from %s", deleted, filename)

        # Prune unified log last
        if from_file == "all":
            unified_path = self._history_dir / EVENT_FILES["all"]
            if unified_path.exists():
                deleted = self._prune_file(unified_path, cutoff_timestamp)
                total_deleted += deleted
                logger.info("Pruned %d events from unified log", deleted)

        return total_deleted

    def _prune_file(self, file_path: Path, cutoff_timestamp: str) -> int:
        """Prune a single JSONL file.

        Args:
            file_path: Path to the JSONL file.
            cutoff_timestamp: ISO timestamp cutoff.

        Returns:
            Number of events deleted.
        """
        temp_path = file_path.with_suffix(".tmp")
        kept_count = 0
        deleted_count = 0

        try:
            with (
                file_path.open("r", encoding="utf-8") as infile,
                temp_path.open("w", encoding="utf-8") as outfile,
            ):
                for raw_line in infile:
                    line = raw_line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        timestamp = data.get("timestamp", "")

                        if timestamp >= cutoff_timestamp:
                            outfile.write(line)
                            outfile.write("\n")
                            kept_count += 1
                        else:
                            deleted_count += 1

                    except (json.JSONDecodeError, KeyError):
                        # Keep malformed lines (don't delete data)
                        outfile.write(line)
                        outfile.write("\n")
                        kept_count += 1

            # Replace original file with pruned version
            temp_path.replace(file_path)
            logger.info(
                "Kept %d events, deleted %d events from %s",
                kept_count,
                deleted_count,
                file_path.name,
            )

        except OSError as exc:
            logger.error("Failed to prune %s: %s", file_path, exc)
            if temp_path.exists():
                temp_path.unlink()
            return 0

        return deleted_count

    def get_file_path(self, file_key: str) -> Path:
        """Get the path to a history file.

        Args:
            file_key: Key for the file (e.g., "all", "llm_usage").

        Returns:
            Path to the history file.
        """
        filename = EVENT_FILES.get(file_key, EVENT_FILES["all"])
        return self._history_dir / filename

    def clear_all(self) -> None:
        """Delete all history files.

        Warning: This is irreversible!
        """
        for filename in EVENT_FILES.values():
            file_path = self._history_dir / filename
            if file_path.exists():
                file_path.unlink()
                logger.info("Deleted history file: %s", filename)
