"""Infrastructure detector — identify CI/CD, Docker, Makefile, and scripts."""

from __future__ import annotations

import contextlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus

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


class CIProvider(Enum):
    """Known CI/CD providers."""

    GITHUB_ACTIONS = "github_actions"
    GITLAB_CI = "gitlab_ci"
    JENKINS = "jenkins"
    CIRCLECI = "circleci"
    TRAVIS = "travis"
    AZURE_PIPELINES = "azure_pipelines"
    BITBUCKET_PIPELINES = "bitbucket_pipelines"


@dataclass
class CIConfig:
    """A detected CI/CD configuration file."""

    provider: CIProvider
    file_path: str
    """Path relative to the project root."""
    test_commands: list[str] = field(default_factory=list)
    """Test commands found in the CI config."""


@dataclass
class DockerConfig:
    """Detected Docker configuration for the project."""

    has_dockerfile: bool = False
    has_compose: bool = False
    has_dockerignore: bool = False
    dockerfile_paths: list[str] = field(default_factory=list)
    """Relative paths to Dockerfiles."""
    compose_paths: list[str] = field(default_factory=list)
    """Relative paths to Compose files."""


@dataclass
class ScriptInfo:
    """A detected build/test script."""

    file_path: str
    """Path relative to the project root."""
    script_type: str
    """One of ``"shell"``, ``"makefile"``, ``"npm_script"``."""
    name: str
    """Script identifier (filename for shell, target for make, key for npm)."""


@dataclass
class InfraProfile:
    """Full infrastructure detection result for a project."""

    root: str
    """Absolute path to the project root."""
    ci_configs: list[CIConfig] = field(default_factory=list)
    docker: DockerConfig = field(default_factory=DockerConfig)
    makefiles: list[str] = field(default_factory=list)
    """Relative paths to detected Makefiles."""
    scripts: list[ScriptInfo] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    """Aggregated test commands found across all CI configs and scripts."""

    @property
    def has_ci(self) -> bool:
        """``True`` when at least one CI config was detected."""
        return len(self.ci_configs) > 0

    @property
    def has_docker(self) -> bool:
        """``True`` when a Dockerfile was detected."""
        return self.docker.has_dockerfile

    @property
    def ci_providers(self) -> list[str]:
        """List of detected CI provider names."""
        return [c.provider.value for c in self.ci_configs]


# ── Test command extraction ────────────────────────────────────────

_TEST_COMMAND_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:^|\s)(npm\s+(?:run\s+)?test\b[^\n]*)"),
    re.compile(r"(?:^|\s)(npx\s+(?:vitest|jest|mocha|playwright)\b[^\n]*)"),
    re.compile(r"(?:^|\s)(yarn\s+(?:run\s+)?test\b[^\n]*)"),
    re.compile(r"(?:^|\s)(pnpm\s+(?:run\s+)?test\b[^\n]*)"),
    re.compile(r"(?:^|\s)(pytest\b[^\n]*)"),
    re.compile(r"(?:^|\s)(python\s+-m\s+pytest\b[^\n]*)"),
    re.compile(r"(?:^|\s)(go\s+test\b[^\n]*)"),
    re.compile(r"(?:^|\s)(cargo\s+test\b[^\n]*)"),
    re.compile(r"(?:^|\s)(dotnet\s+test\b[^\n]*)"),
    re.compile(r"(?:^|\s)(make\s+test\b[^\n]*)"),
    re.compile(r"(?:^|\s)(gradlew?\s+test\b[^\n]*)"),
    re.compile(r"(?:^|\s)(mvn\s+test\b[^\n]*)"),
]


def _extract_test_commands(text: str) -> list[str]:
    """Extract test commands from arbitrary text (CI config, Makefile, etc.)."""
    commands: list[str] = []
    for pattern in _TEST_COMMAND_PATTERNS:
        for m in pattern.finditer(text):
            cmd = m.group(1).strip()
            if cmd and cmd not in commands:
                commands.append(cmd)
    return commands


# ── CI/CD detection ────────────────────────────────────────────────


def _read_text_safe(path: Path) -> str | None:
    """Read a text file, returning ``None`` on any error."""
    with contextlib.suppress(OSError):
        return path.read_text(encoding="utf-8")
    return None


def _detect_github_actions(root: Path) -> list[CIConfig]:
    """Detect GitHub Actions workflow files."""
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []

    configs: list[CIConfig] = []
    for wf in sorted(workflows_dir.iterdir()):
        if wf.is_file() and wf.suffix in (".yml", ".yaml"):
            rel = str(wf.relative_to(root))
            text = _read_text_safe(wf)
            test_cmds = _extract_test_commands(text) if text else []
            configs.append(
                CIConfig(
                    provider=CIProvider.GITHUB_ACTIONS,
                    file_path=rel,
                    test_commands=test_cmds,
                )
            )
    return configs


def _detect_single_ci_file(root: Path, rel_path: str, provider: CIProvider) -> CIConfig | None:
    """Detect a single CI config file at a fixed relative path."""
    path = root / rel_path
    if not path.is_file():
        return None
    text = _read_text_safe(path)
    test_cmds = _extract_test_commands(text) if text else []
    return CIConfig(provider=provider, file_path=rel_path, test_commands=test_cmds)


def _detect_ci_configs(root: Path) -> list[CIConfig]:
    """Detect all CI/CD configuration files in the project."""
    configs: list[CIConfig] = []

    configs.extend(_detect_github_actions(root))

    single_ci_files: list[tuple[str, CIProvider]] = [
        (".gitlab-ci.yml", CIProvider.GITLAB_CI),
        ("Jenkinsfile", CIProvider.JENKINS),
        (".circleci/config.yml", CIProvider.CIRCLECI),
        (".travis.yml", CIProvider.TRAVIS),
        ("azure-pipelines.yml", CIProvider.AZURE_PIPELINES),
        ("bitbucket-pipelines.yml", CIProvider.BITBUCKET_PIPELINES),
    ]
    for rel_path, provider in single_ci_files:
        result = _detect_single_ci_file(root, rel_path, provider)
        if result is not None:
            configs.append(result)

    return configs


# ── Docker detection ───────────────────────────────────────────────


def _detect_docker(root: Path) -> DockerConfig:
    """Detect Docker and Compose configuration files."""
    has_dockerignore = (root / ".dockerignore").is_file()

    dockerfile_paths = [name for name in ("Dockerfile",) if (root / name).is_file()]
    compose_paths = [
        name
        for name in (
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        )
        if (root / name).is_file()
    ]

    return DockerConfig(
        has_dockerfile=len(dockerfile_paths) > 0,
        has_compose=len(compose_paths) > 0,
        has_dockerignore=has_dockerignore,
        dockerfile_paths=dockerfile_paths,
        compose_paths=compose_paths,
    )


# ── Makefile detection ─────────────────────────────────────────────


def _detect_makefiles(root: Path) -> list[str]:
    """Detect Makefile variants at the project root."""
    return [name for name in ("Makefile", "GNUmakefile", "makefile") if (root / name).is_file()]


# ── Script detection ───────────────────────────────────────────────


def _read_json_safe(path: Path) -> dict[str, object]:
    """Read and parse a JSON file, returning ``{}`` on any error."""
    with contextlib.suppress(OSError, json.JSONDecodeError):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    return {}


def _detect_npm_scripts(root: Path) -> list[ScriptInfo]:
    """Extract npm scripts from ``package.json``."""
    pj = _read_json_safe(root / "package.json")
    scripts_obj = pj.get("scripts")
    if not isinstance(scripts_obj, dict):
        return []
    return [
        ScriptInfo(file_path="package.json", script_type="npm_script", name=str(key))
        for key in scripts_obj
    ]


def _detect_shell_scripts(root: Path, skip_dirs: frozenset[str]) -> list[ScriptInfo]:
    """Detect shell scripts in root and ``scripts/`` directory."""
    # Shell scripts directly in root
    found: list[ScriptInfo] = [
        ScriptInfo(file_path=child.name, script_type="shell", name=child.name)
        for child in sorted(root.iterdir())
        if child.is_file() and child.suffix == ".sh"
    ]

    # Shell scripts in scripts/ directory
    scripts_dir = root / "scripts"
    if scripts_dir.is_dir() and "scripts" not in skip_dirs:
        found.extend(
            ScriptInfo(
                file_path=str(child.relative_to(root)),
                script_type="shell",
                name=child.name,
            )
            for child in sorted(scripts_dir.iterdir())
            if child.is_file() and child.suffix == ".sh"
        )

    return found


def _detect_scripts(root: Path, skip_dirs: frozenset[str]) -> list[ScriptInfo]:
    """Detect all scripts (npm, shell) in the project."""
    scripts: list[ScriptInfo] = []
    scripts.extend(_detect_npm_scripts(root))
    scripts.extend(_detect_shell_scripts(root, skip_dirs))
    return scripts


# ── Orchestrator ───────────────────────────────────────────────────


def detect_infra(
    root: str | Path,
    *,
    skip_dirs: frozenset[str] | None = None,
) -> InfraProfile:
    """Scan *root* for CI/CD, Docker, Makefile, and script infrastructure.

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

    effective_skip = skip_dirs if skip_dirs is not None else _SKIP_DIRS

    ci_configs = _detect_ci_configs(root_path)
    docker = _detect_docker(root_path)
    makefiles = _detect_makefiles(root_path)
    scripts = _detect_scripts(root_path, effective_skip)

    # Aggregate test commands from all sources
    all_test_cmds: list[str] = []
    for ci in ci_configs:
        for cmd in ci.test_commands:
            if cmd not in all_test_cmds:
                all_test_cmds.append(cmd)

    # Extract test commands from Makefiles
    for mf in makefiles:
        text = _read_text_safe(root_path / mf)
        if text:
            for cmd in _extract_test_commands(text):
                if cmd not in all_test_cmds:
                    all_test_cmds.append(cmd)

    return InfraProfile(
        root=str(root_path),
        ci_configs=ci_configs,
        docker=docker,
        makefiles=makefiles,
        scripts=scripts,
        test_commands=all_test_cmds,
    )


# ── Agent wrapper ───────────────────────────────────────────────────


class InfraDetector(BaseAgent):
    """Agent that detects CI/CD, Docker, Makefile, and script infrastructure."""

    @property
    def name(self) -> str:
        return "infra-detector"

    @property
    def description(self) -> str:
        return "Detect CI/CD, Docker, Makefile, and script infrastructure in a project."

    async def run(self, task: TaskInput) -> TaskOutput:
        """Run infrastructure detection on *task.target*.

        Optional ``task.context["skip_dirs"]`` overrides default skip dirs.
        """
        target = Path(task.target)
        skip_raw = task.context.get("skip_dirs")
        skip_dirs = frozenset(skip_raw) if skip_raw is not None else None

        try:
            profile = detect_infra(target, skip_dirs=skip_dirs)
        except ValueError as exc:
            return TaskOutput(status=TaskStatus.FAILED, errors=[str(exc)])

        return TaskOutput(
            status=TaskStatus.COMPLETED,
            result={
                "root": profile.root,
                "has_ci": profile.has_ci,
                "ci_providers": profile.ci_providers,
                "has_docker": profile.has_docker,
                "ci_configs": [
                    {
                        "provider": c.provider.value,
                        "file_path": c.file_path,
                        "test_commands": c.test_commands,
                    }
                    for c in profile.ci_configs
                ],
                "docker": {
                    "has_dockerfile": profile.docker.has_dockerfile,
                    "has_compose": profile.docker.has_compose,
                    "has_dockerignore": profile.docker.has_dockerignore,
                    "dockerfile_paths": profile.docker.dockerfile_paths,
                    "compose_paths": profile.docker.compose_paths,
                },
                "makefiles": profile.makefiles,
                "scripts": [
                    {
                        "file_path": s.file_path,
                        "script_type": s.script_type,
                        "name": s.name,
                    }
                    for s in profile.scripts
                ],
                "test_commands": profile.test_commands,
            },
        )
