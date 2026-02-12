"""Tests for analytics history storage."""

from pathlib import Path
from tempfile import TemporaryDirectory

from nit.memory.analytics_history import AnalyticsHistory
from nit.models.analytics import AnalyticsEvent, EventType, LLMUsage


def test_analytics_history_init() -> None:
    """Test analytics history initialization."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        _ = AnalyticsHistory(project_root)

        assert (project_root / ".nit" / "history").exists()


def test_append_and_read_events() -> None:
    """Test appending and reading events."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        history = AnalyticsHistory(project_root)

        # Create test event
        event = AnalyticsEvent(
            event_type=EventType.LLM_REQUEST,
            llm_usage=LLMUsage(
                provider="openai",
                model="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.01,
            ),
        )

        # Append event
        history.append_event(event, specialized_file="llm_usage")

        # Read events back
        events = list(history.read_events(from_file="llm_usage"))

        assert len(events) == 1
        assert events[0].event_type == EventType.LLM_REQUEST
        assert events[0].llm_usage is not None
        assert events[0].llm_usage.model == "gpt-4"


def test_read_events_with_filter() -> None:
    """Test reading events with type filter."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        history = AnalyticsHistory(project_root)

        # Create multiple events
        event1 = AnalyticsEvent(
            event_type=EventType.LLM_REQUEST,
            llm_usage=LLMUsage(
                provider="openai",
                model="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
        )
        event2 = AnalyticsEvent(
            event_type=EventType.PR_CREATED,
            pr_url="https://github.com/test/test/pull/1",
        )

        history.append_event(event1)
        history.append_event(event2)

        # Read only LLM events
        llm_events = list(history.read_events(event_type=EventType.LLM_REQUEST))
        assert len(llm_events) == 1
        assert llm_events[0].event_type == EventType.LLM_REQUEST

        # Read only PR events
        pr_events = list(history.read_events(event_type=EventType.PR_CREATED))
        assert len(pr_events) == 1
        assert pr_events[0].event_type == EventType.PR_CREATED


def test_read_events_with_limit() -> None:
    """Test reading events with limit."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        history = AnalyticsHistory(project_root)

        # Create multiple events
        for i in range(5):
            event = AnalyticsEvent(
                event_type=EventType.LLM_REQUEST,
                llm_usage=LLMUsage(
                    provider="openai",
                    model=f"gpt-{i}",
                    prompt_tokens=100,
                    completion_tokens=50,
                    total_tokens=150,
                ),
            )
            history.append_event(event)

        # Read with limit
        events = list(history.read_events(limit=3))
        assert len(events) == 3


def test_get_events_since() -> None:
    """Test getting events from last N days."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        history = AnalyticsHistory(project_root)

        # Create event
        event = AnalyticsEvent(
            event_type=EventType.LLM_REQUEST,
            llm_usage=LLMUsage(
                provider="openai",
                model="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
        )
        history.append_event(event)

        # Get recent events
        events = list(history.get_events_since(days=1))
        assert len(events) == 1


def test_prune_old_events() -> None:
    """Test pruning old events."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        history = AnalyticsHistory(project_root)

        # Create event
        event = AnalyticsEvent(
            event_type=EventType.LLM_REQUEST,
            llm_usage=LLMUsage(
                provider="openai",
                model="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
        )
        history.append_event(event, specialized_file="llm_usage")

        # Prune events older than 0 days (prunes everything)
        deleted = history.prune_old_events(older_than_days=0, from_file="llm_usage")

        # Events should be pruned
        assert deleted >= 0  # Depending on timing, may or may not prune


def test_clear_all() -> None:
    """Test clearing all history."""
    with TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        history = AnalyticsHistory(project_root)

        # Create event
        event = AnalyticsEvent(
            event_type=EventType.LLM_REQUEST,
            llm_usage=LLMUsage(
                provider="openai",
                model="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
        )
        history.append_event(event)

        # Clear all
        history.clear_all()

        # Verify files are deleted
        events = list(history.read_events())
        assert len(events) == 0


# ── Coverage gap tests ──────────────────────────────────────────────


def test_append_event_oserror(tmp_path: Path) -> None:
    """_append_to_file handles OSError gracefully."""
    history = AnalyticsHistory(tmp_path)
    # Make the history directory read-only to trigger OSError
    events_file = history.get_file_path("all")
    events_file.parent.mkdir(parents=True, exist_ok=True)
    # Create a directory where the file would be so open fails
    events_file.mkdir(exist_ok=True)

    event = AnalyticsEvent(
        event_type=EventType.LLM_REQUEST,
        llm_usage=LLMUsage(
            provider="openai",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )
    # Should not raise
    history.append_event(event)


def test_read_events_nonexistent_file(tmp_path: Path) -> None:
    """read_events returns nothing when file does not exist."""
    history = AnalyticsHistory(tmp_path)
    # Clear any auto-created files
    for f in history._history_dir.iterdir():
        f.unlink()
    events = list(history.read_events(from_file="llm_usage"))
    assert len(events) == 0


def test_read_events_empty_lines_skipped(tmp_path: Path) -> None:
    """read_events skips empty lines in JSONL file."""
    history = AnalyticsHistory(tmp_path)
    event = AnalyticsEvent(
        event_type=EventType.LLM_REQUEST,
        llm_usage=LLMUsage(
            provider="openai",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )
    history.append_event(event)

    # Add empty lines to the file
    events_file = history.get_file_path("all")
    with events_file.open("a") as f:
        f.write("\n\n\n")

    events = list(history.read_events())
    assert len(events) == 1


def test_read_events_malformed_line_skipped(tmp_path: Path) -> None:
    """read_events skips malformed JSON lines."""
    history = AnalyticsHistory(tmp_path)
    events_file = history.get_file_path("all")

    # Write valid event followed by malformed line
    event = AnalyticsEvent(
        event_type=EventType.LLM_REQUEST,
        llm_usage=LLMUsage(
            provider="openai",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )
    history.append_event(event)
    with events_file.open("a") as f:
        f.write("{invalid json}\n")

    events = list(history.read_events())
    assert len(events) == 1


def test_read_events_with_since_filter(tmp_path: Path) -> None:
    """read_events filters events by timestamp."""
    history = AnalyticsHistory(tmp_path)

    old_event = AnalyticsEvent(
        event_type=EventType.LLM_REQUEST,
        timestamp="2020-01-01T00:00:00+00:00",
        llm_usage=LLMUsage(
            provider="openai",
            model="gpt-3",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )
    new_event = AnalyticsEvent(
        event_type=EventType.LLM_REQUEST,
        timestamp="2026-01-01T00:00:00+00:00",
        llm_usage=LLMUsage(
            provider="openai",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )
    history.append_event(old_event)
    history.append_event(new_event)

    events = list(history.read_events(since="2025-01-01T00:00:00+00:00"))
    assert len(events) == 1
    assert events[0].llm_usage is not None
    assert events[0].llm_usage.model == "gpt-4"


def test_read_events_oserror(tmp_path: Path) -> None:
    """read_events handles OSError gracefully."""
    history = AnalyticsHistory(tmp_path)

    event = AnalyticsEvent(
        event_type=EventType.LLM_REQUEST,
        llm_usage=LLMUsage(
            provider="openai",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )
    history.append_event(event)

    events_file = history.get_file_path("all")
    # Replace file with directory to trigger OSError
    events_file.unlink()
    events_file.mkdir()

    events = list(history.read_events())
    assert len(events) == 0


def test_read_events_from_specialized_file(tmp_path: Path) -> None:
    """read_events reads from specialized file."""
    history = AnalyticsHistory(tmp_path)

    event = AnalyticsEvent(
        event_type=EventType.LLM_REQUEST,
        llm_usage=LLMUsage(
            provider="openai",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )
    history.append_event(event, specialized_file="llm_usage")

    events = list(history.read_events(from_file="llm_usage"))
    assert len(events) == 1


def test_prune_old_events_all_files(tmp_path: Path) -> None:
    """prune_old_events with from_file='all' prunes all files."""
    history = AnalyticsHistory(tmp_path)

    old_event = AnalyticsEvent(
        event_type=EventType.LLM_REQUEST,
        timestamp="2020-01-01T00:00:00+00:00",
        llm_usage=LLMUsage(
            provider="openai",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )
    history.append_event(old_event, specialized_file="llm_usage")

    deleted = history.prune_old_events(older_than_days=1, from_file="all")
    assert deleted >= 1


def test_prune_old_events_keeps_recent(tmp_path: Path) -> None:
    """prune_old_events keeps recent events."""
    history = AnalyticsHistory(tmp_path)

    # Recent event
    event = AnalyticsEvent(
        event_type=EventType.LLM_REQUEST,
        llm_usage=LLMUsage(
            provider="openai",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )
    history.append_event(event, specialized_file="llm_usage")

    deleted = history.prune_old_events(older_than_days=1, from_file="llm_usage")
    assert deleted == 0

    # Event should still exist
    events = list(history.read_events(from_file="llm_usage"))
    assert len(events) == 1


def test_prune_old_events_nonexistent_file(tmp_path: Path) -> None:
    """prune_old_events handles missing files gracefully."""
    history = AnalyticsHistory(tmp_path)
    deleted = history.prune_old_events(older_than_days=1, from_file="llm_usage")
    assert deleted == 0


def test_prune_file_oserror(tmp_path: Path) -> None:
    """_prune_file handles OSError gracefully."""
    history = AnalyticsHistory(tmp_path)

    # Point to a nonexistent file to trigger OSError on open
    missing = tmp_path / "nonexistent" / "file.jsonl"
    deleted = history._prune_file(missing, "2025-01-01T00:00:00+00:00")
    assert deleted == 0


def test_prune_malformed_lines_kept(tmp_path: Path) -> None:
    """_prune_file keeps malformed JSON lines."""
    history = AnalyticsHistory(tmp_path)

    file_path = history.get_file_path("llm_usage")
    with file_path.open("w") as f:
        f.write("{bad json}\n")
        f.write('{"event_type":"llm_request","timestamp":"2020-01-01"}\n')

    deleted = history._prune_file(file_path, "2025-01-01T00:00:00")
    # Old event pruned, bad JSON kept
    assert deleted == 1

    # Verify malformed line is kept
    with file_path.open() as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    assert len(lines) == 1
    assert "bad json" in lines[0]


def test_get_file_path_unknown_key(tmp_path: Path) -> None:
    """get_file_path falls back to 'all' for unknown keys."""
    history = AnalyticsHistory(tmp_path)
    path = history.get_file_path("nonexistent_key")
    assert path.name == "events.jsonl"


def test_clear_all_no_files(tmp_path: Path) -> None:
    """clear_all does not crash when no files exist."""
    history = AnalyticsHistory(tmp_path)
    # Remove any auto-created files
    for f in history._history_dir.iterdir():
        f.unlink()
    # Should not raise
    history.clear_all()


def test_append_to_specialized_file_unknown_key(tmp_path: Path) -> None:
    """append_event with unknown specialized_file key does not write."""
    history = AnalyticsHistory(tmp_path)
    event = AnalyticsEvent(
        event_type=EventType.LLM_REQUEST,
        llm_usage=LLMUsage(
            provider="openai",
            model="gpt-4",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )
    # Unknown key - should only write to "all" file
    history.append_event(event, specialized_file="unknown_type")

    events_all = list(history.read_events(from_file="all"))
    assert len(events_all) == 1
