"""Tests for the InfraBuilder agent."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nit.agents.base import TaskInput, TaskStatus
from nit.agents.builders.infra import (
    _DEFAULT_TIMEOUT,
    _DOCKER_IMAGE,
    _DOCKER_PYTHON_IMAGE,
    BootstrapTask,
    InfraBuilder,
)

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


# ── Tests: BootstrapTask dataclass ──────────────────────────────────


def test_bootstrap_task_target_defaults_to_framework() -> None:
    """BootstrapTask.__post_init__ sets target from framework when empty."""
    task = BootstrapTask(framework="vitest", language="typescript")
    assert task.target == "vitest"


def test_bootstrap_task_target_not_overwritten() -> None:
    """BootstrapTask keeps explicit target unchanged."""
    task = BootstrapTask(framework="vitest", language="typescript", target="custom")
    assert task.target == "custom"


def test_bootstrap_task_defaults() -> None:
    """BootstrapTask defaults are sensible."""
    task = BootstrapTask()
    assert task.task_type == "bootstrap_infra"
    assert task.framework == ""
    assert task.language == ""
    assert task.project_path == ""
    assert task.use_docker is False
    assert task.docker_image == ""
    assert task.target == ""


# ── Tests: _has_infrastructure dispatch ─────────────────────────────


def test_has_infrastructure_dispatches_vitest(vitest_project: Path) -> None:
    """_has_infrastructure('vitest') delegates to vitest check."""
    builder = InfraBuilder(vitest_project)
    assert builder._has_infrastructure("vitest", vitest_project) is True


def test_has_infrastructure_dispatches_pytest(pytest_project: Path) -> None:
    """_has_infrastructure('pytest') delegates to pytest check."""
    builder = InfraBuilder(pytest_project)
    assert builder._has_infrastructure("pytest", pytest_project) is True


def test_has_infrastructure_dispatches_playwright(playwright_project: Path) -> None:
    """_has_infrastructure('playwright') delegates to playwright check."""
    builder = InfraBuilder(playwright_project)
    assert builder._has_infrastructure("playwright", playwright_project) is True


def test_has_infrastructure_unknown_returns_false(tmp_path: Path) -> None:
    """_has_infrastructure returns False for unknown frameworks."""
    builder = InfraBuilder(tmp_path)
    assert builder._has_infrastructure("unknown_framework", tmp_path) is False


# ── Tests: Vitest detection edge cases ──────────────────────────────


def test_vitest_detected_with_js_config(tmp_path: Path) -> None:
    """Vitest detected when vitest.config.js exists alongside dep."""
    (tmp_path / "vitest.config.js").write_text("export default {};")
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"vitest": "^1.0.0"}}),
    )
    builder = InfraBuilder(tmp_path)
    assert builder._has_vitest_infrastructure(tmp_path) is True


def test_vitest_detected_with_mjs_config(tmp_path: Path) -> None:
    """Vitest detected when vitest.config.mjs exists alongside dep."""
    (tmp_path / "vitest.config.mjs").write_text("export default {};")
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"vitest": "^1.0.0"}}),
    )
    builder = InfraBuilder(tmp_path)
    assert builder._has_vitest_infrastructure(tmp_path) is True


def test_vitest_not_detected_config_only(tmp_path: Path) -> None:
    """Vitest not detected when config exists but dep is missing."""
    (tmp_path / "vitest.config.ts").write_text("export default {};")
    builder = InfraBuilder(tmp_path)
    assert builder._has_vitest_infrastructure(tmp_path) is False


def test_vitest_not_detected_dep_only(tmp_path: Path) -> None:
    """Vitest not detected when dep exists but config is missing."""
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"vitest": "^1.0.0"}}),
    )
    builder = InfraBuilder(tmp_path)
    assert builder._has_vitest_infrastructure(tmp_path) is False


def test_vitest_not_detected_invalid_json(tmp_path: Path) -> None:
    """Vitest not detected when package.json contains invalid JSON."""
    (tmp_path / "vitest.config.ts").write_text("export default {};")
    (tmp_path / "package.json").write_text("{bad json")
    builder = InfraBuilder(tmp_path)
    assert builder._has_vitest_infrastructure(tmp_path) is False


# ── Tests: Pytest detection edge cases ──────────────────────────────


def test_pytest_detected_via_conftest(tmp_path: Path) -> None:
    """Pytest detected when conftest.py exists (even without pyproject)."""
    (tmp_path / "conftest.py").write_text("")
    builder = InfraBuilder(tmp_path)
    assert builder._has_pytest_infrastructure(tmp_path) is True


def test_pytest_detected_via_test_files(tmp_path: Path) -> None:
    """Pytest detected when tests/ has test_*.py files."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_example.py").write_text("")
    builder = InfraBuilder(tmp_path)
    assert builder._has_pytest_infrastructure(tmp_path) is True


def test_pytest_detected_via_suffix_test_files(tmp_path: Path) -> None:
    """Pytest detected when tests/ has *_test.py files."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "example_test.py").write_text("")
    builder = InfraBuilder(tmp_path)
    assert builder._has_pytest_infrastructure(tmp_path) is True


def test_pytest_detected_via_pyproject_pytest_keyword(tmp_path: Path) -> None:
    """Pytest detected when pyproject.toml mentions pytest."""
    (tmp_path / "pyproject.toml").write_text('[project.optional-dependencies]\ndev = ["pytest"]\n')
    builder = InfraBuilder(tmp_path)
    assert builder._has_pytest_infrastructure(tmp_path) is True


def test_pytest_not_detected_empty_tests_dir(tmp_path: Path) -> None:
    """Pytest not detected with empty tests/ dir and no other markers."""
    (tmp_path / "tests").mkdir()
    builder = InfraBuilder(tmp_path)
    assert builder._has_pytest_infrastructure(tmp_path) is False


# ── Tests: Playwright detection edge cases ──────────────────────────


def test_playwright_detected_with_js_config(tmp_path: Path) -> None:
    """Playwright detected with playwright.config.js alongside dep."""
    (tmp_path / "playwright.config.js").write_text("export default {};")
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "^1.40.0"}}),
    )
    builder = InfraBuilder(tmp_path)
    assert builder._has_playwright_infrastructure(tmp_path) is True


def test_playwright_detected_with_mjs_config(tmp_path: Path) -> None:
    """Playwright detected with playwright.config.mjs alongside dep."""
    (tmp_path / "playwright.config.mjs").write_text("export default {};")
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "^1.40.0"}}),
    )
    builder = InfraBuilder(tmp_path)
    assert builder._has_playwright_infrastructure(tmp_path) is True


def test_playwright_not_detected_config_only(tmp_path: Path) -> None:
    """Playwright not detected when config exists but dep is missing."""
    (tmp_path / "playwright.config.ts").write_text("export default {};")
    builder = InfraBuilder(tmp_path)
    assert builder._has_playwright_infrastructure(tmp_path) is False


def test_playwright_not_detected_invalid_json(tmp_path: Path) -> None:
    """Playwright not detected when package.json has invalid JSON."""
    (tmp_path / "playwright.config.ts").write_text("export default {};")
    (tmp_path / "package.json").write_text("not-json")
    builder = InfraBuilder(tmp_path)
    assert builder._has_playwright_infrastructure(tmp_path) is False


# ── Tests: Project path resolution ──────────────────────────────────


@pytest.mark.asyncio
async def test_run_uses_project_root_when_path_empty(tmp_path: Path) -> None:
    """When project_path is empty, builder uses its own _root."""
    builder = InfraBuilder(tmp_path)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="vitest",
            language="typescript",
            project_path="",
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert (tmp_path / "vitest.config.ts").exists()


@pytest.mark.asyncio
async def test_run_resolves_relative_path(tmp_path: Path) -> None:
    """When project_path is relative, it is resolved from _root."""
    sub = tmp_path / "subdir"
    sub.mkdir()
    builder = InfraBuilder(tmp_path)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(
            framework="vitest",
            language="typescript",
            project_path="subdir",
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert (sub / "vitest.config.ts").exists()


# ── Tests: existing infrastructure skips bootstrap ──────────────────


@pytest.mark.asyncio
async def test_run_skips_for_existing_pytest(pytest_project: Path) -> None:
    """run() skips bootstrap when pytest infrastructure already exists."""
    builder = InfraBuilder(pytest_project)
    task = BootstrapTask(
        framework="pytest",
        language="python",
        project_path=str(pytest_project),
    )
    result = await builder.run(task)
    assert result.status == TaskStatus.COMPLETED
    assert "already exists" in result.result["message"]


@pytest.mark.asyncio
async def test_run_skips_for_existing_playwright(playwright_project: Path) -> None:
    """run() skips bootstrap when Playwright infrastructure already exists."""
    builder = InfraBuilder(playwright_project)
    task = BootstrapTask(
        framework="playwright",
        language="typescript",
        project_path=str(playwright_project),
    )
    result = await builder.run(task)
    assert result.status == TaskStatus.COMPLETED
    assert "already exists" in result.result["message"]


# ── Tests: Vitest config content verification ───────────────────────


@pytest.mark.asyncio
async def test_vitest_config_has_v8_coverage(empty_project: Path) -> None:
    """Vitest config references v8 coverage provider."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="vitest", project_path=str(empty_project))
        await builder.run(task)

    content = (empty_project / "vitest.config.ts").read_text()
    assert "v8" in content
    assert "coverage" in content


@pytest.mark.asyncio
async def test_vitest_setup_file_imports_jest_dom(empty_project: Path) -> None:
    """Vitest setup file imports @testing-library/jest-dom."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="vitest", project_path=str(empty_project))
        await builder.run(task)

    content = (empty_project / "src" / "test" / "setup.ts").read_text()
    assert "@testing-library/jest-dom" in content


# ── Tests: package.json script preservation ─────────────────────────


@pytest.mark.asyncio
async def test_vitest_does_not_overwrite_existing_test_script(
    empty_project: Path,
) -> None:
    """Vitest bootstrap does not overwrite existing 'test' script."""
    (empty_project / "package.json").write_text(
        json.dumps({"name": "t", "scripts": {"test": "jest"}}),
    )
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="vitest", project_path=str(empty_project))
        await builder.run(task)

    data = json.loads((empty_project / "package.json").read_text())
    assert data["scripts"]["test"] == "jest"
    # But new scripts should still be added
    assert "test:ui" in data["scripts"]
    assert "test:coverage" in data["scripts"]


@pytest.mark.asyncio
async def test_playwright_does_not_overwrite_existing_e2e_script(
    empty_project: Path,
) -> None:
    """Playwright bootstrap does not overwrite existing 'test:e2e' script."""
    (empty_project / "package.json").write_text(
        json.dumps({"name": "t", "scripts": {"test:e2e": "cypress"}}),
    )
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="playwright", project_path=str(empty_project))
        await builder.run(task)

    data = json.loads((empty_project / "package.json").read_text())
    assert data["scripts"]["test:e2e"] == "cypress"


# ── Tests: pyproject.toml preservation ──────────────────────────────


@pytest.mark.asyncio
async def test_pytest_does_not_duplicate_config_in_pyproject(
    empty_project: Path,
) -> None:
    """Pytest bootstrap skips pyproject update if config already present."""
    pyproject = empty_project / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "x"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="pytest", project_path=str(empty_project))
        await builder.run(task)

    content = pyproject.read_text()
    assert content.count("[tool.pytest.ini_options]") == 1


# ── Tests: Pytest bootstrap with venv ───────────────────────────────


@pytest.mark.asyncio
async def test_pytest_uses_venv_python_when_available(empty_project: Path) -> None:
    """Pytest bootstrap uses .venv/bin/python when it exists."""
    venv_bin = empty_project / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").write_text("#!/bin/sh")
    (venv_bin / "python").chmod(0o755)

    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="pytest", project_path=str(empty_project))
        await builder.run(task)

    call_args = mock_run.call_args[0][0]
    assert str(venv_bin / "python") in call_args[0]
    assert "-m" in call_args
    assert "pip" in call_args


@pytest.mark.asyncio
async def test_pytest_uses_plain_pip_without_venv(empty_project: Path) -> None:
    """Pytest bootstrap falls back to pip when no venv exists."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="pytest", project_path=str(empty_project))
        await builder.run(task)

    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "pip"


# ── Tests: Docker execution (_run_in_docker) ────────────────────────


@pytest.mark.asyncio
async def test_run_in_docker_builds_correct_command(tmp_path: Path) -> None:
    """_run_in_docker builds the expected docker run command."""
    builder = InfraBuilder(tmp_path)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        await builder._run_in_docker(
            ["npm", "install", "vitest"],
            tmp_path,
            "node:20-slim",
        )

    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "docker"
    assert "run" in call_args
    assert "--rm" in call_args
    assert "-v" in call_args
    assert f"{tmp_path}:/workspace" in call_args
    assert "-w" in call_args
    assert "/workspace" in call_args
    assert "node:20-slim" in call_args
    assert "npm" in call_args
    assert "vitest" in call_args


@pytest.mark.asyncio
async def test_run_in_docker_passes_timeout(tmp_path: Path) -> None:
    """_run_in_docker forwards timeout to _run_command."""
    builder = InfraBuilder(tmp_path)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        await builder._run_in_docker(
            ["echo", "hi"],
            tmp_path,
            "alpine",
            timeout=60.0,
        )

    assert mock_run.call_args[0][2] == 60.0


@pytest.mark.asyncio
async def test_docker_vitest_uses_node_image(empty_project: Path) -> None:
    """Vitest bootstrap in Docker uses node image by default."""
    builder = InfraBuilder(empty_project, enable_docker=True)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(framework="vitest", project_path=str(empty_project))
        await builder.run(task)

    # Find the call that has 'docker' in it
    docker_calls = [c for c in mock_run.call_args_list if "docker" in c[0][0]]
    assert len(docker_calls) > 0
    assert _DOCKER_IMAGE in docker_calls[0][0][0]


@pytest.mark.asyncio
async def test_docker_pytest_uses_python_image(empty_project: Path) -> None:
    """Pytest bootstrap in Docker uses python image by default."""
    builder = InfraBuilder(empty_project, enable_docker=True)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}

        task = BootstrapTask(framework="pytest", project_path=str(empty_project))
        await builder.run(task)

    docker_calls = [c for c in mock_run.call_args_list if "docker" in c[0][0]]
    assert len(docker_calls) > 0
    assert _DOCKER_PYTHON_IMAGE in docker_calls[0][0][0]


# ── Tests: _run_command error paths ─────────────────────────────────


@pytest.mark.asyncio
async def test_run_command_returns_timeout_error(tmp_path: Path) -> None:
    """_run_command returns error dict when command times out."""
    builder = InfraBuilder(tmp_path)

    with patch("nit.agents.builders.infra.asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = AsyncMock()
        mock_exec.return_value = mock_proc
        mock_proc.communicate.side_effect = TimeoutError

        result = await builder._run_command(["sleep", "999"], tmp_path, timeout=0.01)

    assert result["success"] is False
    assert "timed out" in str(result["error"])


@pytest.mark.asyncio
async def test_run_command_returns_error_on_exception(tmp_path: Path) -> None:
    """_run_command returns error dict for unexpected exceptions."""
    builder = InfraBuilder(tmp_path)

    with patch("nit.agents.builders.infra.asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = FileNotFoundError("not found")

        result = await builder._run_command(["nonexistent"], tmp_path)

    assert result["success"] is False
    assert "not found" in str(result["error"])


@pytest.mark.asyncio
async def test_run_command_returns_failure_on_nonzero_exit(tmp_path: Path) -> None:
    """_run_command returns failure when process exits non-zero."""
    builder = InfraBuilder(tmp_path)

    with patch("nit.agents.builders.infra.asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = AsyncMock()
        mock_exec.return_value = mock_proc
        mock_proc.communicate.return_value = (b"out", b"err")
        mock_proc.returncode = 1

        result = await builder._run_command(["false"], tmp_path)

    assert result["success"] is False
    assert result["stdout"] == "out"
    assert result["stderr"] == "err"
    assert "exit code 1" in str(result["error"])


@pytest.mark.asyncio
async def test_run_command_returns_success(tmp_path: Path) -> None:
    """_run_command returns success dict for zero exit code."""
    builder = InfraBuilder(tmp_path)

    with patch("nit.agents.builders.infra.asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = AsyncMock()
        mock_exec.return_value = mock_proc
        mock_proc.communicate.return_value = (b"hello", b"")
        mock_proc.returncode = 0

        result = await builder._run_command(["echo", "hello"], tmp_path)

    assert result["success"] is True
    assert result["stdout"] == "hello"
    assert result["error"] == ""


# ── Tests: Playwright bootstrap details ─────────────────────────────


@pytest.mark.asyncio
async def test_playwright_config_content_has_projects(empty_project: Path) -> None:
    """Playwright config includes browser project definitions."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="playwright", project_path=str(empty_project))
        await builder.run(task)

    content = (empty_project / "playwright.config.ts").read_text()
    assert "chromium" in content
    assert "firefox" in content
    assert "webkit" in content


@pytest.mark.asyncio
async def test_playwright_browser_install_on_success(empty_project: Path) -> None:
    """Playwright installs browsers after deps install succeeds (non-Docker)."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="playwright", project_path=str(empty_project))
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    # Check that npx playwright install was called (second _run_command call)
    calls = mock_run.call_args_list
    browser_calls = [c for c in calls if "playwright" in c[0][0] and "install" in c[0][0]]
    assert len(browser_calls) == 1


@pytest.mark.asyncio
async def test_playwright_skips_browser_install_in_docker(
    empty_project: Path,
) -> None:
    """Playwright skips browser install when using Docker."""
    builder = InfraBuilder(empty_project, enable_docker=True)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="playwright", project_path=str(empty_project))
        await builder.run(task)

    # In Docker mode, _run_command is invoked via _run_in_docker
    # which itself calls _run_command with docker prefix.
    # browser install should NOT happen (npx calls are skipped).
    calls = mock_run.call_args_list
    browser_calls = [
        c for c in calls if isinstance(c[0][0], list) and any(arg == "npx" for arg in c[0][0])
    ]
    assert len(browser_calls) == 0


@pytest.mark.asyncio
async def test_playwright_all_e2e_scripts_added(empty_project: Path) -> None:
    """Playwright adds test:e2e, test:e2e:ui, and test:e2e:headed scripts."""
    (empty_project / "package.json").write_text(json.dumps({"name": "t"}))
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="playwright", project_path=str(empty_project))
        await builder.run(task)

    data = json.loads((empty_project / "package.json").read_text())
    assert data["scripts"]["test:e2e"] == "playwright test"
    assert data["scripts"]["test:e2e:ui"] == "playwright test --ui"
    assert data["scripts"]["test:e2e:headed"] == "playwright test --headed"


# ── Tests: Vitest actions list ──────────────────────────────────────


@pytest.mark.asyncio
async def test_vitest_actions_include_all_steps(empty_project: Path) -> None:
    """Vitest bootstrap reports create_file, install_deps actions."""
    (empty_project / "package.json").write_text(json.dumps({"name": "t"}))
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="vitest", project_path=str(empty_project))
        result = await builder.run(task)

    action_types = [a["type"] for a in result.result["actions"]]
    assert "create_file" in action_types
    assert "install_deps" in action_types
    assert "update_scripts" in action_types


# ── Tests: Pytest actions list ──────────────────────────────────────


@pytest.mark.asyncio
async def test_pytest_actions_include_all_steps(empty_project: Path) -> None:
    """Pytest bootstrap reports create_dir, create_file, install_deps actions."""
    (empty_project / "pyproject.toml").write_text('[project]\nname = "x"\n')
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(framework="pytest", project_path=str(empty_project))
        result = await builder.run(task)

    action_types = [a["type"] for a in result.result["actions"]]
    assert "create_dir" in action_types
    assert "create_file" in action_types
    assert "install_deps" in action_types
    assert "update_config" in action_types


# ── Tests: result metadata ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_result_includes_framework_and_language(empty_project: Path) -> None:
    """Successful result includes framework, language, and project_path."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"success": True, "stdout": "", "stderr": "", "error": ""}
        task = BootstrapTask(
            framework="vitest",
            language="typescript",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.result["framework"] == "vitest"
    assert result.result["language"] == "typescript"
    assert result.result["project_path"] == str(empty_project)


# ── Tests: exception in bootstrap pipeline ──────────────────────────


@pytest.mark.asyncio
async def test_run_catches_unexpected_exception(empty_project: Path) -> None:
    """run() catches exceptions from _bootstrap_framework and returns FAILED."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_bootstrap_framework", side_effect=RuntimeError("boom")):
        task = BootstrapTask(
            framework="vitest",
            project_path=str(empty_project),
        )
        result = await builder.run(task)

    assert result.status == TaskStatus.FAILED
    assert "boom" in result.errors[0]


# ── Tests: command failure during playwright dep install ────────────


@pytest.mark.asyncio
async def test_playwright_dep_install_failure_skips_browsers(
    empty_project: Path,
) -> None:
    """When Playwright dep install fails, browser install is skipped."""
    builder = InfraBuilder(empty_project)

    with patch.object(builder, "_run_command", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {
            "success": False,
            "stdout": "",
            "stderr": "err",
            "error": "fail",
        }
        task = BootstrapTask(framework="playwright", project_path=str(empty_project))
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    # Only one call to _run_command (the failed npm install), no browser install
    assert mock_run.call_count == 1


# ── Tests: default timeout constant ────────────────────────────────


def test_default_timeout_value() -> None:
    """Module-level _DEFAULT_TIMEOUT is 300 seconds."""
    assert _DEFAULT_TIMEOUT == 300.0
