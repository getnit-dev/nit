"""Tests for the WorkspaceDetector agent and detect_workspace function."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from nit.agents.base import TaskInput, TaskStatus
from nit.agents.detectors.workspace import (
    PackageInfo,
    WorkspaceDetector,
    WorkspaceProfile,
    detect_workspace,
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
# detect_workspace — single-repo / generic fallback
# ---------------------------------------------------------------------------


class TestGenericSingleRepo:
    def test_empty_directory(self, tmp_path: Path) -> None:
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"
        assert len(profile.packages) == 1
        assert profile.packages[0].path == "."
        assert profile.packages[0].name == tmp_path.name
        assert not profile.is_monorepo

    def test_not_a_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.touch()
        with pytest.raises(ValueError, match="Not a directory"):
            detect_workspace(f)

    def test_single_repo_with_package_json(self, tmp_path: Path) -> None:
        _write_package_json(tmp_path, {"name": "my-app"})
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"
        assert profile.packages[0].name == "my-app"
        assert not profile.is_monorepo

    def test_single_repo_with_pyproject_toml(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pyproject.toml",
            '[project]\nname = "my-lib"\nversion = "0.1.0"\n',
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"
        assert profile.packages[0].name == "my-lib"

    def test_single_repo_with_cargo_toml(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "Cargo.toml",
            '[package]\nname = "my-crate"\nversion = "0.1.0"\n',
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"
        assert profile.packages[0].name == "my-crate"

    def test_single_repo_with_go_mod(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "go.mod",
            "module github.com/user/repo\n\ngo 1.21\n",
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"
        assert profile.packages[0].name == "github.com/user/repo"


# ---------------------------------------------------------------------------
# Turborepo detection
# ---------------------------------------------------------------------------


class TestTurborepoDetection:
    def test_turbo_json_with_pnpm_workspace(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "turbo.json", '{"pipeline": {}}')
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            "packages:\n  - 'packages/*'\n",
        )
        _write_package_json(tmp_path / "packages" / "ui", {"name": "@repo/ui"})
        _write_package_json(tmp_path / "packages" / "api", {"name": "@repo/api"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "turborepo"
        assert profile.is_monorepo
        names = {pkg.name for pkg in profile.packages}
        assert "@repo/ui" in names
        assert "@repo/api" in names

    def test_turbo_json_with_npm_workspaces(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "turbo.json", "{}")
        _write_package_json(
            tmp_path,
            {"name": "root", "workspaces": ["apps/*"]},
        )
        _write_package_json(tmp_path / "apps" / "web", {"name": "web"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "turborepo"
        names = [pkg.name for pkg in profile.packages]
        assert "web" in names

    def test_turbo_json_no_packages(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "turbo.json", "{}")
        profile = detect_workspace(tmp_path)
        assert profile.tool == "turborepo"
        assert profile.packages == []


# ---------------------------------------------------------------------------
# Nx detection
# ---------------------------------------------------------------------------


class TestNxDetection:
    def test_nx_json_with_workspaces(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "nx.json", "{}")
        _write_package_json(
            tmp_path,
            {"name": "root", "workspaces": ["packages/*"]},
        )
        _write_package_json(tmp_path / "packages" / "core", {"name": "@nx/core"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "nx"
        assert profile.packages[0].name == "@nx/core"

    def test_nx_json_with_conventional_dirs(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "nx.json", "{}")
        (tmp_path / "apps" / "web").mkdir(parents=True)
        (tmp_path / "libs" / "shared").mkdir(parents=True)
        _write_package_json(tmp_path / "apps" / "web", {"name": "web"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "nx"
        names = {pkg.name for pkg in profile.packages}
        assert "web" in names
        assert "shared" in names


# ---------------------------------------------------------------------------
# pnpm detection
# ---------------------------------------------------------------------------


class TestPnpmDetection:
    def test_pnpm_workspace_yaml(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            "packages:\n  - 'packages/*'\n  - 'apps/*'\n",
        )
        _write_package_json(tmp_path / "packages" / "utils", {"name": "utils"})
        _write_package_json(tmp_path / "apps" / "web", {"name": "web"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "pnpm"
        assert profile.is_monorepo
        names = {pkg.name for pkg in profile.packages}
        assert "utils" in names
        assert "web" in names

    def test_pnpm_workspace_no_matches(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            "packages:\n  - 'nonexistent/*'\n",
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "pnpm"
        assert profile.packages == []

    def test_pnpm_workspace_quoted_globs(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            'packages:\n  - "packages/*"\n',
        )
        _write_package_json(tmp_path / "packages" / "a", {"name": "a"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "pnpm"
        assert len(profile.packages) == 1
        assert profile.packages[0].name == "a"


# ---------------------------------------------------------------------------
# Yarn detection
# ---------------------------------------------------------------------------


class TestYarnDetection:
    def test_yarn_workspaces_list(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {"name": "root", "workspaces": ["packages/*"]},
        )
        (tmp_path / "yarn.lock").touch()
        _write_package_json(tmp_path / "packages" / "core", {"name": "core"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "yarn"
        assert profile.packages[0].name == "core"

    def test_yarn_workspaces_object(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {
                "name": "root",
                "workspaces": {"packages": ["libs/*"], "nohoist": ["**/react"]},
            },
        )
        (tmp_path / "yarn.lock").touch()
        _write_package_json(tmp_path / "libs" / "shared", {"name": "shared"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "yarn"
        assert profile.packages[0].name == "shared"

    def test_yarn_needs_lock_file(self, tmp_path: Path) -> None:
        """Without yarn.lock, should fall through to npm detection."""
        _write_package_json(
            tmp_path,
            {"name": "root", "workspaces": ["packages/*"]},
        )
        _write_package_json(tmp_path / "packages" / "a", {"name": "a"})

        profile = detect_workspace(tmp_path)
        # Falls through to npm since yarn.lock is missing.
        assert profile.tool == "npm"


# ---------------------------------------------------------------------------
# npm detection
# ---------------------------------------------------------------------------


class TestNpmDetection:
    def test_npm_workspaces(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {"name": "root", "workspaces": ["packages/*"]},
        )
        _write_package_json(tmp_path / "packages" / "lib", {"name": "lib"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "npm"
        assert profile.packages[0].name == "lib"

    def test_npm_workspaces_empty_list(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {"name": "root", "workspaces": []},
        )
        # Empty workspaces list → no match, falls to generic.
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"


# ---------------------------------------------------------------------------
# Cargo workspace detection
# ---------------------------------------------------------------------------


class TestCargoDetection:
    def test_cargo_workspace(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "Cargo.toml",
            '[workspace]\nmembers = ["crates/a", "crates/b"]\n',
        )
        _write_file(
            tmp_path / "crates" / "a",
            "Cargo.toml",
            '[package]\nname = "crate-a"\nversion = "0.1.0"\n',
        )
        _write_file(
            tmp_path / "crates" / "b",
            "Cargo.toml",
            '[package]\nname = "crate-b"\nversion = "0.1.0"\n',
        )

        profile = detect_workspace(tmp_path)
        assert profile.tool == "cargo"
        assert profile.is_monorepo
        names = {pkg.name for pkg in profile.packages}
        assert "crate-a" in names
        assert "crate-b" in names

    def test_cargo_no_workspace_section(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "Cargo.toml",
            '[package]\nname = "single"\nversion = "0.1.0"\n',
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"
        assert profile.packages[0].name == "single"

    def test_cargo_workspace_with_glob(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "Cargo.toml",
            '[workspace]\nmembers = ["crates/*"]\n',
        )
        _write_file(
            tmp_path / "crates" / "x",
            "Cargo.toml",
            '[package]\nname = "x"\nversion = "0.1.0"\n',
        )

        profile = detect_workspace(tmp_path)
        assert profile.tool == "cargo"
        assert profile.packages[0].name == "x"


# ---------------------------------------------------------------------------
# Go workspace detection
# ---------------------------------------------------------------------------


class TestGoDetection:
    def test_go_work(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "go.work",
            "go 1.21\n\nuse (\n    ./svc-a\n    ./svc-b\n)\n",
        )
        _write_file(
            tmp_path / "svc-a",
            "go.mod",
            "module github.com/user/svc-a\n\ngo 1.21\n",
        )
        _write_file(
            tmp_path / "svc-b",
            "go.mod",
            "module github.com/user/svc-b\n\ngo 1.21\n",
        )

        profile = detect_workspace(tmp_path)
        assert profile.tool == "go"
        assert profile.is_monorepo
        names = {pkg.name for pkg in profile.packages}
        assert "github.com/user/svc-a" in names
        assert "github.com/user/svc-b" in names

    def test_go_work_single_use(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "go.work", "go 1.21\n\nuse ./mymod\n")
        _write_file(
            tmp_path / "mymod",
            "go.mod",
            "module github.com/user/mymod\n\ngo 1.21\n",
        )

        profile = detect_workspace(tmp_path)
        assert profile.tool == "go"
        assert profile.packages[0].name == "github.com/user/mymod"


# ---------------------------------------------------------------------------
# Gradle multi-project detection
# ---------------------------------------------------------------------------


class TestGradleDetection:
    def test_settings_gradle_kts(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "settings.gradle.kts",
            'rootProject.name = "my-project"\ninclude(":app")\ninclude(":lib")\n',
        )
        (tmp_path / "app").mkdir()
        (tmp_path / "lib").mkdir()

        profile = detect_workspace(tmp_path)
        assert profile.tool == "gradle"
        assert profile.is_monorepo
        paths = {pkg.path for pkg in profile.packages}
        assert "app" in paths
        assert "lib" in paths

    def test_settings_gradle_groovy(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "settings.gradle",
            "rootProject.name = 'my-project'\ninclude ':core'\ninclude ':web'\n",
        )
        (tmp_path / "core").mkdir()
        (tmp_path / "web").mkdir()

        profile = detect_workspace(tmp_path)
        assert profile.tool == "gradle"
        paths = {pkg.path for pkg in profile.packages}
        assert "core" in paths
        assert "web" in paths


# ---------------------------------------------------------------------------
# Maven multi-module detection
# ---------------------------------------------------------------------------


class TestMavenDetection:
    def test_pom_xml_modules(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pom.xml",
            (
                "<project>\n"
                "  <modules>\n"
                "    <module>core</module>\n"
                "    <module>web</module>\n"
                "  </modules>\n"
                "</project>\n"
            ),
        )
        _write_file(
            tmp_path / "core",
            "pom.xml",
            "<project><artifactId>core</artifactId></project>",
        )
        _write_file(
            tmp_path / "web",
            "pom.xml",
            "<project><artifactId>web</artifactId></project>",
        )

        profile = detect_workspace(tmp_path)
        assert profile.tool == "maven"
        assert profile.is_monorepo
        names = {pkg.name for pkg in profile.packages}
        assert "core" in names
        assert "web" in names

    def test_pom_without_modules(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pom.xml",
            "<project><artifactId>single</artifactId></project>",
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"


# ---------------------------------------------------------------------------
# Bazel detection
# ---------------------------------------------------------------------------


class TestBazelDetection:
    def test_workspace_with_build_files(self, tmp_path: Path) -> None:
        (tmp_path / "WORKSPACE").touch()
        _make_files(
            tmp_path,
            ["pkg_a/BUILD", "pkg_a/main.go", "pkg_b/BUILD.bazel", "pkg_b/lib.py"],
        )

        profile = detect_workspace(tmp_path)
        assert profile.tool == "bazel"
        paths = {pkg.path for pkg in profile.packages}
        assert "pkg_a" in paths
        assert "pkg_b" in paths

    def test_module_bazel(self, tmp_path: Path) -> None:
        (tmp_path / "MODULE.bazel").touch()
        _make_files(tmp_path, ["lib/BUILD"])

        profile = detect_workspace(tmp_path)
        assert profile.tool == "bazel"
        assert len(profile.packages) == 1
        assert profile.packages[0].path == "lib"

    def test_bazel_skips_skip_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "WORKSPACE").touch()
        _make_files(tmp_path, ["node_modules/foo/BUILD", "src/BUILD"])

        profile = detect_workspace(tmp_path)
        paths = {pkg.path for pkg in profile.packages}
        assert "src" in paths
        assert "node_modules/foo" not in paths


# ---------------------------------------------------------------------------
# CMake multi-project detection
# ---------------------------------------------------------------------------


class TestCMakeDetection:
    def test_cmake_add_subdirectory(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "cmake_minimum_required(VERSION 3.20)\n"
            "project(root)\n"
            "add_subdirectory(lib_a)\n"
            "add_subdirectory(lib_b)\n",
        )
        (tmp_path / "lib_a").mkdir()
        (tmp_path / "lib_b").mkdir()

        profile = detect_workspace(tmp_path)
        assert profile.tool == "cmake"
        assert profile.is_monorepo
        paths = {pkg.path for pkg in profile.packages}
        assert "lib_a" in paths
        assert "lib_b" in paths

    def test_cmake_no_subdirectories(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "cmake_minimum_required(VERSION 3.20)\nproject(single)\n",
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"


# ---------------------------------------------------------------------------
# Priority / ordering
# ---------------------------------------------------------------------------


class TestDetectionPriority:
    def test_turborepo_takes_precedence_over_pnpm(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "turbo.json", "{}")
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            "packages:\n  - 'packages/*'\n",
        )
        _write_package_json(tmp_path / "packages" / "a", {"name": "a"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "turborepo"

    def test_nx_takes_precedence_over_npm(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "nx.json", "{}")
        _write_package_json(
            tmp_path,
            {"name": "root", "workspaces": ["packages/*"]},
        )
        _write_package_json(tmp_path / "packages" / "b", {"name": "b"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "nx"

    def test_yarn_before_npm_when_lock_exists(self, tmp_path: Path) -> None:
        _write_package_json(
            tmp_path,
            {"name": "root", "workspaces": ["packages/*"]},
        )
        (tmp_path / "yarn.lock").touch()
        _write_package_json(tmp_path / "packages" / "c", {"name": "c"})

        profile = detect_workspace(tmp_path)
        assert profile.tool == "yarn"


# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------


class TestDependencyGraph:
    def test_js_internal_deps(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            "packages:\n  - 'packages/*'\n",
        )
        _write_package_json(
            tmp_path / "packages" / "ui",
            {"name": "@repo/ui", "dependencies": {"@repo/utils": "workspace:*"}},
        )
        _write_package_json(
            tmp_path / "packages" / "utils",
            {"name": "@repo/utils"},
        )

        profile = detect_workspace(tmp_path)
        ui_pkg = next(p for p in profile.packages if p.name == "@repo/ui")
        assert "@repo/utils" in ui_pkg.dependencies

    def test_cargo_internal_deps(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "Cargo.toml",
            '[workspace]\nmembers = ["crates/a", "crates/b"]\n',
        )
        _write_file(
            tmp_path / "crates" / "a",
            "Cargo.toml",
            '[package]\nname = "a"\nversion = "0.1.0"\n\n'
            "[dependencies]\n"
            'b = { path = "../b" }\n',
        )
        _write_file(
            tmp_path / "crates" / "b",
            "Cargo.toml",
            '[package]\nname = "b"\nversion = "0.1.0"\n',
        )

        profile = detect_workspace(tmp_path)
        a_pkg = next(p for p in profile.packages if p.name == "a")
        assert "b" in a_pkg.dependencies

    def test_maven_internal_deps(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pom.xml",
            (
                "<project>\n"
                "  <modules>\n"
                "    <module>core</module>\n"
                "    <module>web</module>\n"
                "  </modules>\n"
                "</project>\n"
            ),
        )
        _write_file(
            tmp_path / "core",
            "pom.xml",
            "<project><artifactId>core</artifactId></project>",
        )
        _write_file(
            tmp_path / "web",
            "pom.xml",
            (
                "<project>\n"
                "  <artifactId>web</artifactId>\n"
                "  <dependencies>\n"
                "    <dependency><artifactId>core</artifactId></dependency>\n"
                "  </dependencies>\n"
                "</project>\n"
            ),
        )

        profile = detect_workspace(tmp_path)
        web_pkg = next(p for p in profile.packages if p.name == "web")
        assert "core" in web_pkg.dependencies

    def test_no_self_dependency(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            "packages:\n  - 'packages/*'\n",
        )
        _write_package_json(
            tmp_path / "packages" / "x",
            {"name": "x", "dependencies": {"x": "workspace:*"}},
        )

        profile = detect_workspace(tmp_path)
        x_pkg = profile.packages[0]
        assert "x" not in x_pkg.dependencies


# ---------------------------------------------------------------------------
# Dataclass behaviour
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_package_info_defaults(self) -> None:
        pkg = PackageInfo(name="foo", path=".")
        assert pkg.dependencies == []

    def test_workspace_profile_is_monorepo(self, tmp_path: Path) -> None:
        single = WorkspaceProfile(
            tool="generic",
            root=str(tmp_path),
            packages=[PackageInfo(name="x", path=".")],
        )
        assert not single.is_monorepo

        multi = WorkspaceProfile(
            tool="pnpm",
            root=str(tmp_path),
            packages=[
                PackageInfo(name="a", path="packages/a"),
                PackageInfo(name="b", path="packages/b"),
            ],
        )
        assert multi.is_monorepo


# ---------------------------------------------------------------------------
# Agent interface
# ---------------------------------------------------------------------------


class TestWorkspaceDetectorAgent:
    def test_agent_properties(self) -> None:
        agent = WorkspaceDetector()
        assert agent.name == "workspace-detector"
        assert "workspace" in agent.description.lower()

    def test_agent_run_generic(self, tmp_path: Path) -> None:
        _write_package_json(tmp_path, {"name": "solo-app"})
        agent = WorkspaceDetector()
        output = asyncio.run(agent.run(TaskInput(task_type="detect", target=str(tmp_path))))
        assert output.status == TaskStatus.COMPLETED
        assert output.result["tool"] == "generic"
        assert output.result["is_monorepo"] is False
        assert len(output.result["packages"]) == 1
        assert output.result["packages"][0]["name"] == "solo-app"

    def test_agent_run_monorepo(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            "packages:\n  - 'pkgs/*'\n",
        )
        _write_package_json(tmp_path / "pkgs" / "a", {"name": "a"})
        _write_package_json(tmp_path / "pkgs" / "b", {"name": "b"})

        agent = WorkspaceDetector()
        output = asyncio.run(agent.run(TaskInput(task_type="detect", target=str(tmp_path))))
        assert output.status == TaskStatus.COMPLETED
        assert output.result["tool"] == "pnpm"
        assert output.result["is_monorepo"] is True
        names = {pkg["name"] for pkg in output.result["packages"]}
        assert names == {"a", "b"}

    def test_agent_run_invalid_target(self, tmp_path: Path) -> None:
        agent = WorkspaceDetector()
        output = asyncio.run(
            agent.run(TaskInput(task_type="detect", target=str(tmp_path / "nonexistent")))
        )
        assert output.status == TaskStatus.FAILED
        assert output.errors

    def test_agent_run_with_skip_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "WORKSPACE").touch()
        _make_files(tmp_path, ["src/BUILD"])

        agent = WorkspaceDetector()
        output = asyncio.run(
            agent.run(
                TaskInput(
                    task_type="detect",
                    target=str(tmp_path),
                    context={"skip_dirs": [".git", "node_modules"]},
                )
            )
        )
        assert output.status == TaskStatus.COMPLETED
        assert output.result["tool"] == "bazel"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_duplicate_packages_are_deduped(self, tmp_path: Path) -> None:
        """Ensure the same directory isn't listed twice."""
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            "packages:\n  - 'packages/*'\n  - 'packages/a'\n",
        )
        _write_package_json(tmp_path / "packages" / "a", {"name": "a"})

        profile = detect_workspace(tmp_path)
        # Normalize paths to forward slashes for cross-platform comparison
        paths = [pkg.path.replace("\\", "/") for pkg in profile.packages]
        assert paths.count("packages/a") == 1

    def test_nonexistent_workspace_members_ignored(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "Cargo.toml",
            '[workspace]\nmembers = ["exists", "gone"]\n',
        )
        (tmp_path / "exists").mkdir()
        _write_file(
            tmp_path / "exists",
            "Cargo.toml",
            '[package]\nname = "exists"\nversion = "0.1.0"\n',
        )

        profile = detect_workspace(tmp_path)
        assert profile.tool == "cargo"
        assert len(profile.packages) == 1
        assert profile.packages[0].name == "exists"

    def test_root_path_stored_as_string(self, tmp_path: Path) -> None:
        profile = detect_workspace(tmp_path)
        assert isinstance(profile.root, str)
        assert profile.root == str(tmp_path)


# ---------------------------------------------------------------------------
# Coverage gap tests — gradle settings.gradle name extraction
# ---------------------------------------------------------------------------


class TestGradleSettingsName:
    def test_gradle_settings_name(self, tmp_path: Path) -> None:
        """Test name extraction from settings.gradle rootProject.name."""
        _write_file(
            tmp_path,
            "settings.gradle",
            "rootProject.name = 'my-gradle-app'\n",
        )
        profile = detect_workspace(tmp_path)
        # Should use the rootProject.name from settings.gradle
        assert profile.packages[0].name == "my-gradle-app"

    def test_gradle_settings_kts_name(self, tmp_path: Path) -> None:
        """Test name extraction from settings.gradle.kts rootProject.name."""
        _write_file(
            tmp_path,
            "settings.gradle.kts",
            'rootProject.name = "my-kts-app"\n',
        )
        profile = detect_workspace(tmp_path)
        assert profile.packages[0].name == "my-kts-app"


# ---------------------------------------------------------------------------
# Coverage gap tests — pnpm workspace parsing edge cases
# ---------------------------------------------------------------------------


class TestPnpmWorkspaceParsing:
    def test_pnpm_workspace_yaml_comment_stops_parsing(self, tmp_path: Path) -> None:
        """Non-list line that isn't a comment stops parsing packages."""
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            "packages:\n  - 'packages/*'\nanother_key:\n  - ignored\n",
        )
        _write_package_json(tmp_path / "packages" / "x", {"name": "x"})
        profile = detect_workspace(tmp_path)
        assert profile.tool == "pnpm"
        assert len(profile.packages) == 1

    def test_pnpm_workspace_yaml_with_empty_items(self, tmp_path: Path) -> None:
        """Empty pattern values should be skipped."""
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            "packages:\n  - ''\n  - 'packages/*'\n",
        )
        _write_package_json(tmp_path / "packages" / "y", {"name": "y"})
        profile = detect_workspace(tmp_path)
        assert profile.tool == "pnpm"


# ---------------------------------------------------------------------------
# Coverage gap tests — yarn/npm workspaces object form
# ---------------------------------------------------------------------------


class TestWorkspacesObjectForm:
    def test_yarn_workspaces_dict_packages_key(self, tmp_path: Path) -> None:
        """Yarn workspaces as dict with packages key."""
        _write_package_json(
            tmp_path,
            {
                "name": "root",
                "workspaces": {"packages": ["packages/*"]},
            },
        )
        (tmp_path / "yarn.lock").touch()
        _write_package_json(tmp_path / "packages" / "z", {"name": "z"})
        profile = detect_workspace(tmp_path)
        assert profile.tool == "yarn"
        assert profile.packages[0].name == "z"

    def test_npm_workspaces_dict_form(self, tmp_path: Path) -> None:
        """npm workspaces as object with packages key."""
        _write_package_json(
            tmp_path,
            {
                "name": "root",
                "workspaces": {"packages": ["libs/*"]},
            },
        )
        _write_package_json(tmp_path / "libs" / "core", {"name": "core"})
        profile = detect_workspace(tmp_path)
        assert profile.tool == "npm"
        assert profile.packages[0].name == "core"

    def test_npm_workspaces_dict_no_list(self, tmp_path: Path) -> None:
        """npm workspaces object with packages that isn't a list."""
        _write_package_json(
            tmp_path,
            {
                "name": "root",
                "workspaces": {"packages": "not-a-list"},
            },
        )
        # Empty patterns -> no packages -> falls to generic
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"


# ---------------------------------------------------------------------------
# Coverage gap tests — Go work single use with comment
# ---------------------------------------------------------------------------


class TestGoWorkEdgeCases:
    def test_go_work_comments_skipped(self, tmp_path: Path) -> None:
        """Go work file with comments in use block."""
        _write_file(
            tmp_path,
            "go.work",
            "go 1.21\n\nuse (\n    // comment\n    ./mod-a\n)\n",
        )
        _write_file(
            tmp_path / "mod-a",
            "go.mod",
            "module github.com/user/mod-a\n\ngo 1.21\n",
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "go"
        assert len(profile.packages) == 1


# ---------------------------------------------------------------------------
# Coverage gap tests — Gradle/Maven edge cases
# ---------------------------------------------------------------------------


class TestGradleMavenEdgeCases:
    def test_gradle_settings_no_includes(self, tmp_path: Path) -> None:
        """settings.gradle with no include directives falls to generic."""
        _write_file(
            tmp_path,
            "settings.gradle",
            "rootProject.name = 'solo'\n",
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"

    def test_maven_pom_read_error(self, tmp_path: Path) -> None:
        """Maven pom.xml that can't be parsed falls to generic."""
        _write_file(
            tmp_path,
            "pom.xml",
            "<project><name>no-modules</name></project>",
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "generic"


# ---------------------------------------------------------------------------
# Coverage gap tests — cmake no subdirectory dirs
# ---------------------------------------------------------------------------


class TestCMakeEdgeCases:
    def test_cmake_subdirectory_not_exists(self, tmp_path: Path) -> None:
        """CMake add_subdirectory pointing to nonexistent dirs."""
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "cmake_minimum_required(VERSION 3.20)\n"
            "project(root)\n"
            "add_subdirectory(nonexistent)\n",
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "cmake"
        assert profile.packages == []


# ---------------------------------------------------------------------------
# Coverage gap tests — resolve JS workspace packages
# ---------------------------------------------------------------------------


class TestResolveJSWorkspacePackages:
    def test_turborepo_with_package_json_workspaces_dict(self, tmp_path: Path) -> None:
        """Turborepo resolves packages from package.json workspaces object."""
        _write_file(tmp_path, "turbo.json", "{}")
        _write_package_json(
            tmp_path,
            {"name": "root", "workspaces": {"packages": ["pkgs/*"]}},
        )
        _write_package_json(tmp_path / "pkgs" / "ui", {"name": "ui"})
        profile = detect_workspace(tmp_path)
        assert profile.tool == "turborepo"
        assert len(profile.packages) == 1
        assert profile.packages[0].name == "ui"


# ---------------------------------------------------------------------------
# Coverage gap tests — dependency graph: Go and Python deps
# ---------------------------------------------------------------------------


class TestDependencyGraphExtended:
    def test_go_internal_deps(self, tmp_path: Path) -> None:
        """Go workspace with internal module dependencies."""
        _write_file(
            tmp_path,
            "go.work",
            "go 1.21\n\nuse (\n    ./svc-a\n    ./svc-b\n)\n",
        )
        _write_file(
            tmp_path / "svc-a",
            "go.mod",
            (
                "module github.com/user/svc-a\n\ngo 1.21\n\nrequire (\n"
                "    github.com/user/svc-b v0.1.0\n)\n"
            ),
        )
        _write_file(
            tmp_path / "svc-b",
            "go.mod",
            "module github.com/user/svc-b\n\ngo 1.21\n",
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "go"
        a_pkg = next(p for p in profile.packages if p.name == "github.com/user/svc-a")
        assert "github.com/user/svc-b" in a_pkg.dependencies

    def test_python_internal_deps(self, tmp_path: Path) -> None:
        """pnpm workspace with Python pyproject.toml internal deps."""
        _write_file(
            tmp_path,
            "pnpm-workspace.yaml",
            "packages:\n  - 'packages/*'\n",
        )
        # Package A depends on Package B
        pkg_a = tmp_path / "packages" / "a"
        pkg_a.mkdir(parents=True)
        _write_package_json(pkg_a, {"name": "a"})
        _write_file(
            pkg_a,
            "pyproject.toml",
            '[project]\nname = "a"\ndependencies = ["b"]\n',
        )
        pkg_b = tmp_path / "packages" / "b"
        pkg_b.mkdir(parents=True)
        _write_package_json(pkg_b, {"name": "b"})

        profile = detect_workspace(tmp_path)
        a_pkg = next(p for p in profile.packages if p.name == "a")
        assert "b" in a_pkg.dependencies

    def test_pom_xml_name_from_dir(self, tmp_path: Path) -> None:
        """Package name from pom.xml artifactId."""
        _write_file(
            tmp_path,
            "pom.xml",
            "<project>\n  <modules><module>svc</module></modules>\n</project>\n",
        )
        _write_file(
            tmp_path / "svc",
            "pom.xml",
            "<project><artifactId>svc-core</artifactId></project>",
        )
        profile = detect_workspace(tmp_path)
        assert profile.tool == "maven"
        assert profile.packages[0].name == "svc-core"


# ---------------------------------------------------------------------------
# Coverage gap tests — _read_json error path
# ---------------------------------------------------------------------------


class TestReadJsonEdgeCases:
    def test_read_json_nonexistent(self, tmp_path: Path) -> None:
        """_read_json returns {} on missing file (tested via package_json)."""
        # A directory with no package.json should still resolve its name
        profile = detect_workspace(tmp_path)
        assert profile.packages[0].name == tmp_path.name

    def test_read_json_invalid_json(self, tmp_path: Path) -> None:
        """_read_json returns {} on invalid JSON."""
        _write_file(tmp_path, "package.json", "NOT VALID JSON!!")
        profile = detect_workspace(tmp_path)
        # Falls back to directory name since package.json can't be parsed
        assert profile.packages[0].name == tmp_path.name
