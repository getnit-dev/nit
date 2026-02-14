"""ProjectProfile — unified data model for a fully-detected project."""

from __future__ import annotations

from dataclasses import dataclass, field

from nit.agents.detectors.dependency import (
    DeclaredDependency,
    DependencyProfile,
    DependencySource,
    InternalDependency,
)
from nit.agents.detectors.infra import (
    CIConfig,
    CIProvider,
    DockerConfig,
    InfraProfile,
    ScriptInfo,
)
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

    llm_usage_count: int = 0
    """Number of LLM/AI integration usages detected in the project."""

    llm_providers: list[str] = field(default_factory=list)
    """LLM providers detected (e.g. ``["openai", "anthropic"]``)."""

    infra_profile: InfraProfile | None = None
    """Full infrastructure detection result, or ``None`` if not yet detected."""

    dependency_profile: DependencyProfile | None = None
    """Full dependency detection result, or ``None`` if not yet detected."""

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
        result: dict[str, object] = {
            "root": self.root,
            "primary_language": self.primary_language,
            "workspace_tool": self.workspace_tool,
            "is_monorepo": self.is_monorepo,
            "llm_usage_count": self.llm_usage_count,
            "llm_providers": self.llm_providers,
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

        if self.infra_profile is not None:
            result["infra"] = {
                "root": self.infra_profile.root,
                "ci_configs": [
                    {
                        "provider": c.provider.value,
                        "file_path": c.file_path,
                        "test_commands": c.test_commands,
                    }
                    for c in self.infra_profile.ci_configs
                ],
                "docker": {
                    "has_dockerfile": self.infra_profile.docker.has_dockerfile,
                    "has_compose": self.infra_profile.docker.has_compose,
                    "has_dockerignore": self.infra_profile.docker.has_dockerignore,
                    "dockerfile_paths": self.infra_profile.docker.dockerfile_paths,
                    "compose_paths": self.infra_profile.docker.compose_paths,
                },
                "makefiles": self.infra_profile.makefiles,
                "scripts": [
                    {
                        "file_path": s.file_path,
                        "script_type": s.script_type,
                        "name": s.name,
                    }
                    for s in self.infra_profile.scripts
                ],
                "test_commands": self.infra_profile.test_commands,
            }

        if self.dependency_profile is not None:
            result["dependencies"] = {
                "root": self.dependency_profile.root,
                "declared_deps": [
                    {
                        "name": d.name,
                        "version_spec": d.version_spec,
                        "source": d.source.value,
                        "is_dev": d.is_dev,
                        "package_path": d.package_path,
                    }
                    for d in self.dependency_profile.declared_deps
                ],
                "internal_deps": [
                    {
                        "from_package": d.from_package,
                        "to_package": d.to_package,
                        "dependency_type": d.dependency_type,
                    }
                    for d in self.dependency_profile.internal_deps
                ],
                "lock_files": self.dependency_profile.lock_files,
                "manifest_files": self.dependency_profile.manifest_files,
            }

        return result

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

        llm_providers_raw = data.get("llm_providers", [])
        llm_providers = (
            [str(p) for p in llm_providers_raw] if isinstance(llm_providers_raw, list) else []
        )

        llm_count_raw = data.get("llm_usage_count", 0)
        llm_usage_count = int(llm_count_raw) if isinstance(llm_count_raw, (int, float)) else 0

        infra_profile = _reconstruct_infra_profile(data.get("infra"))
        dependency_profile = _reconstruct_dependency_profile(data.get("dependencies"))

        return cls(
            root=str(data.get("root", "")),
            languages=languages,
            frameworks=frameworks,
            packages=packages,
            workspace_tool=str(data.get("workspace_tool", "generic")),
            llm_usage_count=llm_usage_count,
            llm_providers=llm_providers,
            infra_profile=infra_profile,
            dependency_profile=dependency_profile,
        )


# ── Reconstruction helpers (late imports to avoid circular deps) ──


def _reconstruct_infra_profile(raw: object) -> InfraProfile | None:
    """Reconstruct an ``InfraProfile`` from serialised dict, or ``None``."""
    if not isinstance(raw, dict):
        return None

    ci_configs_raw = raw.get("ci_configs", [])
    ci_configs: list[CIConfig] = []
    if isinstance(ci_configs_raw, list):
        ci_configs = [
            CIConfig(
                provider=CIProvider(str(c["provider"])),
                file_path=str(c["file_path"]),
                test_commands=list(c.get("test_commands", [])),
            )
            for c in ci_configs_raw
            if isinstance(c, dict)
        ]

    docker_raw = raw.get("docker", {})
    docker = DockerConfig()
    if isinstance(docker_raw, dict):
        docker = DockerConfig(
            has_dockerfile=bool(docker_raw.get("has_dockerfile")),
            has_compose=bool(docker_raw.get("has_compose")),
            has_dockerignore=bool(docker_raw.get("has_dockerignore")),
            dockerfile_paths=list(docker_raw.get("dockerfile_paths", [])),
            compose_paths=list(docker_raw.get("compose_paths", [])),
        )

    makefiles_raw = raw.get("makefiles", [])
    makefiles = list(makefiles_raw) if isinstance(makefiles_raw, list) else []

    scripts_raw = raw.get("scripts", [])
    scripts: list[ScriptInfo] = []
    if isinstance(scripts_raw, list):
        scripts = [
            ScriptInfo(
                file_path=str(s["file_path"]),
                script_type=str(s["script_type"]),
                name=str(s["name"]),
            )
            for s in scripts_raw
            if isinstance(s, dict)
        ]

    test_commands_raw = raw.get("test_commands", [])
    test_commands = list(test_commands_raw) if isinstance(test_commands_raw, list) else []

    return InfraProfile(
        root=str(raw.get("root", "")),
        ci_configs=ci_configs,
        docker=docker,
        makefiles=makefiles,
        scripts=scripts,
        test_commands=test_commands,
    )


def _reconstruct_dependency_profile(raw: object) -> DependencyProfile | None:
    """Reconstruct a ``DependencyProfile`` from serialised dict, or ``None``."""
    if not isinstance(raw, dict):
        return None

    declared_raw = raw.get("declared_deps", [])
    declared_deps: list[DeclaredDependency] = []
    if isinstance(declared_raw, list):
        declared_deps = [
            DeclaredDependency(
                name=str(d["name"]),
                version_spec=str(d.get("version_spec", "")),
                source=DependencySource(str(d.get("source", "manifest"))),
                is_dev=bool(d.get("is_dev")),
                package_path=str(d.get("package_path", ".")),
            )
            for d in declared_raw
            if isinstance(d, dict)
        ]

    internal_raw = raw.get("internal_deps", [])
    internal_deps: list[InternalDependency] = []
    if isinstance(internal_raw, list):
        internal_deps = [
            InternalDependency(
                from_package=str(d["from_package"]),
                to_package=str(d["to_package"]),
                dependency_type=str(d.get("dependency_type", "runtime")),
            )
            for d in internal_raw
            if isinstance(d, dict)
        ]

    lock_files_raw = raw.get("lock_files", [])
    lock_files = list(lock_files_raw) if isinstance(lock_files_raw, list) else []

    manifest_files_raw = raw.get("manifest_files", [])
    manifest_files = list(manifest_files_raw) if isinstance(manifest_files_raw, list) else []

    return DependencyProfile(
        root=str(raw.get("root", "")),
        declared_deps=declared_deps,
        internal_deps=internal_deps,
        lock_files=lock_files,
        manifest_files=manifest_files,
    )
