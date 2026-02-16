"""Tests for batched prompt sync (memory/prompt_sync.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nit.memory.prompt_sync import PromptSyncer, _find_record_index, _sha256
from nit.models.prompt_record import PromptRecord
from nit.utils.platform_client import PlatformClientError, PlatformRuntimeConfig


def _make_record(record_id: str = "rec-1") -> PromptRecord:
    """Build a minimal PromptRecord for testing."""
    return PromptRecord(
        id=record_id,
        timestamp="2026-01-01T00:00:00Z",
        session_id="sess-1",
        model="test-model",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.0,
        max_tokens=100,
        response_text="world",
    )


# ── _sha256 helper ───────────────────────────────────────────────


def test_sha256_deterministic() -> None:
    assert _sha256("hello") == _sha256("hello")


def test_sha256_differs_for_different_input() -> None:
    assert _sha256("hello") != _sha256("world")


# ── _find_record_index ───────────────────────────────────────────


def test_find_record_index_found() -> None:
    records = [_make_record("a"), _make_record("b"), _make_record("c")]
    assert _find_record_index(records, "b") == 1


def test_find_record_index_not_found() -> None:
    records = [_make_record("a")]
    assert _find_record_index(records, "z") is None


# ── PromptSyncer ─────────────────────────────────────────────────


def test_sync_no_records() -> None:
    """Syncing with no records returns 0."""
    recorder = MagicMock()
    recorder.read_all.return_value = []
    config = PlatformRuntimeConfig()
    syncer = PromptSyncer(recorder, config)
    assert syncer.sync() == 0


@patch("nit.memory.prompt_sync.post_platform_prompts")
def test_sync_posts_records(mock_post: MagicMock) -> None:
    """Syncing with records posts to platform."""
    rec = _make_record("rec-1")
    recorder = MagicMock()
    recorder.read_all.return_value = [rec]
    config = PlatformRuntimeConfig()
    syncer = PromptSyncer(recorder, config)

    count = syncer.sync()

    assert count == 1
    mock_post.assert_called_once()


@patch("nit.memory.prompt_sync.post_platform_prompts")
def test_sync_skips_already_synced(mock_post: MagicMock) -> None:
    """Records before the last synced ID should be skipped."""
    records = [_make_record("a"), _make_record("b")]
    recorder = MagicMock()
    recorder.read_all.return_value = records
    config = PlatformRuntimeConfig()
    syncer = PromptSyncer(recorder, config)

    # First sync sends both
    syncer.sync()
    assert mock_post.call_count == 1

    # Second sync: last_synced_id is "a", so records[:0] is empty
    recorder.read_all.return_value = records
    count = syncer.sync()
    assert count == 0


@patch("nit.memory.prompt_sync.post_platform_prompts")
def test_sync_handles_api_error(mock_post: MagicMock) -> None:
    """API errors should be caught and return 0."""
    mock_post.side_effect = PlatformClientError("fail")
    recorder = MagicMock()
    recorder.read_all.return_value = [_make_record()]
    config = PlatformRuntimeConfig()
    syncer = PromptSyncer(recorder, config)

    count = syncer.sync()

    assert count == 0


@patch("nit.memory.prompt_sync.post_platform_prompts")
def test_sync_redact_source(mock_post: MagicMock) -> None:
    """With redact_source, message content should be hashed."""
    rec = _make_record()
    recorder = MagicMock()
    recorder.read_all.return_value = [rec]
    config = PlatformRuntimeConfig()
    syncer = PromptSyncer(recorder, config, redact_source=True)

    syncer.sync()

    posted_payloads = mock_post.call_args[0][1]
    payload = posted_payloads[0]
    # Content should be sha256 hashed, not the original
    assert payload["messages"][0]["content"] != "hello"
    assert len(payload["messages"][0]["content"]) == 64  # SHA-256 hex length
    # Response text should also be hashed
    assert payload["response_text"] != "world"
    assert len(payload["response_text"]) == 64
