"""Prerequisite checking and dependency installation utilities.

Provides functionality to:
- Detect package managers (npm, pip, cargo, etc.)
- Find virtual environments (.venv, venv, Poetry, etc.)
- Check if test frameworks and tools are installed
- Offer interactive installation of missing dependencies
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


class PackageManager(Enum):
    """Supported package managers."""

    NPM = "npm"
    YARN = "yarn"
    PNPM = "pnpm"
    BUN = "bun"
    PIP = "pip"
    POETRY = "poetry"
    UV = "uv"
    CARGO = "cargo"
    BUNDLE = "bundle"
    NUGET = "nuget"
    DOTNET = "dotnet"


@dataclass
class PrerequisiteCheck:
    """Result of a prerequisite check."""

    satisfied: bool
    missing_packages: list[str]
    missing_commands: list[str]
    package_manager: PackageManager | None = None
    install_command: str | None = None
    environment_path: Path | None = None


@dataclass
class Environment:
    """Detected project environment (virtualenv, node_modules, etc.)."""

    type: str  # "python_venv", "node_modules", "cargo", etc.
    path: Path
    bin_path: Path | None = None


def detect_python_environment(project_path: Path) -> Environment | None:
    """Detect Python virtual environment in the project.

    Checks for:
    - .venv/
    - venv/
    - virtualenv/
    - Poetry environment
    - UV environment
    """
    # Check common venv directories
    for venv_name in [".venv", "venv", "virtualenv", "env"]:
        venv_path = project_path / venv_name
        if not venv_path.is_dir():
            continue

        # Check for bin/activate (Unix) or Scripts/activate (Windows)
        bin_path = venv_path / "bin"
        scripts_path = venv_path / "Scripts"

        if bin_path.is_dir():
            return Environment(
                type="python_venv",
                path=venv_path,
                bin_path=bin_path,
            )
        if scripts_path.is_dir():
            return Environment(
                type="python_venv",
                path=venv_path,
                bin_path=scripts_path,
            )

    # Check for Poetry
    if (project_path / "poetry.lock").exists():
        # Poetry stores venvs externally, but we can still detect it
        return Environment(
            type="poetry",
            path=project_path,
            bin_path=None,
        )

    return None


def detect_node_environment(project_path: Path) -> Environment | None:
    """Detect Node.js environment in the project.

    Checks for:
    - node_modules/
    - package.json
    - pnpm-lock.yaml
    - yarn.lock
    - bun.lockb
    """
    node_modules = project_path / "node_modules"
    if node_modules.is_dir():
        bin_path = node_modules / ".bin"
        return Environment(
            type="node_modules",
            path=node_modules,
            bin_path=bin_path if bin_path.is_dir() else None,
        )

    # If no node_modules but package.json exists, it needs installation
    if (project_path / "package.json").exists():
        return Environment(
            type="node_modules",
            path=project_path,
            bin_path=None,
        )

    return None


def detect_package_manager(project_path: Path) -> PackageManager | None:
    """Detect the primary package manager for the project.

    Checks for lock files and configuration files to determine the
    package manager in use.
    """
    # Node.js package managers
    if (project_path / "bun.lockb").exists():
        return PackageManager.BUN
    if (project_path / "pnpm-lock.yaml").exists():
        return PackageManager.PNPM
    if (project_path / "yarn.lock").exists():
        return PackageManager.YARN
    if (project_path / "package-lock.json").exists() or (project_path / "package.json").exists():
        return PackageManager.NPM

    # Python package managers
    if (project_path / "uv.lock").exists():
        return PackageManager.UV
    if (project_path / "poetry.lock").exists():
        return PackageManager.POETRY
    if (project_path / "requirements.txt").exists() or (project_path / "pyproject.toml").exists():
        return PackageManager.PIP

    # Rust
    if (project_path / "Cargo.toml").exists():
        return PackageManager.CARGO

    # Ruby
    if (project_path / "Gemfile").exists():
        return PackageManager.BUNDLE

    # .NET
    if list(project_path.glob("*.csproj")) or list(project_path.glob("*.fsproj")):
        return PackageManager.DOTNET

    return None


def get_command_path(
    command: str,
    environment: Environment | None = None,
) -> Path | None:
    """Find the path to a command, preferring environment-local binaries.

    Args:
        command: The command name (e.g., "pytest", "npm", "cargo").
        environment: Optional environment to search first.

    Returns:
        Path to the command if found, None otherwise.
    """
    # Check in environment bin path first
    if environment and environment.bin_path:
        env_cmd = environment.bin_path / command
        if env_cmd.exists():
            return env_cmd

    # Fall back to system PATH
    system_cmd = shutil.which(command)
    if system_cmd:
        return Path(system_cmd)

    return None


async def is_package_installed(
    package: str,
    package_manager: PackageManager,
    project_path: Path,
) -> bool:
    """Check if a package is installed.

    Args:
        package: Package name to check.
        package_manager: The package manager to use.
        project_path: Project root directory.

    Returns:
        True if the package is installed, False otherwise.
    """
    if package_manager in {
        PackageManager.NPM,
        PackageManager.YARN,
        PackageManager.PNPM,
        PackageManager.BUN,
    }:
        # Check if package actually exists in node_modules (not just package.json)
        node_modules = project_path / "node_modules"
        if not node_modules.exists():
            return False

        # Check if the package directory exists in node_modules
        # Handle scoped packages (e.g., @playwright/test -> @playwright/test)
        package_parts = package.split("/")
        package_path = node_modules
        for part in package_parts:
            package_path = package_path / part

        return package_path.exists()

    if package_manager in {PackageManager.PIP, PackageManager.POETRY, PackageManager.UV}:
        # Use importlib.metadata to check by distribution name (handles
        # packages with hyphens like ``pytest-json-report`` that cannot
        # be checked with a plain ``import`` statement).
        env = detect_python_environment(project_path)
        python_cmd = "python"
        if env and env.bin_path:
            python_path = env.bin_path / "python"
            if python_path.exists():
                python_cmd = str(python_path)

        check_script = f"from importlib.metadata import distribution; distribution({package!r})"
        try:
            proc = await asyncio.create_subprocess_exec(
                python_cmd,
                "-c",
                check_script,
                cwd=str(project_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            returncode = await proc.wait()
            return returncode == 0
        except (OSError, FileNotFoundError):
            return False

    if package_manager == PackageManager.CARGO:
        # Check Cargo.toml for the dependency
        cargo_toml = project_path / "Cargo.toml"
        if not cargo_toml.exists():
            return False

        try:
            content = cargo_toml.read_text(encoding="utf-8")
            # Simple heuristic: look for package name in file
            return package in content
        except OSError:
            return False

    return False


def get_install_command(
    packages: Sequence[str],
    package_manager: PackageManager,
    *,
    dev: bool = True,
) -> str:
    """Generate the install command for the given packages and package manager.

    Args:
        packages: List of package names to install.
        dev: Whether to install as dev dependencies.

    Returns:
        The shell command to install the packages.
    """
    pkg_list = " ".join(packages)

    if package_manager == PackageManager.NPM:
        flag = "--save-dev" if dev else "--save"
        return f"npm install {flag} {pkg_list}"
    if package_manager == PackageManager.YARN:
        flag = "--dev" if dev else ""
        return f"yarn add {flag} {pkg_list}".strip()
    if package_manager == PackageManager.PNPM:
        flag = "--save-dev" if dev else ""
        return f"pnpm add {flag} {pkg_list}".strip()
    if package_manager == PackageManager.BUN:
        flag = "--dev" if dev else ""
        return f"bun add {flag} {pkg_list}".strip()
    if package_manager == PackageManager.PIP:
        return f"pip install {pkg_list}"
    if package_manager == PackageManager.POETRY:
        flag = "--group dev" if dev else ""
        return f"poetry add {flag} {pkg_list}".strip()
    if package_manager == PackageManager.UV:
        flag = "--dev" if dev else ""
        return f"uv add {flag} {pkg_list}".strip()
    if package_manager == PackageManager.CARGO:
        flag = "--dev" if dev else ""
        return f"cargo add {flag} {pkg_list}".strip()
    if package_manager == PackageManager.BUNDLE:
        return f"bundle add {pkg_list}"
    if package_manager == PackageManager.DOTNET:
        # For .NET, packages are installed per-project
        return f"dotnet add package {packages[0]}" if packages else ""

    return ""


async def check_prerequisites(
    commands: Sequence[str],
    packages: Sequence[str],
    project_path: Path,
) -> PrerequisiteCheck:
    """Check if all required commands and packages are available.

    Args:
        commands: List of command names that must be available (e.g., "pytest", "node").
        packages: List of package names that must be installed.
        project_path: Project root directory.

    Returns:
        A PrerequisiteCheck with the results.
    """
    # Detect package manager and environment
    package_manager = detect_package_manager(project_path)

    # Detect environment based on package manager
    environment = None
    if package_manager in {
        PackageManager.PIP,
        PackageManager.POETRY,
        PackageManager.UV,
    }:
        environment = detect_python_environment(project_path)
    elif package_manager in {
        PackageManager.NPM,
        PackageManager.YARN,
        PackageManager.PNPM,
        PackageManager.BUN,
    }:
        environment = detect_node_environment(project_path)

    # Check for missing commands
    missing_commands = [cmd for cmd in commands if get_command_path(cmd, environment) is None]

    # Check for missing packages
    missing_packages = []
    if package_manager:
        for pkg in packages:
            installed = await is_package_installed(pkg, package_manager, project_path)
            if not installed:
                missing_packages.append(pkg)

    # Generate install command if there are missing packages
    install_command = None
    if missing_packages and package_manager:
        install_command = get_install_command(missing_packages, package_manager, dev=True)

    satisfied = not missing_commands and not missing_packages

    return PrerequisiteCheck(
        satisfied=satisfied,
        missing_packages=missing_packages,
        missing_commands=missing_commands,
        package_manager=package_manager,
        install_command=install_command,
        environment_path=environment.path if environment else None,
    )


async def install_packages(
    packages: Sequence[str],
    package_manager: PackageManager,
    project_path: Path,
    *,
    dev: bool = True,
) -> bool:
    """Install packages using the specified package manager.

    Args:
        packages: List of package names to install.
        package_manager: The package manager to use.
        project_path: Project root directory.
        dev: Whether to install as dev dependencies.

    Returns:
        True if installation succeeded, False otherwise.
    """
    install_cmd = get_install_command(packages, package_manager, dev=dev)
    if not install_cmd:
        logger.error("Unable to generate install command for %s", package_manager)
        return False

    # Split command into parts
    cmd_parts = install_cmd.split()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_parts,
            cwd=str(project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode == 0:
            logger.info("Successfully installed: %s", ", ".join(packages))
            return True

        logger.error("Installation failed: %s\n%s", stdout, stderr)
        return False

    except (OSError, FileNotFoundError) as exc:
        logger.error("Failed to run install command: %s", exc)
        return False
