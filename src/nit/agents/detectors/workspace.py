"""Workspace detector — identify monorepo tools and enumerate packages."""

from __future__ import annotations

import contextlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

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


@dataclass
class PackageInfo:
    """A single package (or the root project in a single-repo)."""

    name: str
    path: str
    """Path relative to the workspace root (``"."`` for root packages)."""
    dependencies: list[str] = field(default_factory=list)
    """Names of *internal* packages this package depends on."""


@dataclass
class WorkspaceProfile:
    """Full workspace detection result for a project."""

    tool: str
    """Workspace tool name (e.g. ``"turborepo"``, ``"pnpm"``, ``"generic"``)."""
    root: str
    """Absolute path to the workspace root."""
    packages: list[PackageInfo] = field(default_factory=list)

    @property
    def is_monorepo(self) -> bool:
        """Return ``True`` if the workspace contains more than one package."""
        return len(self.packages) > 1


# ── Glob expansion helper ─────────────────────────────────────────


def _expand_globs(root: Path, patterns: Sequence[str]) -> list[Path]:
    """Expand workspace glob patterns into actual directories.

    Each *pattern* may contain ``*`` or ``**`` wildcards.  Only directories
    that exist and contain at least one file are returned.  Patterns without
    wildcards are treated as literal directory paths.
    """
    seen: set[Path] = set()
    result: list[Path] = []
    for pattern in patterns:
        if "*" in pattern or "?" in pattern:
            for match in sorted(root.glob(pattern)):
                if match.is_dir() and match not in seen:
                    seen.add(match)
                    result.append(match)
        else:
            candidate = root / pattern
            if candidate.is_dir() and candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
    return result


# ── Package name resolution ────────────────────────────────────────


def _read_json(path: Path) -> dict[str, Any]:
    """Read and parse a JSON file, returning ``{}`` on any error."""
    with contextlib.suppress(OSError, json.JSONDecodeError):
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    return {}


def _package_name_from_dir(pkg_dir: Path) -> str:
    """Derive a package name from its directory.

    Tries ``package.json`` ``name``, ``Cargo.toml`` ``[package] name``,
    ``go.mod`` ``module`` line, ``pyproject.toml`` ``name``, Maven
    ``artifactId``, and Gradle ``rootProject.name`` — falling back to the
    directory basename.
    """
    # Try each manifest strategy; first match wins.
    strategies = (
        _name_from_package_json,
        _name_from_cargo_toml,
        _name_from_go_mod,
        _name_from_pyproject_toml,
        _name_from_pom_xml,
        _name_from_gradle_settings,
    )
    for strategy in strategies:
        name = strategy(pkg_dir)
        if name is not None:
            return name
    return pkg_dir.name


def _name_from_package_json(pkg_dir: Path) -> str | None:
    pj = _read_json(pkg_dir / "package.json")
    name = pj.get("name")
    if isinstance(name, str) and name:
        return name
    return None


def _name_from_cargo_toml(pkg_dir: Path) -> str | None:
    cargo_toml = pkg_dir / "Cargo.toml"
    if cargo_toml.is_file():
        with contextlib.suppress(OSError):
            text = cargo_toml.read_text(encoding="utf-8")
            m = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if m:
                return m.group(1)
    return None


def _name_from_go_mod(pkg_dir: Path) -> str | None:
    go_mod = pkg_dir / "go.mod"
    if go_mod.is_file():
        with contextlib.suppress(OSError):
            text = go_mod.read_text(encoding="utf-8")
            m = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
            if m:
                return m.group(1)
    return None


def _name_from_pyproject_toml(pkg_dir: Path) -> str | None:
    pyproject = pkg_dir / "pyproject.toml"
    if pyproject.is_file():
        with contextlib.suppress(OSError):
            text = pyproject.read_text(encoding="utf-8")
            m = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if m:
                return m.group(1)
    return None


def _name_from_pom_xml(pkg_dir: Path) -> str | None:
    pom = pkg_dir / "pom.xml"
    if pom.is_file():
        with contextlib.suppress(OSError):
            text = pom.read_text(encoding="utf-8")
            m = re.search(r"<artifactId>([^<]+)</artifactId>", text)
            if m:
                return m.group(1)
    return None


def _name_from_gradle_settings(pkg_dir: Path) -> str | None:
    for settings_name in ("settings.gradle", "settings.gradle.kts"):
        settings = pkg_dir / settings_name
        if settings.is_file():
            with contextlib.suppress(OSError):
                text = settings.read_text(encoding="utf-8")
                m = re.search(
                    r"""rootProject\.name\s*=\s*['"]([^'"]+)['"]""",
                    text,
                )
                if m:
                    return m.group(1)
    return None


# ── Per-tool detectors ─────────────────────────────────────────────
#
# Each detector returns a ``WorkspaceProfile | None``.  ``None`` means the
# tool was not detected.  Detectors are tried in priority order — the
# first match wins.


def _detect_turborepo(root: Path) -> WorkspaceProfile | None:
    """Detect Turborepo via ``turbo.json``."""
    turbo_json = root / "turbo.json"
    if not turbo_json.is_file():
        return None

    # Turborepo itself doesn't define packages — it delegates to the
    # underlying package manager's workspaces (pnpm, yarn, npm).
    # We detect turbo, then resolve packages from the PM workspace config.
    pkg_dirs = _resolve_js_workspace_packages(root)
    packages = _build_package_list(root, pkg_dirs)
    return WorkspaceProfile(tool="turborepo", root=str(root), packages=packages)


def _detect_nx(root: Path) -> WorkspaceProfile | None:
    """Detect Nx via ``nx.json``."""
    nx_json = root / "nx.json"
    if not nx_json.is_file():
        return None

    pkg_dirs = _resolve_js_workspace_packages(root)

    # Nx also supports a ``projects`` directory by convention.
    if not pkg_dirs:
        for candidate in ("packages", "apps", "libs"):
            d = root / candidate
            if d.is_dir():
                pkg_dirs.extend(child for child in sorted(d.iterdir()) if child.is_dir())

    packages = _build_package_list(root, pkg_dirs)
    return WorkspaceProfile(tool="nx", root=str(root), packages=packages)


def _detect_pnpm(root: Path) -> WorkspaceProfile | None:
    """Detect pnpm workspaces via ``pnpm-workspace.yaml``."""
    ws_yaml = root / "pnpm-workspace.yaml"
    if not ws_yaml.is_file():
        return None

    patterns = _parse_pnpm_workspace_yaml(ws_yaml)
    pkg_dirs = _expand_globs(root, patterns)
    packages = _build_package_list(root, pkg_dirs)
    return WorkspaceProfile(tool="pnpm", root=str(root), packages=packages)


def _parse_pnpm_workspace_yaml(path: Path) -> list[str]:
    """Parse ``pnpm-workspace.yaml`` and return the ``packages`` globs.

    Uses a simple regex approach to avoid a YAML dependency.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    lines = text.splitlines()
    in_packages = False
    patterns: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("packages:") or stripped == "packages:":
            in_packages = True
            continue
        if in_packages:
            if stripped.startswith("- "):
                value = stripped[2:].strip().strip("'\"")
                if value:
                    patterns.append(value)
            elif stripped and not stripped.startswith("#"):
                break
    return patterns


def _detect_yarn(root: Path) -> WorkspaceProfile | None:
    """Detect Yarn workspaces via ``package.json`` ``workspaces`` field."""
    pj = _read_json(root / "package.json")
    workspaces = pj.get("workspaces")
    if workspaces is None:
        return None

    # Yarn workspaces can be a list or an object with a ``packages`` key.
    patterns: list[str] = []
    if isinstance(workspaces, list):
        patterns = [str(w) for w in workspaces]
    elif isinstance(workspaces, dict):
        packages_raw = workspaces.get("packages", [])
        if isinstance(packages_raw, list):
            patterns = [str(w) for w in packages_raw]

    if not patterns:
        return None

    # Only report as Yarn if ``yarn.lock`` exists (otherwise fall through
    # to npm detection which also uses the same workspaces field).
    if not (root / "yarn.lock").is_file():
        return None

    pkg_dirs = _expand_globs(root, patterns)
    packages = _build_package_list(root, pkg_dirs)
    return WorkspaceProfile(tool="yarn", root=str(root), packages=packages)


def _detect_npm(root: Path) -> WorkspaceProfile | None:
    """Detect npm workspaces via ``package.json`` ``workspaces`` field."""
    pj = _read_json(root / "package.json")
    workspaces = pj.get("workspaces")
    if workspaces is None:
        return None

    patterns: list[str] = []
    if isinstance(workspaces, list):
        patterns = [str(w) for w in workspaces]
    elif isinstance(workspaces, dict):
        packages_raw = workspaces.get("packages", [])
        if isinstance(packages_raw, list):
            patterns = [str(w) for w in packages_raw]

    if not patterns:
        return None

    pkg_dirs = _expand_globs(root, patterns)
    packages = _build_package_list(root, pkg_dirs)
    return WorkspaceProfile(tool="npm", root=str(root), packages=packages)


def _detect_cargo(root: Path) -> WorkspaceProfile | None:
    """Detect Cargo workspaces via ``Cargo.toml`` ``[workspace]`` section."""
    cargo_toml = root / "Cargo.toml"
    if not cargo_toml.is_file():
        return None

    try:
        text = cargo_toml.read_text(encoding="utf-8")
    except OSError:
        return None

    if "[workspace]" not in text:
        return None

    # Extract ``members = [...]`` from the workspace section.
    patterns = _parse_cargo_workspace_members(text)
    pkg_dirs = _expand_globs(root, patterns)
    packages = _build_package_list(root, pkg_dirs)
    return WorkspaceProfile(tool="cargo", root=str(root), packages=packages)


def _parse_cargo_workspace_members(text: str) -> list[str]:
    """Extract workspace member globs from a ``Cargo.toml`` string."""
    m = re.search(
        r"members\s*=\s*\[(.*?)\]",
        text,
        re.DOTALL,
    )
    if not m:
        return []
    inner = m.group(1)
    return [s.strip().strip("'\"") for s in inner.split(",") if s.strip().strip("'\"")]


def _detect_go(root: Path) -> WorkspaceProfile | None:
    """Detect Go workspaces via ``go.work``."""
    go_work = root / "go.work"
    if not go_work.is_file():
        return None

    try:
        text = go_work.read_text(encoding="utf-8")
    except OSError:
        return None

    # Extract ``use (...)`` or single ``use ./path`` directives.
    dirs: list[str] = []

    # Multi-line ``use ( ... )``
    m = re.search(r"use\s*\((.*?)\)", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("//"):
                dirs.append(stripped)

    # Single ``use ./path`` directives outside parens.
    for single_m in re.finditer(r"^use\s+(\S+)\s*$", text, re.MULTILINE):
        value = single_m.group(1)
        if value != "(":
            dirs.append(value)

    pkg_dirs = [root / d for d in dirs if (root / d).is_dir()]
    packages = _build_package_list(root, pkg_dirs)
    return WorkspaceProfile(tool="go", root=str(root), packages=packages)


def _detect_gradle(root: Path) -> WorkspaceProfile | None:
    """Detect Gradle multi-project via ``settings.gradle(.kts)``."""
    for name in ("settings.gradle.kts", "settings.gradle"):
        settings = root / name
        if settings.is_file():
            try:
                text = settings.read_text(encoding="utf-8")
            except OSError:
                continue

            # Look for ``include("...")`` or ``include '...'`` directives.
            includes = re.findall(
                r"""include\s*\(\s*['"]([^'"]+)['"]\s*\)""",
                text,
            )
            includes.extend(
                re.findall(r"""include\s+['"]([^'"]+)['"]""", text),
            )

            if not includes:
                continue

            # Gradle uses colon-separated paths; ``":sub"`` → ``"sub"``.
            pkg_dirs = []
            for inc in includes:
                rel = inc.lstrip(":").replace(":", "/")
                candidate = root / rel
                if candidate.is_dir():
                    pkg_dirs.append(candidate)

            packages = _build_package_list(root, pkg_dirs)
            return WorkspaceProfile(tool="gradle", root=str(root), packages=packages)
    return None


def _detect_maven(root: Path) -> WorkspaceProfile | None:
    """Detect Maven multi-module via parent ``pom.xml`` ``<modules>``."""
    pom = root / "pom.xml"
    if not pom.is_file():
        return None

    try:
        text = pom.read_text(encoding="utf-8")
    except OSError:
        return None

    m = re.search(r"<modules>(.*?)</modules>", text, re.DOTALL)
    if not m:
        return None

    modules = re.findall(r"<module>([^<]+)</module>", m.group(1))
    pkg_dirs = [root / mod for mod in modules if (root / mod).is_dir()]
    packages = _build_package_list(root, pkg_dirs)
    return WorkspaceProfile(tool="maven", root=str(root), packages=packages)


def _detect_bazel(root: Path) -> WorkspaceProfile | None:
    """Detect Bazel workspace via ``WORKSPACE`` or ``MODULE.bazel``."""
    has_workspace = (root / "WORKSPACE").is_file() or (root / "WORKSPACE.bazel").is_file()
    has_module = (root / "MODULE.bazel").is_file()
    if not has_workspace and not has_module:
        return None

    # Find directories containing BUILD files.
    pkg_dirs: list[Path] = []
    for build_name in ("BUILD", "BUILD.bazel"):
        for build_file in sorted(root.rglob(build_name)):
            parent = build_file.parent
            if (
                parent != root
                and parent not in pkg_dirs
                and not any(part in _SKIP_DIRS for part in parent.relative_to(root).parts)
            ):
                pkg_dirs.append(parent)

    packages = _build_package_list(root, pkg_dirs)
    return WorkspaceProfile(tool="bazel", root=str(root), packages=packages)


def _detect_cmake(root: Path) -> WorkspaceProfile | None:
    """Detect CMake multi-project via ``add_subdirectory`` calls."""
    cmake = root / "CMakeLists.txt"
    if not cmake.is_file():
        return None

    try:
        text = cmake.read_text(encoding="utf-8")
    except OSError:
        return None

    subdirs = re.findall(r"add_subdirectory\s*\(\s*(\S+)", text)
    if not subdirs:
        return None

    pkg_dirs = [root / sd.strip(")") for sd in subdirs if (root / sd.strip(")")).is_dir()]
    packages = _build_package_list(root, pkg_dirs)
    return WorkspaceProfile(tool="cmake", root=str(root), packages=packages)


# ── JS workspace package resolution ───────────────────────────────


def _resolve_js_workspace_packages(root: Path) -> list[Path]:
    """Resolve JS/TS workspace package directories.

    Tries ``pnpm-workspace.yaml`` first, then ``package.json`` ``workspaces``.
    """
    ws_yaml = root / "pnpm-workspace.yaml"
    if ws_yaml.is_file():
        patterns = _parse_pnpm_workspace_yaml(ws_yaml)
        if patterns:
            return _expand_globs(root, patterns)

    pj = _read_json(root / "package.json")
    workspaces = pj.get("workspaces")
    if workspaces is None:
        return []

    ws_patterns: list[str] = []
    if isinstance(workspaces, list):
        ws_patterns = [str(w) for w in workspaces]
    elif isinstance(workspaces, dict):
        packages_raw = workspaces.get("packages", [])
        if isinstance(packages_raw, list):
            ws_patterns = [str(w) for w in packages_raw]

    return _expand_globs(root, ws_patterns)


# ── Dependency graph ──────────────────────────────────────────────


def _build_dependency_graph(
    root: Path,
    packages: list[PackageInfo],
) -> None:
    """Populate ``dependencies`` on each *PackageInfo* with internal deps.

    Internal dependencies are identified by matching package names against
    ``package.json`` dependencies, ``Cargo.toml`` dependencies,
    ``go.mod`` require directives, ``pyproject.toml`` dependencies, and
    Maven ``artifactId`` references.
    """
    known_names = {pkg.name for pkg in packages}

    for pkg in packages:
        pkg_dir = root / pkg.path
        internal_deps: list[str] = []

        _collect_js_internal_deps(pkg_dir, known_names, pkg.name, internal_deps)
        _collect_cargo_internal_deps_from_file(pkg_dir, known_names, pkg.name, internal_deps)
        _collect_go_internal_deps(pkg_dir, known_names, pkg.name, internal_deps)
        _collect_python_internal_deps_from_file(pkg_dir, known_names, pkg.name, internal_deps)
        _collect_maven_internal_deps(pkg_dir, known_names, pkg.name, internal_deps)

        # Deduplicate while preserving order
        pkg.dependencies = list(dict.fromkeys(internal_deps))


def _collect_js_internal_deps(
    pkg_dir: Path,
    known_names: set[str],
    self_name: str,
    out: list[str],
) -> None:
    """Scan ``package.json`` dependency sections for internal packages."""
    pj = _read_json(pkg_dir / "package.json")
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        deps = pj.get(section, {})
        if isinstance(deps, dict):
            out.extend(
                dep_name for dep_name in deps if dep_name in known_names and dep_name != self_name
            )


def _collect_cargo_internal_deps_from_file(
    pkg_dir: Path,
    known_names: set[str],
    self_name: str,
    out: list[str],
) -> None:
    """Scan ``Cargo.toml`` for internal workspace dependencies."""
    cargo_toml = pkg_dir / "Cargo.toml"
    if not cargo_toml.is_file():
        return
    with contextlib.suppress(OSError):
        text = cargo_toml.read_text(encoding="utf-8")
        _parse_cargo_deps(text, known_names, self_name, out)


def _parse_cargo_deps(
    text: str,
    known_names: set[str],
    self_name: str,
    out: list[str],
) -> None:
    """Find Cargo dependency names that match known workspace members."""
    in_deps = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_deps = "dependencies" in stripped.lower()
            continue
        if in_deps:
            m = re.match(r"(\w[\w-]*)\s*=", stripped)
            if m:
                dep_name = m.group(1)
                if dep_name in known_names and dep_name != self_name:
                    out.append(dep_name)


def _collect_go_internal_deps(
    pkg_dir: Path,
    known_names: set[str],
    self_name: str,
    out: list[str],
) -> None:
    """Scan ``go.mod`` require directives for internal module dependencies."""
    go_mod = pkg_dir / "go.mod"
    if not go_mod.is_file():
        return
    with contextlib.suppress(OSError):
        text = go_mod.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("require", "//")):
                continue
            parts = stripped.split()
            if parts:
                mod_name = parts[0]
                if mod_name in known_names and mod_name != self_name:
                    out.append(mod_name)


def _collect_python_internal_deps_from_file(
    pkg_dir: Path,
    known_names: set[str],
    self_name: str,
    out: list[str],
) -> None:
    """Scan ``pyproject.toml`` dependencies for internal packages."""
    pyproject = pkg_dir / "pyproject.toml"
    if not pyproject.is_file():
        return
    with contextlib.suppress(OSError):
        text = pyproject.read_text(encoding="utf-8")
        dep_m = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL)
        if dep_m:
            for name_m in re.finditer(r"""['"]([^'"<>=!~;\[]+)""", dep_m.group(1)):
                dep_name = name_m.group(1).strip()
                if dep_name in known_names and dep_name != self_name:
                    out.append(dep_name)


def _collect_maven_internal_deps(
    pkg_dir: Path,
    known_names: set[str],
    self_name: str,
    out: list[str],
) -> None:
    """Scan ``pom.xml`` for internal artifact dependencies."""
    pom = pkg_dir / "pom.xml"
    if not pom.is_file():
        return
    with contextlib.suppress(OSError):
        text = pom.read_text(encoding="utf-8")
        for art_m in re.finditer(r"<artifactId>([^<]+)</artifactId>", text):
            dep_name = art_m.group(1)
            if dep_name in known_names and dep_name != self_name:
                out.append(dep_name)


# ── Package list construction ──────────────────────────────────────


def _build_package_list(root: Path, pkg_dirs: list[Path]) -> list[PackageInfo]:
    """Create ``PackageInfo`` entries for each discovered package directory."""
    packages: list[PackageInfo] = []
    seen_paths: set[str] = set()
    for pkg_dir in pkg_dirs:
        try:
            rel = str(pkg_dir.relative_to(root))
        except ValueError:
            continue
        if rel in seen_paths:
            continue
        seen_paths.add(rel)
        name = _package_name_from_dir(pkg_dir)
        packages.append(PackageInfo(name=name, path=rel))
    return packages


# ── Orchestrator ───────────────────────────────────────────────────

# Detection functions in priority order.
_DETECTORS = [
    ("turborepo", _detect_turborepo),
    ("nx", _detect_nx),
    ("pnpm", _detect_pnpm),
    ("yarn", _detect_yarn),
    ("npm", _detect_npm),
    ("cargo", _detect_cargo),
    ("go", _detect_go),
    ("gradle", _detect_gradle),
    ("maven", _detect_maven),
    ("bazel", _detect_bazel),
    ("cmake", _detect_cmake),
]


def detect_workspace(
    root: str | Path,
    *,
    skip_dirs: frozenset[str] | None = None,
) -> WorkspaceProfile:
    """Detect the workspace tool and enumerate packages.

    Detectors are tried in priority order — the first match wins.  If
    no workspace tool is detected, the project is treated as a single
    package (generic workspace).

    Parameters
    ----------
    root:
        Project directory to scan.
    skip_dirs:
        Directories to skip.  Defaults to the built-in skip set.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise ValueError(f"Not a directory: {root_path}")

    _ = skip_dirs  # reserved for future filtering

    for _name, detector in _DETECTORS:
        result = detector(root_path)
        if result is not None:
            _build_dependency_graph(root_path, result.packages)
            return result

    # Fallback: single-repo (generic workspace).
    name = _package_name_from_dir(root_path)
    packages = [PackageInfo(name=name, path=".")]
    return WorkspaceProfile(tool="generic", root=str(root_path), packages=packages)


# ── Agent wrapper ───────────────────────────────────────────────────


class WorkspaceDetector(BaseAgent):
    """Agent that detects workspace layout and enumerates packages."""

    @property
    def name(self) -> str:
        return "workspace-detector"

    @property
    def description(self) -> str:
        return "Detect monorepo workspace tools and enumerate packages."

    async def run(self, task: TaskInput) -> TaskOutput:
        """Run workspace detection on *task.target*.

        Optional ``task.context["skip_dirs"]`` overrides default skip dirs.
        """
        target = Path(task.target)
        skip_raw = task.context.get("skip_dirs")
        skip_dirs = frozenset(skip_raw) if skip_raw is not None else None

        try:
            profile = detect_workspace(target, skip_dirs=skip_dirs)
        except ValueError as exc:
            return TaskOutput(status=TaskStatus.FAILED, errors=[str(exc)])

        return TaskOutput(
            status=TaskStatus.COMPLETED,
            result={
                "tool": profile.tool,
                "root": profile.root,
                "is_monorepo": profile.is_monorepo,
                "packages": [
                    {
                        "name": pkg.name,
                        "path": pkg.path,
                        "dependencies": pkg.dependencies,
                    }
                    for pkg in profile.packages
                ],
            },
        )
