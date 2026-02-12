"""Shared memory helpers for injecting GlobalMemory context into LLM prompts.

Provides reusable functions for:
- Retrieving and filtering memory patterns
- Building guidance text from patterns
- Injecting memory context into LLM message lists
- Recording generation outcomes to memory
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nit.llm.engine import LLMMessage

if TYPE_CHECKING:
    from nit.memory.global_memory import GlobalMemory

logger = logging.getLogger(__name__)

# Maximum patterns to include in prompt context
_MAX_PATTERNS = 10


def get_memory_context(
    memory: GlobalMemory | None,
    *,
    known_filter_key: str = "domain",
    failed_filter_key: str = "domain",
    filter_value: str = "",
) -> dict[str, list[str]] | None:
    """Retrieve and filter memory patterns for LLM prompt injection.

    Args:
        memory: GlobalMemory instance, or None if memory is disabled.
        known_filter_key: Context key to filter known patterns on.
        failed_filter_key: Context key to filter failed patterns on.
        filter_value: Value to match against the filter keys (case-insensitive).

    Returns:
        Dictionary with 'known_patterns' and 'failed_patterns' string lists,
        or None if memory is disabled.
    """
    if memory is None:
        return None

    known_patterns = memory.get_known_patterns()
    failed_patterns = memory.get_failed_patterns()

    lv = filter_value.lower()

    relevant_known = [
        p["pattern"]
        for p in known_patterns
        if lv in p.get("context", {}).get(known_filter_key, "").lower()
        or not p.get("context", {}).get(known_filter_key)
    ]

    relevant_failed = [
        f"{p['pattern']}: {p['reason']}"
        for p in failed_patterns
        if lv in p.get("context", {}).get(failed_filter_key, "").lower()
        or not p.get("context", {}).get(failed_filter_key)
    ]

    logger.debug(
        "Retrieved %d known and %d failed patterns from memory",
        len(relevant_known),
        len(relevant_failed),
    )

    return {
        "known_patterns": relevant_known[:_MAX_PATTERNS],
        "failed_patterns": relevant_failed[:_MAX_PATTERNS],
    }


def build_memory_guidance(memory_context: dict[str, list[str]] | None) -> str:
    """Build guidance text from memory patterns.

    Args:
        memory_context: Dictionary with 'known_patterns' and 'failed_patterns',
            or None.

    Returns:
        Guidance text string, or empty string if no patterns.
    """
    if not memory_context:
        return ""

    known = memory_context.get("known_patterns", [])
    failed = memory_context.get("failed_patterns", [])

    if not known and not failed:
        return ""

    parts: list[str] = []

    if known:
        parts.append(
            "**Known successful patterns from previous runs:**\n"
            + "\n".join(f"- {p}" for p in known)
        )

    if failed:
        parts.append(
            "**Patterns to avoid (these failed previously):**\n"
            + "\n".join(f"- {p}" for p in failed)
        )

    return "\n\n".join(parts)


def inject_memory_into_messages(
    messages: list[LLMMessage],
    memory_context: dict[str, list[str]] | None,
) -> None:
    """Append memory guidance to an LLM message list in place.

    Args:
        messages: List of LLMMessage to extend.
        memory_context: Dictionary with pattern lists, or None.
    """
    guidance = build_memory_guidance(memory_context)
    if guidance:
        messages.append(LLMMessage(role="user", content=f"\n\n{guidance}"))
        logger.debug("Injected memory context into prompt")


def record_outcome(
    memory: GlobalMemory | None,
    *,
    successful: bool,
    domain: str = "",
    context_dict: dict[str, Any] | None = None,
    error_message: str = "",
) -> None:
    """Record a generation outcome as known/failed patterns in memory.

    Records successful patterns to learn from and failed patterns to avoid.
    Does NOT update stats — callers should call ``memory.update_stats()``
    directly when they need to track generation counts.

    Args:
        memory: GlobalMemory instance, or None if memory is disabled.
        successful: Whether the generation succeeded.
        domain: Domain label for the pattern (e.g., 'unit_test', 'fix_generation').
        context_dict: Context metadata to attach to the pattern.
        error_message: Error message on failure (truncated in pattern).
    """
    if memory is None:
        return

    ctx = context_dict or {}

    if successful:
        memory.add_known_pattern(
            pattern=f"{domain} completed successfully",
            context=ctx,
        )
    elif error_message:
        memory.add_failed_pattern(
            pattern=error_message[:100],
            reason=error_message[:200],
            context=ctx,
        )
