"""Tests for the LLM engine factory (src/nit/llm/factory.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nit.llm.builtin import BuiltinLLM
from nit.llm.cli_adapter import ClaudeCodeAdapter, CodexAdapter, CustomCommandAdapter
from nit.llm.config import LLMConfig
from nit.llm.engine import LLMError
from nit.llm.factory import create_engine

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_platform_and_callbacks() -> object:
    """Mock platform environment and usage callbacks for all tests.

    The BuiltinLLM constructor calls ensure_nit_usage_callback_registered()
    which would register litellm callbacks. We mock it to avoid side effects.
    """
    with (
        patch("nit.llm.factory.configure_platform_environment"),
        patch("nit.llm.builtin.ensure_nit_usage_callback_registered"),
    ):
        yield


# ── Helpers ──────────────────────────────────────────────────────


def _make_config(**overrides: str | int | float | list[str] | None) -> LLMConfig:
    """Build an LLMConfig with sensible defaults, applying *overrides*."""
    defaults: dict[str, str | int | float | list[str] | None] = {
        "mode": "builtin",
        "model": "gpt-4o",
        "api_key": "sk-test-key",
        "provider": "openai",
    }
    defaults.update(overrides)
    return LLMConfig(
        provider=str(defaults.get("provider", "openai")),
        model=str(defaults.get("model", "")),
        api_key=str(defaults.get("api_key", "")),
        base_url=str(defaults.get("base_url", "")),
        mode=str(defaults.get("mode", "builtin")),
        cli_command=str(defaults.get("cli_command", "")),
        cli_timeout=int(str(defaults.get("cli_timeout", 300))),
        platform_url=str(defaults.get("platform_url", "")),
        platform_api_key=str(defaults.get("platform_api_key", "")),
        platform_mode=str(defaults.get("platform_mode", "")),
    )


# ── Builtin mode ─────────────────────────────────────────────────


def test_create_builtin_engine() -> None:
    """Test creating a builtin engine returns BuiltinLLM."""
    config = _make_config(mode="builtin", model="gpt-4o", api_key="sk-test")
    engine = create_engine(config)
    assert isinstance(engine, BuiltinLLM)


def test_create_builtin_engine_uses_model() -> None:
    """Test that builtin engine is configured with the right model."""
    config = _make_config(mode="builtin", model="claude-sonnet-4-5-20250514", api_key="sk-test")
    engine = create_engine(config)
    assert isinstance(engine, BuiltinLLM)
    assert engine.model_name == "claude-sonnet-4-5-20250514"


def test_create_builtin_raises_without_model() -> None:
    """Test that builtin mode requires a model."""
    config = _make_config(mode="builtin", model="", api_key="sk-test")
    with pytest.raises(LLMError, match="No LLM model configured"):
        create_engine(config)


# ── Ollama mode ──────────────────────────────────────────────────


def test_create_ollama_engine() -> None:
    """Test creating an ollama engine returns BuiltinLLM."""
    config = _make_config(mode="ollama", model="llama3")
    engine = create_engine(config)
    assert isinstance(engine, BuiltinLLM)


def test_create_ollama_raises_without_model() -> None:
    """Test that ollama mode raises without a model."""
    config = _make_config(mode="ollama", model="")
    with pytest.raises(LLMError, match="No LLM model configured"):
        create_engine(config)


# ── CLI mode ─────────────────────────────────────────────────────


@patch("shutil.which", return_value="/usr/local/bin/claude")
def test_create_cli_engine_claude(mock_which: MagicMock) -> None:
    """Test CLI mode with 'claude' command creates ClaudeCodeAdapter."""
    config = _make_config(mode="cli", model="claude-sonnet-4-5-20250514", cli_command="claude")
    engine = create_engine(config)
    assert isinstance(engine, ClaudeCodeAdapter)


@patch("shutil.which", return_value="/usr/local/bin/codex")
def test_create_cli_engine_codex(mock_which: MagicMock) -> None:
    """Test CLI mode with 'codex' command creates CodexAdapter."""
    config = _make_config(mode="cli", model="gpt-4o", cli_command="codex")
    engine = create_engine(config)
    assert isinstance(engine, CodexAdapter)


@patch("shutil.which", return_value="/usr/local/bin/mytool")
def test_create_cli_engine_unknown_defaults_to_claude(mock_which: MagicMock) -> None:
    """Test CLI mode with unknown command defaults to ClaudeCodeAdapter."""
    config = _make_config(mode="cli", model="gpt-4o", cli_command="mytool")
    engine = create_engine(config)
    assert isinstance(engine, ClaudeCodeAdapter)


def test_create_cli_raises_without_model() -> None:
    """Test CLI mode raises without a model."""
    config = _make_config(mode="cli", model="", cli_command="claude")
    with pytest.raises(LLMError, match="No LLM model configured"):
        create_engine(config)


def test_create_cli_raises_without_command() -> None:
    """Test CLI mode raises without a cli_command."""
    config = _make_config(mode="cli", model="gpt-4o", cli_command="")
    with pytest.raises(LLMError, match="No CLI command configured"):
        create_engine(config)


# ── Custom mode ──────────────────────────────────────────────────


@patch("shutil.which", return_value="/usr/local/bin/myscript")
def test_create_custom_engine(mock_which: MagicMock) -> None:
    """Test custom mode creates CustomCommandAdapter."""
    config = _make_config(mode="custom", model="gpt-4o", cli_command="myscript")
    engine = create_engine(config)
    assert isinstance(engine, CustomCommandAdapter)


def test_create_custom_raises_without_model() -> None:
    """Test custom mode raises without a model."""
    config = _make_config(mode="custom", model="", cli_command="myscript")
    with pytest.raises(LLMError, match="No LLM model configured"):
        create_engine(config)


def test_create_custom_raises_without_command() -> None:
    """Test custom mode raises without cli_command."""
    config = _make_config(mode="custom", model="gpt-4o", cli_command="")
    with pytest.raises(LLMError, match="No CLI command configured"):
        create_engine(config)


# ── Unsupported mode ─────────────────────────────────────────────


def test_create_engine_unsupported_mode() -> None:
    """Test unsupported mode raises LLMError."""
    config = _make_config(mode="imaginary")
    with pytest.raises(LLMError, match="Unsupported LLM mode"):
        create_engine(config)


# ── Platform runtime ─────────────────────────────────────────────


def test_platform_mode_disabled_passthrough() -> None:
    """Test that platform_mode=disabled passes config through unchanged."""
    config = _make_config(
        mode="builtin",
        model="gpt-4o",
        api_key="sk-test",
        platform_mode="disabled",
    )
    engine = create_engine(config)
    assert isinstance(engine, BuiltinLLM)


def test_platform_mode_byok_passthrough() -> None:
    """Test that platform_mode=byok passes config through unchanged."""
    config = _make_config(
        mode="builtin",
        model="gpt-4o",
        api_key="sk-test",
        platform_mode="byok",
    )
    engine = create_engine(config)
    assert isinstance(engine, BuiltinLLM)


def test_platform_mode_platform_requires_url() -> None:
    """Test that platform mode requires platform_url."""
    config = _make_config(
        mode="builtin",
        model="gpt-4o",
        platform_mode="platform",
        platform_url="",
        platform_api_key="pk-test",
    )
    with pytest.raises(LLMError, match=r"platform\.url"):
        create_engine(config)


def test_platform_mode_platform_requires_api_key() -> None:
    """Test that platform mode requires platform_api_key."""
    config = _make_config(
        mode="builtin",
        model="gpt-4o",
        platform_mode="platform",
        platform_url="https://platform.getnit.dev",
        platform_api_key="",
    )
    with pytest.raises(LLMError, match=r"platform\.api_key"):
        create_engine(config)


def test_platform_mode_platform_requires_builtin_or_ollama() -> None:
    """Test that platform mode only works with builtin/ollama LLM modes."""
    config = _make_config(
        mode="cli",
        model="gpt-4o",
        cli_command="claude",
        platform_mode="platform",
        platform_url="https://platform.getnit.dev",
        platform_api_key="pk-test",
    )
    with pytest.raises(LLMError, match=r"requires llm\.mode"):
        create_engine(config)


@patch("nit.llm.factory.build_llm_proxy_base_url", return_value="https://proxy.example.com/v1")
def test_platform_mode_platform_sets_base_url(mock_proxy: MagicMock) -> None:
    """Test that platform mode sets base_url and api_key from platform config."""
    config = _make_config(
        mode="builtin",
        model="gpt-4o",
        platform_mode="platform",
        platform_url="https://platform.getnit.dev",
        platform_api_key="pk-test",
    )
    engine = create_engine(config)
    assert isinstance(engine, BuiltinLLM)
    mock_proxy.assert_called_once_with("https://platform.getnit.dev")


def test_platform_mode_invalid_falls_back_to_disabled() -> None:
    """Test that invalid platform_mode without url/key resolves to disabled."""
    config = _make_config(
        mode="builtin",
        model="gpt-4o",
        api_key="sk-test",
        platform_mode="invalid_mode",
        platform_url="",
        platform_api_key="",
    )
    # Should succeed because resolved_platform_mode falls back to "disabled"
    engine = create_engine(config)
    assert isinstance(engine, BuiltinLLM)
