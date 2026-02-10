"""Tests for CLI tool adapters."""

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.llm.cli_adapter import (
    ClaudeCodeAdapter,
    CLIToolConfig,
    CodexAdapter,
    CustomCommandAdapter,
)
from nit.llm.engine import GenerationRequest, LLMConnectionError, LLMError, LLMMessage

# ── Fixtures ──


@pytest.fixture
def mock_which() -> Any:
    """Mock shutil.which to always find the command."""
    with patch("nit.llm.cli_adapter.shutil.which", return_value="/usr/bin/mock"):
        yield


async def _create_mock_proc(stdout: str = "", stderr: str = "", exit_code: int = 0) -> MagicMock:
    """Helper to create a mock process with given outputs."""
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout.encode("utf-8"), stderr.encode("utf-8")))
    proc.returncode = exit_code
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


# ── ClaudeCodeAdapter Tests ──


@pytest.mark.asyncio
async def test_claude_code_adapter_success(mock_which: Any) -> None:
    """Test successful generation with Claude Code adapter."""

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        return await _create_mock_proc(
            stdout="This is the generated response.",
            stderr="prompt_tokens: 100\ncompletion_tokens: 50",
            exit_code=0,
        )

    with (
        patch("asyncio.create_subprocess_exec", new=_mock_exec),
        patch("nit.llm.cli_adapter.report_cli_usage_event") as mock_report,
    ):
        config = CLIToolConfig(command="claude", model="claude-sonnet-4-5")
        adapter = ClaudeCodeAdapter(config)

        request = GenerationRequest(
            messages=[
                LLMMessage(role="system", content="You are a helpful assistant."),
                LLMMessage(role="user", content="Write a hello world function."),
            ]
        )

        response = await adapter.generate(request)

        assert response.text == "This is the generated response."
        assert response.model == "claude-sonnet-4-5"
        assert response.prompt_tokens == 100
        assert response.completion_tokens == 50
        assert mock_report.call_count == 1
        assert mock_report.call_args.kwargs["provider"] == "anthropic"
        assert mock_report.call_args.kwargs["source"] == "cli"


@pytest.mark.asyncio
async def test_claude_code_adapter_token_estimation(mock_which: Any) -> None:
    """Test token estimation when no usage info is provided."""

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        return await _create_mock_proc(stdout="Short text", stderr="", exit_code=0)

    with patch("asyncio.create_subprocess_exec", new=_mock_exec):
        config = CLIToolConfig(command="claude", model="claude-sonnet-4-5")
        adapter = ClaudeCodeAdapter(config)

        request = GenerationRequest(messages=[LLMMessage(role="user", content="Test")])

        response = await adapter.generate(request)

        assert response.text == "Short text"
        assert response.completion_tokens > 0  # Estimated


@pytest.mark.asyncio
async def test_claude_code_adapter_error_handling(mock_which: Any) -> None:
    """Test error handling when Claude Code returns an error."""

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        return await _create_mock_proc(
            stdout="", stderr="Error: Model 'invalid-model' not found", exit_code=1
        )

    with patch("asyncio.create_subprocess_exec", new=_mock_exec):
        config = CLIToolConfig(command="claude", model="invalid-model")
        adapter = ClaudeCodeAdapter(config)

        request = GenerationRequest(messages=[LLMMessage(role="user", content="Test")])

        with pytest.raises(LLMError, match="Model not found"):
            await adapter.generate(request)


@pytest.mark.asyncio
async def test_claude_code_adapter_timeout(mock_which: Any) -> None:
    """Test timeout handling."""

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        proc = MagicMock()

        async def _hang() -> tuple[bytes, bytes]:
            await asyncio.sleep(10)
            return (b"", b"")

        proc.communicate = _hang
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        return proc

    with patch("asyncio.create_subprocess_exec", new=_mock_exec):
        config = CLIToolConfig(command="claude", model="claude-sonnet-4-5", timeout=1)
        adapter = ClaudeCodeAdapter(config)

        request = GenerationRequest(messages=[LLMMessage(role="user", content="Test")])

        with pytest.raises(LLMConnectionError, match="timed out"):
            await adapter.generate(request)


# ── CodexAdapter Tests ──


@pytest.mark.asyncio
async def test_codex_adapter_success(mock_which: Any) -> None:
    """Test successful generation with Codex adapter."""
    response_data = {
        "text": "def hello():\n    print('Hello, world!')",
        "prompt_tokens": 80,
        "completion_tokens": 40,
    }

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        return await _create_mock_proc(stdout=json.dumps(response_data), stderr="", exit_code=0)

    with patch("asyncio.create_subprocess_exec", new=_mock_exec):
        config = CLIToolConfig(command="codex", model="code-davinci-002")
        adapter = CodexAdapter(config)

        request = GenerationRequest(
            messages=[LLMMessage(role="user", content="Write a hello function")]
        )

        response = await adapter.generate(request)

        assert response.text == "def hello():\n    print('Hello, world!')"
        assert response.model == "code-davinci-002"
        assert response.prompt_tokens == 80
        assert response.completion_tokens == 40


@pytest.mark.asyncio
async def test_codex_adapter_non_json_response(mock_which: Any) -> None:
    """Test fallback when Codex returns non-JSON response."""

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        return await _create_mock_proc(stdout="Plain text response", stderr="", exit_code=0)

    with patch("asyncio.create_subprocess_exec", new=_mock_exec):
        config = CLIToolConfig(command="codex", model="code-davinci-002")
        adapter = CodexAdapter(config)

        request = GenerationRequest(messages=[LLMMessage(role="user", content="Test")])

        response = await adapter.generate(request)

        assert response.text == "Plain text response"
        assert response.completion_tokens > 0  # Estimated


@pytest.mark.asyncio
async def test_codex_adapter_error(mock_which: Any) -> None:
    """Test error handling for Codex adapter."""

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        return await _create_mock_proc(
            stdout="", stderr="Authentication failed: invalid API key", exit_code=1
        )

    with patch("asyncio.create_subprocess_exec", new=_mock_exec):
        config = CLIToolConfig(command="codex", model="code-davinci-002")
        adapter = CodexAdapter(config)

        request = GenerationRequest(messages=[LLMMessage(role="user", content="Test")])

        with pytest.raises(LLMError, match="Authentication failed"):
            await adapter.generate(request)


# ── CustomCommandAdapter Tests ──


@pytest.mark.asyncio
async def test_custom_command_adapter_success(mock_which: Any, tmp_path: Path) -> None:
    """Test custom command adapter with template substitution."""

    # Track the output file that will be created
    output_files: list[Path] = []

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        # Write to the output file that was created by the adapter
        if output_files:
            output_files[0].write_text("Custom command output", encoding="utf-8")
        return await _create_mock_proc(stdout="", stderr="", exit_code=0)

    with (
        patch("asyncio.create_subprocess_exec", new=_mock_exec),
        patch("tempfile.NamedTemporaryFile") as mock_temp,
    ):
        # Create real temp files for testing
        ctx_file = tmp_path / "context.txt"
        out_file = tmp_path / "output.txt"
        output_files.append(out_file)

        # Mock NamedTemporaryFile to return our controlled temp files
        def _temp_factory(*args: Any, **kwargs: Any) -> Any:
            mock_file = MagicMock()
            mock_file.__enter__ = lambda self: self
            mock_file.__exit__ = lambda *args: None
            # Return context file first, then output file
            if not ctx_file.exists():
                mock_file.name = str(ctx_file)
                mock_file.write = lambda text: ctx_file.write_text(text, encoding="utf-8")
                return mock_file
            mock_file.name = str(out_file)
            mock_file.write = lambda text: None
            return mock_file

        mock_temp.side_effect = _temp_factory

        config = CLIToolConfig(
            command="my-custom-tool --input {context_file} --model {model}",
            model="custom-model",
        )
        adapter = CustomCommandAdapter(config)

        request = GenerationRequest(messages=[LLMMessage(role="user", content="Generate code")])

        response = await adapter.generate(request)

        assert response.text == "Custom command output"
        assert response.model == "custom-model"


@pytest.mark.asyncio
async def test_custom_command_adapter_output_file(mock_which: Any, tmp_path: Path) -> None:
    """Test custom command adapter reading from output file."""
    ctx_file = tmp_path / "context.txt"
    output_file = tmp_path / "output.txt"

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        # Simulate command writing to output file
        output_file.write_text("Output from file", encoding="utf-8")
        return await _create_mock_proc(stdout="", stderr="", exit_code=0)

    with (
        patch("asyncio.create_subprocess_exec", new=_mock_exec),
        patch("tempfile.NamedTemporaryFile") as mock_temp,
    ):
        # Mock NamedTemporaryFile to return our controlled temp files
        def _temp_factory(*args: Any, **kwargs: Any) -> Any:
            mock_file = MagicMock()
            mock_file.__enter__ = lambda self: self
            mock_file.__exit__ = lambda *args: None
            # Return context file first, then output file
            if not ctx_file.exists():
                mock_file.name = str(ctx_file)
                mock_file.write = lambda text: ctx_file.write_text(text, encoding="utf-8")
                return mock_file
            mock_file.name = str(output_file)
            mock_file.write = lambda text: None
            return mock_file

        mock_temp.side_effect = _temp_factory

        config = CLIToolConfig(
            command="my-tool --output {output_file}",
            model="custom-model",
        )
        adapter = CustomCommandAdapter(config)

        request = GenerationRequest(messages=[LLMMessage(role="user", content="Test")])

        response = await adapter.generate(request)

        assert response.text == "Output from file"


@pytest.mark.asyncio
async def test_custom_command_adapter_error(mock_which: Any) -> None:
    """Test error handling for custom command adapter."""

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        return await _create_mock_proc(
            stdout="", stderr="Custom tool error: something went wrong", exit_code=2
        )

    with patch("asyncio.create_subprocess_exec", new=_mock_exec):
        config = CLIToolConfig(
            command="failing-tool {prompt}",
            model="custom-model",
        )
        adapter = CustomCommandAdapter(config)

        request = GenerationRequest(messages=[LLMMessage(role="user", content="Test")])

        with pytest.raises(LLMError, match="CLI tool error"):
            await adapter.generate(request)


# ── Command Validation Tests ──


def test_command_not_found() -> None:
    """Test that missing command is detected."""
    with patch("nit.llm.cli_adapter.shutil.which", return_value=None):
        config = CLIToolConfig(command="nonexistent-command", model="test")
        with pytest.raises(LLMError, match="not found in PATH"):
            ClaudeCodeAdapter(config)


# ── generate_text Tests ──


@pytest.mark.asyncio
async def test_generate_text(mock_which: Any) -> None:
    """Test convenience generate_text method."""

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        return await _create_mock_proc(stdout="Generated text response", stderr="", exit_code=0)

    with patch("asyncio.create_subprocess_exec", new=_mock_exec):
        config = CLIToolConfig(command="claude", model="claude-sonnet-4-5")
        adapter = ClaudeCodeAdapter(config)

        text = await adapter.generate_text("Write hello world", context="You are a coder")

        assert text == "Generated text response"


# ── Error Pattern Detection Tests ──


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stderr", "expected_match"),
    [
        ("Error: Model 'xyz' not found", "Model not found"),
        ("Unknown model: abc", "Model not found"),
        ("Authentication error: invalid API key", "Authentication failed"),
        ("Rate limit exceeded for this API key", "Rate limit exceeded"),
        ("API quota exhausted", "Rate limit exceeded"),
    ],
)
async def test_error_detection(
    mock_which: Any,
    stderr: str,
    expected_match: str,
) -> None:
    """Test that different error patterns are correctly detected."""

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        return await _create_mock_proc(stdout="", stderr=stderr, exit_code=1)

    with patch("asyncio.create_subprocess_exec", new=_mock_exec):
        config = CLIToolConfig(command="claude", model="test-model")
        adapter = ClaudeCodeAdapter(config)

        request = GenerationRequest(messages=[LLMMessage(role="user", content="Test")])

        with pytest.raises(LLMError, match=expected_match):
            await adapter.generate(request)
