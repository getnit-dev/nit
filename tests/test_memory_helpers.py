"""Tests for the shared memory helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from nit.llm.engine import LLMMessage
from nit.memory.helpers import (
    build_memory_guidance,
    get_memory_context,
    inject_memory_into_messages,
    record_outcome,
)


def _make_memory(
    known: list[dict[str, object]] | None = None,
    failed: list[dict[str, object]] | None = None,
) -> MagicMock:
    """Create a mock GlobalMemory with given patterns."""
    mem = MagicMock()
    mem.get_known_patterns.return_value = known or []
    mem.get_failed_patterns.return_value = failed or []
    return mem


# -- get_memory_context -------------------------------------------------------


def test_get_memory_context_returns_none_when_memory_is_none() -> None:
    assert get_memory_context(None) is None


def test_get_memory_context_returns_empty_lists_when_no_patterns() -> None:
    mem = _make_memory()
    result = get_memory_context(mem, filter_value="pytest")
    assert result is not None
    assert result["known_patterns"] == []
    assert result["failed_patterns"] == []


def test_get_memory_context_filters_known_by_key() -> None:
    mem = _make_memory(
        known=[
            {"pattern": "use fixtures", "context": {"domain": "testing"}},
            {"pattern": "use mocks", "context": {"domain": "debugging"}},
        ]
    )
    result = get_memory_context(
        mem,
        known_filter_key="domain",
        failed_filter_key="domain",
        filter_value="testing",
    )
    assert result is not None
    assert result["known_patterns"] == ["use fixtures"]


def test_get_memory_context_filters_failed_by_key() -> None:
    mem = _make_memory(
        failed=[
            {"pattern": "bad import", "reason": "not found", "context": {"domain": "testing"}},
            {"pattern": "timeout", "reason": "slow", "context": {"domain": "debugging"}},
        ]
    )
    result = get_memory_context(
        mem,
        known_filter_key="domain",
        failed_filter_key="domain",
        filter_value="debugging",
    )
    assert result is not None
    assert len(result["failed_patterns"]) == 1
    assert "timeout" in result["failed_patterns"][0]


def test_get_memory_context_includes_universal_patterns() -> None:
    """Patterns without the filter key should always be included."""
    mem = _make_memory(
        known=[
            {"pattern": "universal", "context": {}},
            {"pattern": "specific", "context": {"domain": "other"}},
        ]
    )
    result = get_memory_context(mem, filter_value="testing")
    assert result is not None
    assert "universal" in result["known_patterns"]
    assert "specific" not in result["known_patterns"]


def test_get_memory_context_limits_to_max_patterns() -> None:
    mem = _make_memory(known=[{"pattern": f"p{i}", "context": {}} for i in range(20)])
    result = get_memory_context(mem, filter_value="any")
    assert result is not None
    assert len(result["known_patterns"]) == 10


# -- build_memory_guidance ----------------------------------------------------


def test_build_memory_guidance_returns_empty_for_none() -> None:
    assert build_memory_guidance(None) == ""


def test_build_memory_guidance_returns_empty_when_no_patterns() -> None:
    assert build_memory_guidance({"known_patterns": [], "failed_patterns": []}) == ""


def test_build_memory_guidance_includes_known_patterns() -> None:
    guidance = build_memory_guidance(
        {"known_patterns": ["use fixtures", "mock API"], "failed_patterns": []}
    )
    assert "Known successful patterns" in guidance
    assert "- use fixtures" in guidance
    assert "- mock API" in guidance


def test_build_memory_guidance_includes_failed_patterns() -> None:
    guidance = build_memory_guidance(
        {"known_patterns": [], "failed_patterns": ["bad import: missing dep"]}
    )
    assert "Patterns to avoid" in guidance
    assert "- bad import: missing dep" in guidance


def test_build_memory_guidance_includes_both() -> None:
    guidance = build_memory_guidance(
        {"known_patterns": ["good"], "failed_patterns": ["bad: reason"]}
    )
    assert "Known successful patterns" in guidance
    assert "Patterns to avoid" in guidance


# -- inject_memory_into_messages -----------------------------------------------


def test_inject_memory_into_messages_appends_message() -> None:
    messages: list[LLMMessage] = [
        LLMMessage(role="system", content="system"),
        LLMMessage(role="user", content="prompt"),
    ]
    ctx = {"known_patterns": ["pattern1"], "failed_patterns": []}
    inject_memory_into_messages(messages, ctx)
    assert len(messages) == 3
    assert messages[-1].role == "user"
    assert "pattern1" in messages[-1].content


def test_inject_memory_into_messages_noop_when_none() -> None:
    messages: list[LLMMessage] = [LLMMessage(role="user", content="hi")]
    inject_memory_into_messages(messages, None)
    assert len(messages) == 1


def test_inject_memory_into_messages_noop_when_empty() -> None:
    messages: list[LLMMessage] = [LLMMessage(role="user", content="hi")]
    inject_memory_into_messages(messages, {"known_patterns": [], "failed_patterns": []})
    assert len(messages) == 1


# -- record_outcome -----------------------------------------------------------


def test_record_outcome_noop_when_memory_is_none() -> None:
    record_outcome(None, successful=True, domain="test")


def test_record_outcome_records_success() -> None:
    mem = MagicMock()
    record_outcome(
        mem,
        successful=True,
        domain="unit_test",
        context_dict={"framework": "pytest"},
    )
    mem.add_known_pattern.assert_called_once()
    call_args = mem.add_known_pattern.call_args
    assert "unit_test" in call_args.kwargs["pattern"]
    assert call_args.kwargs["context"]["framework"] == "pytest"
    mem.add_failed_pattern.assert_not_called()


def test_record_outcome_records_failure_with_error() -> None:
    mem = MagicMock()
    record_outcome(
        mem,
        successful=False,
        domain="fix_gen",
        context_dict={"domain": "debugging"},
        error_message="Fix too short",
    )
    mem.add_failed_pattern.assert_called_once()
    call_args = mem.add_failed_pattern.call_args
    assert "Fix too short" in call_args.kwargs["pattern"]
    mem.add_known_pattern.assert_not_called()


def test_record_outcome_no_pattern_on_failure_without_message() -> None:
    mem = MagicMock()
    record_outcome(mem, successful=False, domain="test")
    mem.add_known_pattern.assert_not_called()
    mem.add_failed_pattern.assert_not_called()
