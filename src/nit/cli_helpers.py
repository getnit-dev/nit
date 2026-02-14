"""CLI helper functions for prerequisite checking and user interaction."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import click

from nit.agents.reporters.terminal import reporter
from nit.utils.prerequisites import check_prerequisites, install_packages

if TYPE_CHECKING:
    from pathlib import Path

    from nit.adapters.base import TestFrameworkAdapter

logger = logging.getLogger(__name__)


async def check_and_install_prerequisites(
    adapter: TestFrameworkAdapter,
    project_path: Path,
    *,
    ci_mode: bool = False,
) -> bool:
    """Check prerequisites and offer to install missing dependencies.

    Args:
        adapter: The test framework adapter to check.
        project_path: Project root directory.
        ci_mode: If True, skip interactive prompts and fail if prerequisites are missing.

    Returns:
        True if all prerequisites are satisfied (or were successfully installed),
        False otherwise.
    """
    # Get required packages and commands from adapter
    required_packages = adapter.get_required_packages()
    required_commands = adapter.get_required_commands()

    # Check for environment-specific packages (e.g., jsdom for vitest)
    if hasattr(adapter, "get_environment_packages"):
        env_packages = adapter.get_environment_packages(project_path)
        required_packages = list(required_packages) + env_packages

    # Skip check if nothing is required
    if not required_packages and not required_commands:
        return True

    # Check prerequisites
    prereq_check = await check_prerequisites(
        commands=required_commands,
        packages=required_packages,
        project_path=project_path,
    )

    # All prerequisites satisfied
    if prereq_check.satisfied:
        return True

    # Missing prerequisites — report them
    if prereq_check.missing_commands:
        reporter.print_error(
            f"Missing required commands: {', '.join(prereq_check.missing_commands)}"
        )
        if not ci_mode:
            reporter.print_info(
                "Please install the required tools and ensure they are available in your PATH."
            )

    if prereq_check.missing_packages:
        reporter.print_error(
            f"Missing required packages: {', '.join(prereq_check.missing_packages)}"
        )

    # Can't auto-install: CI mode, no package manager, or only missing commands
    pkg_mgr = prereq_check.package_manager
    can_install = (
        not ci_mode and prereq_check.install_command and pkg_mgr and prereq_check.missing_packages
    )
    if not can_install or pkg_mgr is None:
        return False

    # Offer to install missing packages
    reporter.print_info(f"\nPackage manager detected: {pkg_mgr.value}")
    reporter.print_info(f"Install command: {prereq_check.install_command}")

    if not click.confirm("\nWould you like to install missing packages now?", default=True):
        reporter.print_info("Skipping installation. Please install manually to continue.")
        return False

    reporter.print_info("Installing packages...")
    success = await install_packages(
        packages=prereq_check.missing_packages,
        package_manager=pkg_mgr,
        project_path=project_path,
        dev=True,
    )

    if success:
        reporter.print_success("Packages installed successfully!")
        return True

    reporter.print_error("Package installation failed.")
    return False
