"""ProjectProfile — unified data model for a fully-detected project."""

from __future__ import annotations

from dataclasses import dataclass, field

from nit.agents.detectors.signals import DetectedFramework, FrameworkCategory
from nit.agents.detectors.stack import LanguageInfo
from nit.agents.detectors.workspace import PackageInfo


@dataclass
class ProjectProfile:
    """Aggregated detection result for an entire project.

    Combines language detection (``LanguageProfile``), framework detection
    (``FrameworkProfile``), and workspace detection (``WorkspaceProfile``)
    into a single, serialisable snapshot.
    """

    root: str
    """Absolute path to the project root."""

    languages: list[LanguageInfo] = field(default_factory=list)
    """Detected languages, sorted by file count descending."""

    frameworks: list[DetectedFramework] = field(default_factory=list)
    """Detected test / doc frameworks."""

    packages: list[PackageInfo] = field(default_factory=list)
    """Packages in the workspace (single entry for non-monorepos)."""

    workspace_tool: str = "generic"
    """Name of the workspace tool (e.g. ``"turborepo"``, ``"pnpm"``, ``"generic"``)."""

    # ── Convenience accessors ──────────────────────────────────────

    @property
    def primary_language(self) -> str | None:
        """Language with the highest file count, or ``None`` if empty."""
        if not self.languages:
            return None
        return self.languages[0].language

    @property
    def is_monorepo(self) -> bool:
        """``True`` when the workspace contains more than one package."""
        return len(self.packages) > 1

    def frameworks_by_category(self, category: FrameworkCategory) -> list[DetectedFramework]:
        """Return frameworks matching *category*, sorted by confidence."""
        return sorted(
            [f for f in self.frameworks if f.category == category],
            key=lambda f: -f.confidence,
        )

    # ── Serialisation ──────────────────────────────────────────────

    def to_dict(self) -> dict[str, object]:
        """Serialise the profile to a JSON-compatible dict."""
        return {
            "root": self.root,
            "primary_language": self.primary_language,
            "workspace_tool": self.workspace_tool,
            "is_monorepo": self.is_monorepo,
            "languages": [
                {
                    "language": li.language,
                    "file_count": li.file_count,
                    "confidence": li.confidence,
                    "extensions": li.extensions,
                }
                for li in self.languages
            ],
            "frameworks": [
                {
                    "name": fw.name,
                    "language": fw.language,
                    "category": fw.category.value,
                    "confidence": fw.confidence,
                }
                for fw in self.frameworks
            ],
            "packages": [
                {
                    "name": pkg.name,
                    "path": pkg.path,
                    "dependencies": pkg.dependencies,
                }
                for pkg in self.packages
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ProjectProfile:
        """Reconstruct a ``ProjectProfile`` from a dict produced by ``to_dict``."""
        languages_raw = data.get("languages")
        languages: list[LanguageInfo] = []
        if isinstance(languages_raw, list):
            languages = [
                LanguageInfo(
                    language=str(li["language"]),
                    file_count=int(li["file_count"]),
                    confidence=float(li["confidence"]),
                    extensions={str(k): int(v) for k, v in li["extensions"].items()},
                )
                for li in languages_raw
                if isinstance(li, dict)
            ]

        frameworks_raw = data.get("frameworks")
        frameworks: list[DetectedFramework] = []
        if isinstance(frameworks_raw, list):
            frameworks = [
                DetectedFramework(
                    name=str(fw["name"]),
                    language=str(fw["language"]),
                    category=FrameworkCategory(str(fw["category"])),
                    confidence=float(fw["confidence"]),
                )
                for fw in frameworks_raw
                if isinstance(fw, dict)
            ]

        packages_raw = data.get("packages")
        packages: list[PackageInfo] = []
        if isinstance(packages_raw, list):
            packages = [
                PackageInfo(
                    name=str(pkg["name"]),
                    path=str(pkg["path"]),
                    dependencies=list(pkg.get("dependencies", [])),
                )
                for pkg in packages_raw
                if isinstance(pkg, dict)
            ]

        return cls(
            root=str(data.get("root", "")),
            languages=languages,
            frameworks=frameworks,
            packages=packages,
            workspace_tool=str(data.get("workspace_tool", "generic")),
        )
