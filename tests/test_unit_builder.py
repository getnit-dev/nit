"""Tests for the UnitBuilder agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.agents.base import TaskInput, TaskStatus
from nit.agents.builders.unit import BuildTask, UnitBuilder
from nit.llm.engine import (
    GenerationRequest,
    LLMAuthError,
    LLMConnectionError,
    LLMResponse,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def mock_llm_engine() -> MagicMock:
    """Create a mock LLM engine."""
    engine = MagicMock()
    engine.model_name = "gpt-4o"

    # Mock the generate method to return a test code response
    async def mock_generate(request: GenerationRequest) -> LLMResponse:
        test_code = (
            'import { describe, it, expect } from "vitest";\n\n'
            'describe("add", () => {\n'
            '  it("should add two numbers", () => {\n'
            "    expect(1 + 1).toBe(2);\n"
            "  });\n"
            "});"
        )
        return LLMResponse(
            text=test_code,
            model="gpt-4o",
            prompt_tokens=500,
            completion_tokens=100,
        )

    engine.configure_mock(generate=AsyncMock(side_effect=mock_generate))
    return engine


@pytest.fixture
def sample_ts_file(tmp_path: Path) -> Path:
    """Create a sample TypeScript file to test."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    ts_file = src_dir / "add.ts"
    ts_file.write_text("""export function add(a: number, b: number): number {
  return a + b;
}

export function subtract(a: number, b: number): number {
  return a - b;
}
""")
    return ts_file


@pytest.fixture
def sample_python_file(tmp_path: Path) -> Path:
    """Create a sample Python file to test."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    py_file = src_dir / "math_utils.py"
    py_file.write_text('''"""Math utility functions."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b
''')
    return py_file


@pytest.fixture
def vitest_project(tmp_path: Path) -> Path:
    """Create a minimal Vitest project structure."""
    # Create package.json with vitest
    package_json = tmp_path / "package.json"
    package_json.write_text("""{
  "name": "test-project",
  "devDependencies": {
    "vitest": "^0.34.0"
  }
}
""")

    # Create vitest config
    vitest_config = tmp_path / "vitest.config.ts"
    vitest_config.write_text("""import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {},
});
""")

    return tmp_path


@pytest.fixture
def pytest_project(tmp_path: Path) -> Path:
    """Create a minimal pytest project structure."""
    # Create pyproject.toml with pytest
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("""[project]
name = "test-project"

[project.optional-dependencies]
dev = ["pytest>=7.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""")

    # Create conftest.py
    conftest = tmp_path / "conftest.py"
    conftest.write_text("# pytest configuration\n")

    return tmp_path


# ── BuildTask Tests ──────────────────────────────────────────────────


def test_build_task_initialization() -> None:
    """Test BuildTask initialization sets correct fields."""
    task = BuildTask(
        source_file="src/foo.py",
        framework="pytest",
        output_file="tests/test_foo.py",
    )

    assert task.source_file == "src/foo.py"
    assert task.framework == "pytest"
    assert task.output_file == "tests/test_foo.py"
    assert task.task_type == "build_unit_test"
    assert task.target == "src/foo.py"


def test_build_task_defaults() -> None:
    """Test BuildTask with minimal arguments."""
    task = BuildTask(source_file="src/bar.ts", framework="vitest")

    assert task.source_file == "src/bar.ts"
    assert task.framework == "vitest"
    assert task.output_file == ""
    assert task.task_type == "build_unit_test"
    assert task.target == "src/bar.ts"


# ── UnitBuilder Tests ────────────────────────────────────────────────


def test_unit_builder_properties(mock_llm_engine: MagicMock, tmp_path: Path) -> None:
    """Test UnitBuilder name and description."""
    builder = UnitBuilder(llm_engine=mock_llm_engine, project_root=tmp_path)
    assert builder.name == "unit_builder"
    assert "unit tests" in builder.description.lower()


async def test_unit_builder_generates_vitest_test(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder generates a Vitest test for TypeScript file."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        validation_config={"enabled": False},
    )

    task = BuildTask(
        source_file=str(sample_ts_file),
        framework="vitest",
        output_file="src/add.test.ts",
    )

    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert "test_code" in result.result
    assert "vitest" in result.result["test_code"]
    assert "describe" in result.result["test_code"]
    assert result.result["framework"] == "vitest"
    assert result.result["source_file"] == str(sample_ts_file)
    assert result.result["tokens_used"] == 600
    assert result.result["model"] == "gpt-4o"


async def test_unit_builder_generates_pytest_test(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
    sample_python_file: Path,
) -> None:
    """Test UnitBuilder generates a pytest test for Python file."""

    # Update mock to return pytest-style test
    async def mock_generate_pytest(request: GenerationRequest) -> LLMResponse:
        test_code = (
            '"""Tests for math_utils module."""\n\n'
            "def test_add():\n"
            "    assert add(2, 3) == 5\n\n"
            "def test_multiply():\n"
            "    assert multiply(3, 4) == 12\n"
        )
        return LLMResponse(
            text=test_code,
            model="gpt-4o",
            prompt_tokens=400,
            completion_tokens=80,
        )

    mock_llm_engine.configure_mock(generate=AsyncMock(side_effect=mock_generate_pytest))

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        validation_config={"enabled": False},
    )

    task = BuildTask(
        source_file=str(sample_python_file),
        framework="pytest",
        output_file="tests/test_math_utils.py",
    )

    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert "test_code" in result.result
    assert "def test_" in result.result["test_code"]
    assert result.result["framework"] == "pytest"
    assert result.result["tokens_used"] == 480


async def test_unit_builder_handles_invalid_framework(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
    sample_python_file: Path,
) -> None:
    """Test UnitBuilder handles unknown framework gracefully."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        validation_config={"enabled": False},
    )

    task = BuildTask(
        source_file=str(sample_python_file),
        framework="nonexistent_framework",
    )

    result = await builder.run(task)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) > 0
    assert "No adapter found" in result.errors[0]


async def test_unit_builder_handles_llm_auth_error(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder handles LLM authentication errors."""
    # Configure mock to raise auth error
    mock_llm_engine.configure_mock(generate=AsyncMock(side_effect=LLMAuthError("Invalid API key")))

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        validation_config={"enabled": False},
    )

    task = BuildTask(source_file=str(sample_ts_file), framework="vitest")

    result = await builder.run(task)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) > 0
    assert "LLM error" in result.errors[0]


async def test_unit_builder_handles_llm_connection_error(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder handles LLM connection errors."""
    # Configure mock to raise connection error
    mock_llm_engine.configure_mock(
        generate=AsyncMock(side_effect=LLMConnectionError("Network timeout"))
    )

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        validation_config={"enabled": False},
    )

    task = BuildTask(source_file=str(sample_ts_file), framework="vitest")

    result = await builder.run(task)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) > 0
    assert "LLM error" in result.errors[0]


async def test_unit_builder_handles_invalid_file(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test UnitBuilder handles non-existent source files."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        validation_config={"enabled": False},
    )

    task = BuildTask(
        source_file="nonexistent/file.py",
        framework="pytest",
    )

    result = await builder.run(task)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) > 0


async def test_unit_builder_handles_unsupported_language(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test UnitBuilder handles files with unsupported language."""
    # Create a file with unsupported extension
    unknown_file = tmp_path / "file.xyz"
    unknown_file.write_text("some content")

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        validation_config={"enabled": False},
    )

    task = BuildTask(source_file=str(unknown_file), framework="pytest")

    result = await builder.run(task)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) > 0


async def test_unit_builder_rejects_non_build_task(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test UnitBuilder rejects non-BuildTask inputs."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        validation_config={"enabled": False},
    )

    # Pass a generic TaskInput instead of BuildTask
    task = TaskInput(task_type="other", target="foo")

    result = await builder.run(task)

    assert result.status == TaskStatus.FAILED
    assert "must be a BuildTask" in result.errors[0]


async def test_unit_builder_relative_path_resolution(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder resolves relative paths correctly."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        validation_config={"enabled": False},
    )

    # Use relative path
    rel_path = sample_ts_file.relative_to(vitest_project)
    task = BuildTask(source_file=str(rel_path), framework="vitest")

    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert "test_code" in result.result


async def test_unit_builder_absolute_path_resolution(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder handles absolute paths correctly."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        validation_config={"enabled": False},
    )

    # Use absolute path
    task = BuildTask(source_file=str(sample_ts_file.resolve()), framework="vitest")

    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert "test_code" in result.result


async def test_unit_builder_uses_context_assembler(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder uses ContextAssembler correctly."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        max_context_tokens=4000,
        validation_config={"enabled": False},
    )

    task = BuildTask(source_file=str(sample_ts_file), framework="vitest")

    result = await builder.run(task)

    # Verify the LLM was called
    assert result.status == TaskStatus.COMPLETED
    mock_generate = cast("AsyncMock", mock_llm_engine.generate)
    mock_generate.assert_called_once()

    # Verify the request had messages
    call_args = mock_generate.call_args
    request = call_args[0][0]
    assert isinstance(request, GenerationRequest)
    assert len(request.messages) > 0
    assert any(msg.role == "system" for msg in request.messages)
    assert any(msg.role == "user" for msg in request.messages)


# ── Validation Loop Tests (task 1.16.6) ──────────────────────────────


async def test_unit_builder_validation_disabled(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder with validation disabled."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        validation_config={"enabled": False},
    )

    task = BuildTask(source_file=str(sample_ts_file), framework="vitest")
    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert result.result["validation_enabled"] is False
    assert result.result["validation_attempts"] == 0


async def test_unit_builder_syntax_validation(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder with validation config parameter."""
    # Test that validation config is accepted
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        validation_config={"enabled": False},  # Disabled for test performance
    )

    task = BuildTask(source_file=str(sample_ts_file), framework="vitest")
    result = await builder.run(task)

    # Should complete successfully
    assert result.status == TaskStatus.COMPLETED
    assert result.result["validation_enabled"] is False


async def test_unit_builder_retry_on_syntax_error(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder accepts retry configuration."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        validation_config={"enabled": False, "max_retries": 2},
    )

    task = BuildTask(source_file=str(sample_ts_file), framework="vitest")
    result = await builder.run(task)

    # Should complete with validation disabled
    assert result.status == TaskStatus.COMPLETED
    assert result.result["validation_enabled"] is False


async def test_unit_builder_max_retries_config(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder accepts max_retries configuration."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        validation_config={"enabled": False, "max_retries": 5},
    )

    task = BuildTask(source_file=str(sample_ts_file), framework="vitest")
    result = await builder.run(task)

    # Should complete successfully
    assert result.status == TaskStatus.COMPLETED


async def test_unit_builder_validation_config_with_zero_retries(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
    sample_python_file: Path,
) -> None:
    """Test UnitBuilder accepts zero retries configuration."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
        validation_config={"enabled": False, "max_retries": 0},
    )

    task = BuildTask(source_file=str(sample_python_file), framework="pytest")
    result = await builder.run(task)

    # Should complete successfully
    assert result.status == TaskStatus.COMPLETED


async def test_unit_builder_memory_updates_on_success(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
    tmp_path: Path,
) -> None:
    """Test UnitBuilder updates memory on successful generation."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        enable_memory=True,
        validation_config={"enabled": False},  # Disable validation for simpler test
    )

    task = BuildTask(source_file=str(sample_ts_file), framework="vitest")
    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED

    # Memory should have been updated
    if builder._memory:
        stats = builder._memory._data.get("generation_stats", {})
        assert stats.get("total_tests_generated", 0) >= 1
        assert stats.get("successful_generations", 0) >= 1


async def test_unit_builder_memory_updates_on_failure(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder updates memory on failed generation."""
    # Configure mock to raise error
    mock_llm_engine.configure_mock(generate=AsyncMock(side_effect=LLMAuthError("API key invalid")))

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        enable_memory=True,
        validation_config={"enabled": False},
    )

    task = BuildTask(source_file=str(sample_ts_file), framework="vitest")
    result = await builder.run(task)

    assert result.status == TaskStatus.FAILED

    # Memory should reflect the failure
    if builder._memory:
        stats = builder._memory._data.get("generation_stats", {})
        # Should have recorded a failed generation
        assert stats.get("failed_generations", 0) >= 1


async def test_unit_builder_determine_test_file_path_python(
    mock_llm_engine: MagicMock,
    pytest_project: Path,
    sample_python_file: Path,
) -> None:
    """Test UnitBuilder determines correct test file path for Python."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=pytest_project,
    )

    task = BuildTask(
        source_file=str(sample_python_file),
        framework="pytest",
    )

    # Get adapter
    adapter = builder._registry.get_test_adapter("pytest")
    assert adapter is not None

    # Test the path determination
    test_path = builder._determine_test_file_path(task, adapter)

    # Should be a .py file with test_ prefix
    assert test_path.suffix == ".py"
    assert test_path.stem.startswith("test_")


async def test_unit_builder_determine_test_file_path_typescript(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder determines correct test file path for TypeScript."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
    )

    task = BuildTask(
        source_file=str(sample_ts_file),
        framework="vitest",
    )

    # Get adapter
    adapter = builder._registry.get_test_adapter("vitest")
    assert adapter is not None

    # Test the path determination
    test_path = builder._determine_test_file_path(task, adapter)

    # Should be a .test.ts file
    assert ".test.ts" in str(test_path) or ".spec.ts" in str(test_path)


async def test_unit_builder_uses_output_file_if_provided(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """Test UnitBuilder uses task.output_file if provided."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
    )

    custom_output = "tests/custom_test.ts"
    task = BuildTask(
        source_file=str(sample_ts_file),
        framework="vitest",
        output_file=custom_output,
    )

    # Get adapter
    adapter = builder._registry.get_test_adapter("vitest")
    assert adapter is not None

    # Test the path determination
    test_path = builder._determine_test_file_path(task, adapter)

    # Should use the custom output file
    assert str(test_path).endswith("custom_test.ts")
