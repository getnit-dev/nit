"""Tests for file watcher and file watch UI."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

from nit.agents.watchers.file_watch_ui import FileWatchUI
from nit.agents.watchers.file_watcher import (
    FileChange,
    FileWatchConfig,
    FileWatcher,
    WatchEvent,
)

# ---------------------------------------------------------------------------
# FileWatchConfig
# ---------------------------------------------------------------------------


class TestFileWatchConfig:
    """Tests for FileWatchConfig defaults and overrides."""

    def test_default_patterns_include_common_extensions(self) -> None:
        """Default watch patterns cover Python, TypeScript, and JavaScript."""
        config = FileWatchConfig()
        assert "**/*.py" in config.watch_patterns
        assert "**/*.ts" in config.watch_patterns
        assert "**/*.js" in config.watch_patterns
        assert "**/*.tsx" in config.watch_patterns
        assert "**/*.jsx" in config.watch_patterns

    def test_default_ignore_patterns_include_known_dirs(self) -> None:
        """Default ignore patterns exclude __pycache__, node_modules, and .git."""
        config = FileWatchConfig()
        assert "**/__pycache__/**" in config.ignore_patterns
        assert "**/node_modules/**" in config.ignore_patterns
        assert "**/.git/**" in config.ignore_patterns

    def test_custom_patterns_override_defaults(self) -> None:
        """Custom patterns fully replace the default lists."""
        config = FileWatchConfig(
            watch_patterns=["**/*.rs"],
            ignore_patterns=["**/target/**"],
        )
        assert config.watch_patterns == ["**/*.rs"]
        assert config.ignore_patterns == ["**/target/**"]


# ---------------------------------------------------------------------------
# FileWatcher
# ---------------------------------------------------------------------------


class TestFileWatcherScanFiles:
    """Tests for FileWatcher._scan_files."""

    def test_scan_finds_matching_files(self, tmp_path: Path) -> None:
        """_scan_files returns files that match watch patterns."""
        (tmp_path / "app.py").write_text("pass")
        (tmp_path / "utils.py").write_text("pass")

        watcher = FileWatcher(tmp_path)
        result = watcher._scan_files()

        assert "app.py" in result
        assert "utils.py" in result

    def test_scan_ignores_files_in_ignore_patterns(self, tmp_path: Path) -> None:
        """_scan_files excludes files that match ignore patterns."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "cached.py").write_text("pass")
        (tmp_path / "main.py").write_text("pass")

        watcher = FileWatcher(tmp_path)
        result = watcher._scan_files()

        assert "main.py" in result
        assert "__pycache__/cached.py" not in result


class TestFileWatcherDetectChanges:
    """Tests for FileWatcher._detect_changes."""

    def test_detect_new_files(self, tmp_path: Path) -> None:
        """_detect_changes detects files that are new (created)."""
        watcher = FileWatcher(tmp_path)
        watcher._file_mtimes = {}

        current = {"new_file.py": 1000.0}
        changes = watcher._detect_changes(current)

        assert len(changes) == 1
        assert changes[0].path == "new_file.py"
        assert changes[0].change_type == "created"

    def test_detect_modified_files(self, tmp_path: Path) -> None:
        """_detect_changes detects files whose mtime changed."""
        watcher = FileWatcher(tmp_path)
        watcher._file_mtimes = {"app.py": 1000.0}

        current = {"app.py": 2000.0}
        changes = watcher._detect_changes(current)

        assert len(changes) == 1
        assert changes[0].path == "app.py"
        assert changes[0].change_type == "modified"

    def test_detect_deleted_files(self, tmp_path: Path) -> None:
        """_detect_changes detects files that were removed."""
        watcher = FileWatcher(tmp_path)
        watcher._file_mtimes = {"old_file.py": 1000.0}

        current: dict[str, float] = {}
        changes = watcher._detect_changes(current)

        assert len(changes) == 1
        assert changes[0].path == "old_file.py"
        assert changes[0].change_type == "deleted"


class TestFileWatcherPoll:
    """Tests for FileWatcher.poll."""

    def test_poll_returns_none_when_no_changes(self, tmp_path: Path) -> None:
        """poll returns None when no files have changed."""
        (tmp_path / "app.py").write_text("pass")
        watcher = FileWatcher(tmp_path)
        watcher.start()

        result = watcher.poll()
        assert result is None

    def test_poll_returns_event_after_debounce(self, tmp_path: Path) -> None:
        """poll returns a WatchEvent after the debounce delay has elapsed."""
        config = FileWatchConfig(debounce_delay=0.0)
        watcher = FileWatcher(tmp_path, config=config)
        watcher.start()

        # Create a new file after the initial snapshot
        (tmp_path / "new_module.py").write_text("pass")

        result = watcher.poll()
        assert result is not None
        assert isinstance(result, WatchEvent)
        assert len(result.changes) == 1
        assert result.changes[0].change_type == "created"


class TestFileWatcherStartStop:
    """Tests for FileWatcher.start and stop."""

    def test_start_takes_initial_snapshot(self, tmp_path: Path) -> None:
        """start populates the file mtime snapshot."""
        (tmp_path / "app.py").write_text("pass")
        watcher = FileWatcher(tmp_path)

        assert watcher._file_mtimes == {}
        watcher.start()
        assert "app.py" in watcher._file_mtimes

    def test_stop_sets_running_to_false(self, tmp_path: Path) -> None:
        """stop sets _running to False."""
        watcher = FileWatcher(tmp_path)
        watcher.start()
        assert watcher.running is True

        watcher.stop()
        assert watcher.running is False


class TestFileWatcherMapToTests:
    """Tests for FileWatcher.map_to_tests."""

    def test_maps_python_source_to_test(self, tmp_path: Path) -> None:
        """Python source file maps to test_*.py in tests/ directory."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_utils.py").write_text("pass")

        watcher = FileWatcher(tmp_path)
        changes = [FileChange(path="utils.py", change_type="modified", timestamp=time.time())]

        result = watcher.map_to_tests(changes)
        assert "tests/test_utils.py" in result

    def test_maps_typescript_source_to_test(self, tmp_path: Path) -> None:
        """TypeScript source file maps to *.test.ts or *.spec.ts."""
        (tmp_path / "utils.test.ts").write_text("test")

        watcher = FileWatcher(tmp_path)
        changes = [FileChange(path="utils.ts", change_type="modified", timestamp=time.time())]

        result = watcher.map_to_tests(changes)
        assert "utils.test.ts" in result

    def test_includes_changed_test_files_directly(self, tmp_path: Path) -> None:
        """Changed test files are included directly in the result."""
        watcher = FileWatcher(tmp_path)
        changes = [
            FileChange(path="test_app.py", change_type="modified", timestamp=time.time()),
        ]

        result = watcher.map_to_tests(changes)
        assert "test_app.py" in result

    def test_returns_empty_for_non_source_files(self, tmp_path: Path) -> None:
        """Non-source files (e.g. .txt, .json) do not map to tests."""
        watcher = FileWatcher(tmp_path)
        changes = [
            FileChange(path="readme.md", change_type="modified", timestamp=time.time()),
        ]

        result = watcher.map_to_tests(changes)
        assert result == []


# ---------------------------------------------------------------------------
# FileWatchUI
# ---------------------------------------------------------------------------


class TestFileWatchUI:
    """Tests for the FileWatchUI display."""

    def test_update_status_changes_status(self) -> None:
        """update_status stores the new status."""
        ui = FileWatchUI()
        assert ui._status == "IDLE"

        ui.update_status("RUNNING")
        assert ui._status == "RUNNING"

    def test_update_changes_stores_files_with_limit(self) -> None:
        """update_changes keeps at most 10 recent files."""
        ui = FileWatchUI()
        files = [f"file_{i}.py" for i in range(15)]

        ui.update_changes(files)
        assert len(ui._last_changes) == 10
        assert ui._last_changes[0] == "file_5.py"
        assert ui._last_changes[-1] == "file_14.py"

    def test_update_result_stores_result(self) -> None:
        """update_result stores the result string."""
        ui = FileWatchUI()
        ui.update_result("5 passed, 0 failed")
        assert ui._last_result == "5 passed, 0 failed"

    def test_render_outputs_without_error(self) -> None:
        """render prints to console without raising."""
        ui = FileWatchUI()
        ui._console = MagicMock()

        ui.update_status("SUCCESS")
        ui.update_changes(["app.py"])
        ui.update_result("all passed")
        ui.render()

        ui._console.print.assert_called_once()
        printed = ui._console.print.call_args[0][0]
        assert "SUCCESS" in printed
        assert "changes=1" in printed
        assert "all passed" in printed


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestFileWatcherIntegration:
    """Integration tests for end-to-end watcher behaviour."""

    def test_detects_file_creation_in_watched_directory(self, tmp_path: Path) -> None:
        """FileWatcher detects newly created files after start."""
        config = FileWatchConfig(debounce_delay=0.0)
        watcher = FileWatcher(tmp_path, config=config)
        watcher.start()

        # Create a new file
        new_file = tmp_path / "service.py"
        new_file.write_text("class Service: ...")

        event = watcher.poll()
        assert event is not None
        paths = [c.path for c in event.changes]
        assert "service.py" in paths

    def test_ignores_files_in_pycache(self, tmp_path: Path) -> None:
        """FileWatcher does not report changes in __pycache__."""
        config = FileWatchConfig(debounce_delay=0.0)
        watcher = FileWatcher(tmp_path, config=config)
        watcher.start()

        # Create a file inside __pycache__
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "module.cpython-311.pyc").write_text("bytecode")

        # Also create a normal .py so poll has something to check
        # (pyc won't match *.py pattern anyway, but test the ignore path)
        event = watcher.poll()
        # Event should be None because .pyc doesn't match watch patterns
        # and __pycache__ is in ignore patterns
        assert event is None
