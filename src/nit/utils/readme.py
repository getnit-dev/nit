"""README detection and project structure gathering for auto-update (section 4.6)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nit.models.profile import ProjectProfile

# Preferred README filenames in order (case-sensitive first, then case-insensitive).
README_CANDIDATES = ("README.md", "readme.md", "README", "Readme.md", "README.txt")


@dataclass
class ProjectStructureSummary:
    """Summary of project structure for README generation."""

    languages: list[str] = field(default_factory=list)
    """Detected languages (primary first)."""

    frameworks: list[str] = field(default_factory=list)
    """Detected frameworks (e.g. pytest, vitest)."""

    packages: list[str] = field(default_factory=list)
    """Package names/paths (e.g. root ".", or "packages/foo")."""

    workspace_tool: str = "generic"
    """Workspace tool (turborepo, pnpm, generic, etc.)."""

    scripts: list[str] = field(default_factory=list)
    """CLI/scripts from package.json or pyproject.toml (e.g. "test", "build")."""

    is_monorepo: bool = False
    """Whether the project is a monorepo."""

    def to_markdown(self) -> str:
        """Render a short markdown summary for the LLM."""
        lines: list[str] = []
        if self.languages:
            lines.append(f"- **Languages:** {', '.join(self.languages)}")
        if self.frameworks:
            lines.append(f"- **Frameworks:** {', '.join(self.frameworks)}")
        if self.packages:
            lines.append(f"- **Packages:** {', '.join(self.packages)}")
        lines.append(f"- **Workspace:** {self.workspace_tool}")
        if self.is_monorepo:
            lines.append("- **Monorepo:** yes")
        if self.scripts:
            lines.append(f"- **Scripts/commands:** {', '.join(sorted(self.scripts))}")
        return "\n".join(lines) if lines else "No structure detected."


def find_readme(root: str | Path) -> Path | None:
    """Locate the project README file under *root*.

    Checks common names in order: README.md, readme.md, README, Readme.md, README.txt.
    Returns the first existing path, or None if none found.
    """
    base = Path(root).resolve()
    if not base.is_dir():
        return None
    for name in README_CANDIDATES:
        candidate = base / name
        if candidate.is_file():
            return candidate
    # Case-insensitive fallback: any file named readme.* or README.*
    for p in base.iterdir():
        if p.is_file() and p.name.lower().startswith("readme"):
            return p
    return None


def _scripts_from_package_json(root: Path) -> list[str]:
    """Extract script names from package.json."""
    pkg = root / "package.json"
    if not pkg.is_file():
        return []
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    scripts = data.get("scripts")
    if isinstance(scripts, dict):
        return list(scripts.keys())
    return []


def _scripts_from_pyproject(root: Path) -> list[str]:
    """Extract console script names from pyproject.toml [project.scripts]."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return []
    text = pyproject.read_text(encoding="utf-8")
    in_scripts = False
    names: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[project.scripts]":
            in_scripts = True
            continue
        if in_scripts:
            if stripped.startswith("["):
                break
            if "=" in stripped:
                key_part = stripped.split("=", 1)[0].strip().strip("'\"")
                if key_part and re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", key_part):
                    names.append(key_part)
    return names


def gather_project_structure(root: str | Path, profile: ProjectProfile) -> ProjectStructureSummary:
    """Build a project structure summary from the project root and profile.

    Uses *profile* for languages, frameworks, packages, workspace tool, and
    optionally gathers scripts from package.json / pyproject.toml.
    """
    base = Path(root).resolve()
    languages = [li.language for li in profile.languages]
    frameworks = [fw.name for fw in profile.frameworks]
    packages = [pkg.path if pkg.path != "." else "root" for pkg in profile.packages]
    scripts = _scripts_from_package_json(base) + _scripts_from_pyproject(base)
    # Deduplicate scripts while preserving order
    seen: set[str] = set()
    unique_scripts: list[str] = []
    for s in scripts:
        if s not in seen:
            seen.add(s)
            unique_scripts.append(s)
    return ProjectStructureSummary(
        languages=languages,
        frameworks=frameworks,
        packages=packages,
        workspace_tool=profile.workspace_tool,
        scripts=unique_scripts,
        is_monorepo=profile.is_monorepo,
    )
