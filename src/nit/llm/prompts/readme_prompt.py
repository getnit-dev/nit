"""README update prompt for LLM-based section generation (section 4.6)."""

from __future__ import annotations

from nit.llm.engine import LLMMessage


def build_readme_update_messages(
    current_readme: str,
    structure_summary: str,
) -> list[LLMMessage]:
    """Build system and user messages for README section updates.

    Args:
        current_readme: Current README content (may be empty).
        structure_summary: Markdown summary of project structure (languages,
            frameworks, packages, scripts).

    Returns:
        Messages to send to the LLM: one system, one user.
    """
    system = """You are a technical writer. Your task is to update a project README to match
the current project structure and conventions.

Rules:
- Output only valid Markdown. No surrounding explanation or code fences unless
  the content is a code block.
- Preserve the tone and style of the existing README when present.
- For new sections, use clear headings (## or ###) and concise bullet points.
- Include: Installation (or Getting started), Project structure (or Repository layout),
  and Usage/Commands (based on available scripts).
- Do not invent scripts or commands that are not listed in the project structure.
- If the current README is empty or minimal, generate a complete but concise README.
- Keep installation steps accurate for the stated languages and package managers."""
    user_parts = [
        "## Current README\n\n",
        current_readme if current_readme.strip() else "(empty or no README)",
        "\n\n## Project structure (detected)\n\n",
        structure_summary,
        "\n\nUpdate the README so that Installation, Project structure, and Usage/Commands "
        "sections reflect the project structure above. Output the full updated "
        "README content only.",
    ]
    user_content = "".join(user_parts)
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user_content),
    ]
