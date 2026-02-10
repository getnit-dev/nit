"""Tests for the IntegrationBuilder agent and integration dependency detection."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.agents.analyzers.integration_deps import (
    IntegrationDependencyType,
    detect_integration_dependencies,
)
from nit.agents.base import TaskInput, TaskStatus
from nit.agents.builders.integration import IntegrationBuilder, IntegrationBuildTask
from nit.llm.engine import GenerationRequest, LLMResponse
from nit.parsing.languages import extract_from_file

if TYPE_CHECKING:
    from pathlib import Path


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_llm_engine() -> MagicMock:
    """Create a mock LLM engine."""
    engine = MagicMock()
    engine.model_name = "gpt-4o"

    # Mock the generate method to return integration test code
    async def mock_generate(request: GenerationRequest) -> LLMResponse:
        test_code = (
            'import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";\n'
            'import { http, HttpResponse } from "msw";\n'
            'import { setupServer } from "msw/node";\n\n'
            "const server = setupServer();\n\n"
            "beforeEach(() => server.listen());\n"
            "afterEach(() => server.close());\n\n"
            'describe("API integration", () => {\n'
            '  it("should fetch data from API", async () => {\n'
            "    server.use(\n"
            '      http.get("/api/users", () => {\n'
            '        return HttpResponse.json([{ id: 1, name: "Test" }]);\n'
            "      })\n"
            "    );\n"
            "    // Test implementation\n"
            "  });\n"
            "});"
        )
        return LLMResponse(
            text=test_code,
            model="gpt-4o",
            prompt_tokens=800,
            completion_tokens=200,
        )

    engine.configure_mock(generate=AsyncMock(side_effect=mock_generate))
    return engine


@pytest.fixture
def python_http_client_file(tmp_path: Path) -> Path:
    """Create a Python file with HTTP client code."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    py_file = src_dir / "api_client.py"
    py_file.write_text('''"""API client module."""

import requests


def fetch_users():
    """Fetch users from the API."""
    response = requests.get("https://api.example.com/users")
    response.raise_for_status()
    return response.json()


def create_user(name: str, email: str):
    """Create a new user."""
    response = requests.post(
        "https://api.example.com/users",
        json={"name": name, "email": email}
    )
    response.raise_for_status()
    return response.json()
''')
    return py_file


@pytest.fixture
def python_db_file(tmp_path: Path) -> Path:
    """Create a Python file with database code."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    py_file = src_dir / "user_repository.py"
    py_file.write_text('''"""User repository module."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import User


def get_user_by_id(session: Session, user_id: int):
    """Get a user by ID."""
    stmt = select(User).where(User.id == user_id)
    return session.execute(stmt).scalar_one_or_none()


def create_user(session: Session, name: str, email: str):
    """Create a new user."""
    user = User(name=name, email=email)
    session.add(user)
    session.commit()
    return user
''')
    return py_file


@pytest.fixture
def typescript_http_file(tmp_path: Path) -> Path:
    """Create a TypeScript file with HTTP client code."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    ts_file = src_dir / "apiClient.ts"
    ts_file.write_text("""import axios from 'axios';

export interface User {
  id: number;
  name: string;
  email: string;
}

export async function fetchUsers(): Promise<User[]> {
  const response = await axios.get<User[]>('https://api.example.com/users');
  return response.data;
}

export async function createUser(name: string, email: string): Promise<User> {
  const response = await axios.post<User>('https://api.example.com/users', {
    name,
    email,
  });
  return response.data;
}
""")
    return ts_file


@pytest.fixture
def python_filesystem_file(tmp_path: Path) -> Path:
    """Create a Python file with filesystem operations."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    py_file = src_dir / "file_manager.py"
    py_file.write_text('''"""File management module."""

from pathlib import Path


def read_config(path: Path) -> dict:
    """Read configuration from file."""
    with open(path) as f:
        return eval(f.read())


def write_config(path: Path, config: dict) -> None:
    """Write configuration to file."""
    with open(path, 'w') as f:
        f.write(str(config))
''')
    return py_file


@pytest.fixture
def pytest_project(tmp_path: Path) -> Path:
    """Create a minimal pytest project structure."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""[project]
name = "test-project"

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-mock>=3.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""")

    conftest = tmp_path / "conftest.py"
    conftest.write_text("# pytest configuration\n")

    return tmp_path


@pytest.fixture
def vitest_project(tmp_path: Path) -> Path:
    """Create a minimal Vitest project structure."""
    package_json = tmp_path / "package.json"
    package_json.write_text("""{
  "name": "test-project",
  "devDependencies": {
    "vitest": "^0.34.0",
    "msw": "^2.0.0"
  }
}
""")

    vitest_config = tmp_path / "vitest.config.ts"
    vitest_config.write_text("""import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {},
});
""")

    return tmp_path


# ── Integration Dependency Detection Tests ───────────────────────────


def test_detect_http_dependency_python(python_http_client_file: Path) -> None:
    """Test detecting HTTP client dependency in Python code."""
    parse_result = extract_from_file(str(python_http_client_file))
    report = detect_integration_dependencies(python_http_client_file, parse_result, "python")

    assert report.needs_integration_tests
    assert len(report.dependencies) > 0

    # Find HTTP client dependency
    http_deps = [
        d for d in report.dependencies if d.dependency_type == IntegrationDependencyType.HTTP_CLIENT
    ]
    assert len(http_deps) > 0

    http_dep = http_deps[0]
    assert "requests" in http_dep.module_name.lower()
    # Function mapping is a heuristic - it may or may not detect usage
    # The important part is that we detected the HTTP dependency

    # Check mocking strategies
    assert len(http_dep.mock_strategies) > 0
    assert any("responses" in s or "mock" in s.lower() for s in http_dep.mock_strategies)


def test_detect_database_dependency_python(python_db_file: Path) -> None:
    """Test detecting database dependency in Python code."""
    parse_result = extract_from_file(str(python_db_file))
    report = detect_integration_dependencies(python_db_file, parse_result, "python")

    assert report.needs_integration_tests
    assert len(report.dependencies) > 0

    # Find database dependency
    db_deps = [
        d for d in report.dependencies if d.dependency_type == IntegrationDependencyType.DATABASE
    ]
    assert len(db_deps) > 0

    db_dep = db_deps[0]
    assert "sqlalchemy" in db_dep.module_name.lower()


def test_detect_http_dependency_typescript(typescript_http_file: Path) -> None:
    """Test detecting HTTP client dependency in TypeScript code."""
    parse_result = extract_from_file(str(typescript_http_file))
    report = detect_integration_dependencies(typescript_http_file, parse_result, "typescript")

    assert report.needs_integration_tests
    assert len(report.dependencies) > 0

    # Find HTTP client dependency
    http_deps = [
        d for d in report.dependencies if d.dependency_type == IntegrationDependencyType.HTTP_CLIENT
    ]
    assert len(http_deps) > 0

    http_dep = http_deps[0]
    assert "axios" in http_dep.module_name.lower()

    # Check mocking strategies for TypeScript
    assert len(http_dep.mock_strategies) > 0
    assert any("msw" in s.lower() or "nock" in s.lower() for s in http_dep.mock_strategies)


def test_detect_filesystem_dependency(python_filesystem_file: Path) -> None:
    """Test detecting filesystem dependency."""
    parse_result = extract_from_file(str(python_filesystem_file))
    report = detect_integration_dependencies(python_filesystem_file, parse_result, "python")

    assert report.needs_integration_tests
    assert len(report.dependencies) > 0

    # Find filesystem dependency
    fs_deps = [
        d for d in report.dependencies if d.dependency_type == IntegrationDependencyType.FILESYSTEM
    ]
    assert len(fs_deps) > 0


def test_recommended_fixtures_http(python_http_client_file: Path) -> None:
    """Test that HTTP dependencies generate appropriate fixture recommendations."""
    parse_result = extract_from_file(str(python_http_client_file))
    report = detect_integration_dependencies(python_http_client_file, parse_result, "python")

    assert len(report.recommended_fixtures) > 0
    assert any("http" in f.lower() or "response" in f.lower() for f in report.recommended_fixtures)


def test_recommended_fixtures_database(python_db_file: Path) -> None:
    """Test that database dependencies generate appropriate fixture recommendations."""
    parse_result = extract_from_file(str(python_db_file))
    report = detect_integration_dependencies(python_db_file, parse_result, "python")

    assert len(report.recommended_fixtures) > 0
    assert any(
        "database" in f.lower() or "session" in f.lower() or "model" in f.lower()
        for f in report.recommended_fixtures
    )


# ── IntegrationBuildTask Tests ────────────────────────────────────────


def test_integration_build_task_initialization() -> None:
    """Test IntegrationBuildTask initialization sets correct fields."""
    task = IntegrationBuildTask(
        source_file="src/api_client.py",
        framework="pytest",
        output_file="tests/integration/test_api_client.py",
    )

    assert task.source_file == "src/api_client.py"
    assert task.framework == "pytest"
    assert task.output_file == "tests/integration/test_api_client.py"
    assert task.task_type == "build_integration_test"
    assert task.target == "src/api_client.py"


def test_integration_build_task_post_init() -> None:
    """Test IntegrationBuildTask __post_init__ sets target from source_file."""
    task = IntegrationBuildTask(
        source_file="src/api_client.py",
        framework="pytest",
    )

    assert task.target == "src/api_client.py"


# ── IntegrationBuilder Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_integration_builder_basic_generation(
    mock_llm_engine: MagicMock,
    python_http_client_file: Path,
    pytest_project: Path,
) -> None:
    """Test basic integration test generation."""
    # Set up the project root to be the pytest project
    project_root = pytest_project

    # Move the source file into the project
    src_in_project = project_root / "src"
    src_in_project.mkdir(exist_ok=True)
    (src_in_project / "api_client.py").write_text(python_http_client_file.read_text())

    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=project_root,
        enable_memory=False,
        validation_config={"enabled": False},
    )

    task = IntegrationBuildTask(
        source_file="src/api_client.py",
        framework="pytest",
    )

    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert "test_code" in result.result
    assert len(result.result["test_code"]) > 0
    assert result.result["framework"] == "pytest"
    assert "integration_dependencies" in result.result
    assert result.result["integration_dependencies"] > 0


@pytest.mark.asyncio
async def test_integration_builder_detects_http_dependency(
    mock_llm_engine: MagicMock,
    python_http_client_file: Path,
    pytest_project: Path,
) -> None:
    """Test that IntegrationBuilder detects HTTP dependencies."""
    project_root = pytest_project
    src_in_project = project_root / "src"
    src_in_project.mkdir(exist_ok=True)
    (src_in_project / "api_client.py").write_text(python_http_client_file.read_text())

    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=project_root,
        enable_memory=False,
        validation_config={"enabled": False},
    )

    task = IntegrationBuildTask(
        source_file="src/api_client.py",
        framework="pytest",
    )

    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert "dependency_types" in result.result
    assert IntegrationDependencyType.HTTP_CLIENT.value in result.result["dependency_types"]


@pytest.mark.asyncio
async def test_integration_builder_detects_database_dependency(
    mock_llm_engine: MagicMock,
    python_db_file: Path,
    pytest_project: Path,
) -> None:
    """Test that IntegrationBuilder detects database dependencies."""
    project_root = pytest_project
    src_in_project = project_root / "src"
    src_in_project.mkdir(exist_ok=True)
    (src_in_project / "user_repository.py").write_text(python_db_file.read_text())

    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=project_root,
        enable_memory=False,
        validation_config={"enabled": False},
    )

    task = IntegrationBuildTask(
        source_file="src/user_repository.py",
        framework="pytest",
    )

    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert "dependency_types" in result.result
    assert IntegrationDependencyType.DATABASE.value in result.result["dependency_types"]


@pytest.mark.asyncio
async def test_integration_builder_uses_correct_template(
    mock_llm_engine: MagicMock,
    typescript_http_file: Path,
    vitest_project: Path,
) -> None:
    """Test that IntegrationBuilder uses the correct template for the framework."""
    project_root = vitest_project
    src_in_project = project_root / "src"
    src_in_project.mkdir(exist_ok=True)
    (src_in_project / "apiClient.ts").write_text(typescript_http_file.read_text())

    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=project_root,
        enable_memory=False,
        validation_config={"enabled": False},
    )

    task = IntegrationBuildTask(
        source_file="src/apiClient.ts",
        framework="vitest",
    )

    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED

    # Verify the LLM was called
    mock_llm_engine.generate.assert_called_once()

    # Get the actual call arguments
    call_args = mock_llm_engine.generate.call_args
    request = call_args[0][0]

    # Check that the prompt includes Vitest-specific instructions
    prompt_text = " ".join([msg.content for msg in request.messages])
    assert "vitest" in prompt_text.lower() or "msw" in prompt_text.lower()


@pytest.mark.asyncio
async def test_integration_builder_handles_no_dependencies(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
    pytest_project: Path,
) -> None:
    """Test IntegrationBuilder handles files with no integration dependencies gracefully."""
    # Create a simple file with no external dependencies
    project_root = pytest_project
    src_in_project = project_root / "src"
    src_in_project.mkdir(exist_ok=True)
    simple_file = src_in_project / "utils.py"
    simple_file.write_text("""def add(a: int, b: int) -> int:
    return a + b
""")

    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=project_root,
        enable_memory=False,
        validation_config={"enabled": False},
    )

    task = IntegrationBuildTask(
        source_file="src/utils.py",
        framework="pytest",
    )

    result = await builder.run(task)

    # Should still complete, but note no dependencies
    assert result.status == TaskStatus.COMPLETED
    assert result.result["integration_dependencies"] == 0


@pytest.mark.asyncio
async def test_integration_builder_invalid_task_type(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test IntegrationBuilder rejects invalid task types."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    invalid_task = TaskInput(task_type="invalid", target="invalid")

    result = await builder.run(invalid_task)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) > 0
    assert "IntegrationBuildTask" in result.errors[0] or "BuildTask" in result.errors[0]


@pytest.mark.asyncio
async def test_integration_builder_invalid_source_file(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test IntegrationBuilder handles missing source files."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    task = IntegrationBuildTask(
        source_file="nonexistent/file.py",
        framework="pytest",
    )

    result = await builder.run(task)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) > 0
