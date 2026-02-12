"""Tests for CLI helper functions (prerequisite checking and installation)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.cli_helpers import check_and_install_prerequisites
from nit.utils.prerequisites import PackageManager, PrerequisiteCheck


def _make_adapter(
    required_packages: list[str] | None = None,
    required_commands: list[str] | None = None,
    env_packages: list[str] | None = None,
) -> MagicMock:
    """Build a mock TestFrameworkAdapter with configurable requirements."""
    adapter = MagicMock()
    adapter.get_required_packages.return_value = required_packages or []
    adapter.get_required_commands.return_value = required_commands or []
    if env_packages is not None:
        adapter.get_environment_packages = MagicMock(return_value=env_packages)
    else:
        # Remove the attribute so hasattr returns False
        del adapter.get_environment_packages
    return adapter


class TestNoRequirements:
    """When nothing is required the helper should return True immediately."""

    @pytest.mark.asyncio
    async def test_returns_true(self, tmp_path: Path) -> None:
        adapter = _make_adapter()
        result = await check_and_install_prerequisites(adapter, tmp_path)
        assert result is True


class TestAllSatisfied:
    """When all prerequisites are already satisfied."""

    @pytest.mark.asyncio
    async def test_returns_true(self, tmp_path: Path) -> None:
        adapter = _make_adapter(required_packages=["vitest"])
        satisfied_check = PrerequisiteCheck(
            satisfied=True,
            missing_packages=[],
            missing_commands=[],
        )
        with patch(
            "nit.cli_helpers.check_prerequisites",
            new_callable=AsyncMock,
            return_value=satisfied_check,
        ):
            result = await check_and_install_prerequisites(adapter, tmp_path)
        assert result is True


class TestMissingCommandsCIMode:
    """Missing commands in CI mode should return False."""

    @pytest.mark.asyncio
    async def test_fails_in_ci_mode(self, tmp_path: Path) -> None:
        adapter = _make_adapter(required_commands=["node"])
        check = PrerequisiteCheck(
            satisfied=False,
            missing_packages=[],
            missing_commands=["node"],
        )
        with (
            patch(
                "nit.cli_helpers.check_prerequisites",
                new_callable=AsyncMock,
                return_value=check,
            ),
            patch("nit.cli_helpers.reporter") as mock_reporter,
        ):
            result = await check_and_install_prerequisites(adapter, tmp_path, ci_mode=True)
        assert result is False
        mock_reporter.print_error.assert_called()


class TestMissingCommandsInteractiveMode:
    """Missing commands in interactive mode should still fail (can't auto-install)."""

    @pytest.mark.asyncio
    async def test_fails_gracefully(self, tmp_path: Path) -> None:
        adapter = _make_adapter(required_commands=["node"])
        check = PrerequisiteCheck(
            satisfied=False,
            missing_packages=[],
            missing_commands=["node"],
        )
        with (
            patch(
                "nit.cli_helpers.check_prerequisites",
                new_callable=AsyncMock,
                return_value=check,
            ),
            patch("nit.cli_helpers.reporter"),
        ):
            result = await check_and_install_prerequisites(adapter, tmp_path)
        assert result is False


class TestMissingPackagesCIMode:
    """Missing packages in CI mode should return False without prompting."""

    @pytest.mark.asyncio
    async def test_fails_in_ci_mode(self, tmp_path: Path) -> None:
        adapter = _make_adapter(required_packages=["vitest"])
        check = PrerequisiteCheck(
            satisfied=False,
            missing_packages=["vitest"],
            missing_commands=[],
            package_manager=PackageManager.NPM,
            install_command="npm install --save-dev vitest",
        )
        with (
            patch(
                "nit.cli_helpers.check_prerequisites",
                new_callable=AsyncMock,
                return_value=check,
            ),
            patch("nit.cli_helpers.reporter") as mock_reporter,
        ):
            result = await check_and_install_prerequisites(adapter, tmp_path, ci_mode=True)
        assert result is False
        mock_reporter.print_error.assert_called()


class TestMissingPackagesInstallAccepted:
    """User accepts package installation and it succeeds."""

    @pytest.mark.asyncio
    async def test_install_succeeds(self, tmp_path: Path) -> None:
        adapter = _make_adapter(required_packages=["vitest"])
        check = PrerequisiteCheck(
            satisfied=False,
            missing_packages=["vitest"],
            missing_commands=[],
            package_manager=PackageManager.NPM,
            install_command="npm install --save-dev vitest",
        )
        with (
            patch(
                "nit.cli_helpers.check_prerequisites",
                new_callable=AsyncMock,
                return_value=check,
            ),
            patch("nit.cli_helpers.reporter"),
            patch("nit.cli_helpers.click") as mock_click,
            patch(
                "nit.cli_helpers.install_packages",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            mock_click.confirm.return_value = True
            result = await check_and_install_prerequisites(adapter, tmp_path)
        assert result is True


class TestMissingPackagesInstallFailed:
    """User accepts package installation but it fails."""

    @pytest.mark.asyncio
    async def test_install_fails(self, tmp_path: Path) -> None:
        adapter = _make_adapter(required_packages=["vitest"])
        check = PrerequisiteCheck(
            satisfied=False,
            missing_packages=["vitest"],
            missing_commands=[],
            package_manager=PackageManager.NPM,
            install_command="npm install --save-dev vitest",
        )
        with (
            patch(
                "nit.cli_helpers.check_prerequisites",
                new_callable=AsyncMock,
                return_value=check,
            ),
            patch("nit.cli_helpers.reporter"),
            patch("nit.cli_helpers.click") as mock_click,
            patch(
                "nit.cli_helpers.install_packages",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            mock_click.confirm.return_value = True
            result = await check_and_install_prerequisites(adapter, tmp_path)
        assert result is False


class TestMissingPackagesInstallDeclined:
    """User declines package installation."""

    @pytest.mark.asyncio
    async def test_user_declines(self, tmp_path: Path) -> None:
        adapter = _make_adapter(required_packages=["vitest"])
        check = PrerequisiteCheck(
            satisfied=False,
            missing_packages=["vitest"],
            missing_commands=[],
            package_manager=PackageManager.NPM,
            install_command="npm install --save-dev vitest",
        )
        with (
            patch(
                "nit.cli_helpers.check_prerequisites",
                new_callable=AsyncMock,
                return_value=check,
            ),
            patch("nit.cli_helpers.reporter") as mock_reporter,
            patch("nit.cli_helpers.click") as mock_click,
        ):
            mock_click.confirm.return_value = False
            result = await check_and_install_prerequisites(adapter, tmp_path)
        assert result is False
        # Should print skip message
        mock_reporter.print_info.assert_called()


class TestNoInstallCommand:
    """Missing packages but no install command available."""

    @pytest.mark.asyncio
    async def test_returns_false(self, tmp_path: Path) -> None:
        adapter = _make_adapter(required_packages=["vitest"])
        check = PrerequisiteCheck(
            satisfied=False,
            missing_packages=["vitest"],
            missing_commands=[],
            package_manager=None,
            install_command=None,
        )
        with (
            patch(
                "nit.cli_helpers.check_prerequisites",
                new_callable=AsyncMock,
                return_value=check,
            ),
            patch("nit.cli_helpers.reporter"),
        ):
            result = await check_and_install_prerequisites(adapter, tmp_path)
        assert result is False


class TestEnvironmentPackages:
    """Adapters with get_environment_packages are handled."""

    @pytest.mark.asyncio
    async def test_env_packages_included(self, tmp_path: Path) -> None:
        adapter = _make_adapter(
            required_packages=["vitest"],
            env_packages=["jsdom"],
        )
        satisfied_check = PrerequisiteCheck(
            satisfied=True,
            missing_packages=[],
            missing_commands=[],
        )
        with patch(
            "nit.cli_helpers.check_prerequisites",
            new_callable=AsyncMock,
            return_value=satisfied_check,
        ) as mock_check:
            result = await check_and_install_prerequisites(adapter, tmp_path)
        assert result is True
        # Verify that jsdom was included in the packages checked
        call_kwargs = mock_check.call_args
        packages = call_kwargs.kwargs.get("packages") or call_kwargs[1].get("packages")
        assert "jsdom" in packages


class TestOnlyMissingCommandsNoPackages:
    """Only missing commands, no missing packages — can't auto-fix."""

    @pytest.mark.asyncio
    async def test_returns_false(self, tmp_path: Path) -> None:
        adapter = _make_adapter(required_commands=["cargo"])
        check = PrerequisiteCheck(
            satisfied=False,
            missing_packages=[],
            missing_commands=["cargo"],
            package_manager=PackageManager.CARGO,
            install_command=None,
        )
        with (
            patch(
                "nit.cli_helpers.check_prerequisites",
                new_callable=AsyncMock,
                return_value=check,
            ),
            patch("nit.cli_helpers.reporter"),
        ):
            result = await check_and_install_prerequisites(adapter, tmp_path)
        assert result is False
