"""Tests for the IntegrationBuilder agent and integration dependency detection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.adapters.base import CaseResult, CaseStatus, RunResult
from nit.agents.analyzers.integration_deps import (
    DetectedDependency,
    IntegrationDependencyReport,
    IntegrationDependencyType,
    detect_integration_dependencies,
)
from nit.agents.base import TaskInput, TaskStatus
from nit.agents.builders.integration import IntegrationBuilder, IntegrationBuildTask
from nit.agents.builders.unit import BuildTask, FailureType, ValidationAttempt
from nit.llm.engine import GenerationRequest, LLMError, LLMResponse
from nit.llm.prompts.integration_test import (
    IntegrationTestTemplate,
    JestIntegrationTemplate,
    PytestIntegrationTemplate,
    VitestIntegrationTemplate,
)
from nit.parsing.languages import extract_from_file

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


# ── Additional IntegrationBuilder coverage tests ─────────────────────


def test_integration_build_task_explicit_target() -> None:
    """Test IntegrationBuildTask keeps explicit target when provided."""
    task = IntegrationBuildTask(
        source_file="src/api_client.py",
        framework="pytest",
        target="custom_target",
    )
    assert task.target == "custom_target"


def test_builder_properties(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test name and description properties."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    assert builder.name == "integration_builder"
    assert "integration" in builder.description.lower()


def test_resolve_path_absolute(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _resolve_path returns absolute paths unchanged."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    abs_path = Path("/absolute/path/file.py").resolve()
    assert builder._resolve_path(str(abs_path)) == abs_path


def test_resolve_path_relative(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _resolve_path resolves relative paths to project root."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    resolved = builder._resolve_path("src/file.py")
    assert resolved == pytest_project / "src" / "file.py"


def test_get_integration_template_pytest(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _get_integration_template returns PytestIntegrationTemplate."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    template = builder._get_integration_template("pytest")
    assert isinstance(template, PytestIntegrationTemplate)


def test_get_integration_template_vitest(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _get_integration_template returns VitestIntegrationTemplate."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    template = builder._get_integration_template("vitest")
    assert isinstance(template, VitestIntegrationTemplate)


def test_get_integration_template_jest(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _get_integration_template returns JestIntegrationTemplate."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    template = builder._get_integration_template("jest")
    assert isinstance(template, JestIntegrationTemplate)


def test_get_integration_template_fallback(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _get_integration_template falls back to generic template."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    template = builder._get_integration_template("unknown_framework")
    assert type(template) is IntegrationTestTemplate


def test_handle_generation_error_value_error(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _handle_generation_error with ValueError."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    result = builder._handle_generation_error(ValueError("bad input"))
    assert result.status == TaskStatus.FAILED
    assert "Invalid input" in result.errors[0]


def test_handle_generation_error_llm_error(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _handle_generation_error with LLMError."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    result = builder._handle_generation_error(LLMError("model failure"))
    assert result.status == TaskStatus.FAILED
    assert "LLM error" in result.errors[0]


def test_handle_generation_error_unexpected(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _handle_generation_error with unexpected exception."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    result = builder._handle_generation_error(RuntimeError("oops"))
    assert result.status == TaskStatus.FAILED
    assert "Unexpected error" in result.errors[0]


def test_handle_generation_error_llm_error_updates_memory(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _handle_generation_error with LLMError updates memory stats."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=True,
    )
    # Replace memory with a mock
    builder._memory = MagicMock()
    builder._handle_generation_error(LLMError("fail"))
    builder._memory.update_stats.assert_called_once_with(successful=False)


def test_add_integration_info_no_messages_attr(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _add_integration_info_to_prompt with object lacking messages."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    report = IntegrationDependencyReport(
        source_path=pytest_project / "file.py",
        language="python",
    )
    # Should not raise — silently return
    builder._add_integration_info_to_prompt(object(), report)


def test_add_integration_info_no_dependencies(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _add_integration_info_to_prompt with no dependencies."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    report = IntegrationDependencyReport(
        source_path=pytest_project / "file.py",
        language="python",
    )
    rendered = SimpleNamespace(messages=[])
    builder._add_integration_info_to_prompt(rendered, report)
    assert len(rendered.messages) == 1
    assert "No external dependencies detected" in rendered.messages[0].content


def test_add_integration_info_with_dependencies(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _add_integration_info_to_prompt with dependencies."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    dep = DetectedDependency(
        dependency_type=IntegrationDependencyType.HTTP_CLIENT,
        module_name="requests",
        pattern_matched="requests",
        used_in_functions=["fetch_data"],
        mock_strategies=["responses", "unittest.mock.patch"],
    )
    report = IntegrationDependencyReport(
        source_path=pytest_project / "file.py",
        language="python",
        dependencies=[dep],
        needs_integration_tests=True,
        recommended_fixtures=["http_mock_fixture"],
    )
    rendered = SimpleNamespace(messages=[])
    builder._add_integration_info_to_prompt(rendered, report)
    content = rendered.messages[0].content
    assert "HTTP_CLIENT" in content
    assert "requests" in content
    assert "fetch_data" in content
    assert "responses" in content
    assert "http_mock_fixture" in content


def test_classify_test_failure_missing_dep(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _classify_test_failure identifies missing dependency."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    result = RunResult(
        failed=1,
        test_cases=[
            CaseResult(
                name="test_it",
                status=CaseStatus.FAILED,
                failure_message="ModuleNotFoundError: No module named 'foo'",
            )
        ],
    )
    assert builder._classify_test_failure(result) == FailureType.MISSING_DEP


def test_classify_test_failure_test_bug(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _classify_test_failure identifies test bug."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    result = RunResult(
        failed=1,
        test_cases=[
            CaseResult(
                name="test_it",
                status=CaseStatus.FAILED,
                failure_message="AssertionError: expected 1 but got 2",
            )
        ],
    )
    assert builder._classify_test_failure(result) == FailureType.TEST_BUG


def test_classify_test_failure_default(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _classify_test_failure defaults to TEST_BUG for unknown errors."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    result = RunResult(
        failed=1,
        test_cases=[
            CaseResult(
                name="test_it",
                status=CaseStatus.FAILED,
                failure_message="some random error not in patterns",
            )
        ],
    )
    assert builder._classify_test_failure(result) == FailureType.TEST_BUG


def test_extract_error_message_from_test_cases(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _extract_error_message extracts from test cases."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    result = RunResult(
        failed=2,
        test_cases=[
            CaseResult(
                name="test_a",
                status=CaseStatus.FAILED,
                failure_message="Error A",
            ),
            CaseResult(
                name="test_b",
                status=CaseStatus.FAILED,
                failure_message="Error B",
            ),
        ],
    )
    msg = builder._extract_error_message(result)
    assert "test_a" in msg
    assert "Error A" in msg


def test_extract_error_message_from_raw_output(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _extract_error_message falls back to raw output."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    result = RunResult(
        failed=1,
        raw_output="FATAL: something went wrong in the test runner",
        test_cases=[],
    )
    msg = builder._extract_error_message(result)
    assert "something went wrong" in msg


def test_get_memory_context_disabled(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _get_memory_context returns None when memory disabled."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    assert builder._get_memory_context("pytest") is None


def test_add_memory_to_prompt_no_messages_attr(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _add_memory_to_prompt with object lacking messages."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    # Should not raise
    builder._add_memory_to_prompt(object(), {"known_patterns": [], "failed_patterns": []})


def test_add_memory_to_prompt_empty_context(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _add_memory_to_prompt with empty patterns does nothing."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    rendered = SimpleNamespace(messages=[])
    builder._add_memory_to_prompt(rendered, {"known_patterns": [], "failed_patterns": []})
    assert len(rendered.messages) == 0


def test_add_memory_to_prompt_with_patterns(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Test _add_memory_to_prompt adds guidance when patterns exist."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    rendered = SimpleNamespace(messages=[])
    builder._add_memory_to_prompt(
        rendered,
        {
            "known_patterns": ["pattern_a"],
            "failed_patterns": ["pattern_b: reason"],
        },
    )
    assert len(rendered.messages) == 1
    assert "pattern_a" in rendered.messages[0].content
    assert "pattern_b" in rendered.messages[0].content


# ── Validation Pipeline, Execute Test, and Retry Tests ────────────────


@pytest.mark.asyncio
async def test_validation_pipeline_disabled(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """Validation pipeline returns early when disabled."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
        validation_config={"enabled": False},
    )

    adapter = MagicMock()
    task = IntegrationBuildTask(source_file="src/api_client.py", framework="pytest")
    request = GenerationRequest(messages=[])

    attempts, code, attempt = await builder._run_validation_pipeline(
        "test code", adapter, task, request
    )

    assert attempts == []
    assert code == "test code"
    assert attempt is None


@pytest.mark.asyncio
async def test_validation_pipeline_passes_first_attempt(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
    tmp_path: Path,
) -> None:
    """Validation passes on first attempt."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
        validation_config={"enabled": True, "max_retries": 2},
    )

    adapter = MagicMock()
    adapter.validate_test.return_value = MagicMock(valid=True, errors=[])
    adapter.get_test_pattern.return_value = ["**/*.py"]

    success_result = RunResult(passed=2, failed=0, skipped=0, errors=0, success=True)
    adapter.run_tests = AsyncMock(return_value=success_result)

    task = IntegrationBuildTask(
        source_file="src/api_client.py",
        framework="pytest",
        output_file=str(tmp_path / "test_output.py"),
    )
    request = GenerationRequest(messages=[])

    attempts, code, _attempt = await builder._run_validation_pipeline(
        "test code", adapter, task, request
    )

    assert len(attempts) == 1
    assert attempts[0].syntax_valid is True
    assert code == "test code"


@pytest.mark.asyncio
async def test_validation_pipeline_retries_on_failure(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
    tmp_path: Path,
) -> None:
    """Validation retries when test execution fails."""
    # First generate call returns original code, retry returns fixed code
    call_count = 0

    async def mock_generate(request: GenerationRequest) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        return LLMResponse(
            text=f"fixed test code {call_count}",
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
        )

    mock_llm_engine.configure_mock(generate=AsyncMock(side_effect=mock_generate))

    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
        validation_config={"enabled": True, "max_retries": 3},
    )

    adapter = MagicMock()
    adapter.validate_test.return_value = MagicMock(valid=True, errors=[])
    adapter.get_test_pattern.return_value = ["**/*.py"]

    fail_result = RunResult(
        passed=0,
        failed=1,
        skipped=0,
        errors=0,
        success=False,
        test_cases=[
            CaseResult(
                name="test_it",
                status=CaseStatus.FAILED,
                failure_message="AssertionError: expected 1 but got 2",
            )
        ],
    )
    success_result = RunResult(passed=1, failed=0, skipped=0, errors=0, success=True)
    adapter.run_tests = AsyncMock(side_effect=[fail_result, success_result])

    task = IntegrationBuildTask(
        source_file="src/api_client.py",
        framework="pytest",
        output_file=str(tmp_path / "test_output.py"),
    )
    request = GenerationRequest(messages=[])

    attempts, _code, attempt = await builder._run_validation_pipeline(
        "original code", adapter, task, request
    )

    assert len(attempts) >= 2
    assert attempt is not None
    assert attempt.syntax_valid is True


@pytest.mark.asyncio
async def test_validation_pipeline_syntax_failure(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
    tmp_path: Path,
) -> None:
    """Validation handles syntax failure correctly."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
        validation_config={"enabled": True, "max_retries": 1},
    )

    adapter = MagicMock()
    adapter.validate_test.return_value = MagicMock(valid=False, errors=["SyntaxError on line 1"])
    adapter.get_test_pattern.return_value = ["**/*.py"]

    task = IntegrationBuildTask(
        source_file="src/api_client.py",
        framework="pytest",
        output_file=str(tmp_path / "test_output.py"),
    )
    request = GenerationRequest(messages=[])

    attempts, _code, _attempt = await builder._run_validation_pipeline(
        "bad syntax", adapter, task, request
    )

    assert len(attempts) == 1
    assert attempts[0].syntax_valid is False
    assert attempts[0].failure_type == FailureType.TEST_BUG


@pytest.mark.asyncio
async def test_execute_test_success(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
    tmp_path: Path,
) -> None:
    """_execute_test runs adapter and returns success."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    adapter = MagicMock()
    success_result = RunResult(passed=2, failed=0, skipped=0, errors=0, success=True)
    adapter.run_tests = AsyncMock(return_value=success_result)

    test_file = tmp_path / "test_integration.py"

    result, failure_type, error_msg = await builder._execute_test(
        "def test_foo(): pass", adapter, test_file
    )

    assert result is not None
    assert result.success is True
    assert failure_type is None
    assert error_msg == ""


@pytest.mark.asyncio
async def test_execute_test_failure(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
    tmp_path: Path,
) -> None:
    """_execute_test classifies failure when tests fail."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    adapter = MagicMock()
    fail_result = RunResult(
        passed=0,
        failed=1,
        skipped=0,
        errors=0,
        success=False,
        test_cases=[
            CaseResult(
                name="test_it",
                status=CaseStatus.FAILED,
                failure_message="AssertionError: expected 1 but got 2",
            )
        ],
    )
    adapter.run_tests = AsyncMock(return_value=fail_result)

    test_file = tmp_path / "test_integration.py"

    result, failure_type, error_msg = await builder._execute_test(
        "def test_foo(): assert False", adapter, test_file
    )

    assert result is not None
    assert result.success is False
    assert failure_type == FailureType.TEST_BUG
    assert "test_it" in error_msg


@pytest.mark.asyncio
async def test_execute_test_exception(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
    tmp_path: Path,
) -> None:
    """_execute_test catches exceptions during execution."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    adapter = MagicMock()
    adapter.run_tests = AsyncMock(side_effect=RuntimeError("adapter crash"))

    test_file = tmp_path / "test_integration.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)

    result, failure_type, error_msg = await builder._execute_test(
        "def test_foo(): pass", adapter, test_file
    )

    assert result is None
    assert failure_type == FailureType.UNKNOWN
    assert "Execution error" in error_msg


@pytest.mark.asyncio
async def test_retry_with_feedback(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_retry_with_feedback sends error info and returns new code."""

    async def mock_gen(request: GenerationRequest) -> LLMResponse:
        return LLMResponse(
            text="fixed integration test code",
            model="gpt-4o",
            prompt_tokens=200,
            completion_tokens=100,
        )

    mock_llm_engine.configure_mock(generate=AsyncMock(side_effect=mock_gen))

    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    prev_attempt = ValidationAttempt(
        attempt=1,
        test_code="original code",
        syntax_valid=True,
        syntax_errors=[],
        test_result=None,
        failure_type=FailureType.TEST_BUG,
        error_message="AssertionError: expected 1",
    )
    original_request = GenerationRequest(messages=[])

    new_code = await builder._retry_with_feedback(original_request, prev_attempt)

    assert new_code == "fixed integration test code"
    mock_llm_engine.generate.assert_called_once()


def test_determine_test_file_path_with_output_file(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_determine_test_file_path uses output_file when provided."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    adapter = MagicMock()
    task = IntegrationBuildTask(
        source_file="src/api.py",
        framework="pytest",
        output_file="tests/test_api_integration.py",
    )

    path = builder._determine_test_file_path(task, adapter)
    assert str(path).endswith("test_api_integration.py")


def test_determine_test_file_path_python(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_determine_test_file_path generates Python path for pytest."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    adapter = MagicMock()
    adapter.get_test_pattern.return_value = ["**/test_*.py"]

    task = IntegrationBuildTask(source_file="src/api_client.py", framework="pytest")

    path = builder._determine_test_file_path(task, adapter)
    assert path.suffix == ".py"
    assert "integration" in path.stem


def test_determine_test_file_path_vitest(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_determine_test_file_path generates TypeScript path for vitest."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    adapter = MagicMock()
    adapter.get_test_pattern.return_value = ["**/*.test.ts"]

    task = IntegrationBuildTask(source_file="src/api.ts", framework="vitest")

    path = builder._determine_test_file_path(task, adapter)
    assert ".test.ts" in str(path)
    assert "integration" in str(path)


def test_determine_test_file_path_spec_ts(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_determine_test_file_path handles .spec.ts patterns."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    adapter = MagicMock()
    adapter.get_test_pattern.return_value = ["**/*.spec.ts"]

    task = IntegrationBuildTask(source_file="src/api.ts", framework="vitest")

    path = builder._determine_test_file_path(task, adapter)
    assert ".spec.ts" in str(path)


def test_determine_test_file_path_test_js(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_determine_test_file_path handles .test.js patterns."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    adapter = MagicMock()
    adapter.get_test_pattern.return_value = ["**/*.test.js"]

    task = IntegrationBuildTask(source_file="src/api.js", framework="jest")

    path = builder._determine_test_file_path(task, adapter)
    assert ".test.js" in str(path)


def test_update_memory_from_validation_success(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_update_memory_from_validation records success pattern."""

    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=True,
    )
    builder._memory = MagicMock()

    final_attempt = ValidationAttempt(
        attempt=1,
        test_code="test code",
        syntax_valid=True,
        syntax_errors=[],
        test_result=MagicMock(success=True),
        failure_type=None,
        error_message="",
    )

    builder._update_memory_from_validation("pytest", [final_attempt], final_attempt)

    builder._memory.update_stats.assert_called_once()
    builder._memory.add_known_pattern.assert_called_once()


def test_update_memory_from_validation_failure(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_update_memory_from_validation records failure pattern."""

    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=True,
    )
    builder._memory = MagicMock()

    final_attempt = ValidationAttempt(
        attempt=1,
        test_code="test code",
        syntax_valid=False,
        syntax_errors=["error"],
        test_result=None,
        failure_type=FailureType.TEST_BUG,
        error_message="syntax error",
    )

    builder._update_memory_from_validation("pytest", [final_attempt], final_attempt)

    builder._memory.update_stats.assert_called_once()
    builder._memory.add_failed_pattern.assert_called_once()


def test_update_memory_from_validation_no_memory(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_update_memory_from_validation does nothing without memory."""

    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )

    final_attempt = ValidationAttempt(
        attempt=1,
        test_code="test code",
        syntax_valid=True,
        syntax_errors=[],
        test_result=None,
        failure_type=None,
        error_message="",
    )

    # Should not raise
    builder._update_memory_from_validation("pytest", [final_attempt], final_attempt)


@pytest.mark.asyncio
async def test_run_accepts_build_task(
    mock_llm_engine: MagicMock,
    python_http_client_file: Path,
    pytest_project: Path,
) -> None:
    """IntegrationBuilder.run accepts a BuildTask and converts it."""

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

    task = BuildTask(
        source_file="src/api_client.py",
        framework="pytest",
    )

    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert "test_code" in result.result


def test_get_memory_context_with_patterns(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_get_memory_context returns filtered patterns from memory."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=True,
    )
    builder._memory = MagicMock()
    builder._memory.get_known_patterns.return_value = [
        {
            "pattern": "use fixtures",
            "context": {"language": "pytest", "test_type": "integration"},
        },
        {
            "pattern": "irrelevant",
            "context": {"language": "rust", "test_type": "unit"},
        },
        {
            "pattern": "no language integration",
            "context": {"test_type": "integration"},
        },
    ]
    builder._memory.get_failed_patterns.return_value = [
        {
            "pattern": "avoid global state",
            "reason": "causes flaky",
            "context": {"framework": "pytest", "test_type": "integration"},
        },
        {
            "pattern": "irrelevant failure",
            "reason": "n/a",
            "context": {"framework": "jest", "test_type": "unit"},
        },
    ]

    result = builder._get_memory_context("pytest")

    assert result is not None
    assert len(result["known_patterns"]) == 2
    assert "use fixtures" in result["known_patterns"][0]
    assert "no language integration" in result["known_patterns"][1]
    assert len(result["failed_patterns"]) == 1


def test_classify_test_failure_connection_refused(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_classify_test_failure detects connection refused as MISSING_DEP."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    result = RunResult(
        failed=1,
        test_cases=[
            CaseResult(
                name="test_it",
                status=CaseStatus.FAILED,
                failure_message="Connection refused: connect ECONNREFUSED",
            )
        ],
    )
    assert builder._classify_test_failure(result) == FailureType.MISSING_DEP


def test_extract_error_message_empty_errors_no_raw(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
) -> None:
    """_extract_error_message returns empty when no errors and no raw output."""
    builder = IntegrationBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        enable_memory=False,
    )
    result = RunResult(failed=0, test_cases=[], raw_output="")
    msg = builder._extract_error_message(result)
    assert msg == ""
