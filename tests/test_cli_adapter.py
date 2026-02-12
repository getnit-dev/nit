"""Tests for CLI tool adapters."""

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.llm.cli_adapter import (
    ClaudeCodeAdapter,
    CLIToolAdapter,
    CLIToolConfig,
    CodexAdapter,
    CustomCommandAdapter,
    _parse_bool_pattern,
    _parse_float_pattern,
    _parse_int_pattern,
    _parse_model_pattern,
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
        usage_event = mock_report.call_args.args[0]
        assert usage_event.provider == "anthropic"
        assert usage_event.source == "cli"


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


# ── Helper function tests ──


def test_parse_int_pattern_match() -> None:
    assert _parse_int_pattern("prompt_tokens: 100", [r"prompt_tokens:\s*(\d+)"]) == 100


def test_parse_int_pattern_no_match() -> None:
    assert _parse_int_pattern("no match here", [r"tokens:\s*(\d+)"]) == 0


def test_parse_int_pattern_invalid_value() -> None:
    # Pattern matches but group isn't valid int — tries next pattern
    assert _parse_int_pattern("tokens: abc", [r"tokens:\s*(\w+)"]) == 0


def test_parse_float_pattern_match() -> None:
    assert _parse_float_pattern("cost: $1.23", [r"\$([0-9]+\.[0-9]+)"]) == 1.23


def test_parse_float_pattern_no_match() -> None:
    assert _parse_float_pattern("nothing", [r"\$([0-9]+\.[0-9]+)"]) == 0.0


def test_parse_float_pattern_invalid() -> None:
    assert _parse_float_pattern("cost: abc", [r"cost:\s*(\w+)"]) == 0.0


def test_parse_bool_pattern_true() -> None:
    assert _parse_bool_pattern("cache_hit: true", [r"cache_hit:\s*(\w+)"]) is True
    assert _parse_bool_pattern("cache_hit: 1", [r"cache_hit:\s*(\w+)"]) is True
    assert _parse_bool_pattern("cache_hit: yes", [r"cache_hit:\s*(\w+)"]) is True
    assert _parse_bool_pattern("cache_hit: hit", [r"cache_hit:\s*(\w+)"]) is True


def test_parse_bool_pattern_false() -> None:
    assert _parse_bool_pattern("cache_hit: false", [r"cache_hit:\s*(\w+)"]) is False
    assert _parse_bool_pattern("cache_hit: 0", [r"cache_hit:\s*(\w+)"]) is False
    assert _parse_bool_pattern("cache_hit: miss", [r"cache_hit:\s*(\w+)"]) is False


def test_parse_bool_pattern_no_match() -> None:
    assert _parse_bool_pattern("nothing", [r"cache_hit:\s*(\w+)"]) is False


def test_parse_bool_pattern_unknown_value() -> None:
    assert _parse_bool_pattern("cache_hit: maybe", [r"cache_hit:\s*(\w+)"]) is False


def test_parse_model_pattern_found() -> None:
    assert _parse_model_pattern("model: gpt-4") == "gpt-4"
    assert _parse_model_pattern("model_name = claude-3") == "claude-3"


def test_parse_model_pattern_not_found() -> None:
    assert _parse_model_pattern("no model info") is None


# ── _infer_provider_from_model tests ──


def test_infer_provider_from_model() -> None:
    assert CLIToolAdapter._infer_provider_from_model("claude-3") == "anthropic"
    assert CLIToolAdapter._infer_provider_from_model("gpt-4") == "openai"
    assert CLIToolAdapter._infer_provider_from_model("o1-mini") == "openai"
    assert CLIToolAdapter._infer_provider_from_model("o3-mini") == "openai"
    assert CLIToolAdapter._infer_provider_from_model("gemini-pro") == "google"
    assert CLIToolAdapter._infer_provider_from_model("mistral-7b") == "mistral"
    assert CLIToolAdapter._infer_provider_from_model("custom/model") == "custom"
    assert CLIToolAdapter._infer_provider_from_model("llama-3") == "unknown"


# ── _estimate_tokens ──


def test_estimate_tokens() -> None:
    assert CLIToolAdapter._estimate_tokens("") == 1
    assert CLIToolAdapter._estimate_tokens("a" * 100) == 25


# ── _format_messages_as_text ──


def test_format_messages_as_text() -> None:
    messages = [
        LLMMessage(role="system", content="You are helpful"),
        LLMMessage(role="user", content="Hello"),
        LLMMessage(role="assistant", content="Hi"),
    ]
    text = CLIToolAdapter._format_messages_as_text(messages)
    assert "System: You are helpful" in text
    assert "User: Hello" in text
    assert "Assistant: Hi" in text


# ── CodexAdapter extended parsing ──


@pytest.mark.asyncio
async def test_codex_adapter_json_usage_fields(mock_which: Any) -> None:
    """Test codex with usage dict containing token info."""
    data = {
        "output_text": "result text",
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 25,
            "total_tokens": 75,
        },
        "model": "codex-v2",
        "provider": "openai",
        "cache_hit": True,
        "response_cost": 0.005,
    }

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        return await _create_mock_proc(stdout=json.dumps(data), stderr="", exit_code=0)

    with patch("asyncio.create_subprocess_exec", new=_mock_exec):
        config = CLIToolConfig(command="codex", model="codex-v2")
        adapter = CodexAdapter(config)
        request = GenerationRequest(messages=[LLMMessage(role="user", content="Test")])
        response = await adapter.generate(request)
        assert response.text == "result text"
        assert response.prompt_tokens == 50
        assert response.completion_tokens == 25


@pytest.mark.asyncio
async def test_codex_adapter_stderr_fallback(mock_which: Any) -> None:
    """Test codex falls back to stderr for token info."""
    data = {"text": "output"}

    async def _mock_exec(*args: Any, **kwargs: Any) -> MagicMock:
        return await _create_mock_proc(
            stdout=json.dumps(data),
            stderr="prompt_tokens: 30\ncompletion_tokens: 15\ncost: $0.01\n"
            "model: gpt-4\ncache_hit: true\n",
            exit_code=0,
        )

    with patch("asyncio.create_subprocess_exec", new=_mock_exec):
        config = CLIToolConfig(command="codex", model="codex-v2")
        adapter = CodexAdapter(config)
        request = GenerationRequest(messages=[LLMMessage(role="user", content="Test")])
        response = await adapter.generate(request)
        assert response.text == "output"


# ── ClaudeCodeAdapter model_name property ──


def test_claude_code_model_name(mock_which: Any) -> None:
    config = CLIToolConfig(command="claude", model="claude-sonnet-4-5")
    adapter = ClaudeCodeAdapter(config)
    assert adapter.model_name == "claude-sonnet-4-5"


# ── CustomCommandAdapter stdout fallback ──


def test_custom_command_parse_output_no_file(mock_which: Any) -> None:
    """When no output file exists, _parse_output uses stdout."""
    config = CLIToolConfig(command="my-tool {prompt}", model="m")
    adapter = CustomCommandAdapter(config)
    # No _output_file attribute set
    resp = adapter._parse_output("stdout text", "", 0, "m")
    assert resp.text == "stdout text"
    assert resp.error is None


def test_custom_command_parse_output_error(mock_which: Any) -> None:
    """Non-zero exit code sets error."""
    config = CLIToolConfig(command="my-tool {prompt}", model="m")
    adapter = CustomCommandAdapter(config)
    resp = adapter._parse_output("", "fail msg", 1, "m")
    assert resp.error == "fail msg"
