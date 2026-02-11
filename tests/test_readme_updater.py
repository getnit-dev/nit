"""Tests for ReadmeUpdater (section 4.6)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.agents.builders.readme import ReadmeUpdater, _strip_code_fence
from nit.llm.engine import LLMResponse
from nit.models.profile import ProjectProfile

if TYPE_CHECKING:
    from nit.llm.engine import LLMEngine


def _minimal_profile(root: str) -> ProjectProfile:
    """Build a minimal ProjectProfile for tests."""
    return ProjectProfile.from_dict(
        {
            "root": root,
            "primary_language": "python",
            "workspace_tool": "generic",
            "is_monorepo": False,
            "languages": [
                {
                    "language": "python",
                    "file_count": 10,
                    "confidence": 1.0,
                    "extensions": {".py": 10},
                },
            ],
            "frameworks": [
                {
                    "name": "pytest",
                    "language": "python",
                    "category": "unit_test",
                    "confidence": 0.9,
                },
            ],
            "packages": [
                {"name": "myapp", "path": ".", "dependencies": []},
            ],
        }
    )


def test_strip_code_fence_removes_markdown_fence() -> None:
    """_strip_code_fence removes surrounding ``` and returns content between them."""
    text = "```markdown\n# Hello\n```"
    assert _strip_code_fence(text) == "markdown\n# Hello"


def test_strip_code_fence_passthrough_when_no_fence() -> None:
    """_strip_code_fence leaves content unchanged when no fence."""
    text = "# Hello\n\nWorld"
    assert _strip_code_fence(text) == text


@pytest.fixture
def mock_llm_engine() -> LLMEngine:
    """LLM engine that returns fixed README content."""
    engine = MagicMock(spec_set=["generate", "generate_text", "model_name"])
    engine.model_name = "test-model"

    async def _generate(request: object) -> LLMResponse:
        return LLMResponse(
            text="# Updated README\n\nInstall: `pip install foo`",
            model=engine.model_name,
            prompt_tokens=0,
            completion_tokens=0,
        )

    engine.generate = AsyncMock(side_effect=_generate)
    return engine


async def test_readme_updater_update_readme_returns_generated_content(
    tmp_path: Path,
    mock_llm_engine: LLMEngine,
) -> None:
    """ReadmeUpdater.update_readme returns LLM-generated content."""
    (tmp_path / "README.md").write_text("# Old")
    profile = _minimal_profile(str(tmp_path.resolve()))
    updater = ReadmeUpdater(mock_llm_engine)
    content = await updater.update_readme(tmp_path, profile)
    assert "Updated README" in content
    assert "pip install" in content


async def test_readme_updater_raises_when_no_readme(
    tmp_path: Path,
    mock_llm_engine: LLMEngine,
) -> None:
    """ReadmeUpdater.update_readme raises FileNotFoundError when no README."""
    profile = _minimal_profile(str(tmp_path.resolve()))
    updater = ReadmeUpdater(mock_llm_engine)
    with pytest.raises(FileNotFoundError, match="No README"):
        await updater.update_readme(tmp_path, profile, readme_path=None)


async def test_readme_updater_uses_provided_readme_path(
    tmp_path: Path,
    mock_llm_engine: LLMEngine,
) -> None:
    """ReadmeUpdater.update_readme uses explicit readme_path when given."""
    custom = tmp_path / "readme.md"
    custom.write_text("# Custom")
    profile = _minimal_profile(str(tmp_path.resolve()))
    updater = ReadmeUpdater(mock_llm_engine)
    content = await updater.update_readme(tmp_path, profile, readme_path=custom)
    assert "Updated README" in content
