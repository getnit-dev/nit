"""Prompt for polishing changelog entries into human-readable bullets."""

from __future__ import annotations


def build_changelog_polish_prompt(section: str, entries: list[str]) -> str:
    """Build a prompt that asks the LLM to polish raw changelog entries.

    Args:
        section: Keep a Changelog section name (e.g. Added, Fixed).
        entries: List of markdown bullet lines (e.g. "- description").

    Returns:
        User prompt string for the LLM.
    """
    block = "\n".join(entries)
    return f"""Rewrite the following "{section}" changelog entries into clear bullets.
Keep the same meaning but use consistent phrasing and fix any typos or unclear wording.
Output only a markdown list: one line per bullet starting with "- ".
Do not add a title or extra text.

Entries to rewrite:

{block}
"""
