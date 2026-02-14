"""File-watch mode agent for detecting source changes and mapping to tests.

Implements a polling-based filesystem watcher that detects source code changes
and maps them to affected test files using naming conventions.
"""

from __future__ import annotations

import fnmatch
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Number of parts when splitting a pattern on '**'
_SINGLE_STAR_PARTS = 2  # e.g. **/*.py  -> ['', '/*.py']
_DOUBLE_STAR_PARTS = 3  # e.g. **/foo/** -> ['', '/foo/', '']


def _match_one_doublestar(path: str, parts: list[str]) -> bool:
    """Match a path against a pattern split into exactly two parts on ``**``.

    Handles patterns like ``**/*.py``, ``src/**``, and ``src/**/test.py``.

    Args:
        path: Relative file path.
        parts: Pattern split on ``**`` (must have length 2).

    Returns:
        True if the path matches the pattern.
    """
    prefix = parts[0].rstrip("/")
    suffix = parts[1].lstrip("/")

    # Pattern like **/*.py -> prefix='', suffix='*.py'
    if not prefix and suffix:
        segments = path.split("/")
        return any(fnmatch.fnmatch("/".join(segments[i:]), suffix) for i in range(len(segments)))

    # Pattern like src/** -> prefix='src', suffix=''
    if prefix and not suffix:
        return path.startswith(prefix + "/") or path == prefix

    # Pattern like src/**/test.py -> prefix='src', suffix='test.py'
    if prefix and suffix:
        if not path.startswith(prefix + "/"):
            return False
        rest = path[len(prefix) + 1 :]
        rest_segments = rest.split("/")
        return any(
            fnmatch.fnmatch("/".join(rest_segments[i:]), suffix) for i in range(len(rest_segments))
        )

    return False


@dataclass
class FileChange:
    """A single file change event."""

    path: str
    """Relative path to the changed file."""

    change_type: str
    """Type of change: 'modified', 'created', or 'deleted'."""

    timestamp: float
    """Unix timestamp when the change was detected."""


@dataclass
class WatchEvent:
    """A batch of file changes with affected tests."""

    changes: list[FileChange] = field(default_factory=list)
    """List of file changes in this event."""

    affected_tests: list[str] = field(default_factory=list)
    """List of test file paths affected by the changes."""


@dataclass
class FileWatchConfig:
    """Configuration for the file watcher."""

    watch_patterns: list[str] = field(
        default_factory=lambda: [
            "**/*.py",
            "**/*.ts",
            "**/*.js",
            "**/*.tsx",
            "**/*.jsx",
        ]
    )
    """Glob patterns for files to watch."""

    ignore_patterns: list[str] = field(
        default_factory=lambda: [
            "**/__pycache__/**",
            "**/node_modules/**",
            "**/.git/**",
            "**/.nit/**",
            "**/dist/**",
            "**/build/**",
        ]
    )
    """Glob patterns for files to ignore."""

    debounce_delay: float = 0.5
    """Seconds to wait after last change before emitting event."""

    poll_interval: float = 1.0
    """Seconds between filesystem polls."""


class FileWatcher:
    """Polling-based filesystem watcher that detects source changes.

    Scans the project directory on each poll, compares file modification times
    against a stored snapshot, and maps changed files to affected tests.
    """

    def __init__(self, project_root: Path, config: FileWatchConfig | None = None) -> None:
        """Initialize the file watcher.

        Args:
            project_root: Root directory of the project to watch.
            config: Watcher configuration. Uses defaults if not provided.
        """
        self._project_root = project_root
        self._config = config or FileWatchConfig()
        self._file_mtimes: dict[str, float] = {}
        self._pending_changes: list[FileChange] = []
        self._last_change_time: float = 0.0
        self._running: bool = False
        self._lock: threading.Lock = threading.Lock()

    @property
    def running(self) -> bool:
        """Whether the watcher is currently running."""
        return self._running

    def start(self) -> None:
        """Start watching for file changes.

        Takes an initial snapshot of file modification times.
        """
        self._running = True
        self._file_mtimes = self._scan_files()
        logger.info(
            "File watcher started, monitoring %d files in %s",
            len(self._file_mtimes),
            self._project_root,
        )

    def stop(self) -> None:
        """Stop watching for file changes."""
        self._running = False
        logger.info("File watcher stopped")

    def poll(self) -> WatchEvent | None:
        """Poll for file changes and return a watch event if ready.

        Scans the filesystem, detects changes, and debounces by waiting
        for ``debounce_delay`` seconds after the last detected change
        before returning an event.

        Returns:
            A WatchEvent if changes are ready, or None if no changes
            detected or still debouncing.
        """
        with self._lock:
            current = self._scan_files()
            new_changes = self._detect_changes(current)

            if new_changes:
                self._pending_changes.extend(new_changes)
                self._last_change_time = time.time()

            if not self._pending_changes:
                return None

            elapsed = time.time() - self._last_change_time
            if elapsed < self._config.debounce_delay:
                return None

            changes = list(self._pending_changes)
            self._pending_changes.clear()

        affected_tests = self.map_to_tests(changes)
        return WatchEvent(changes=changes, affected_tests=affected_tests)

    def _scan_files(self) -> dict[str, float]:
        """Scan the project directory for matching files.

        Walks the project root, filters by watch patterns, excludes
        files matching ignore patterns, and returns a mapping of
        relative path to modification time.

        Returns:
            Dictionary mapping relative file paths to their mtime.
        """
        result: dict[str, float] = {}
        try:
            for file_path in self._project_root.rglob("*"):
                if not file_path.is_file():
                    continue

                relative = str(file_path.relative_to(self._project_root))

                if self._matches_pattern(relative, self._config.ignore_patterns):
                    continue

                if not self._matches_pattern(relative, self._config.watch_patterns):
                    continue

                try:
                    result[relative] = file_path.stat().st_mtime
                except OSError:
                    continue
        except OSError:
            logger.warning("Failed to scan project directory: %s", self._project_root)

        return result

    def _detect_changes(self, current: dict[str, float]) -> list[FileChange]:
        """Compare current file snapshot against stored mtimes.

        Detects created, modified, and deleted files by comparing
        the current scan results against the previously stored snapshot.
        Updates ``_file_mtimes`` with the new snapshot.

        Args:
            current: Current mapping of relative paths to mtimes.

        Returns:
            List of detected file changes.
        """
        now = time.time()
        changes: list[FileChange] = []

        # Detect created and modified files
        for path, mtime in current.items():
            if path not in self._file_mtimes:
                changes.append(FileChange(path=path, change_type="created", timestamp=now))
            elif mtime != self._file_mtimes[path]:
                changes.append(FileChange(path=path, change_type="modified", timestamp=now))

        # Detect deleted files
        deleted_paths = set(self._file_mtimes) - set(current)
        changes.extend(
            FileChange(path=path, change_type="deleted", timestamp=now)
            for path in sorted(deleted_paths)
        )

        self._file_mtimes = dict(current)
        return changes

    def _matches_pattern(self, path: str, patterns: list[str]) -> bool:
        """Check if a path matches any of the given glob patterns.

        Handles ``**`` as a recursive wildcard that matches zero or more
        directory levels. For example:

        - ``**/*.py`` matches ``app.py`` and ``src/app.py``
        - ``**/__pycache__/**`` matches ``__pycache__/foo.pyc``
          and ``src/__pycache__/bar.pyc``

        Args:
            path: Relative file path to check.
            patterns: List of glob patterns to match against.

        Returns:
            True if the path matches at least one pattern.
        """
        return any(self._match_single(path, pattern) for pattern in patterns)

    @staticmethod
    def _match_single(path: str, pattern: str) -> bool:
        """Match a single path against a glob pattern with ``**`` support.

        Args:
            path: Relative file path to check.
            pattern: Glob pattern that may contain ``**``.

        Returns:
            True if the path matches the pattern.
        """
        if "**" not in pattern:
            return fnmatch.fnmatch(path, pattern)

        parts = pattern.split("**")

        # Pattern with one ** like **/*.py or src/** or src/**/test.py
        if len(parts) == _SINGLE_STAR_PARTS:
            return _match_one_doublestar(path, parts)

        # Pattern with two ** like **/foo/** -> check middle component
        if len(parts) == _DOUBLE_STAR_PARTS:
            middle = parts[1].strip("/")
            if middle:
                path_segments = path.split("/")
                return any(fnmatch.fnmatch(seg, middle) for seg in path_segments)

        return fnmatch.fnmatch(path, pattern)

    def map_to_tests(self, changes: list[FileChange]) -> list[str]:
        """Map changed source files to affected test files.

        Uses naming conventions to determine which tests correspond
        to changed source files:

        - Python: ``foo.py`` maps to ``test_foo.py`` or ``tests/test_foo.py``
        - TypeScript/JavaScript: ``foo.ts`` maps to ``foo.test.ts`` or ``foo.spec.ts``
        - If a test file itself changed, it is included directly.

        Args:
            changes: List of file changes to map.

        Returns:
            Deduplicated list of affected test file paths.
        """
        test_files: list[str] = []

        for change in changes:
            path = Path(change.path)
            stem = path.stem
            suffix = path.suffix

            # If the file is already a test file, include it directly
            if self._is_test_file(path):
                test_files.append(change.path)
                continue

            # Map Python source files to test files
            if suffix == ".py":
                candidates = [
                    f"test_{stem}.py",
                    f"tests/test_{stem}.py",
                    str(path.parent / f"test_{stem}.py"),
                ]
                test_files.extend(
                    candidate
                    for candidate in candidates
                    if (self._project_root / candidate).exists()
                )

            # Map TypeScript/JavaScript source files to test files
            elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
                base_suffix = suffix
                candidates = [
                    f"{stem}.test{base_suffix}",
                    f"{stem}.spec{base_suffix}",
                    str(path.parent / f"{stem}.test{base_suffix}"),
                    str(path.parent / f"{stem}.spec{base_suffix}"),
                ]
                test_files.extend(
                    candidate
                    for candidate in candidates
                    if (self._project_root / candidate).exists()
                )

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for test_file in test_files:
            if test_file not in seen:
                seen.add(test_file)
                unique.append(test_file)

        return unique

    @staticmethod
    def _is_test_file(path: Path) -> bool:
        """Check if a file path looks like a test file.

        Args:
            path: Path to check.

        Returns:
            True if the file appears to be a test file.
        """
        name = path.name

        # Python test files: test_*.py or *_test.py
        if name.startswith("test_") and name.endswith(".py"):
            return True
        if name.endswith("_test.py"):
            return True

        # JS/TS test files: *.test.ts, *.spec.ts, etc.
        return ".test." in name or ".spec." in name
