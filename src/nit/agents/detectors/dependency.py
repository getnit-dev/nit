"""Dependency detector — parse manifests, lock files, and map internal deps."""

from __future__ import annotations

import contextlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus

if TYPE_CHECKING:
    from nit.agents.detectors.workspace import WorkspaceProfile

logger = logging.getLogger(__name__)

# Minimum number of parts in a go.mod require line ("module version").
_MIN_REQUIRE_PARTS = 2

# Expected part counts for Gradle dependency strings ("group:artifact:version").
_GRADLE_GROUP_ARTIFACT_PARTS = 2
_GRADLE_VERSION_PARTS = 3

# Default directories to skip during scanning (consistent with other detectors).
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".nit",
        ".next",
        "target",
        "vendor",
    }
)


# ── Data models ────────────────────────────────────────────────────


class DependencySource(Enum):
    """Where a dependency was detected."""

    MANIFEST = "manifest"
    LOCK_FILE = "lock_file"


@dataclass
class DeclaredDependency:
    """A single dependency declared in a manifest file."""

    name: str
    version_spec: str = ""
    """Version specifier (e.g. ``"^1.0.0"``, ``">=3.8"``)."""
    source: DependencySource = DependencySource.MANIFEST
    is_dev: bool = False
    """``True`` for dev/test dependencies."""
    package_path: str = "."
    """Relative path to the package declaring this dependency."""


@dataclass
class InternalDependency:
    """A dependency link between two packages within the same workspace."""

    from_package: str
    to_package: str
    dependency_type: str = "runtime"
    """One of ``"runtime"``, ``"dev"``, ``"peer"``."""


@dataclass
class DependencyProfile:
    """Full dependency detection result for a project."""

    root: str
    """Absolute path to the project root."""
    declared_deps: list[DeclaredDependency] = field(default_factory=list)
    """All declared external dependencies across all packages."""
    internal_deps: list[InternalDependency] = field(default_factory=list)
    """Cross-package dependency links within the workspace."""
    lock_files: list[str] = field(default_factory=list)
    """Relative paths to detected lock files."""
    manifest_files: list[str] = field(default_factory=list)
    """Relative paths to detected manifest files."""

    @property
    def external_dep_count(self) -> int:
        """Number of declared external dependencies."""
        return len(self.declared_deps)

    @property
    def internal_dep_count(self) -> int:
        """Number of internal cross-package dependencies."""
        return len(self.internal_deps)

    def deps_for_package(self, package_path: str) -> list[DeclaredDependency]:
        """Return dependencies declared in a specific package."""
        return [d for d in self.declared_deps if d.package_path == package_path]


# ── Lock file detection ────────────────────────────────────────────

_LOCK_FILE_NAMES: list[str] = [
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "go.sum",
    "Cargo.lock",
    "gradle.lockfile",
    "composer.lock",
]


def _detect_lock_files(root: Path) -> list[str]:
    """Detect which lock files exist at the project root."""
    return [name for name in _LOCK_FILE_NAMES if (root / name).is_file()]


# ── JSON / text helpers ────────────────────────────────────────────


def _read_json_safe(path: Path) -> dict[str, object]:
    """Read and parse a JSON file, returning ``{}`` on any error."""
    with contextlib.suppress(OSError, json.JSONDecodeError):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    return {}


def _read_text_safe(path: Path) -> str | None:
    """Read a text file, returning ``None`` on any error."""
    with contextlib.suppress(OSError):
        return path.read_text(encoding="utf-8")
    return None


# ── Manifest parsers ──────────────────────────────────────────────


def _parse_package_json(
    root: Path, package_path: str
) -> tuple[str | None, list[DeclaredDependency]]:
    """Parse ``package.json`` for declared dependencies.

    Returns (manifest_rel_path_or_None, deps).
    """
    pkg_dir = root / package_path
    pj_path = pkg_dir / "package.json"
    if not pj_path.is_file():
        return None, []

    pj = _read_json_safe(pj_path)
    if not pj:
        return None, []

    rel = str(pj_path.relative_to(root))
    deps: list[DeclaredDependency] = []

    for section, is_dev in (
        ("dependencies", False),
        ("devDependencies", True),
        ("peerDependencies", False),
    ):
        section_data = pj.get(section)
        if isinstance(section_data, dict):
            deps.extend(
                DeclaredDependency(
                    name=str(name),
                    version_spec=str(ver),
                    is_dev=is_dev,
                    package_path=package_path,
                )
                for name, ver in section_data.items()
            )

    return rel, deps


def _parse_pyproject_toml(
    root: Path, package_path: str
) -> tuple[str | None, list[DeclaredDependency]]:
    """Parse ``pyproject.toml`` for declared dependencies."""
    pkg_dir = root / package_path
    pp_path = pkg_dir / "pyproject.toml"
    if not pp_path.is_file():
        return None, []

    text = _read_text_safe(pp_path)
    if text is None:
        return None, []

    rel = str(pp_path.relative_to(root))
    deps: list[DeclaredDependency] = []

    # Match dependencies = ["dep1", "dep2>=1.0"]
    dep_m = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if dep_m:
        for name_m in re.finditer(r"""['"]([^'"<>=!~;\[]+)""", dep_m.group(1)):
            dep_name = name_m.group(1).strip()
            if dep_name:
                deps.append(DeclaredDependency(name=dep_name, package_path=package_path))

    # Match optional-dependencies sections (dev deps)
    opt_m = re.search(
        r"\[(?:project\.)?optional-dependencies\](.*?)(?:\n\[|\Z)",
        text,
        re.DOTALL,
    )
    if opt_m:
        for name_m in re.finditer(r"""['"]([^'"<>=!~;\[]+)""", opt_m.group(1)):
            dep_name = name_m.group(1).strip()
            if dep_name:
                deps.append(
                    DeclaredDependency(name=dep_name, is_dev=True, package_path=package_path)
                )

    return rel, deps


def _parse_requirements_txt(
    root: Path, package_path: str
) -> tuple[str | None, list[DeclaredDependency]]:
    """Parse ``requirements.txt`` for declared dependencies."""
    pkg_dir = root / package_path
    req_path = pkg_dir / "requirements.txt"
    if not req_path.is_file():
        return None, []

    text = _read_text_safe(req_path)
    if text is None:
        return None, []

    rel = str(req_path.relative_to(root))
    deps: list[DeclaredDependency] = []
    for line in text.splitlines():
        stripped = line.strip()
        # Skip comments, blank lines, options, and -r includes
        if not stripped or stripped.startswith(("#", "-")):
            continue
        # Extract package name (before any version specifier)
        m = re.match(r"([A-Za-z0-9_][A-Za-z0-9._-]*)", stripped)
        if m:
            name = m.group(1)
            # Extract version spec
            version_spec = stripped[len(name) :].strip()
            deps.append(
                DeclaredDependency(
                    name=name,
                    version_spec=version_spec,
                    package_path=package_path,
                )
            )

    return rel, deps


def _parse_go_mod(root: Path, package_path: str) -> tuple[str | None, list[DeclaredDependency]]:
    """Parse ``go.mod`` for declared dependencies."""
    pkg_dir = root / package_path
    go_mod_path = pkg_dir / "go.mod"
    if not go_mod_path.is_file():
        return None, []

    text = _read_text_safe(go_mod_path)
    if text is None:
        return None, []

    rel = str(go_mod_path.relative_to(root))
    deps: list[DeclaredDependency] = []

    # Match require block
    require_m = re.search(r"require\s*\((.*?)\)", text, re.DOTALL)
    if require_m:
        deps.extend(
            DeclaredDependency(
                name=parts[0],
                version_spec=parts[1],
                package_path=package_path,
            )
            for line in require_m.group(1).splitlines()
            if (stripped := line.strip())
            and not stripped.startswith("//")
            and len(parts := stripped.split()) >= _MIN_REQUIRE_PARTS
        )

    # Match single-line require directives
    deps.extend(
        DeclaredDependency(
            name=m.group(1),
            version_spec=m.group(2),
            package_path=package_path,
        )
        for m in re.finditer(r"^require\s+(\S+)\s+(\S+)", text, re.MULTILINE)
    )

    return rel, deps


def _parse_cargo_toml(root: Path, package_path: str) -> tuple[str | None, list[DeclaredDependency]]:
    """Parse ``Cargo.toml`` for declared dependencies."""
    pkg_dir = root / package_path
    cargo_path = pkg_dir / "Cargo.toml"
    if not cargo_path.is_file():
        return None, []

    text = _read_text_safe(cargo_path)
    if text is None:
        return None, []

    rel = str(cargo_path.relative_to(root))
    deps: list[DeclaredDependency] = []

    _parse_cargo_section(text, "dependencies", is_dev=False, package_path=package_path, out=deps)
    _parse_cargo_section(text, "dev-dependencies", is_dev=True, package_path=package_path, out=deps)

    return rel, deps


def _parse_cargo_section(
    text: str,
    section_name: str,
    *,
    is_dev: bool,
    package_path: str,
    out: list[DeclaredDependency],
) -> None:
    """Parse a ``[dependencies]`` or ``[dev-dependencies]`` section from Cargo.toml."""
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_section = stripped == f"[{section_name}]"
            continue
        if in_section:
            m = re.match(r'(\w[\w-]*)\s*=\s*"([^"]*)"', stripped)
            if m:
                out.append(
                    DeclaredDependency(
                        name=m.group(1),
                        version_spec=m.group(2),
                        is_dev=is_dev,
                        package_path=package_path,
                    )
                )
                continue
            # Table-style: serde = { version = "1.0", features = [...] }
            m_table = re.match(r"(\w[\w-]*)\s*=\s*\{", stripped)
            if m_table:
                out.append(
                    DeclaredDependency(
                        name=m_table.group(1),
                        is_dev=is_dev,
                        package_path=package_path,
                    )
                )


def _parse_build_gradle(
    root: Path, package_path: str
) -> tuple[str | None, list[DeclaredDependency]]:
    """Parse ``build.gradle`` or ``build.gradle.kts`` for declared dependencies."""
    pkg_dir = root / package_path
    for name in ("build.gradle.kts", "build.gradle"):
        gradle_path = pkg_dir / name
        if gradle_path.is_file():
            text = _read_text_safe(gradle_path)
            if text is None:
                continue

            rel = str(gradle_path.relative_to(root))
            deps: list[DeclaredDependency] = []

            for m in re.finditer(
                r"(test)?[Ii]mplementation\s*\(?['\"]([^'\"]+)['\"]",
                text,
            ):
                is_dev = m.group(1) is not None
                dep_str = m.group(2)
                parts = dep_str.split(":")
                has_group_and_artifact = len(parts) >= _GRADLE_GROUP_ARTIFACT_PARTS
                dep_name = ":".join(parts[:2]) if has_group_and_artifact else dep_str
                version_spec = parts[2] if len(parts) >= _GRADLE_VERSION_PARTS else ""
                deps.append(
                    DeclaredDependency(
                        name=dep_name,
                        version_spec=version_spec,
                        is_dev=is_dev,
                        package_path=package_path,
                    )
                )

            return rel, deps
    return None, []


def _parse_pom_xml(root: Path, package_path: str) -> tuple[str | None, list[DeclaredDependency]]:
    """Parse ``pom.xml`` for declared dependencies."""
    pkg_dir = root / package_path
    pom_path = pkg_dir / "pom.xml"
    if not pom_path.is_file():
        return None, []

    text = _read_text_safe(pom_path)
    if text is None:
        return None, []

    rel = str(pom_path.relative_to(root))
    deps: list[DeclaredDependency] = []

    for m in re.finditer(
        r"<dependency>\s*"
        r"<groupId>([^<]+)</groupId>\s*"
        r"<artifactId>([^<]+)</artifactId>"
        r"(?:\s*<version>([^<]*)</version>)?"
        r"(?:\s*<scope>([^<]*)</scope>)?",
        text,
        re.DOTALL,
    ):
        group_id = m.group(1)
        artifact_id = m.group(2)
        version = m.group(3) or ""
        scope = m.group(4) or ""
        deps.append(
            DeclaredDependency(
                name=f"{group_id}:{artifact_id}",
                version_spec=version,
                is_dev=scope == "test",
                package_path=package_path,
            )
        )

    return rel, deps


def _parse_composer_json(
    root: Path, package_path: str
) -> tuple[str | None, list[DeclaredDependency]]:
    """Parse ``composer.json`` for declared dependencies."""
    pkg_dir = root / package_path
    composer_path = pkg_dir / "composer.json"
    if not composer_path.is_file():
        return None, []

    data = _read_json_safe(composer_path)
    if not data:
        return None, []

    rel = str(composer_path.relative_to(root))
    deps: list[DeclaredDependency] = []

    for section, is_dev in (("require", False), ("require-dev", True)):
        section_data = data.get(section)
        if isinstance(section_data, dict):
            deps.extend(
                DeclaredDependency(
                    name=str(name),
                    version_spec=str(ver),
                    is_dev=is_dev,
                    package_path=package_path,
                )
                for name, ver in section_data.items()
            )

    return rel, deps


# ── Manifest detection orchestrator ────────────────────────────────


def _detect_and_parse_manifests(
    root: Path, package_paths: list[str]
) -> tuple[list[str], list[DeclaredDependency]]:
    """Detect and parse all manifest files across all package paths.

    Returns (manifest_file_paths, all_dependencies).
    """
    parsers = [
        _parse_package_json,
        _parse_pyproject_toml,
        _parse_requirements_txt,
        _parse_go_mod,
        _parse_cargo_toml,
        _parse_build_gradle,
        _parse_pom_xml,
        _parse_composer_json,
    ]

    manifest_files: list[str] = []
    all_deps: list[DeclaredDependency] = []

    for pkg_path in package_paths:
        for parser in parsers:
            rel, deps = parser(root, pkg_path)
            if rel is not None:
                if rel not in manifest_files:
                    manifest_files.append(rel)
                all_deps.extend(deps)

    return manifest_files, all_deps


# ── Internal dependency mapping ────────────────────────────────────


def _map_internal_deps(
    root: Path,
    package_paths: list[str],
    package_names: set[str],
) -> list[InternalDependency]:
    """Cross-reference declared dependencies against workspace package names."""
    internal_deps: list[InternalDependency] = []

    for pkg_path in package_paths:
        pkg_dir = root / pkg_path
        pkg_name = _package_name_for_path(pkg_dir)

        # Check package.json
        _collect_js_internal(pkg_dir, pkg_name, package_names, internal_deps)
        # Check Cargo.toml
        _collect_cargo_internal(pkg_dir, pkg_name, package_names, internal_deps)
        # Check go.mod
        _collect_go_internal(pkg_dir, pkg_name, package_names, internal_deps)
        # Check pyproject.toml
        _collect_python_internal(pkg_dir, pkg_name, package_names, internal_deps)

    return internal_deps


def _package_name_for_path(pkg_dir: Path) -> str:
    """Derive a package name from its directory (simplified)."""
    pj = _read_json_safe(pkg_dir / "package.json")
    name = pj.get("name")
    if isinstance(name, str) and name:
        return name
    return pkg_dir.name


def _collect_js_internal(
    pkg_dir: Path,
    pkg_name: str,
    known_names: set[str],
    out: list[InternalDependency],
) -> None:
    """Scan ``package.json`` for internal dependencies."""
    pj = _read_json_safe(pkg_dir / "package.json")
    dep_type_map: list[tuple[str, str]] = [
        ("dependencies", "runtime"),
        ("devDependencies", "dev"),
        ("peerDependencies", "peer"),
    ]
    for section, dep_type in dep_type_map:
        deps = pj.get(section)
        if isinstance(deps, dict):
            out.extend(
                InternalDependency(
                    from_package=pkg_name,
                    to_package=str(dep_name),
                    dependency_type=dep_type,
                )
                for dep_name in deps
                if str(dep_name) in known_names and str(dep_name) != pkg_name
            )


def _collect_cargo_internal(
    pkg_dir: Path,
    pkg_name: str,
    known_names: set[str],
    out: list[InternalDependency],
) -> None:
    """Scan ``Cargo.toml`` for internal dependencies."""
    cargo_toml = pkg_dir / "Cargo.toml"
    if not cargo_toml.is_file():
        return

    text = _read_text_safe(cargo_toml)
    if text is None:
        return

    in_section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            if "dev-dependencies" in stripped.lower():
                in_section = "dev"
            elif "dependencies" in stripped.lower():
                in_section = "runtime"
            else:
                in_section = ""
            continue
        if in_section:
            m = re.match(r"(\w[\w-]*)\s*=", stripped)
            if m:
                dep_name = m.group(1)
                if dep_name in known_names and dep_name != pkg_name:
                    out.append(
                        InternalDependency(
                            from_package=pkg_name,
                            to_package=dep_name,
                            dependency_type=in_section,
                        )
                    )


def _collect_go_internal(
    pkg_dir: Path,
    pkg_name: str,
    known_names: set[str],
    out: list[InternalDependency],
) -> None:
    """Scan ``go.mod`` for internal module dependencies."""
    go_mod = pkg_dir / "go.mod"
    if not go_mod.is_file():
        return

    text = _read_text_safe(go_mod)
    if text is None:
        return

    require_m = re.search(r"require\s*\((.*?)\)", text, re.DOTALL)
    if require_m:
        for line in require_m.group(1).splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("//"):
                parts = stripped.split()
                if parts and parts[0] in known_names and parts[0] != pkg_name:
                    out.append(
                        InternalDependency(
                            from_package=pkg_name,
                            to_package=parts[0],
                        )
                    )


def _collect_python_internal(
    pkg_dir: Path,
    pkg_name: str,
    known_names: set[str],
    out: list[InternalDependency],
) -> None:
    """Scan ``pyproject.toml`` for internal dependencies."""
    pyproject = pkg_dir / "pyproject.toml"
    if not pyproject.is_file():
        return

    text = _read_text_safe(pyproject)
    if text is None:
        return

    dep_m = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if dep_m:
        for name_m in re.finditer(r"""['"]([^'"<>=!~;\[]+)""", dep_m.group(1)):
            dep_name = name_m.group(1).strip()
            if dep_name in known_names and dep_name != pkg_name:
                out.append(
                    InternalDependency(
                        from_package=pkg_name,
                        to_package=dep_name,
                    )
                )


# ── Orchestrator ───────────────────────────────────────────────────


def detect_dependencies(
    root: str | Path,
    *,
    workspace: WorkspaceProfile | None = None,
    skip_dirs: frozenset[str] | None = None,
) -> DependencyProfile:
    """Scan *root* for dependency manifests and lock files.

    Parameters
    ----------
    root:
        Project directory to scan.
    workspace:
        Optional workspace profile for monorepo-aware scanning.
        When provided, manifests in each package directory are scanned.
    skip_dirs:
        Directories to skip.  Defaults to the built-in skip set.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise ValueError(f"Not a directory: {root_path}")

    _ = skip_dirs  # reserved for future filtering

    # Determine which package paths to scan
    if workspace is not None and workspace.packages:
        package_paths = [pkg.path for pkg in workspace.packages]
        package_names = {pkg.name for pkg in workspace.packages}
    else:
        package_paths = ["."]
        package_names = set()

    lock_files = _detect_lock_files(root_path)
    manifest_files, declared_deps = _detect_and_parse_manifests(root_path, package_paths)

    # Map internal deps only when workspace has multiple packages
    internal_deps: list[InternalDependency] = []
    if len(package_names) > 1:
        internal_deps = _map_internal_deps(root_path, package_paths, package_names)

    return DependencyProfile(
        root=str(root_path),
        declared_deps=declared_deps,
        internal_deps=internal_deps,
        lock_files=lock_files,
        manifest_files=manifest_files,
    )


# ── Agent wrapper ───────────────────────────────────────────────────


class DependencyDetector(BaseAgent):
    """Agent that parses dependency manifests, lock files, and maps internal deps."""

    @property
    def name(self) -> str:
        return "dependency-detector"

    @property
    def description(self) -> str:
        return "Parse dependency manifests, lock files, and map internal dependencies."

    async def run(self, task: TaskInput) -> TaskOutput:
        """Run dependency detection on *task.target*.

        Optional context keys:

        - ``"skip_dirs"``: Override default skip dirs.
        """
        target = Path(task.target)
        skip_raw = task.context.get("skip_dirs")
        skip_dirs = frozenset(skip_raw) if skip_raw is not None else None

        try:
            profile = detect_dependencies(target, skip_dirs=skip_dirs)
        except ValueError as exc:
            return TaskOutput(status=TaskStatus.FAILED, errors=[str(exc)])

        return TaskOutput(
            status=TaskStatus.COMPLETED,
            result={
                "root": profile.root,
                "external_dep_count": profile.external_dep_count,
                "internal_dep_count": profile.internal_dep_count,
                "lock_files": profile.lock_files,
                "manifest_files": profile.manifest_files,
                "declared_deps": [
                    {
                        "name": d.name,
                        "version_spec": d.version_spec,
                        "source": d.source.value,
                        "is_dev": d.is_dev,
                        "package_path": d.package_path,
                    }
                    for d in profile.declared_deps
                ],
                "internal_deps": [
                    {
                        "from_package": d.from_package,
                        "to_package": d.to_package,
                        "dependency_type": d.dependency_type,
                    }
                    for d in profile.internal_deps
                ],
            },
        )
