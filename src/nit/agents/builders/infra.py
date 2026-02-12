"""InfraBuilder agent — bootstraps test infrastructure when none exists.

This agent:
1. Detects missing test infrastructure for a given framework
2. Bootstraps it by installing dependencies, creating config files, and adding scripts
3. Supports Vitest, pytest, and Playwright frameworks
4. Optionally runs bootstrap actions in Docker container for isolation
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus

logger = logging.getLogger(__name__)

# Constants
_DEFAULT_TIMEOUT = 300.0  # Bootstrap operations can take longer
_DOCKER_IMAGE = "node:20-slim"  # Default Docker image for Node.js projects
_DOCKER_PYTHON_IMAGE = "python:3.12-slim"  # Default Docker image for Python projects


@dataclass
class BootstrapTask(TaskInput):
    """Task input for bootstrapping test infrastructure.

    Extends TaskInput with infrastructure-specific fields.
    """

    task_type: str = "bootstrap_infra"
    """Type of task (defaults to 'bootstrap_infra')."""

    target: str = ""
    """Target for the task (defaults to framework name)."""

    framework: str = ""
    """Framework to bootstrap (e.g., 'vitest', 'pytest', 'playwright')."""

    language: str = ""
    """Language for the framework (e.g., 'typescript', 'python')."""

    project_path: str = ""
    """Path to the project where infrastructure should be bootstrapped."""

    use_docker: bool = False
    """Whether to run bootstrap actions in Docker container."""

    docker_image: str = ""
    """Optional: custom Docker image to use. If empty, uses default based on language."""

    def __post_init__(self) -> None:
        """Initialize base TaskInput fields if not already set."""
        if not self.target and self.framework:
            self.target = self.framework


class InfraBuilder(BaseAgent):
    """Agent that bootstraps test infrastructure when none exists.

    Detects missing infrastructure and creates necessary configuration files,
    installs dependencies, and sets up scripts for test frameworks.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        enable_docker: bool = False,
        docker_image: str = "",
    ) -> None:
        """Initialize the InfraBuilder agent.

        Args:
            project_root: Root directory of the project.
            enable_docker: Whether to enable Docker execution mode by default.
            docker_image: Custom Docker image to use (if empty, uses defaults).
        """
        self._root = project_root
        self._enable_docker = enable_docker
        self._docker_image = docker_image

    @property
    def name(self) -> str:
        """Unique name identifying this agent."""
        return "infra_builder"

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return "Bootstraps test infrastructure by installing dependencies and creating config files"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute the infrastructure bootstrap pipeline.

        Args:
            task: A BootstrapTask specifying the framework to bootstrap.

        Returns:
            TaskOutput with bootstrap results in result['actions'],
            or errors if bootstrap failed.
        """
        if not isinstance(task, BootstrapTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a BootstrapTask instance"],
            )

        try:
            logger.info(
                "Starting infrastructure bootstrap for framework: %s",
                task.framework,
            )

            # Resolve project path
            project_path = Path(task.project_path) if task.project_path else self._root
            if not project_path.is_absolute():
                project_path = self._root / project_path

            # Check if framework infrastructure already exists
            if self._has_infrastructure(task.framework, project_path):
                logger.info("Infrastructure for %s already exists", task.framework)
                return TaskOutput(
                    status=TaskStatus.COMPLETED,
                    result={
                        "framework": task.framework,
                        "message": "Infrastructure already exists",
                        "actions": [],
                    },
                )

            # Determine whether to use Docker
            use_docker = task.use_docker or self._enable_docker

            # Bootstrap the framework
            actions = await self._bootstrap_framework(
                framework=task.framework,
                _language=task.language,
                project_path=project_path,
                use_docker=use_docker,
                docker_image=task.docker_image or self._docker_image,
            )

            logger.info(
                "Successfully bootstrapped %s infrastructure with %d actions",
                task.framework,
                len(actions),
            )

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "framework": task.framework,
                    "language": task.language,
                    "actions": actions,
                    "project_path": str(project_path),
                },
            )

        except Exception as exc:
            logger.exception("Failed to bootstrap infrastructure for %s", task.framework)
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Bootstrap failed: {exc}"],
            )

    def _has_infrastructure(self, framework: str, project_path: Path) -> bool:
        """Check if infrastructure for a framework already exists.

        Args:
            framework: Framework name (e.g., 'vitest', 'pytest', 'playwright').
            project_path: Path to the project.

        Returns:
            True if infrastructure exists, False otherwise.
        """
        if framework == "vitest":
            return self._has_vitest_infrastructure(project_path)
        if framework == "pytest":
            return self._has_pytest_infrastructure(project_path)
        if framework == "playwright":
            return self._has_playwright_infrastructure(project_path)
        return False

    def _has_vitest_infrastructure(self, project_path: Path) -> bool:
        """Check if Vitest infrastructure exists."""
        # Check for config file
        config_patterns = ["vitest.config.ts", "vitest.config.js", "vitest.config.mjs"]
        has_config = any((project_path / cfg).exists() for cfg in config_patterns)

        # Check for package.json with vitest dependency
        package_json = project_path / "package.json"
        has_dep = False
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                dev_deps = data.get("devDependencies", {})
                has_dep = "vitest" in dev_deps
            except (json.JSONDecodeError, OSError):
                pass

        return has_config and has_dep

    def _has_pytest_infrastructure(self, project_path: Path) -> bool:
        """Check if pytest infrastructure exists."""
        # Check for pytest in pyproject.toml or setup.cfg
        pyproject_toml = project_path / "pyproject.toml"
        if pyproject_toml.exists():
            content = pyproject_toml.read_text()
            if "[tool.pytest" in content or "pytest" in content:
                return True

        # Check for conftest.py
        conftest = project_path / "conftest.py"
        if conftest.exists():
            return True

        # Check for tests directory with test files
        tests_dir = project_path / "tests"
        if tests_dir.exists() and tests_dir.is_dir():
            test_files = list(tests_dir.glob("test_*.py")) + list(tests_dir.glob("*_test.py"))
            if test_files:
                return True

        return False

    def _has_playwright_infrastructure(self, project_path: Path) -> bool:
        """Check if Playwright infrastructure exists."""
        # Check for config file
        config_patterns = [
            "playwright.config.ts",
            "playwright.config.js",
            "playwright.config.mjs",
        ]
        has_config = any((project_path / cfg).exists() for cfg in config_patterns)

        # Check for package.json with @playwright/test dependency
        package_json = project_path / "package.json"
        has_dep = False
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                dev_deps = data.get("devDependencies", {})
                has_dep = "@playwright/test" in dev_deps
            except (json.JSONDecodeError, OSError):
                pass

        return has_config and has_dep

    async def _bootstrap_framework(
        self,
        framework: str,
        _language: str,
        project_path: Path,
        *,
        use_docker: bool,
        docker_image: str,
    ) -> list[dict[str, str]]:
        """Bootstrap infrastructure for a specific framework.

        Args:
            framework: Framework name.
            language: Language for the framework.
            project_path: Path to the project.
            use_docker: Whether to use Docker.
            docker_image: Docker image to use.

        Returns:
            List of actions performed (dict with 'type' and 'description').
        """
        if framework == "vitest":
            return await self._bootstrap_vitest(
                project_path,
                use_docker=use_docker,
                docker_image=docker_image,
            )
        if framework == "pytest":
            return await self._bootstrap_pytest(
                project_path,
                use_docker=use_docker,
                docker_image=docker_image,
            )
        if framework == "playwright":
            return await self._bootstrap_playwright(
                project_path,
                use_docker=use_docker,
                docker_image=docker_image,
            )

        msg = f"Unknown framework: {framework}"
        raise ValueError(msg)

    async def _bootstrap_vitest(
        self,
        project_path: Path,
        *,
        use_docker: bool,
        docker_image: str,
    ) -> list[dict[str, str]]:
        """Bootstrap Vitest infrastructure (task 2.8.2).

        Creates vitest.config.ts, installs vitest + @testing-library/react,
        adds test scripts to package.json.
        """
        actions: list[dict[str, str]] = []

        # Create vitest.config.ts
        config_path = project_path / "vitest.config.ts"
        if not config_path.exists():
            config_content = """import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
    },
  },
});
"""
            config_path.write_text(config_content)
            actions.append({"type": "create_file", "description": "Created vitest.config.ts"})
            logger.info("Created %s", config_path)

        # Create test setup file directory
        setup_dir = project_path / "src" / "test"
        setup_dir.mkdir(parents=True, exist_ok=True)
        setup_file = setup_dir / "setup.ts"
        if not setup_file.exists():
            setup_content = """import '@testing-library/jest-dom';
"""
            setup_file.write_text(setup_content)
            actions.append({"type": "create_file", "description": "Created src/test/setup.ts"})
            logger.info("Created %s", setup_file)

        # Install dependencies
        deps = [
            "vitest",
            "@vitejs/plugin-react",
            "@testing-library/react",
            "@testing-library/jest-dom",
        ]
        if use_docker:
            install_result = await self._run_in_docker(
                ["npm", "install", "--save-dev", *deps],
                project_path,
                docker_image or _DOCKER_IMAGE,
            )
        else:
            install_result = await self._run_command(
                ["npm", "install", "--save-dev", *deps],
                project_path,
            )

        if install_result["success"]:
            actions.append(
                {
                    "type": "install_deps",
                    "description": f"Installed dependencies: {', '.join(deps)}",
                }
            )
            logger.info("Installed Vitest dependencies")
        else:
            logger.warning("Failed to install dependencies: %s", install_result.get("error"))

        # Add test scripts to package.json
        package_json = project_path / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                scripts = data.setdefault("scripts", {})
                if "test" not in scripts:
                    scripts["test"] = "vitest"
                if "test:ui" not in scripts:
                    scripts["test:ui"] = "vitest --ui"
                if "test:coverage" not in scripts:
                    scripts["test:coverage"] = "vitest --coverage"
                package_json.write_text(json.dumps(data, indent=2) + "\n")
                actions.append(
                    {"type": "update_scripts", "description": "Added test scripts to package.json"}
                )
                logger.info("Updated package.json scripts")
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to update package.json: %s", exc)

        return actions

    async def _bootstrap_pytest(
        self,
        project_path: Path,
        *,
        use_docker: bool,
        docker_image: str,
    ) -> list[dict[str, str]]:
        """Bootstrap pytest infrastructure (task 2.8.3).

        Creates conftest.py, adds pytest to dev dependencies, creates test directory.
        """
        actions: list[dict[str, str]] = []

        # Create tests directory
        tests_dir = project_path / "tests"
        tests_dir.mkdir(exist_ok=True)
        actions.append({"type": "create_dir", "description": "Created tests/ directory"})
        logger.info("Created %s", tests_dir)

        # Create conftest.py
        conftest_path = project_path / "conftest.py"
        if not conftest_path.exists():
            conftest_content = '''"""Pytest configuration and fixtures."""

import pytest
'''
            conftest_path.write_text(conftest_content)
            actions.append({"type": "create_file", "description": "Created conftest.py"})
            logger.info("Created %s", conftest_path)

        # Create __init__.py in tests directory
        init_file = tests_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("")
            actions.append({"type": "create_file", "description": "Created tests/__init__.py"})

        # Update pyproject.toml with pytest configuration
        pyproject_toml = project_path / "pyproject.toml"
        if pyproject_toml.exists():
            content = pyproject_toml.read_text()
            if "[tool.pytest.ini_options]" not in content:
                pytest_config = """

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "--strict-markers",
    "--strict-config",
    "--cov=src",
    "--cov-report=term-missing",
    "--cov-report=html",
    "--cov-report=json",
]
"""
                pyproject_toml.write_text(content + pytest_config)
                actions.append(
                    {
                        "type": "update_config",
                        "description": "Added pytest configuration to pyproject.toml",
                    }
                )
                logger.info("Updated pyproject.toml with pytest config")

        # Install pytest and pytest-cov
        deps = ["pytest", "pytest-cov", "pytest-asyncio"]
        if use_docker:
            install_result = await self._run_in_docker(
                ["pip", "install", *deps],
                project_path,
                docker_image or _DOCKER_PYTHON_IMAGE,
            )
        else:
            # Check if using virtual environment
            venv_python = project_path / ".venv" / "bin" / "python"
            if venv_python.exists():
                install_result = await self._run_command(
                    [str(venv_python), "-m", "pip", "install", *deps],
                    project_path,
                )
            else:
                install_result = await self._run_command(
                    ["pip", "install", *deps],
                    project_path,
                )

        if install_result["success"]:
            actions.append(
                {
                    "type": "install_deps",
                    "description": f"Installed dependencies: {', '.join(deps)}",
                }
            )
            logger.info("Installed pytest dependencies")
        else:
            logger.warning("Failed to install dependencies: %s", install_result.get("error"))

        return actions

    async def _bootstrap_playwright(
        self,
        project_path: Path,
        *,
        use_docker: bool,
        docker_image: str,
    ) -> list[dict[str, str]]:
        """Bootstrap Playwright infrastructure (task 2.8.4).

        Installs @playwright/test, creates playwright.config.ts, creates example test.
        """
        actions: list[dict[str, str]] = []

        # Create config and test files
        actions.extend(self._create_playwright_config(project_path))
        actions.extend(self._create_playwright_example_test(project_path))

        # Install dependencies
        deps_actions = await self._install_playwright_deps(
            project_path,
            use_docker=use_docker,
            docker_image=docker_image,
        )
        actions.extend(deps_actions)

        # Update package.json scripts
        actions.extend(self._update_playwright_scripts(project_path))

        return actions

    def _create_playwright_config(self, project_path: Path) -> list[dict[str, str]]:
        """Create playwright.config.ts file."""
        actions: list[dict[str, str]] = []
        config_path = project_path / "playwright.config.ts"
        if not config_path.exists():
            config_content = """import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
  },
});
"""
            config_path.write_text(config_content)
            actions.append({"type": "create_file", "description": "Created playwright.config.ts"})
            logger.info("Created %s", config_path)
        return actions

    def _create_playwright_example_test(self, project_path: Path) -> list[dict[str, str]]:
        """Create e2e directory and example test."""
        actions: list[dict[str, str]] = []

        # Create e2e directory
        e2e_dir = project_path / "e2e"
        e2e_dir.mkdir(exist_ok=True)
        actions.append({"type": "create_dir", "description": "Created e2e/ directory"})
        logger.info("Created %s", e2e_dir)

        # Create example test
        example_test = e2e_dir / "example.spec.ts"
        if not example_test.exists():
            example_content = """import { test, expect } from '@playwright/test';

test('homepage has correct title', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Home/);
});

test('navigation works', async ({ page }) => {
  await page.goto('/');
  // Add your test assertions here
});
"""
            example_test.write_text(example_content)
            actions.append({"type": "create_file", "description": "Created e2e/example.spec.ts"})
            logger.info("Created %s", example_test)

        return actions

    async def _install_playwright_deps(
        self,
        project_path: Path,
        *,
        use_docker: bool,
        docker_image: str,
    ) -> list[dict[str, str]]:
        """Install Playwright dependencies."""
        actions: list[dict[str, str]] = []
        deps = ["@playwright/test"]

        if use_docker:
            install_result = await self._run_in_docker(
                ["npm", "install", "--save-dev", *deps],
                project_path,
                docker_image or _DOCKER_IMAGE,
            )
        else:
            install_result = await self._run_command(
                ["npm", "install", "--save-dev", *deps],
                project_path,
            )

        if install_result["success"]:
            actions.append(
                {
                    "type": "install_deps",
                    "description": f"Installed dependencies: {', '.join(deps)}",
                }
            )
            logger.info("Installed Playwright dependencies")

            # Install Playwright browsers (only if not in Docker)
            if not use_docker:
                browser_install = await self._run_command(
                    ["npx", "playwright", "install", "--with-deps"],
                    project_path,
                )
                if browser_install["success"]:
                    actions.append(
                        {"type": "install_browsers", "description": "Installed Playwright browsers"}
                    )
                    logger.info("Installed Playwright browsers")
        else:
            logger.warning("Failed to install dependencies: %s", install_result.get("error"))

        return actions

    def _update_playwright_scripts(self, project_path: Path) -> list[dict[str, str]]:
        """Add Playwright test scripts to package.json."""
        actions: list[dict[str, str]] = []
        package_json = project_path / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                scripts = data.setdefault("scripts", {})
                if "test:e2e" not in scripts:
                    scripts["test:e2e"] = "playwright test"
                if "test:e2e:ui" not in scripts:
                    scripts["test:e2e:ui"] = "playwright test --ui"
                if "test:e2e:headed" not in scripts:
                    scripts["test:e2e:headed"] = "playwright test --headed"
                package_json.write_text(json.dumps(data, indent=2) + "\n")
                actions.append(
                    {
                        "type": "update_scripts",
                        "description": "Added E2E test scripts to package.json",
                    }
                )
                logger.info("Updated package.json scripts")
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to update package.json: %s", exc)
        return actions

    async def _run_command(
        self,
        cmd: list[str],
        cwd: Path,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, object]:
        """Run a command in the specified directory.

        Args:
            cmd: Command and arguments to run.
            cwd: Working directory.
            timeout: Timeout in seconds.

        Returns:
            Dict with 'success' (bool), 'stdout' (str), 'stderr' (str), 'error' (str).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            success = proc.returncode == 0
            return {
                "success": success,
                "stdout": stdout,
                "stderr": stderr,
                "error": "" if success else f"Command failed with exit code {proc.returncode}",
            }
        except TimeoutError:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": f"Command timed out after {timeout} seconds",
            }
        except Exception as exc:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": str(exc),
            }

    async def _run_in_docker(
        self,
        cmd: list[str],
        cwd: Path,
        image: str,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, object]:
        """Run a command in a Docker container (task 2.8.5).

        Args:
            cmd: Command and arguments to run.
            cwd: Working directory (mounted as /workspace).
            image: Docker image to use.
            timeout: Timeout in seconds.

        Returns:
            Dict with 'success' (bool), 'stdout' (str), 'stderr' (str), 'error' (str).
        """
        # Build docker run command
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{cwd}:/workspace",
            "-w",
            "/workspace",
            image,
            *cmd,
        ]

        logger.info("Running command in Docker: %s", " ".join(docker_cmd))
        return await self._run_command(docker_cmd, cwd, timeout)
