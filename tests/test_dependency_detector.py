"""Tests for the DependencyDetector agent and detect_dependencies function."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from nit.agents.base import TaskInput, TaskStatus
from nit.agents.detectors.dependency import (
    DeclaredDependency,
    DependencyDetector,
    DependencyProfile,
    DependencySource,
    InternalDependency,
    detect_dependencies,
)
from nit.agents.detectors.workspace import PackageInfo, WorkspaceProfile

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


def _write_json(root: Path, rel: str, data: dict[str, object]) -> None:
    """Write a JSON file to *root/rel*."""
    _write_file(root, rel, json.dumps(data))


# ---------------------------------------------------------------------------
# Lock file detection
# ---------------------------------------------------------------------------


class TestLockFileDetection:
    def test_package_lock_json(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["package-lock.json"])
        profile = detect_dependencies(tmp_path)
        assert "package-lock.json" in profile.lock_files

    def test_yarn_lock(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["yarn.lock"])
        profile = detect_dependencies(tmp_path)
        assert "yarn.lock" in profile.lock_files

    def test_pnpm_lock_yaml(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["pnpm-lock.yaml"])
        profile = detect_dependencies(tmp_path)
        assert "pnpm-lock.yaml" in profile.lock_files

    def test_poetry_lock(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["poetry.lock"])
        profile = detect_dependencies(tmp_path)
        assert "poetry.lock" in profile.lock_files

    def test_pipfile_lock(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["Pipfile.lock"])
        profile = detect_dependencies(tmp_path)
        assert "Pipfile.lock" in profile.lock_files

    def test_go_sum(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["go.sum"])
        profile = detect_dependencies(tmp_path)
        assert "go.sum" in profile.lock_files

    def test_cargo_lock(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["Cargo.lock"])
        profile = detect_dependencies(tmp_path)
        assert "Cargo.lock" in profile.lock_files

    def test_gradle_lockfile(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["gradle.lockfile"])
        profile = detect_dependencies(tmp_path)
        assert "gradle.lockfile" in profile.lock_files

    def test_composer_lock(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["composer.lock"])
        profile = detect_dependencies(tmp_path)
        assert "composer.lock" in profile.lock_files

    def test_multiple_lock_files(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["package-lock.json", "yarn.lock", "poetry.lock"])
        profile = detect_dependencies(tmp_path)
        assert len(profile.lock_files) == 3

    def test_no_lock_files(self, tmp_path: Path) -> None:
        profile = detect_dependencies(tmp_path)
        assert profile.lock_files == []


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------


class TestManifestParsing:
    def test_package_json_deps(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path,
            "package.json",
            {
                "name": "my-app",
                "dependencies": {"react": "^18.0.0", "lodash": "^4.17.0"},
                "devDependencies": {"vitest": "^1.0.0"},
            },
        )
        profile = detect_dependencies(tmp_path)
        assert "package.json" in profile.manifest_files
        names = {d.name for d in profile.declared_deps}
        assert "react" in names
        assert "lodash" in names
        assert "vitest" in names
        vitest_dep = next(d for d in profile.declared_deps if d.name == "vitest")
        assert vitest_dep.is_dev
        react_dep = next(d for d in profile.declared_deps if d.name == "react")
        assert not react_dep.is_dev

    def test_pyproject_toml_deps(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pyproject.toml",
            '[project]\nname = "my-lib"\ndependencies = [\n  "requests",\n  "click",\n]\n',
        )
        profile = detect_dependencies(tmp_path)
        assert "pyproject.toml" in profile.manifest_files
        names = {d.name for d in profile.declared_deps}
        assert "requests" in names
        assert "click" in names

    def test_requirements_txt(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "requirements.txt",
            "requests==2.31.0\nflask>=2.0\n# comment\n\n-r other.txt\nclick\n",
        )
        profile = detect_dependencies(tmp_path)
        assert "requirements.txt" in profile.manifest_files
        names = {d.name for d in profile.declared_deps}
        assert "requests" in names
        assert "flask" in names
        assert "click" in names
        requests_dep = next(d for d in profile.declared_deps if d.name == "requests")
        assert requests_dep.version_spec == "==2.31.0"

    def test_go_mod_require(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "go.mod",
            (
                "module example.com/myapp\n\ngo 1.21\n\n"
                "require (\n"
                "\tgithub.com/gin-gonic/gin v1.9.0\n"
                "\tgithub.com/stretchr/testify v1.8.0\n"
                ")\n"
            ),
        )
        profile = detect_dependencies(tmp_path)
        assert "go.mod" in profile.manifest_files
        names = {d.name for d in profile.declared_deps}
        assert "github.com/gin-gonic/gin" in names
        assert "github.com/stretchr/testify" in names

    def test_cargo_toml_deps(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "Cargo.toml",
            (
                '[package]\nname = "my-crate"\n\n'
                "[dependencies]\n"
                'serde = "1.0"\n'
                'tokio = { version = "1.0" }\n\n'
                "[dev-dependencies]\n"
                'criterion = "0.5"\n'
            ),
        )
        profile = detect_dependencies(tmp_path)
        assert "Cargo.toml" in profile.manifest_files
        names = {d.name for d in profile.declared_deps}
        assert "serde" in names
        assert "tokio" in names
        assert "criterion" in names
        criterion_dep = next(d for d in profile.declared_deps if d.name == "criterion")
        assert criterion_dep.is_dev

    def test_build_gradle_deps(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "build.gradle",
            (
                'plugins {\n  id "java"\n}\n'
                "dependencies {\n"
                '  implementation "org.springframework:spring-core:5.3.0"\n'
                '  testImplementation "junit:junit:4.13"\n'
                "}\n"
            ),
        )
        profile = detect_dependencies(tmp_path)
        assert "build.gradle" in profile.manifest_files
        names = {d.name for d in profile.declared_deps}
        assert "org.springframework:spring-core" in names
        junit_dep = next(d for d in profile.declared_deps if "junit" in d.name)
        assert junit_dep.is_dev

    def test_pom_xml_deps(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pom.xml",
            (
                "<project>\n  <dependencies>\n"
                "    <dependency>\n"
                "      <groupId>org.springframework</groupId>\n"
                "      <artifactId>spring-core</artifactId>\n"
                "      <version>5.3.0</version>\n"
                "    </dependency>\n"
                "    <dependency>\n"
                "      <groupId>junit</groupId>\n"
                "      <artifactId>junit</artifactId>\n"
                "      <version>4.13</version>\n"
                "      <scope>test</scope>\n"
                "    </dependency>\n"
                "  </dependencies>\n</project>\n"
            ),
        )
        profile = detect_dependencies(tmp_path)
        assert "pom.xml" in profile.manifest_files
        names = {d.name for d in profile.declared_deps}
        assert "org.springframework:spring-core" in names
        junit_dep = next(d for d in profile.declared_deps if "junit:junit" in d.name)
        assert junit_dep.is_dev

    def test_composer_json_deps(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path,
            "composer.json",
            {
                "require": {"laravel/framework": "^10.0"},
                "require-dev": {"phpunit/phpunit": "^10.0"},
            },
        )
        profile = detect_dependencies(tmp_path)
        assert "composer.json" in profile.manifest_files
        names = {d.name for d in profile.declared_deps}
        assert "laravel/framework" in names
        phpunit_dep = next(d for d in profile.declared_deps if "phpunit" in d.name)
        assert phpunit_dep.is_dev


# ---------------------------------------------------------------------------
# Internal dependency mapping
# ---------------------------------------------------------------------------


class TestInternalDependencyMapping:
    def test_js_workspace_internal_deps(self, tmp_path: Path) -> None:
        # Create a workspace with two packages
        (tmp_path / "packages" / "core").mkdir(parents=True)
        (tmp_path / "packages" / "web").mkdir(parents=True)

        _write_json(
            tmp_path,
            "packages/core/package.json",
            {"name": "@myorg/core", "dependencies": {}},
        )
        _write_json(
            tmp_path,
            "packages/web/package.json",
            {
                "name": "@myorg/web",
                "dependencies": {"@myorg/core": "workspace:*", "react": "^18.0.0"},
            },
        )

        ws = WorkspaceProfile(
            tool="pnpm",
            root=str(tmp_path),
            packages=[
                PackageInfo(name="@myorg/core", path="packages/core"),
                PackageInfo(name="@myorg/web", path="packages/web"),
            ],
        )
        profile = detect_dependencies(tmp_path, workspace=ws)

        assert profile.internal_dep_count >= 1
        internal = profile.internal_deps[0]
        assert internal.from_package == "@myorg/web"
        assert internal.to_package == "@myorg/core"

    def test_no_internal_deps_single_repo(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path,
            "package.json",
            {"name": "my-app", "dependencies": {"react": "^18.0.0"}},
        )
        profile = detect_dependencies(tmp_path)
        assert profile.internal_dep_count == 0

    def test_cargo_workspace_internal_deps(self, tmp_path: Path) -> None:
        (tmp_path / "crates" / "core").mkdir(parents=True)
        (tmp_path / "crates" / "api").mkdir(parents=True)

        _write_file(
            tmp_path,
            "crates/core/Cargo.toml",
            '[package]\nname = "core"\n\n[dependencies]\n',
        )
        _write_file(
            tmp_path,
            "crates/api/Cargo.toml",
            '[package]\nname = "api"\n\n[dependencies]\ncore = { path = "../core" }\n',
        )

        ws = WorkspaceProfile(
            tool="cargo",
            root=str(tmp_path),
            packages=[
                PackageInfo(name="core", path="crates/core"),
                PackageInfo(name="api", path="crates/api"),
            ],
        )
        profile = detect_dependencies(tmp_path, workspace=ws)
        assert profile.internal_dep_count >= 1
        internal = profile.internal_deps[0]
        assert internal.from_package == "api"
        assert internal.to_package == "core"


# ---------------------------------------------------------------------------
# DependencyProfile properties
# ---------------------------------------------------------------------------


class TestDependencyProfile:
    def test_external_dep_count(self) -> None:
        profile = DependencyProfile(
            root="/dummy/root",
            declared_deps=[
                DeclaredDependency(name="react"),
                DeclaredDependency(name="lodash"),
            ],
        )
        assert profile.external_dep_count == 2

    def test_internal_dep_count(self) -> None:
        profile = DependencyProfile(
            root="/dummy/root",
            internal_deps=[
                InternalDependency(from_package="a", to_package="b"),
            ],
        )
        assert profile.internal_dep_count == 1

    def test_deps_for_package(self) -> None:
        profile = DependencyProfile(
            root="/dummy/root",
            declared_deps=[
                DeclaredDependency(name="react", package_path="packages/web"),
                DeclaredDependency(name="lodash", package_path="packages/core"),
                DeclaredDependency(name="express", package_path="packages/web"),
            ],
        )
        web_deps = profile.deps_for_package("packages/web")
        assert len(web_deps) == 2
        assert {d.name for d in web_deps} == {"react", "express"}

    def test_empty_profile(self) -> None:
        profile = DependencyProfile(root="/dummy/root")
        assert profile.external_dep_count == 0
        assert profile.internal_dep_count == 0
        assert profile.lock_files == []
        assert profile.manifest_files == []


# ---------------------------------------------------------------------------
# DependencyDetector agent
# ---------------------------------------------------------------------------


class TestDependencyDetectorAgent:
    def test_agent_properties(self) -> None:
        agent = DependencyDetector()
        assert agent.name == "dependency-detector"
        assert "dependency" in agent.description.lower() or "manifest" in agent.description.lower()

    def test_agent_run_success(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path,
            "package.json",
            {"name": "test-app", "dependencies": {"react": "^18.0.0"}},
        )
        _make_files(tmp_path, ["package-lock.json"])

        agent = DependencyDetector()
        task = TaskInput(task_type="detect-dependencies", target=str(tmp_path))
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.COMPLETED
        assert output.result["external_dep_count"] >= 1
        assert "package-lock.json" in output.result["lock_files"]

    def test_agent_run_invalid_target(self) -> None:
        agent = DependencyDetector()
        task = TaskInput(task_type="detect-dependencies", target="/nonexistent/path")
        output = asyncio.run(agent.run(task))
        assert output.status == TaskStatus.FAILED
        assert len(output.errors) > 0

    def test_agent_run_empty_directory(self, tmp_path: Path) -> None:
        agent = DependencyDetector()
        task = TaskInput(task_type="detect-dependencies", target=str(tmp_path))
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.COMPLETED
        assert output.result["external_dep_count"] == 0
        assert output.result["lock_files"] == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_project(self, tmp_path: Path) -> None:
        profile = detect_dependencies(tmp_path)
        assert profile.external_dep_count == 0
        assert profile.internal_dep_count == 0
        assert profile.lock_files == []
        assert profile.manifest_files == []

    def test_malformed_package_json(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "package.json", "not json {{{")
        profile = detect_dependencies(tmp_path)
        assert profile.declared_deps == []

    def test_malformed_requirements_txt(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "requirements.txt",
            "# just comments\n\n# and blank lines\nrequests\n",
        )
        profile = detect_dependencies(tmp_path)
        names = {d.name for d in profile.declared_deps}
        assert "requests" in names

    def test_not_a_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.touch()
        with pytest.raises(ValueError, match="Not a directory"):
            detect_dependencies(f)

    def test_monorepo_scans_all_packages(self, tmp_path: Path) -> None:
        (tmp_path / "packages" / "a").mkdir(parents=True)
        (tmp_path / "packages" / "b").mkdir(parents=True)

        _write_json(
            tmp_path,
            "packages/a/package.json",
            {"name": "pkg-a", "dependencies": {"react": "^18.0.0"}},
        )
        _write_json(
            tmp_path,
            "packages/b/package.json",
            {"name": "pkg-b", "dependencies": {"express": "^4.0.0"}},
        )

        ws = WorkspaceProfile(
            tool="npm",
            root=str(tmp_path),
            packages=[
                PackageInfo(name="pkg-a", path="packages/a"),
                PackageInfo(name="pkg-b", path="packages/b"),
            ],
        )
        profile = detect_dependencies(tmp_path, workspace=ws)
        names = {d.name for d in profile.declared_deps}
        assert "react" in names
        assert "express" in names
        assert len(profile.manifest_files) == 2

    def test_dependency_source_default(self) -> None:
        dep = DeclaredDependency(name="test")
        assert dep.source == DependencySource.MANIFEST
