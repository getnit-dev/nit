"""Tests for the InfraDetector agent and detect_infra function."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from nit.agents.base import TaskInput, TaskStatus
from nit.agents.detectors.infra import (
    CIConfig,
    CIProvider,
    DockerConfig,
    InfraDetector,
    InfraProfile,
    detect_infra,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_files(root: Path, rel_paths: list[str]) -> None:
    """Create empty files at the given relative paths under *root*."""
    for rel in rel_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


def _write_file(root: Path, rel: str, content: str) -> None:
    """Write *content* to a file at *root/rel*."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _write_package_json(root: Path, data: dict[str, object]) -> None:
    """Write a ``package.json`` to *root*."""
    _write_file(root, "package.json", json.dumps(data))


# ---------------------------------------------------------------------------
# CI/CD detection
# ---------------------------------------------------------------------------


class TestCIDetection:
    def test_github_actions_single_workflow(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".github/workflows/ci.yml",
            "name: CI\non:\n  push:\njobs:\n  test:\n    steps:\n      - run: npm test\n",
        )
        profile = detect_infra(tmp_path)
        assert profile.has_ci
        assert len(profile.ci_configs) == 1
        assert profile.ci_configs[0].provider == CIProvider.GITHUB_ACTIONS
        assert profile.ci_configs[0].file_path == ".github/workflows/ci.yml"

    def test_github_actions_multiple_workflows(self, tmp_path: Path) -> None:
        _write_file(tmp_path, ".github/workflows/ci.yml", "name: CI\n")
        _write_file(tmp_path, ".github/workflows/release.yaml", "name: Release\n")
        profile = detect_infra(tmp_path)
        assert len(profile.ci_configs) == 2
        providers = [c.provider for c in profile.ci_configs]
        assert all(p == CIProvider.GITHUB_ACTIONS for p in providers)

    def test_gitlab_ci(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".gitlab-ci.yml",
            "test:\n  script:\n    - pytest\n",
        )
        profile = detect_infra(tmp_path)
        assert profile.has_ci
        assert profile.ci_configs[0].provider == CIProvider.GITLAB_CI
        assert profile.ci_configs[0].file_path == ".gitlab-ci.yml"

    def test_jenkinsfile(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "Jenkinsfile", "pipeline {\n  stages {}\n}\n")
        profile = detect_infra(tmp_path)
        assert profile.has_ci
        assert profile.ci_configs[0].provider == CIProvider.JENKINS

    def test_circleci(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".circleci/config.yml",
            "version: 2.1\njobs:\n  test:\n    steps:\n      - run: pytest\n",
        )
        profile = detect_infra(tmp_path)
        assert profile.has_ci
        assert profile.ci_configs[0].provider == CIProvider.CIRCLECI

    def test_travis(self, tmp_path: Path) -> None:
        _write_file(tmp_path, ".travis.yml", "language: python\nscript: pytest\n")
        profile = detect_infra(tmp_path)
        assert profile.has_ci
        assert profile.ci_configs[0].provider == CIProvider.TRAVIS

    def test_azure_pipelines(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "azure-pipelines.yml",
            "trigger:\n  - main\nsteps:\n  - script: npm test\n",
        )
        profile = detect_infra(tmp_path)
        assert profile.has_ci
        assert profile.ci_configs[0].provider == CIProvider.AZURE_PIPELINES

    def test_bitbucket_pipelines(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "bitbucket-pipelines.yml",
            "pipelines:\n  default:\n    - step:\n        script:\n          - npm test\n",
        )
        profile = detect_infra(tmp_path)
        assert profile.has_ci
        assert profile.ci_configs[0].provider == CIProvider.BITBUCKET_PIPELINES

    def test_multiple_ci_providers(self, tmp_path: Path) -> None:
        _write_file(tmp_path, ".github/workflows/ci.yml", "name: CI\n")
        _write_file(tmp_path, ".gitlab-ci.yml", "test:\n  script: pytest\n")
        profile = detect_infra(tmp_path)
        assert len(profile.ci_configs) == 2
        providers = {c.provider for c in profile.ci_configs}
        assert providers == {CIProvider.GITHUB_ACTIONS, CIProvider.GITLAB_CI}

    def test_no_ci(self, tmp_path: Path) -> None:
        profile = detect_infra(tmp_path)
        assert not profile.has_ci
        assert profile.ci_configs == []
        assert profile.ci_providers == []


# ---------------------------------------------------------------------------
# Test command extraction
# ---------------------------------------------------------------------------


class TestTestCommandExtraction:
    def test_npm_test_in_github_actions(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".github/workflows/ci.yml",
            "jobs:\n  test:\n    steps:\n      - run: npm test\n",
        )
        profile = detect_infra(tmp_path)
        assert "npm test" in profile.test_commands

    def test_pytest_in_gitlab_ci(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".gitlab-ci.yml",
            "test:\n  script:\n    - pytest --cov\n",
        )
        profile = detect_infra(tmp_path)
        assert any("pytest" in cmd for cmd in profile.test_commands)

    def test_cargo_test(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".github/workflows/ci.yml",
            "jobs:\n  test:\n    steps:\n      - run: cargo test\n",
        )
        profile = detect_infra(tmp_path)
        assert any("cargo test" in cmd for cmd in profile.test_commands)

    def test_go_test(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".github/workflows/ci.yml",
            "jobs:\n  test:\n    steps:\n      - run: go test ./...\n",
        )
        profile = detect_infra(tmp_path)
        assert any("go test" in cmd for cmd in profile.test_commands)

    def test_make_test_in_makefile(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "Makefile",
            "test:\n\tpytest\n\nclean:\n\trm -rf build\n",
        )
        profile = detect_infra(tmp_path)
        assert any("pytest" in cmd for cmd in profile.test_commands)

    def test_multiple_test_commands(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".github/workflows/ci.yml",
            "steps:\n  - run: npm test\n  - run: pytest\n",
        )
        profile = detect_infra(tmp_path)
        assert len(profile.test_commands) >= 2

    def test_no_test_commands(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".github/workflows/deploy.yml",
            "name: Deploy\nsteps:\n  - run: echo hello\n",
        )
        profile = detect_infra(tmp_path)
        assert profile.test_commands == []


# ---------------------------------------------------------------------------
# Docker detection
# ---------------------------------------------------------------------------


class TestDockerDetection:
    def test_dockerfile_only(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["Dockerfile"])
        profile = detect_infra(tmp_path)
        assert profile.has_docker
        assert profile.docker.has_dockerfile
        assert not profile.docker.has_compose
        assert "Dockerfile" in profile.docker.dockerfile_paths

    def test_docker_compose_yml(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["docker-compose.yml"])
        profile = detect_infra(tmp_path)
        assert profile.docker.has_compose
        assert "docker-compose.yml" in profile.docker.compose_paths

    def test_compose_yaml(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["compose.yaml"])
        profile = detect_infra(tmp_path)
        assert profile.docker.has_compose
        assert "compose.yaml" in profile.docker.compose_paths

    def test_dockerignore(self, tmp_path: Path) -> None:
        _make_files(tmp_path, [".dockerignore"])
        profile = detect_infra(tmp_path)
        assert profile.docker.has_dockerignore

    def test_full_docker_setup(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["Dockerfile", "docker-compose.yml", ".dockerignore"])
        profile = detect_infra(tmp_path)
        assert profile.has_docker
        assert profile.docker.has_dockerfile
        assert profile.docker.has_compose
        assert profile.docker.has_dockerignore

    def test_no_docker(self, tmp_path: Path) -> None:
        profile = detect_infra(tmp_path)
        assert not profile.has_docker
        assert not profile.docker.has_dockerfile
        assert not profile.docker.has_compose


# ---------------------------------------------------------------------------
# Makefile detection
# ---------------------------------------------------------------------------


class TestMakefileDetection:
    def test_makefile(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["Makefile"])
        profile = detect_infra(tmp_path)
        assert "Makefile" in profile.makefiles

    def test_gnumakefile(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["GNUmakefile"])
        profile = detect_infra(tmp_path)
        assert "GNUmakefile" in profile.makefiles

    def test_lowercase_makefile(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["makefile"])
        profile = detect_infra(tmp_path)
        assert "makefile" in profile.makefiles

    def test_no_makefile(self, tmp_path: Path) -> None:
        profile = detect_infra(tmp_path)
        assert profile.makefiles == []


# ---------------------------------------------------------------------------
# Script detection
# ---------------------------------------------------------------------------


class TestScriptDetection:
    def test_scripts_directory(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["scripts/deploy.sh", "scripts/test.sh"])
        profile = detect_infra(tmp_path)
        shell_scripts = [s for s in profile.scripts if s.script_type == "shell"]
        names = {s.name for s in shell_scripts}
        assert "deploy.sh" in names
        assert "test.sh" in names

    def test_npm_scripts(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {"scripts": {"test": "vitest", "build": "tsc", "lint": "eslint ."}},
        )
        profile = detect_infra(tmp_path)
        npm_scripts = [s for s in profile.scripts if s.script_type == "npm_script"]
        names = {s.name for s in npm_scripts}
        assert "test" in names
        assert "build" in names
        assert "lint" in names

    def test_shell_scripts_in_root(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["run_tests.sh"])
        profile = detect_infra(tmp_path)
        shell_scripts = [s for s in profile.scripts if s.script_type == "shell"]
        assert any(s.name == "run_tests.sh" for s in shell_scripts)

    def test_no_scripts(self, tmp_path: Path) -> None:
        profile = detect_infra(tmp_path)
        assert profile.scripts == []


# ---------------------------------------------------------------------------
# InfraProfile properties
# ---------------------------------------------------------------------------


class TestInfraProfile:
    def test_has_ci_property(self) -> None:
        profile = InfraProfile(
            root="/dummy/root",
            ci_configs=[CIConfig(provider=CIProvider.GITHUB_ACTIONS, file_path="ci.yml")],
        )
        assert profile.has_ci

    def test_has_ci_false_when_empty(self) -> None:
        profile = InfraProfile(root="/dummy/root")
        assert not profile.has_ci

    def test_has_docker_property(self) -> None:
        profile = InfraProfile(
            root="/dummy/root",
            docker=DockerConfig(has_dockerfile=True, dockerfile_paths=["Dockerfile"]),
        )
        assert profile.has_docker

    def test_ci_providers_property(self) -> None:
        profile = InfraProfile(
            root="/dummy/root",
            ci_configs=[
                CIConfig(provider=CIProvider.GITHUB_ACTIONS, file_path="ci.yml"),
                CIConfig(provider=CIProvider.GITLAB_CI, file_path=".gitlab-ci.yml"),
            ],
        )
        assert profile.ci_providers == ["github_actions", "gitlab_ci"]


# ---------------------------------------------------------------------------
# InfraDetector agent
# ---------------------------------------------------------------------------


class TestInfraDetectorAgent:
    def test_agent_properties(self) -> None:
        agent = InfraDetector()
        assert agent.name == "infra-detector"
        assert "CI" in agent.description or "infra" in agent.description.lower()

    def test_agent_run_success(self, tmp_path: Path) -> None:
        _write_file(tmp_path, ".github/workflows/ci.yml", "steps:\n  - run: npm test\n")
        _make_files(tmp_path, ["Dockerfile"])

        agent = InfraDetector()
        task = TaskInput(task_type="detect-infra", target=str(tmp_path))
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.COMPLETED
        assert output.result["has_ci"] is True
        assert output.result["has_docker"] is True

    def test_agent_run_invalid_target(self) -> None:
        agent = InfraDetector()
        task = TaskInput(task_type="detect-infra", target="/nonexistent/path")
        output = asyncio.run(agent.run(task))
        assert output.status == TaskStatus.FAILED
        assert len(output.errors) > 0

    def test_agent_run_empty_directory(self, tmp_path: Path) -> None:
        agent = InfraDetector()
        task = TaskInput(task_type="detect-infra", target=str(tmp_path))
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.COMPLETED
        assert output.result["has_ci"] is False
        assert output.result["has_docker"] is False

    def test_agent_run_with_skip_dirs(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["scripts/test.sh", "hidden/scripts/deploy.sh"])

        agent = InfraDetector()
        task = TaskInput(
            task_type="detect-infra",
            target=str(tmp_path),
            context={"skip_dirs": ["hidden"]},
        )
        output = asyncio.run(agent.run(task))
        assert output.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_invalid_yaml_in_ci_config(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            ".github/workflows/bad.yml",
            "this is: [not: valid: yaml: {{{\n",
        )
        # Should not crash — gracefully handles malformed YAML
        profile = detect_infra(tmp_path)
        assert profile.has_ci
        assert profile.ci_configs[0].provider == CIProvider.GITHUB_ACTIONS

    def test_empty_workflows_directory(self, tmp_path: Path) -> None:
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        profile = detect_infra(tmp_path)
        assert not profile.has_ci

    def test_not_a_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.touch()
        with pytest.raises(ValueError, match="Not a directory"):
            detect_infra(f)

    def test_malformed_package_json(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "package.json", "not json at all {{{")
        profile = detect_infra(tmp_path)
        npm_scripts = [s for s in profile.scripts if s.script_type == "npm_script"]
        assert npm_scripts == []

    def test_realistic_project(self, tmp_path: Path) -> None:
        """A realistic project with multiple infra components."""
        _write_file(
            tmp_path,
            ".github/workflows/ci.yml",
            "steps:\n  - run: npm test\n  - run: npm run build\n",
        )
        _make_files(tmp_path, ["Dockerfile", "docker-compose.yml", "Makefile"])
        _write_file(tmp_path, "Makefile", "test:\n\tpytest\n")
        _write_package_json(
            tmp_path,
            {"scripts": {"test": "vitest", "build": "tsc"}},
        )
        _make_files(tmp_path, ["scripts/deploy.sh"])

        profile = detect_infra(tmp_path)
        assert profile.has_ci
        assert profile.has_docker
        assert len(profile.makefiles) >= 1
        assert len(profile.scripts) > 0
        assert len(profile.test_commands) > 0
