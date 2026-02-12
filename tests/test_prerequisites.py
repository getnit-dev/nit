"""Tests for prerequisite checking utilities."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nit.utils.prerequisites import (
    Environment,
    PackageManager,
    check_prerequisites,
    detect_node_environment,
    detect_package_manager,
    detect_python_environment,
    get_command_path,
    get_install_command,
    install_packages,
    is_package_installed,
)


class TestPackageManagerDetection:
    """Test package manager detection."""

    def test_detect_npm(self, tmp_path: Path) -> None:
        """Detect npm from package-lock.json."""
        (tmp_path / "package-lock.json").touch()
        assert detect_package_manager(tmp_path) == PackageManager.NPM

    def test_detect_yarn(self, tmp_path: Path) -> None:
        """Detect yarn from yarn.lock."""
        (tmp_path / "yarn.lock").touch()
        assert detect_package_manager(tmp_path) == PackageManager.YARN

    def test_detect_pnpm(self, tmp_path: Path) -> None:
        """Detect pnpm from pnpm-lock.yaml."""
        (tmp_path / "pnpm-lock.yaml").touch()
        assert detect_package_manager(tmp_path) == PackageManager.PNPM

    def test_detect_bun(self, tmp_path: Path) -> None:
        """Detect bun from bun.lockb."""
        (tmp_path / "bun.lockb").touch()
        assert detect_package_manager(tmp_path) == PackageManager.BUN

    def test_detect_pip(self, tmp_path: Path) -> None:
        """Detect pip from pyproject.toml."""
        (tmp_path / "pyproject.toml").touch()
        assert detect_package_manager(tmp_path) == PackageManager.PIP

    def test_detect_poetry(self, tmp_path: Path) -> None:
        """Detect poetry from poetry.lock."""
        (tmp_path / "poetry.lock").touch()
        assert detect_package_manager(tmp_path) == PackageManager.POETRY

    def test_detect_cargo(self, tmp_path: Path) -> None:
        """Detect cargo from Cargo.toml."""
        (tmp_path / "Cargo.toml").touch()
        assert detect_package_manager(tmp_path) == PackageManager.CARGO

    def test_no_package_manager(self, tmp_path: Path) -> None:
        """Return None when no package manager detected."""
        assert detect_package_manager(tmp_path) is None


class TestPythonEnvironmentDetection:
    """Test Python virtual environment detection."""

    def test_detect_venv(self, tmp_path: Path) -> None:
        """Detect .venv directory."""
        venv_path = tmp_path / ".venv"
        venv_bin = venv_path / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").touch()

        env = detect_python_environment(tmp_path)
        assert env is not None
        assert env.type == "python_venv"
        assert env.path == venv_path
        assert env.bin_path == venv_bin

    def test_detect_poetry(self, tmp_path: Path) -> None:
        """Detect Poetry environment."""
        (tmp_path / "poetry.lock").touch()

        env = detect_python_environment(tmp_path)
        assert env is not None
        assert env.type == "poetry"
        assert env.path == tmp_path

    def test_no_environment(self, tmp_path: Path) -> None:
        """Return None when no environment detected."""
        assert detect_python_environment(tmp_path) is None


class TestNodeEnvironmentDetection:
    """Test Node.js environment detection."""

    def test_detect_node_modules(self, tmp_path: Path) -> None:
        """Detect node_modules directory."""
        node_modules = tmp_path / "node_modules"
        node_modules_bin = node_modules / ".bin"
        node_modules_bin.mkdir(parents=True)

        env = detect_node_environment(tmp_path)
        assert env is not None
        assert env.type == "node_modules"
        assert env.path == node_modules
        assert env.bin_path == node_modules_bin

    def test_detect_package_json_without_modules(self, tmp_path: Path) -> None:
        """Detect package.json even without node_modules installed."""
        (tmp_path / "package.json").write_text("{}")

        env = detect_node_environment(tmp_path)
        assert env is not None
        assert env.type == "node_modules"
        assert env.path == tmp_path
        assert env.bin_path is None

    def test_no_environment(self, tmp_path: Path) -> None:
        """Return None when no environment detected."""
        assert detect_node_environment(tmp_path) is None


class TestCommandPath:
    """Test command path resolution."""

    def test_get_command_from_environment(self, tmp_path: Path) -> None:
        """Find command in environment bin path."""
        bin_path = tmp_path / "bin"
        bin_path.mkdir()
        pytest_path = bin_path / "pytest"
        pytest_path.touch()
        pytest_path.chmod(0o755)

        env = Environment(type="python_venv", path=tmp_path, bin_path=bin_path)
        result = get_command_path("pytest", env)
        assert result == pytest_path

    def test_command_not_in_environment(self, tmp_path: Path) -> None:
        """Return None when command not in environment."""
        bin_path = tmp_path / "bin"
        bin_path.mkdir()

        env = Environment(type="python_venv", path=tmp_path, bin_path=bin_path)
        result = get_command_path("nonexistent", env)
        # Will fall back to system PATH, might exist or not
        assert result is None or result.name == "nonexistent"


class TestPackageInstallation:
    """Test package installation checking."""

    @pytest.mark.asyncio
    async def test_npm_package_installed(self, tmp_path: Path) -> None:
        """Check if npm package is installed in node_modules."""
        node_modules = tmp_path / "node_modules"
        vitest_dir = node_modules / "vitest"
        vitest_dir.mkdir(parents=True)

        installed = await is_package_installed("vitest", PackageManager.NPM, tmp_path)
        assert installed is True

    @pytest.mark.asyncio
    async def test_npm_package_not_installed(self, tmp_path: Path) -> None:
        """Return False when package not in node_modules."""
        node_modules = tmp_path / "node_modules"
        node_modules.mkdir()

        installed = await is_package_installed("vitest", PackageManager.NPM, tmp_path)
        assert installed is False

    @pytest.mark.asyncio
    async def test_scoped_package_installed(self, tmp_path: Path) -> None:
        """Check if scoped package (@playwright/test) is installed."""
        node_modules = tmp_path / "node_modules"
        playwright_scope = node_modules / "@playwright"
        test_dir = playwright_scope / "test"
        test_dir.mkdir(parents=True)

        installed = await is_package_installed("@playwright/test", PackageManager.NPM, tmp_path)
        assert installed is True

    @pytest.mark.asyncio
    async def test_no_node_modules(self, tmp_path: Path) -> None:
        """Return False when node_modules doesn't exist."""
        installed = await is_package_installed("vitest", PackageManager.NPM, tmp_path)
        assert installed is False


# ── Additional coverage tests ─────────────────────────────────────────


class TestGetInstallCommand:
    """Test install command generation for all package managers."""

    def test_npm_dev(self) -> None:
        cmd = get_install_command(["vitest"], PackageManager.NPM, dev=True)
        assert cmd == "npm install --save-dev vitest"

    def test_npm_prod(self) -> None:
        cmd = get_install_command(["react"], PackageManager.NPM, dev=False)
        assert cmd == "npm install --save react"

    def test_yarn_dev(self) -> None:
        cmd = get_install_command(["vitest"], PackageManager.YARN, dev=True)
        assert cmd == "yarn add --dev vitest"

    def test_yarn_prod(self) -> None:
        cmd = get_install_command(["react"], PackageManager.YARN, dev=False)
        assert "yarn add" in cmd
        assert "react" in cmd

    def test_pnpm_dev(self) -> None:
        cmd = get_install_command(["vitest"], PackageManager.PNPM, dev=True)
        assert cmd == "pnpm add --save-dev vitest"

    def test_bun_dev(self) -> None:
        cmd = get_install_command(["vitest"], PackageManager.BUN, dev=True)
        assert cmd == "bun add --dev vitest"

    def test_pip(self) -> None:
        cmd = get_install_command(["pytest", "coverage"], PackageManager.PIP, dev=True)
        assert cmd == "pip install pytest coverage"

    def test_poetry_dev(self) -> None:
        cmd = get_install_command(["pytest"], PackageManager.POETRY, dev=True)
        assert cmd == "poetry add --group dev pytest"

    def test_poetry_prod(self) -> None:
        cmd = get_install_command(["requests"], PackageManager.POETRY, dev=False)
        assert "poetry add" in cmd
        assert "requests" in cmd

    def test_uv_dev(self) -> None:
        cmd = get_install_command(["pytest"], PackageManager.UV, dev=True)
        assert cmd == "uv add --dev pytest"

    def test_cargo_dev(self) -> None:
        cmd = get_install_command(["serde"], PackageManager.CARGO, dev=True)
        assert cmd == "cargo add --dev serde"

    def test_bundle(self) -> None:
        cmd = get_install_command(["rspec"], PackageManager.BUNDLE, dev=True)
        assert cmd == "bundle add rspec"

    def test_dotnet(self) -> None:
        cmd = get_install_command(["xunit"], PackageManager.DOTNET, dev=True)
        assert cmd == "dotnet add package xunit"

    def test_dotnet_empty_packages(self) -> None:
        cmd = get_install_command([], PackageManager.DOTNET, dev=True)
        assert cmd == ""

    def test_multiple_packages(self) -> None:
        cmd = get_install_command(["vitest", "msw"], PackageManager.NPM, dev=True)
        assert cmd == "npm install --save-dev vitest msw"


class TestPackageManagerDetectionExtended:
    """Extended package manager detection tests."""

    def test_detect_uv(self, tmp_path: Path) -> None:
        """Detect uv from uv.lock."""
        (tmp_path / "uv.lock").touch()
        assert detect_package_manager(tmp_path) == PackageManager.UV

    def test_detect_bundle(self, tmp_path: Path) -> None:
        """Detect bundle from Gemfile."""
        (tmp_path / "Gemfile").touch()
        assert detect_package_manager(tmp_path) == PackageManager.BUNDLE

    def test_detect_dotnet_csproj(self, tmp_path: Path) -> None:
        """Detect dotnet from .csproj file."""
        (tmp_path / "MyApp.csproj").touch()
        assert detect_package_manager(tmp_path) == PackageManager.DOTNET

    def test_detect_dotnet_fsproj(self, tmp_path: Path) -> None:
        """Detect dotnet from .fsproj file."""
        (tmp_path / "MyApp.fsproj").touch()
        assert detect_package_manager(tmp_path) == PackageManager.DOTNET

    def test_npm_from_package_json(self, tmp_path: Path) -> None:
        """Detect npm from package.json alone (no lock)."""
        (tmp_path / "package.json").write_text("{}")
        assert detect_package_manager(tmp_path) == PackageManager.NPM

    def test_pip_from_requirements_txt(self, tmp_path: Path) -> None:
        """Detect pip from requirements.txt."""
        (tmp_path / "requirements.txt").touch()
        assert detect_package_manager(tmp_path) == PackageManager.PIP


class TestPythonEnvDetectionExtended:
    """Extended Python environment detection tests."""

    def test_detect_venv_named_venv(self, tmp_path: Path) -> None:
        """Detect venv/ directory."""
        venv_path = tmp_path / "venv"
        bin_path = venv_path / "bin"
        bin_path.mkdir(parents=True)
        env = detect_python_environment(tmp_path)
        assert env is not None
        assert env.type == "python_venv"

    def test_detect_windows_scripts(self, tmp_path: Path) -> None:
        """Detect venv with Scripts/ (Windows-style)."""
        venv_path = tmp_path / ".venv"
        scripts_path = venv_path / "Scripts"
        scripts_path.mkdir(parents=True)
        env = detect_python_environment(tmp_path)
        assert env is not None
        assert env.bin_path == scripts_path


class TestNodeEnvDetectionExtended:
    """Extended Node environment detection tests."""

    def test_node_modules_without_bin(self, tmp_path: Path) -> None:
        """node_modules exists but no .bin directory."""
        (tmp_path / "node_modules").mkdir()
        env = detect_node_environment(tmp_path)
        assert env is not None
        assert env.bin_path is None


class TestCargoPackageInstalled:
    """Test cargo package installation check."""

    @pytest.mark.asyncio
    async def test_cargo_package_present(self, tmp_path: Path) -> None:
        """Return True when package is listed in Cargo.toml."""
        cargo_toml = tmp_path / "Cargo.toml"
        cargo_toml.write_text('[dependencies]\nserde = "1.0"\n')
        installed = await is_package_installed("serde", PackageManager.CARGO, tmp_path)
        assert installed is True

    @pytest.mark.asyncio
    async def test_cargo_package_missing(self, tmp_path: Path) -> None:
        """Return False when package not in Cargo.toml."""
        cargo_toml = tmp_path / "Cargo.toml"
        cargo_toml.write_text("[dependencies]\n")
        installed = await is_package_installed("serde", PackageManager.CARGO, tmp_path)
        assert installed is False

    @pytest.mark.asyncio
    async def test_cargo_no_toml(self, tmp_path: Path) -> None:
        """Return False when Cargo.toml missing."""
        installed = await is_package_installed("serde", PackageManager.CARGO, tmp_path)
        assert installed is False


class TestCheckPrerequisites:
    """Test check_prerequisites end-to-end."""

    @pytest.mark.asyncio
    async def test_all_satisfied_no_requirements(self, tmp_path: Path) -> None:
        """Return satisfied when nothing is required."""
        result = await check_prerequisites(
            commands=[],
            packages=[],
            project_path=tmp_path,
        )
        assert result.satisfied is True
        assert result.missing_commands == []
        assert result.missing_packages == []

    @pytest.mark.asyncio
    async def test_missing_command(self, tmp_path: Path) -> None:
        """Detect missing command."""
        result = await check_prerequisites(
            commands=["nonexistent_cmd_xyz"],
            packages=[],
            project_path=tmp_path,
        )
        assert result.satisfied is False
        assert "nonexistent_cmd_xyz" in result.missing_commands

    @pytest.mark.asyncio
    async def test_npm_missing_package(self, tmp_path: Path) -> None:
        """Detect missing npm package."""
        (tmp_path / "package-lock.json").touch()
        (tmp_path / "node_modules").mkdir()
        result = await check_prerequisites(
            commands=[],
            packages=["nonexistent_pkg"],
            project_path=tmp_path,
        )
        assert result.satisfied is False
        assert "nonexistent_pkg" in result.missing_packages
        assert result.install_command is not None


class TestInstallPackages:
    """Test install_packages function."""

    @pytest.mark.asyncio
    async def test_install_returns_false_on_empty_command(self, tmp_path: Path) -> None:
        """Return False when install command cannot be generated."""
        result = await install_packages(
            packages=[],
            package_manager=PackageManager.DOTNET,
            project_path=tmp_path,
        )
        assert result is False


class TestGetCommandPath:
    """Extended get_command_path tests."""

    def test_no_environment(self) -> None:
        """Falls back to system PATH when no environment given."""
        result = get_command_path("python", None)
        # python likely exists on the system
        if result is not None:
            assert result.stem.lower() == "python"

    def test_empty_bin_path(self, tmp_path: Path) -> None:
        """Environment with no bin_path falls back to system."""
        env = Environment(type="python_venv", path=tmp_path, bin_path=None)
        result = get_command_path("python", env)
        # Just verify it doesn't crash; python may or may not exist
        assert result is None or result.stem.lower() == "python"


# ── Coverage: is_package_installed Python path ──────────────────


class TestPythonPackageInstalled:
    @pytest.mark.asyncio
    async def test_pip_package_not_found(self, tmp_path: Path) -> None:
        """Return False for a package that's definitely not installed."""
        # No venv present — falls back to system python
        installed = await is_package_installed(
            "nonexistent_package_xyz_12345",
            PackageManager.PIP,
            tmp_path,
        )
        assert installed is False

    @pytest.mark.asyncio
    async def test_pip_package_with_venv(self, tmp_path: Path) -> None:
        """Check package via venv python binary."""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        # Create a fake python that always fails
        py = venv / "python"
        py.write_text("#!/bin/sh\nexit 1\n")
        py.chmod(0o755)

        installed = await is_package_installed(
            "nonexistent_xyz",
            PackageManager.PIP,
            tmp_path,
        )
        assert installed is False

    @pytest.mark.asyncio
    async def test_uv_package_check(self, tmp_path: Path) -> None:
        """UV uses same path as pip."""
        installed = await is_package_installed(
            "nonexistent_xyz_12345",
            PackageManager.UV,
            tmp_path,
        )
        assert installed is False

    @pytest.mark.asyncio
    async def test_poetry_package_check(self, tmp_path: Path) -> None:
        """Poetry uses same path as pip."""
        installed = await is_package_installed(
            "nonexistent_xyz_12345",
            PackageManager.POETRY,
            tmp_path,
        )
        assert installed is False


# ── Coverage: is_package_installed unsupported PM ───────────────


class TestUnsupportedPMInstalled:
    @pytest.mark.asyncio
    async def test_nuget_returns_false(self, tmp_path: Path) -> None:
        """Unsupported package manager returns False."""
        installed = await is_package_installed(
            "pkg",
            PackageManager.NUGET,
            tmp_path,
        )
        assert installed is False


# ── Coverage: check_prerequisites with node env ─────────────────


class TestCheckPrerequisitesExtended:
    @pytest.mark.asyncio
    async def test_node_env_detected(self, tmp_path: Path) -> None:
        """Prerequisites with node package manager detects node environment."""
        (tmp_path / "package-lock.json").touch()
        node_modules = tmp_path / "node_modules"
        node_modules.mkdir()

        result = await check_prerequisites(
            commands=[],
            packages=[],
            project_path=tmp_path,
        )
        assert result.satisfied is True
        assert result.package_manager == PackageManager.NPM

    @pytest.mark.asyncio
    async def test_python_env_detected(self, tmp_path: Path) -> None:
        """Prerequisites with pip package manager detects python env."""
        (tmp_path / "pyproject.toml").touch()
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)

        result = await check_prerequisites(
            commands=[],
            packages=[],
            project_path=tmp_path,
        )
        assert result.satisfied is True
        assert result.environment_path == tmp_path / ".venv"

    @pytest.mark.asyncio
    async def test_no_package_manager_skips_packages(self, tmp_path: Path) -> None:
        """Without a PM, package checks are skipped."""
        result = await check_prerequisites(
            commands=[],
            packages=["some-package"],
            project_path=tmp_path,
        )
        # No PM means packages aren't checked, so no missing
        assert result.missing_packages == []
        assert result.satisfied is True


# ── Coverage: install_packages ───────────────────────────────────


class TestInstallPackagesExtended:
    @pytest.mark.asyncio
    async def test_install_success(self, tmp_path: Path) -> None:
        """Successful install returns True."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ok", b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await install_packages(
                ["pytest"],
                PackageManager.PIP,
                tmp_path,
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_install_failure(self, tmp_path: Path) -> None:
        """Failed install returns False."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"error")
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await install_packages(
                ["bad-pkg"],
                PackageManager.PIP,
                tmp_path,
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_install_os_error(self, tmp_path: Path) -> None:
        """OSError during install returns False."""
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("pip not found"),
        ):
            result = await install_packages(
                ["pkg"],
                PackageManager.PIP,
                tmp_path,
            )
            assert result is False


# ── Coverage: get_install_command edge cases ─────────────────────


class TestGetInstallCommandExtended:
    def test_nuget_returns_empty(self) -> None:
        """NUGET is not fully handled, returns empty string."""
        cmd = get_install_command(["pkg"], PackageManager.NUGET, dev=True)
        assert cmd == ""

    def test_uv_prod(self) -> None:
        cmd = get_install_command(["pkg"], PackageManager.UV, dev=False)
        assert "uv add" in cmd
        assert "--dev" not in cmd

    def test_cargo_prod(self) -> None:
        cmd = get_install_command(["pkg"], PackageManager.CARGO, dev=False)
        assert "cargo add" in cmd
        assert "--dev" not in cmd

    def test_bun_prod(self) -> None:
        cmd = get_install_command(["pkg"], PackageManager.BUN, dev=False)
        assert "bun add" in cmd
        assert "--dev" not in cmd

    def test_pnpm_prod(self) -> None:
        cmd = get_install_command(["pkg"], PackageManager.PNPM, dev=False)
        assert "pnpm add" in cmd
        assert "--save-dev" not in cmd
