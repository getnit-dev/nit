"""Tests for ProfileManager - per-package detection in monorepos."""

from pathlib import Path

import pytest

from nit.agents.detectors.workspace import PackageInfo
from nit.models.profile import ProjectProfile
from nit.models.profile_manager import PackageProfile, ProfileManager


@pytest.fixture
def temp_monorepo(tmp_path: Path) -> Path:
    """Create a temporary monorepo structure for testing."""
    # Create root package.json for pnpm workspace
    root_package_json = tmp_path / "package.json"
    root_package_json.write_text('{"name": "monorepo-root", "private": true}')

    # Create pnpm-workspace.yaml
    ws_yaml = tmp_path / "pnpm-workspace.yaml"
    ws_yaml.write_text("packages:\n  - packages/*\n")

    # Create package A (TypeScript)
    pkg_a = tmp_path / "packages" / "pkg-a"
    pkg_a.mkdir(parents=True)
    (pkg_a / "package.json").write_text(
        '{"name": "@monorepo/pkg-a", "devDependencies": {"vitest": "^1.0.0"}}'
    )
    (pkg_a / "vitest.config.ts").write_text('import { defineConfig } from "vitest"')
    (pkg_a / "src").mkdir()
    (pkg_a / "src" / "index.ts").write_text("export function hello() { return 'world'; }")

    # Create package B (Python)
    pkg_b = tmp_path / "packages" / "pkg-b"
    pkg_b.mkdir(parents=True)
    (pkg_b / "pyproject.toml").write_text(
        '[project]\nname = "pkg-b"\n\n[tool.pytest.ini_options]\n'
    )
    (pkg_b / "src").mkdir()
    (pkg_b / "src" / "main.py").write_text("def greet(): return 'hello'")

    return tmp_path


def test_profile_manager_init(tmp_path: Path) -> None:
    """Test ProfileManager initialization."""
    manager = ProfileManager(tmp_path)
    assert manager.project_root == tmp_path
    assert manager._package_profiles == {}


def test_profile_manager_single_repo(tmp_path: Path) -> None:
    """Test profile manager with single-repo project."""
    # Create simple Python project
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-project"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass")

    manager = ProfileManager(tmp_path)

    # Create a simple project profile
    profile = ProjectProfile(
        root=str(tmp_path),
        packages=[PackageInfo(name="test-project", path=".")],
        workspace_tool="generic",
    )

    package_profiles = manager.build_project_profile(profile)

    assert len(package_profiles) == 1
    assert "test-project" in package_profiles
    assert package_profiles["test-project"].path == "."


def test_profile_manager_monorepo(temp_monorepo: Path) -> None:
    """Test profile manager with monorepo."""
    manager = ProfileManager(temp_monorepo)

    # Create project profile with detected packages
    profile = ProjectProfile(
        root=str(temp_monorepo),
        packages=[
            PackageInfo(name="@monorepo/pkg-a", path="packages/pkg-a"),
            PackageInfo(name="pkg-b", path="packages/pkg-b"),
        ],
        workspace_tool="pnpm",
    )

    package_profiles = manager.build_project_profile(profile)

    assert len(package_profiles) == 2
    assert "@monorepo/pkg-a" in package_profiles
    assert "pkg-b" in package_profiles

    # Check package A profile
    pkg_a_profile = package_profiles["@monorepo/pkg-a"]
    assert pkg_a_profile.name == "@monorepo/pkg-a"
    assert pkg_a_profile.path == "packages/pkg-a"
    # Should detect TypeScript
    assert any(lang.language == "typescript" for lang in pkg_a_profile.languages)
    # Should detect vitest
    assert any(fw.name == "vitest" for fw in pkg_a_profile.frameworks)

    # Check package B profile
    pkg_b_profile = package_profiles["pkg-b"]
    assert pkg_b_profile.name == "pkg-b"
    assert pkg_b_profile.path == "packages/pkg-b"
    # Should detect Python
    assert any(lang.language == "python" for lang in pkg_b_profile.languages)
    # Should detect pytest
    assert any(fw.name == "pytest" for fw in pkg_b_profile.frameworks)


def test_profile_manager_get_package_profile(temp_monorepo: Path) -> None:
    """Test getting a specific package profile."""
    manager = ProfileManager(temp_monorepo)

    profile = ProjectProfile(
        root=str(temp_monorepo),
        packages=[
            PackageInfo(name="@monorepo/pkg-a", path="packages/pkg-a"),
            PackageInfo(name="pkg-b", path="packages/pkg-b"),
        ],
        workspace_tool="pnpm",
    )

    manager.build_project_profile(profile)

    pkg_a = manager.get_package_profile("@monorepo/pkg-a")
    assert pkg_a is not None
    assert pkg_a.name == "@monorepo/pkg-a"

    nonexistent = manager.get_package_profile("nonexistent")
    assert nonexistent is None


def test_profile_manager_filter_by_path(temp_monorepo: Path) -> None:
    """Test filtering packages by path."""
    manager = ProfileManager(temp_monorepo)

    profile = ProjectProfile(
        root=str(temp_monorepo),
        packages=[
            PackageInfo(name="@monorepo/pkg-a", path="packages/pkg-a"),
            PackageInfo(name="pkg-b", path="packages/pkg-b"),
        ],
        workspace_tool="pnpm",
    )

    manager.build_project_profile(profile)

    # Filter for pkg-a
    matches = manager.filter_packages_by_path("packages/pkg-a")
    assert len(matches) == 1
    assert matches[0].name == "@monorepo/pkg-a"

    # Filter for all packages
    all_matches = manager.filter_packages_by_path("packages")
    assert len(all_matches) == 2


def test_package_profile_to_dict() -> None:
    """Test PackageProfile serialization."""
    profile = PackageProfile(
        name="test-pkg",
        path="packages/test-pkg",
        dependencies=["dep1", "dep2"],
    )

    data = profile.to_dict()
    assert data["name"] == "test-pkg"
    assert data["path"] == "packages/test-pkg"
    assert data["dependencies"] == ["dep1", "dep2"]
    assert isinstance(data["languages"], list)
    assert isinstance(data["frameworks"], list)


def test_profile_manager_nonexistent_package(tmp_path: Path) -> None:
    """Test handling of nonexistent package directory."""
    manager = ProfileManager(tmp_path)

    profile = ProjectProfile(
        root=str(tmp_path),
        packages=[
            PackageInfo(name="nonexistent", path="packages/nonexistent"),
        ],
        workspace_tool="generic",
    )

    package_profiles = manager.build_project_profile(profile)

    assert len(package_profiles) == 1
    pkg_profile = package_profiles["nonexistent"]
    assert pkg_profile.name == "nonexistent"
    assert pkg_profile.languages == []
    assert pkg_profile.frameworks == []
