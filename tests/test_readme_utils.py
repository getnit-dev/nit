"""Tests for README detection and project structure (section 4.6) — no builders import."""

from __future__ import annotations

import json
from pathlib import Path

from nit.llm.prompts.readme_prompt import build_readme_update_messages
from nit.models.profile import ProjectProfile
from nit.utils.readme import (
    ProjectStructureSummary,
    find_readme,
    gather_project_structure,
)


def test_find_readme_returns_none_when_no_readme(tmp_path: Path) -> None:
    """When no README file exists, find_readme returns None."""
    assert find_readme(tmp_path) is None


def test_find_readme_finds_readme_md(tmp_path: Path) -> None:
    """find_readme returns path to README.md when present."""
    readme = tmp_path / "README.md"
    readme.write_text("# Project")
    assert find_readme(tmp_path) == readme


def test_find_readme_prefers_readme_md(tmp_path: Path) -> None:
    """README.md is preferred over readme.md when both exist."""
    (tmp_path / "readme.md").write_text("lower")
    preferred = tmp_path / "README.md"
    preferred.write_text("upper")
    assert find_readme(tmp_path) == preferred


def test_find_readme_finds_readme_no_extension(tmp_path: Path) -> None:
    """find_readme finds README (no extension) when no .md version exists."""
    (tmp_path / "README").write_text("# Project")
    assert find_readme(tmp_path) == tmp_path / "README"


def test_find_readme_returns_none_for_file_root(tmp_path: Path) -> None:
    """When root is a file, find_readme returns None."""
    f = tmp_path / "file.txt"
    f.write_text("x")
    assert find_readme(f) is None


def test_project_structure_summary_to_markdown() -> None:
    """to_markdown includes languages, frameworks, packages, scripts."""
    s = ProjectStructureSummary(
        languages=["Python", "TypeScript"],
        frameworks=["pytest", "vitest"],
        packages=["root", "packages/foo"],
        workspace_tool="pnpm",
        scripts=["test", "build"],
        is_monorepo=True,
    )
    md = s.to_markdown()
    assert "Python" in md
    assert "TypeScript" in md
    assert "pytest" in md
    assert "vitest" in md
    assert "root" in md
    assert "packages/foo" in md
    assert "pnpm" in md
    assert "test" in md
    assert "build" in md
    assert "Monorepo" in md or "yes" in md


def test_project_structure_summary_empty() -> None:
    """Empty summary produces minimal markdown."""
    s = ProjectStructureSummary(workspace_tool="generic")
    md = s.to_markdown()
    assert "generic" in md


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


def test_gather_project_structure_uses_profile(tmp_path: Path) -> None:
    """gather_project_structure returns summary from profile."""
    root = str(tmp_path.resolve())
    profile = _minimal_profile(root)
    summary = gather_project_structure(tmp_path, profile)
    assert "python" in summary.languages
    assert "pytest" in summary.frameworks
    assert summary.workspace_tool == "generic"
    assert summary.packages


def test_gather_project_structure_collects_package_json_scripts(tmp_path: Path) -> None:
    """Scripts from package.json are included in summary."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "scripts": {"test": "vitest", "build": "tsup"}}),
        encoding="utf-8",
    )
    root = str(tmp_path.resolve())
    profile = _minimal_profile(root)
    summary = gather_project_structure(tmp_path, profile)
    assert "test" in summary.scripts
    assert "build" in summary.scripts


def test_gather_project_structure_collects_pyproject_scripts(tmp_path: Path) -> None:
    """Console scripts from pyproject.toml [project.scripts] are included."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "foo"\n\n[project.scripts]\nnit = "nit.cli:cli"\nother = "other:main"\n',
        encoding="utf-8",
    )
    root = str(tmp_path.resolve())
    profile = _minimal_profile(root)
    summary = gather_project_structure(tmp_path, profile)
    assert "nit" in summary.scripts
    assert "other" in summary.scripts


def test_build_readme_update_messages_returns_two_messages() -> None:
    """Prompt builder returns system and user messages."""
    messages = build_readme_update_messages("", "Python, pytest")
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"


def test_build_readme_update_messages_includes_current_and_structure() -> None:
    """User message contains current README and structure summary."""
    current = "# Old Title"
    structure = "- **Languages:** Python"
    messages = build_readme_update_messages(current, structure)
    user_content = messages[1].content
    assert "Old Title" in user_content
    assert "Python" in user_content
    assert "Project structure" in user_content or "structure" in user_content
