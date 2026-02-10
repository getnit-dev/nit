"""Tests for the InfraBuilder agent."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nit.agents.base import TaskInput, TaskStatus
from nit.agents.builders.infra import BootstrapTask, InfraBuilder

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def empty_project(tmp_path: Path) -> Path:
    """Create an empty project directory."""
    return tmp_path


@pytest.fixture
def vitest_project(tmp_path: Path) -> Path:
    """Create a project with existing Vitest infrastructure."""
    # Create package.json with vitest
    package_json = tmp_path / "package.json"
    package_json.write_text(
        json.dumps(
            {
                "name": "test-project",
                "devDependencies": {
                    "vitest": "^1.0.0",
                },
            },
        ),
    )

    # Create vitest.config.ts
    config_file = tmp_path / "vitest.config.ts"
    config_file.write_text("export default { test: {} };")

    return tmp_path


@pytest.fixture
def pytest_project(tmp_path: Path) -> Path:
    """Create a project with existing pytest infrastructure."""
    # Create pyproject.toml with pytest config
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.pytest.ini_options]
testpaths = ["tests"]
""",
    )

    # Create conftest.py
    conftest = tmp_path / "conftest.py"
    conftest.write_text('"""Pytest configuration."""\n')

    # Create tests directory
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    return tmp_path


@pytest.fixture
def playwright_project(tmp_path: Path) -> Path:
    """Create a project with existing Playwright infrastructure."""
    # Create package.json with @playwright/test
    package_json = tmp_path / "package.json"
    package_json.write_text(
        json.dumps(
            {
                "name": "test-project",
                "devDependencies": {
                    "@playwright/test": "^1.40.0",
                },
            },
        ),
    )

    # Create playwright.config.ts
    config_file = tmp_path / "playwright.config.ts"
    config_file.write_text("export default { testDir: './e2e' };")

    return tmp_path


# ── Tests: Infrastructure Detection ─────────────────────────────────


def test_has_vitest_infrastructure_when_exists(vitest_project: Path) -> None:
    """Test that existing Vitest infrastructure is detected."""
    builder = InfraBuilder(vitest_project)
    assert builder._has_vitest_infrastructure(vitest_project)


def test_has_vitest_infrastructure_when_missing(empty_project: Path) -> None:
    """Test that missing Vitest infrastructure is detected."""
    builder = InfraBuilder(empty_project)
    assert not builder._has_vitest_infrastructure(empty_project)


def test_has_pytest_infrastructure_when_exists(pytest_project: Path) -> None:
    """Test that existing pytest infrastructure is detected."""
    builder = InfraBuilder(pytest_project)
    assert builder._has_pytest_infrastructure(pytest_project)


def test_has_pytest_infrastructure_when_missing(empty_project: Path) -> None:
    """Test that missing pytest infrastructure is detected."""
    builder = InfraBuilder(empty_project)
    assert not builder._has_pytest_infrastructure(empty_project)


def test_has_playwright_infrastructure_when_exists(playwright_project: Path) -> None:
    """Test that existing Playwright infrastructure is detected."""
    builder = InfraBuilder(playwright_project)
    assert builder._has_playwright_infrastructure(playwright_project)


def test_has_playwright_infrastructure_when_missing(empty_project: Path) -> None:
    """Test that missing Playwright infrastructure is detected."""
    builder = InfraBuilder(empty_project)
    assert not builder._has_playwright_infrastructure(empty_project)


# ── Tests: Agent Interface ──────────────────────────────────────────


def test_agent_name(tmp_path: Path) -> None:
    """Test that agent has correct name."""
    builder = InfraBuilder(tmp_path)
    assert builder.name == "infra_builder"


def test_agent_description(tmp_path: Path) -> None:
    """Test that agent has correct description."""
    builder = InfraBuilder(tmp_path)
    assert "bootstrap" in builder.description.lower()


@pytest.mark.asyncio
async def test_run_with_invalid_task(empty_project: Path) -> None:
    """Test that run returns error for invalid task type."""
    builder = InfraBuilder(empty_project)
    task = TaskInput(task_type="invalid", target="test")
    result = await builder.run(task)
    assert result.status == TaskStatus.FAILED
    assert "BootstrapTask" in result.errors[0]


@pytest.mark.asyncio
async def test_run_with_existing_infrastructure(vitest_project: Path) -> None:
    """Test that run skips bootstrap when infrastructure exists."""
    builder = InfraBuilder(vitest_project)
    task = BootstrapTask(
        framework="vitest",
        language="typescript",
        project_path=str(vitest_project),
    )
    result = await builder.run(task)
    assert result.status == TaskStatus.COMPLETED
    assert "already exists" in result.result["message"]
    assert len(result.result["actions"]) == 0


# ── Tests: Vitest Bootstrap ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_vitest_creates_config(empty_project: Path) -> None:
    """Test that Vitest bootstrap creates vitest.config.ts."""
    builder = InfraBuilder(empty_project)

    # Mock the command runner to avoid actual npm install
    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="vitest",
            language="typescript",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert (empty_project / "vitest.config.ts").exists()

    # Check config content
    config_content = (empty_project / "vitest.config.ts").read_text()
    assert "defineConfig" in config_content
    assert "jsdom" in config_content


@pytest.mark.asyncio
async def test_bootstrap_vitest_creates_setup_file(empty_project: Path) -> None:
    """Test that Vitest bootstrap creates test setup file."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="vitest",
            language="typescript",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert (empty_project / "src" / "test" / "setup.ts").exists()


@pytest.mark.asyncio
async def test_bootstrap_vitest_installs_dependencies(empty_project: Path) -> None:
    """Test that Vitest bootstrap installs required dependencies."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="vitest",
            language="typescript",
            project_path=str(empty_project),
        )
        await builder.run(task)

        # Check that npm install was called
        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert "npm" in call_args
        assert "install" in call_args
        assert "vitest" in call_args
        assert "@testing-library/react" in call_args


@pytest.mark.asyncio
async def test_bootstrap_vitest_updates_package_json(empty_project: Path) -> None:
    """Test that Vitest bootstrap adds test scripts to package.json."""
    # Create minimal package.json
    package_json = empty_project / "package.json"
    package_json.write_text(json.dumps({"name": "test"}))

    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="vitest",
            language="typescript",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED

    # Check package.json was updated
    data = json.loads(package_json.read_text())
    assert "scripts" in data
    assert data["scripts"]["test"] == "vitest"
    assert "test:coverage" in data["scripts"]


# ── Tests: Pytest Bootstrap ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_pytest_creates_tests_directory(empty_project: Path) -> None:
    """Test that pytest bootstrap creates tests directory."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="pytest",
            language="python",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert (empty_project / "tests").is_dir()
    assert (empty_project / "tests" / "__init__.py").exists()


@pytest.mark.asyncio
async def test_bootstrap_pytest_creates_conftest(empty_project: Path) -> None:
    """Test that pytest bootstrap creates conftest.py."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="pytest",
            language="python",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert (empty_project / "conftest.py").exists()

    # Check conftest content
    conftest_content = (empty_project / "conftest.py").read_text()
    assert "pytest" in conftest_content.lower()


@pytest.mark.asyncio
async def test_bootstrap_pytest_updates_pyproject_toml(empty_project: Path) -> None:
    """Test that pytest bootstrap updates pyproject.toml."""
    # Create minimal pyproject.toml
    pyproject = empty_project / "pyproject.toml"
    pyproject.write_text('[project]\nname = "test"\n')

    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="pytest",
            language="python",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED

    # Check pyproject.toml was updated
    content = pyproject.read_text()
    assert "[tool.pytest.ini_options]" in content
    assert "testpaths" in content


@pytest.mark.asyncio
async def test_bootstrap_pytest_installs_dependencies(empty_project: Path) -> None:
    """Test that pytest bootstrap installs required dependencies."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="pytest",
            language="python",
            project_path=str(empty_project),
        )
        await builder.run(task)

        # Check that pip install was called
        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert "pip" in call_args or "python" in call_args[0]
        assert "pytest" in call_args


# ── Tests: Playwright Bootstrap ─────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_playwright_creates_config(empty_project: Path) -> None:
    """Test that Playwright bootstrap creates playwright.config.ts."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="playwright",
            language="typescript",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert (empty_project / "playwright.config.ts").exists()

    # Check config content
    config_content = (empty_project / "playwright.config.ts").read_text()
    assert "defineConfig" in config_content
    assert "testDir" in config_content


@pytest.mark.asyncio
async def test_bootstrap_playwright_creates_e2e_directory(empty_project: Path) -> None:
    """Test that Playwright bootstrap creates e2e directory."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="playwright",
            language="typescript",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert (empty_project / "e2e").is_dir()


@pytest.mark.asyncio
async def test_bootstrap_playwright_creates_example_test(empty_project: Path) -> None:
    """Test that Playwright bootstrap creates example test."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="playwright",
            language="typescript",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert (empty_project / "e2e" / "example.spec.ts").exists()

    # Check example test content
    test_content = (empty_project / "e2e" / "example.spec.ts").read_text()
    assert "test(" in test_content
    assert "expect" in test_content


@pytest.mark.asyncio
async def test_bootstrap_playwright_updates_package_json(empty_project: Path) -> None:
    """Test that Playwright bootstrap adds test scripts to package.json."""
    # Create minimal package.json
    package_json = empty_project / "package.json"
    package_json.write_text(json.dumps({"name": "test"}))

    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="playwright",
            language="typescript",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED

    # Check package.json was updated
    data = json.loads(package_json.read_text())
    assert "scripts" in data
    assert "test:e2e" in data["scripts"]
    assert "playwright test" in data["scripts"]["test:e2e"]


# ── Tests: Docker Execution Mode ────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_with_docker_enabled(empty_project: Path) -> None:
    """Test that bootstrap uses Docker when enabled."""
    builder = InfraBuilder(empty_project, enable_docker=True)

    with patch.object(builder, "_run_in_docker", new_callable=AsyncMock) as mock_docker:
        mock_docker.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="vitest",
            language="typescript",
            project_path=str(empty_project),
        )
        await builder.run(task)

        # Check that Docker was used
        assert mock_docker.called


@pytest.mark.asyncio
async def test_bootstrap_with_custom_docker_image(empty_project: Path) -> None:
    """Test that bootstrap uses custom Docker image when specified."""
    custom_image = "custom/node:latest"
    builder = InfraBuilder(empty_project, enable_docker=True, docker_image=custom_image)

    with patch.object(builder, "_run_in_docker", new_callable=AsyncMock) as mock_docker:
        mock_docker.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="vitest",
            language="typescript",
            project_path=str(empty_project),
        )
        await builder.run(task)

        # Check that custom image was used
        assert mock_docker.called
        call_args = mock_docker.call_args
        assert custom_image in call_args[0]


@pytest.mark.asyncio
async def test_bootstrap_task_with_use_docker_flag(empty_project: Path) -> None:
    """Test that BootstrapTask use_docker flag enables Docker."""
    builder = InfraBuilder(empty_project, enable_docker=False)

    with patch.object(builder, "_run_in_docker", new_callable=AsyncMock) as mock_docker:
        mock_docker.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="vitest",
            language="typescript",
            project_path=str(empty_project),
            use_docker=True,
        )
        await builder.run(task)

        # Check that Docker was used even though builder default is False
        assert mock_docker.called


# ── Tests: Error Handling ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_bootstrap_unknown_framework(empty_project: Path) -> None:
    """Test that bootstrap fails for unknown framework."""
    builder = InfraBuilder(empty_project)

    task = BootstrapTask(
        framework="unknown",
        language="unknown",
        project_path=str(empty_project),
    )
    result = await builder.run(task)

    assert result.status == TaskStatus.FAILED
    assert "Unknown framework" in result.errors[0]


@pytest.mark.asyncio
async def test_bootstrap_handles_command_failure(empty_project: Path) -> None:
    """Test that bootstrap handles command execution failures gracefully."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {
            "success": False,
            "stdout": "",
            "stderr": "Error",
            "error": "Command failed",
        }

        task = BootstrapTask(
            framework="vitest",
            language="typescript",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

        # Should complete but log warnings
        assert result.status == TaskStatus.COMPLETED
        # Files should still be created even if install fails
        assert (empty_project / "vitest.config.ts").exists()
