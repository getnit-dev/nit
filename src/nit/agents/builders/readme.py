"""ReadmeUpdater — generates README section updates via LLM (section 4.6)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nit.llm.engine import GenerationRequest
from nit.llm.prompts.readme_prompt import build_readme_update_messages
from nit.utils.readme import (
    find_readme,
    gather_project_structure,
)

if TYPE_CHECKING:
    from nit.llm.engine import LLMEngine
    from nit.models.profile import ProjectProfile

logger = logging.getLogger(__name__)


def _strip_code_fence(text: str) -> str:
    """Remove leading/trailing markdown code fence if present."""
    stripped = text.strip()
    if stripped.startswith("```") and "```" in stripped[3:]:
        first = stripped.index("```", 3)
        stripped = stripped[3:first].strip()
    elif stripped.startswith("```"):
        stripped = stripped.lstrip("`").strip()
    return stripped


class ReadmeUpdater:
    """Updates README content using project structure and LLM generation.

    Detects README file, gathers project structure from profile,
    builds a prompt, and returns LLM-generated README content.
    """

    def __init__(
        self,
        llm_engine: LLMEngine,
        *,
        max_tokens: int = 8192,
    ) -> None:
        self._engine = llm_engine
        self._max_tokens = max_tokens

    async def update_readme(
        self,
        project_root: str | Path,
        profile: ProjectProfile,
        readme_path: Path | None = None,
    ) -> str:
        """Generate updated README content from project structure and current README.

        Args:
            project_root: Project root directory.
            profile: Detected project profile (languages, frameworks, packages).
            readme_path: Optional path to README file; if None, auto-detect.

        Returns:
            Generated README content (full document).

        Raises:
            FileNotFoundError: If no README file is found when readme_path is None.
            LLMError: If the LLM call fails.
        """
        root = Path(project_root).resolve()
        path = readme_path
        if path is None:
            found = find_readme(root)
            if found is None:
                raise FileNotFoundError(f"No README file found under {root}")
            path = found
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        structure = gather_project_structure(root, profile)
        structure_md = structure.to_markdown()
        messages = build_readme_update_messages(current, structure_md)
        request = GenerationRequest(
            messages=messages,
            max_tokens=self._max_tokens,
            temperature=0.3,
        )
        response = await self._engine.generate(request)
        return _strip_code_fence(response.text.strip())
