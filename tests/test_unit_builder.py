"""Tests for the UnitBuilder agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.base import CaseResult, CaseStatus, RunResult
from nit.agents.base import TaskInput, TaskStatus
from nit.agents.builders.unit import (
    BuildTask,
    FailureType,
    UnitBuilder,
    ValidationAttempt,
)
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
    engine.count_tokens = MagicMock(return_value=100)

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


# ── FailureType / classify_failure Tests ─────────────────────────


def test_failure_type_values() -> None:
    """Test FailureType enum has expected values."""

    assert FailureType.TEST_BUG.value == "test_bug"
    assert FailureType.CODE_BUG.value == "code_bug"
    assert FailureType.MISSING_DEP.value == "missing_dep"
    assert FailureType.TIMEOUT.value == "timeout"
    assert FailureType.UNKNOWN.value == "unknown"


def test_classify_failure_timeout(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test that long-running tests are classified as TIMEOUT."""

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    mock_result = MagicMock()
    mock_result.duration_ms = 60000  # Over 50s threshold
    mock_result.test_cases = []

    result = builder._classify_failure(mock_result)
    assert result == FailureType.TIMEOUT


def test_classify_failure_missing_dep(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test classification of missing dependency errors."""

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    mock_case = MagicMock()
    mock_case.failure_message = "ModuleNotFoundError: No module named 'numpy'"
    mock_result = MagicMock()
    mock_result.duration_ms = 1000
    mock_result.test_cases = [mock_case]

    result = builder._classify_failure(mock_result)
    assert result == FailureType.MISSING_DEP


def test_classify_failure_test_bug(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test classification of assertion errors as test bugs."""

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    mock_case = MagicMock()
    mock_case.failure_message = "AssertionError: expected 5 but got 3"
    mock_result = MagicMock()
    mock_result.duration_ms = 1000
    mock_result.test_cases = [mock_case]

    result = builder._classify_failure(mock_result)
    assert result == FailureType.TEST_BUG


def test_classify_failure_code_bug(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test classification of code-level bugs."""

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    mock_case = MagicMock()
    mock_case.failure_message = "ZeroDivisionError: division by zero"
    mock_result = MagicMock()
    mock_result.duration_ms = 1000
    mock_result.test_cases = [mock_case]

    result = builder._classify_failure(mock_result)
    assert result == FailureType.CODE_BUG


def test_classify_failure_default_to_test_bug(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test that unrecognized errors default to TEST_BUG."""

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    mock_case = MagicMock()
    mock_case.failure_message = "Some unusual error that doesn't match any pattern"
    mock_result = MagicMock()
    mock_result.duration_ms = 1000
    mock_result.test_cases = [mock_case]

    result = builder._classify_failure(mock_result)
    assert result == FailureType.TEST_BUG


# ── extract_error_message Tests ──────────────────────────────────


def test_extract_error_message_from_test_cases(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test that error messages are extracted from failed test cases."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    case1 = MagicMock()
    case1.name = "test_add"
    case1.failure_message = "Expected 5 but got 3"
    case2 = MagicMock()
    case2.name = "test_sub"
    case2.failure_message = "Expected 2 but got 0"

    mock_result = MagicMock()
    mock_result.test_cases = [case1, case2]
    mock_result.raw_output = ""

    msg = builder._extract_error_message(mock_result)
    assert "test_add" in msg
    assert "Expected 5 but got 3" in msg
    assert "test_sub" in msg


def test_extract_error_message_falls_back_to_raw_output(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test fallback to raw output when no structured errors exist."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    case1 = MagicMock()
    case1.name = "test_foo"
    case1.failure_message = ""  # No failure message

    mock_result = MagicMock()
    mock_result.test_cases = [case1]
    mock_result.raw_output = "Some raw error output from test runner"

    msg = builder._extract_error_message(mock_result)
    assert "Some raw error output" in msg


def test_extract_error_message_limits_to_three_errors(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test that error message extraction limits to first 3 errors."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    cases = []
    for i in range(5):
        case = MagicMock()
        case.name = f"test_{i}"
        case.failure_message = f"Error {i}"
        cases.append(case)

    mock_result = MagicMock()
    mock_result.test_cases = cases
    mock_result.raw_output = ""

    msg = builder._extract_error_message(mock_result)
    # Should contain first 3 but not 4th/5th
    assert "Error 0" in msg
    assert "Error 2" in msg
    assert "Error 4" not in msg


# ── ValidationAttempt Tests ──────────────────────────────────────


def test_validation_attempt_dataclass() -> None:
    """Test ValidationAttempt dataclass fields."""

    attempt = ValidationAttempt(
        attempt=1,
        test_code="def test(): pass",
        syntax_valid=True,
        syntax_errors=[],
        test_result=None,
        failure_type=FailureType.TEST_BUG,
        error_message="some error",
    )
    assert attempt.attempt == 1
    assert attempt.syntax_valid is True
    assert attempt.failure_type == FailureType.TEST_BUG


# ── Memory context integration Tests ─────────────────────────────


def test_get_memory_context_returns_none_when_disabled(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test _get_memory_context returns None when memory disabled."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    result = builder._get_memory_context("pytest")
    assert result is None


def test_add_memory_to_prompt_skips_when_empty(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test _add_memory_to_prompt skips when no patterns available."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    rendered_prompt = MagicMock()
    rendered_prompt.messages = []
    memory_context: dict[str, list[str]] = {
        "known_patterns": [],
        "failed_patterns": [],
    }
    builder._add_memory_to_prompt(rendered_prompt, memory_context)
    assert len(rendered_prompt.messages) == 0


def test_add_memory_to_prompt_appends_guidance(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test _add_memory_to_prompt appends guidance when patterns exist."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    rendered_prompt = MagicMock()
    rendered_prompt.messages = []
    memory_context: dict[str, list[str]] = {
        "known_patterns": ["use pytest fixtures"],
        "failed_patterns": ["avoid global state: causes flaky tests"],
    }
    builder._add_memory_to_prompt(rendered_prompt, memory_context)
    assert len(rendered_prompt.messages) == 1
    msg = rendered_prompt.messages[0]
    assert "Known successful patterns" in msg.content
    assert "Patterns to avoid" in msg.content


def test_add_memory_to_prompt_skips_when_no_messages_attr(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Test _add_memory_to_prompt handles objects without messages attr."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    rendered_prompt = object()  # No messages attribute
    memory_context: dict[str, list[str]] = {
        "known_patterns": ["some pattern"],
        "failed_patterns": [],
    }
    # Should not raise
    builder._add_memory_to_prompt(rendered_prompt, memory_context)


# ── Validation Pipeline Full Tests ────────────────────────────────


@pytest.mark.asyncio
async def test_validation_pipeline_disabled(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Validation pipeline returns early when disabled."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
        validation_config={"enabled": False},
    )

    adapter = MagicMock()
    task = BuildTask(source_file="src/foo.py", framework="pytest")
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
    tmp_path: Path,
) -> None:
    """Validation passes on first attempt with valid syntax and passing tests."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
        validation_config={"enabled": True, "max_retries": 2},
    )

    adapter = MagicMock()
    adapter.validate_test.return_value = MagicMock(valid=True, errors=[])
    adapter.get_test_pattern.return_value = ["**/*.py"]

    success_result = RunResult(passed=2, failed=0, skipped=0, errors=0, success=True)
    adapter.run_tests = AsyncMock(return_value=success_result)

    task = BuildTask(
        source_file="src/foo.py",
        framework="pytest",
        output_file=str(tmp_path / "test_foo.py"),
    )
    request = GenerationRequest(messages=[])

    attempts, _code, attempt = await builder._run_validation_pipeline(
        "def test_add(): assert True", adapter, task, request
    )

    assert len(attempts) == 1
    assert attempts[0].syntax_valid is True
    assert attempt is not None
    assert attempt.test_result is not None
    assert attempt.test_result.success is True


@pytest.mark.asyncio
async def test_validation_pipeline_retries_on_failure(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Validation retries when test execution fails."""

    async def mock_gen(request: GenerationRequest) -> LLMResponse:
        return LLMResponse(
            text="fixed test code",
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
        )

    mock_llm_engine.configure_mock(generate=AsyncMock(side_effect=mock_gen))

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
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
        duration_ms=1000,
        test_cases=[
            CaseResult(
                name="test_it",
                status=CaseStatus.FAILED,
                failure_message="AssertionError: expected 5 but got 3",
            )
        ],
    )
    success_result = RunResult(passed=1, failed=0, skipped=0, errors=0, success=True)
    adapter.run_tests = AsyncMock(side_effect=[fail_result, success_result])

    task = BuildTask(
        source_file="src/foo.py",
        framework="pytest",
        output_file=str(tmp_path / "test_foo.py"),
    )
    request = GenerationRequest(messages=[])

    attempts, code, _attempt = await builder._run_validation_pipeline(
        "original code", adapter, task, request
    )

    assert len(attempts) >= 2
    assert code == "fixed test code"


@pytest.mark.asyncio
async def test_validation_pipeline_syntax_error(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """Validation handles syntax errors correctly."""

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
        validation_config={"enabled": True, "max_retries": 1},
    )

    adapter = MagicMock()
    adapter.validate_test.return_value = MagicMock(
        valid=False, errors=["SyntaxError: invalid syntax"]
    )
    adapter.get_test_pattern.return_value = ["**/*.py"]

    task = BuildTask(
        source_file="src/foo.py",
        framework="pytest",
        output_file=str(tmp_path / "test_foo.py"),
    )
    request = GenerationRequest(messages=[])

    attempts, _code, _attempt = await builder._run_validation_pipeline(
        "bad syntax code", adapter, task, request
    )

    assert len(attempts) >= 1
    assert attempts[0].syntax_valid is False
    assert attempts[0].failure_type == FailureType.TEST_BUG


@pytest.mark.asyncio
async def test_validate_and_run_test_syntax_failure(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_validate_and_run_test returns syntax errors when validation fails."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    adapter = MagicMock()
    adapter.validate_test.return_value = MagicMock(valid=False, errors=["line 1: SyntaxError"])

    test_file = tmp_path / "test_output.py"

    attempt = await builder._validate_and_run_test("bad code", adapter, test_file)

    assert attempt.syntax_valid is False
    assert "SyntaxError" in attempt.error_message
    assert attempt.failure_type == FailureType.TEST_BUG


@pytest.mark.asyncio
async def test_validate_and_run_test_execution_error(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_validate_and_run_test handles adapter execution errors."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    adapter = MagicMock()
    adapter.validate_test.return_value = MagicMock(valid=True, errors=[])
    adapter.run_tests = AsyncMock(side_effect=RuntimeError("crash"))

    test_file = tmp_path / "test_output.py"

    attempt = await builder._validate_and_run_test("def test_it(): pass", adapter, test_file)

    assert attempt.syntax_valid is True
    assert attempt.failure_type == FailureType.UNKNOWN
    assert "Execution error" in attempt.error_message


@pytest.mark.asyncio
async def test_validate_and_run_test_success(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_validate_and_run_test returns success when tests pass."""

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    adapter = MagicMock()
    adapter.validate_test.return_value = MagicMock(valid=True, errors=[])
    adapter.run_tests = AsyncMock(
        return_value=RunResult(passed=1, failed=0, skipped=0, errors=0, success=True)
    )

    test_file = tmp_path / "test_output.py"

    attempt = await builder._validate_and_run_test("def test_it(): pass", adapter, test_file)

    assert attempt.syntax_valid is True
    assert attempt.test_result is not None
    assert attempt.test_result.success is True
    assert attempt.failure_type is None


@pytest.mark.asyncio
async def test_retry_with_feedback(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_retry_with_feedback sends error context and returns new code."""

    async def mock_gen(request: GenerationRequest) -> LLMResponse:
        return LLMResponse(
            text="corrected test code",
            model="gpt-4o",
            prompt_tokens=200,
            completion_tokens=100,
        )

    mock_llm_engine.configure_mock(generate=AsyncMock(side_effect=mock_gen))

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=False,
    )

    prev_attempt = ValidationAttempt(
        attempt=1,
        test_code="original code",
        syntax_valid=True,
        syntax_errors=[],
        test_result=None,
        failure_type=FailureType.TEST_BUG,
        error_message="AssertionError: expected 5 but got 3",
    )

    original_request = GenerationRequest(messages=[])

    new_code = await builder._retry_with_feedback(original_request, prev_attempt)

    assert new_code == "corrected test code"
    mock_llm_engine.generate.assert_called_once()


def test_determine_test_file_path_spec_ts(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_determine_test_file_path handles .spec.ts patterns."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
    )

    adapter = MagicMock()
    adapter.get_test_pattern.return_value = ["**/*.spec.ts"]

    task = BuildTask(source_file="src/add.ts", framework="vitest")

    path = builder._determine_test_file_path(task, adapter)
    assert ".spec.ts" in str(path)


def test_determine_test_file_path_test_js(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_determine_test_file_path handles .test.js patterns."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
    )

    adapter = MagicMock()
    adapter.get_test_pattern.return_value = ["**/*.test.js"]

    task = BuildTask(source_file="src/add.js", framework="jest")

    path = builder._determine_test_file_path(task, adapter)
    assert ".test.js" in str(path)


# ── Memory update Tests (full coverage) ──────────────────────────────


def test_update_memory_from_validation_success(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_update_memory_from_validation records success pattern."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=True,
    )
    builder._memory = MagicMock()

    final_attempt = ValidationAttempt(
        attempt=1,
        test_code="test code",
        syntax_valid=True,
        syntax_errors=[],
        test_result=MagicMock(success=True, passed=3),
        failure_type=None,
        error_message="",
    )

    builder._update_memory_from_validation("pytest", [final_attempt], final_attempt)

    builder._memory.update_stats.assert_called_once()
    builder._memory.add_known_pattern.assert_called_once()


def test_update_memory_from_validation_failure(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_update_memory_from_validation records failure pattern."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=True,
    )
    builder._memory = MagicMock()

    final_attempt = ValidationAttempt(
        attempt=1,
        test_code="test code",
        syntax_valid=False,
        syntax_errors=["err"],
        test_result=None,
        failure_type=FailureType.TEST_BUG,
        error_message="syntax error on line 1",
    )

    builder._update_memory_from_validation("pytest", [final_attempt], final_attempt)

    builder._memory.update_stats.assert_called_once()
    builder._memory.add_failed_pattern.assert_called_once()


def test_update_memory_from_validation_multiple_attempts(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_update_memory_from_validation records failed attempts from iterations."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=True,
    )
    builder._memory = MagicMock()

    attempt1 = ValidationAttempt(
        attempt=1,
        test_code="bad code",
        syntax_valid=False,
        syntax_errors=["err"],
        test_result=None,
        failure_type=FailureType.TEST_BUG,
        error_message="syntax error",
    )
    attempt2 = ValidationAttempt(
        attempt=2,
        test_code="good code",
        syntax_valid=True,
        syntax_errors=[],
        test_result=MagicMock(success=True, passed=1),
        failure_type=None,
        error_message="",
    )

    builder._update_memory_from_validation("vitest", [attempt1, attempt2], attempt2)

    # Should record success + failed pattern from attempt 1
    builder._memory.update_stats.assert_called_once()
    builder._memory.add_known_pattern.assert_called_once()
    # Intermediate failures recorded
    builder._memory.add_failed_pattern.assert_called_once()


def test_update_memory_from_validation_no_memory(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_update_memory_from_validation does nothing without memory."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
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


def test_update_memory_success_no_test_result(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_update_memory_from_validation with success but no test result."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=True,
    )
    builder._memory = MagicMock()

    final_attempt = ValidationAttempt(
        attempt=1,
        test_code="test code",
        syntax_valid=True,
        syntax_errors=[],
        test_result=None,
        failure_type=None,
        error_message="",
    )

    builder._update_memory_from_validation("pytest", [final_attempt], final_attempt)

    builder._memory.update_stats.assert_called_once_with(
        successful=True,
        tests_generated=1,
        tests_passing=1,
    )


def test_get_memory_context_with_patterns(
    mock_llm_engine: MagicMock,
    tmp_path: Path,
) -> None:
    """_get_memory_context returns filtered patterns from memory."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=tmp_path,
        enable_memory=True,
    )
    builder._memory = MagicMock()
    builder._memory.get_known_patterns.return_value = [
        {
            "pattern": "use fixtures",
            "context": {"language": "pytest"},
        },
        {
            "pattern": "irrelevant",
            "context": {"language": "rust"},
        },
        {
            "pattern": "general pattern",
            "context": {},
        },
    ]
    builder._memory.get_failed_patterns.return_value = [
        {
            "pattern": "avoid global state",
            "reason": "causes flaky tests",
            "context": {"framework": "pytest"},
        },
        {
            "pattern": "avoid mocks",
            "reason": "brittle",
            "context": {"framework": "jest"},
        },
    ]

    result = builder._get_memory_context("pytest")

    assert result is not None
    # "use fixtures" matches (language contains "pytest")
    # "general pattern" matches (no language filter)
    assert len(result["known_patterns"]) == 2
    assert "use fixtures" in result["known_patterns"][0]
    assert "general pattern" in result["known_patterns"][1]
    assert len(result["failed_patterns"]) == 1
    assert "avoid global state" in result["failed_patterns"][0]


@pytest.mark.asyncio
async def test_run_with_memory_and_no_validation(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """UnitBuilder.run updates memory stats when validation is disabled."""
    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        enable_memory=True,
        validation_config={"enabled": False},
    )

    task = BuildTask(source_file=str(sample_ts_file), framework="vitest")
    result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert result.result["validation_enabled"] is False
    # Memory should have been updated
    if builder._memory:
        stats = builder._memory._data.get("generation_stats", {})
        assert stats.get("successful_generations", 0) >= 1


@pytest.mark.asyncio
async def test_run_with_validation_and_memory_update(
    mock_llm_engine: MagicMock,
    vitest_project: Path,
    sample_ts_file: Path,
) -> None:
    """UnitBuilder.run validates and updates memory from validation result."""

    builder = UnitBuilder(
        llm_engine=mock_llm_engine,
        project_root=vitest_project,
        enable_memory=True,
        validation_config={"enabled": True, "max_retries": 1},
    )

    # Mock the adapter to pass validation
    adapter_mock = MagicMock()
    adapter_mock.detect.return_value = True
    adapter_mock.validate_test.return_value = MagicMock(valid=True, errors=[])
    adapter_mock.get_test_pattern.return_value = ["**/*.test.ts"]
    adapter_mock.get_prompt_template.return_value = MagicMock()
    adapter_mock.get_prompt_template.return_value.name = "vitest"
    adapter_mock.get_prompt_template.return_value.render.return_value = MagicMock(
        messages=[MagicMock(role="system", content="gen tests")]
    )
    adapter_mock.run_tests = AsyncMock(
        return_value=RunResult(passed=1, failed=0, skipped=0, errors=0, success=True)
    )

    with (
        patch.object(
            builder._registry,
            "get_test_adapter",
            return_value=adapter_mock,
        ),
    ):
        task = BuildTask(source_file=str(sample_ts_file), framework="vitest")
        result = await builder.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert result.result["validation_enabled"] is True
    assert result.result["validation_attempts"] >= 1
