"""Tests for drift test specification and execution (tasks 3.11.2, 3.11.3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nit.agents.watchers.drift_comparator import ComparisonType
from nit.agents.watchers.drift_test import (
    DriftTestExecutor,
    DriftTestParser,
    DriftTestSpec,
    EndpointType,
)


@pytest.fixture
def sample_drift_tests_yaml(tmp_path: Path) -> Path:
    """Create a sample drift tests YAML file."""
    yaml_content = """
tests:
  - id: test_semantic_function
    name: "Test semantic similarity with function"
    endpoint_type: function
    comparison_type: semantic
    endpoint_config:
      module: builtins
      function: str
      args: [42]
    comparison_config:
      threshold: 0.8

  - id: test_exact_cli
    name: "Test exact match with CLI"
    endpoint_type: cli
    comparison_type: exact
    endpoint_config:
      command: ["echo", "hello world"]
    enabled: true
    timeout: 10.0

  - id: test_regex
    name: "Test regex pattern"
    endpoint_type: cli
    comparison_type: regex
    endpoint_config:
      command: ["echo", "test output"]
    comparison_config:
      pattern: "^test.*"

  - id: test_disabled
    name: "Disabled test"
    endpoint_type: function
    comparison_type: exact
    enabled: false
"""

    yaml_file = tmp_path / "drift-tests.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")
    return yaml_file


def test_parse_drift_tests(sample_drift_tests_yaml: Path) -> None:
    """Test parsing drift tests from YAML."""
    specs = DriftTestParser.parse_file(sample_drift_tests_yaml)

    assert len(specs) == 4

    # Check first test
    assert specs[0].id == "test_semantic_function"
    assert specs[0].name == "Test semantic similarity with function"
    assert specs[0].endpoint_type == EndpointType.FUNCTION
    assert specs[0].comparison_type == ComparisonType.SEMANTIC
    assert specs[0].endpoint_config["module"] == "builtins"
    assert specs[0].endpoint_config["function"] == "str"
    assert specs[0].comparison_config["threshold"] == 0.8
    assert specs[0].enabled

    # Check second test
    assert specs[1].id == "test_exact_cli"
    assert specs[1].endpoint_type == EndpointType.CLI
    assert specs[1].comparison_type == ComparisonType.EXACT
    assert specs[1].timeout == 10.0

    # Check disabled test
    assert specs[3].id == "test_disabled"
    assert not specs[3].enabled


def test_parse_nonexistent_file(tmp_path: Path) -> None:
    """Test parsing a file that doesn't exist."""
    nonexistent = tmp_path / "nonexistent.yml"
    specs = DriftTestParser.parse_file(nonexistent)

    assert specs == []


def test_parse_empty_file(tmp_path: Path) -> None:
    """Test parsing an empty YAML file."""
    yaml_file = tmp_path / "empty.yml"
    yaml_file.write_text("", encoding="utf-8")

    specs = DriftTestParser.parse_file(yaml_file)

    assert specs == []


def test_parse_defaults(tmp_path: Path) -> None:
    """Test that default values are applied."""
    yaml_content = """
tests:
  - id: minimal_test
"""
    yaml_file = tmp_path / "minimal.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    specs = DriftTestParser.parse_file(yaml_file)

    assert len(specs) == 1
    spec = specs[0]

    assert spec.id == "minimal_test"
    assert spec.name == "minimal_test"  # Defaults to ID
    assert spec.endpoint_type == EndpointType.FUNCTION  # Default
    assert spec.comparison_type == ComparisonType.SEMANTIC  # Default
    assert spec.enabled  # Default
    assert spec.timeout == 30.0  # Default


@pytest.mark.asyncio
async def test_execute_function_endpoint() -> None:
    """Test executing a function endpoint."""
    spec = DriftTestSpec(
        id="test_1",
        name="Test function",
        endpoint_type=EndpointType.FUNCTION,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={
            "module": "builtins",
            "function": "str",
            "args": [42],
        },
    )

    executor = DriftTestExecutor()
    output = await executor.execute_test(spec)

    assert output == "42"


@pytest.mark.asyncio
async def test_execute_function_with_kwargs() -> None:
    """Test executing a function with kwargs."""
    spec = DriftTestSpec(
        id="test_2",
        name="Test function with kwargs",
        endpoint_type=EndpointType.FUNCTION,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={
            "module": "builtins",
            "function": "int",
            "args": ["42"],
            "kwargs": {"base": 10},
        },
    )

    executor = DriftTestExecutor()
    output = await executor.execute_test(spec)

    assert output == "42"


@pytest.mark.asyncio
async def test_execute_cli_endpoint() -> None:
    """Test executing a CLI endpoint."""
    spec = DriftTestSpec(
        id="test_3",
        name="Test CLI",
        endpoint_type=EndpointType.CLI,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={
            "command": ["echo", "hello world"],
        },
    )

    executor = DriftTestExecutor()
    output = await executor.execute_test(spec)

    assert "hello world" in output


@pytest.mark.asyncio
async def test_execute_disabled_test() -> None:
    """Test that disabled tests are skipped."""
    spec = DriftTestSpec(
        id="test_4",
        name="Disabled test",
        endpoint_type=EndpointType.FUNCTION,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={"module": "builtins", "function": "str", "args": [1]},
        enabled=False,
    )

    executor = DriftTestExecutor()
    output = await executor.execute_test(spec)

    assert output == ""


@pytest.mark.asyncio
async def test_execute_function_missing_module() -> None:
    """Test error handling for missing module."""
    spec = DriftTestSpec(
        id="test_5",
        name="Missing module",
        endpoint_type=EndpointType.FUNCTION,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={
            "function": "some_function",
        },
    )

    executor = DriftTestExecutor()

    with pytest.raises(ValueError, match="requires 'module' and 'function'"):
        await executor.execute_test(spec)


@pytest.mark.asyncio
async def test_execute_cli_missing_command() -> None:
    """Test error handling for missing CLI command."""
    spec = DriftTestSpec(
        id="test_6",
        name="Missing command",
        endpoint_type=EndpointType.CLI,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={},
    )

    executor = DriftTestExecutor()

    with pytest.raises(ValueError, match="requires 'command'"):
        await executor.execute_test(spec)


@pytest.mark.asyncio
async def test_execute_cli_failed_command() -> None:
    """Test error handling for failed CLI command."""
    spec = DriftTestSpec(
        id="test_7",
        name="Failed command",
        endpoint_type=EndpointType.CLI,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={
            "command": ["false"],  # Always exits with code 1
        },
    )

    executor = DriftTestExecutor()

    with pytest.raises(RuntimeError, match="Command failed"):
        await executor.execute_test(spec)


# ── Coverage: HTTP endpoint ──────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_http_endpoint_get() -> None:
    """Test HTTP endpoint execution with mock server."""
    spec = DriftTestSpec(
        id="test_http_get",
        name="HTTP GET test",
        endpoint_type=EndpointType.HTTP,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={
            "url": "https://httpbin.org/get",
            "method": "GET",
        },
    )

    mock_response = AsyncMock()
    mock_response.text = '{"status": "ok"}'

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("nit.agents.watchers.drift_test.httpx.AsyncClient", return_value=mock_client):
        executor = DriftTestExecutor()
        output = await executor.execute_test(spec)
        assert output == '{"status": "ok"}'


@pytest.mark.asyncio
async def test_execute_http_endpoint_post_json() -> None:
    """Test HTTP POST with JSON body."""
    spec = DriftTestSpec(
        id="test_http_post",
        name="HTTP POST test",
        endpoint_type=EndpointType.HTTP,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={
            "url": "https://httpbin.org/post",
            "method": "POST",
            "body": {"key": "value"},
            "headers": {"X-Custom": "header"},
        },
    )

    mock_response = AsyncMock()
    mock_response.text = "response body"

    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("nit.agents.watchers.drift_test.httpx.AsyncClient", return_value=mock_client):
        executor = DriftTestExecutor()
        output = await executor.execute_test(spec)
        assert output == "response body"
        # Verify Content-Type was set for dict body
        call_kwargs = mock_client.request.call_args[1]
        assert call_kwargs["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_execute_http_missing_url() -> None:
    """Test HTTP endpoint without url raises ValueError."""
    spec = DriftTestSpec(
        id="test_http_no_url",
        name="No URL",
        endpoint_type=EndpointType.HTTP,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={},
    )

    executor = DriftTestExecutor()
    with pytest.raises(ValueError, match="requires 'url'"):
        await executor.execute_test(spec)


# ── Coverage: function endpoint returning non-string ─────────────


@pytest.mark.asyncio
async def test_execute_function_returns_dict() -> None:
    """Function returning a dict should be JSON-serialized."""
    spec = DriftTestSpec(
        id="test_dict",
        name="Dict test",
        endpoint_type=EndpointType.FUNCTION,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={
            "module": "builtins",
            "function": "dict",
            "kwargs": {"a": 1},
        },
    )

    executor = DriftTestExecutor()
    output = await executor.execute_test(spec)
    assert '"a": 1' in output


# ── Coverage: unknown endpoint type and invalid config ───────────


def test_parse_unknown_endpoint_type(tmp_path: Path) -> None:
    """Unknown endpoint type defaults to FUNCTION."""
    yaml_content = """
tests:
  - id: test_unknown
    endpoint_type: grpc
    comparison_type: exact
"""
    yaml_file = tmp_path / "test.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")
    specs = DriftTestParser.parse_file(yaml_file)
    assert len(specs) == 1
    assert specs[0].endpoint_type == EndpointType.FUNCTION


def test_parse_unknown_comparison_type(tmp_path: Path) -> None:
    """Unknown comparison type defaults to SEMANTIC."""
    yaml_content = """
tests:
  - id: test_unknown_cmp
    comparison_type: fuzzy
"""
    yaml_file = tmp_path / "test.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")
    specs = DriftTestParser.parse_file(yaml_file)
    assert len(specs) == 1
    assert specs[0].comparison_type == ComparisonType.SEMANTIC


def test_parse_test_with_error(tmp_path: Path) -> None:
    """Test that errors in parsing individual tests are handled."""
    yaml_content = """
tests:
  - name: "missing id"
"""
    yaml_file = tmp_path / "test.yml"
    yaml_file.write_text(yaml_content, encoding="utf-8")
    # Missing "id" field should cause a KeyError that gets caught
    specs = DriftTestParser.parse_file(yaml_file)
    assert specs == []


# ── Coverage: CLI endpoint with env/cwd ──────────────────────────


@pytest.mark.asyncio
async def test_execute_cli_with_cwd(tmp_path: Path) -> None:
    """Test CLI execution with cwd option."""
    spec = DriftTestSpec(
        id="test_cwd",
        name="CLI with cwd",
        endpoint_type=EndpointType.CLI,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={
            "command": ["echo", "from cwd"],
            "cwd": str(tmp_path),
        },
    )
    executor = DriftTestExecutor()
    output = await executor.execute_test(spec)
    assert "from cwd" in output


@pytest.mark.asyncio
async def test_execute_function_missing_function_name() -> None:
    """Test that missing function name raises ValueError."""
    spec = DriftTestSpec(
        id="test_no_func",
        name="No function",
        endpoint_type=EndpointType.FUNCTION,
        comparison_type=ComparisonType.EXACT,
        endpoint_config={
            "module": "builtins",
        },
    )
    executor = DriftTestExecutor()
    with pytest.raises(ValueError, match="requires 'module' and 'function'"):
        await executor.execute_test(spec)
