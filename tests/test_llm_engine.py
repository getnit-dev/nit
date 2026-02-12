"""Tests for the LLM engine abstraction, built-in adapter, config, and factory."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from litellm.exceptions import (
    APIConnectionError as LiteLLMConnectionError,
)
from litellm.exceptions import (
    AuthenticationError as LiteLLMAuthError,
)
from litellm.exceptions import (
    RateLimitError as LiteLLMRateLimitError,
)

from nit.llm.builtin import BuiltinLLM, BuiltinLLMConfig, RateLimitConfig, RetryConfig, _TokenBucket
from nit.llm.config import LLMConfig, _resolve_env_vars, load_llm_config
from nit.llm.engine import (
    GenerationRequest,
    LLMAuthError,
    LLMConnectionError,
    LLMError,
    LLMMessage,
    LLMRateLimitError,
    LLMResponse,
)
from nit.llm.factory import create_engine
from nit.llm.usage_callback import _SINGLETONS
from nit.utils.platform_client import get_platform_api_key

if TYPE_CHECKING:
    from pathlib import Path

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_usage_callback() -> Any:
    """Mock ensure_nit_usage_callback_registered to prevent global state issues."""
    # Reset the singleton state before each test
    _SINGLETONS.reporter = None
    _SINGLETONS.callback = None

    with patch("nit.llm.builtin.ensure_nit_usage_callback_registered"):
        yield

    # Clean up after the test
    _SINGLETONS.reporter = None
    _SINGLETONS.callback = None


# ── LLMResponse dataclass tests ──────────────────────────────────


def test_llm_response_total_tokens() -> None:
    resp = LLMResponse(text="hi", model="m", prompt_tokens=10, completion_tokens=5)
    assert resp.total_tokens == 15


def test_llm_response_defaults() -> None:
    resp = LLMResponse(text="hi", model="m")
    assert resp.prompt_tokens == 0
    assert resp.completion_tokens == 0
    assert resp.total_tokens == 0


# ── LLMConfig tests ──────────────────────────────────────────────


def test_config_defaults() -> None:
    cfg = LLMConfig()
    assert cfg.provider == "openai"
    assert cfg.model == ""
    assert cfg.mode == "builtin"
    assert cfg.temperature == 0.2
    assert cfg.max_tokens == 4096
    assert not cfg.is_configured


def test_config_is_configured_builtin() -> None:
    cfg = LLMConfig(model="gpt-4o", api_key="sk-test")
    assert cfg.is_configured


def test_config_is_configured_ollama_no_key() -> None:
    cfg = LLMConfig(mode="ollama", model="codellama")
    assert cfg.is_configured


def test_config_not_configured_missing_model() -> None:
    cfg = LLMConfig(api_key="sk-test")
    assert not cfg.is_configured


# ── Env var resolution ────────────────────────────────────────────


def test_resolve_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "secret123")
    assert _resolve_env_vars("${MY_KEY}") == "secret123"


def test_resolve_env_vars_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NONEXISTENT", raising=False)
    assert _resolve_env_vars("${NONEXISTENT}") == ""


def test_resolve_env_vars_mixed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST", "localhost")
    assert _resolve_env_vars("http://${HOST}:8080") == "http://localhost:8080"


# ── load_llm_config tests ────────────────────────────────────────


def test_load_config_from_yaml(tmp_path: Path) -> None:
    nit_yml = tmp_path / ".nit.yml"
    nit_yml.write_text(
        "llm:\n"
        "  provider: anthropic\n"
        "  model: claude-sonnet-4-5-20250514\n"
        "  api_key: sk-ant-test\n"
        "  temperature: 0.5\n"
    )
    cfg = load_llm_config(tmp_path)
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-sonnet-4-5-20250514"
    assert cfg.api_key == "sk-ant-test"
    assert cfg.temperature == 0.5


def test_load_config_env_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("NIT_LLM_MODEL", "claude-haiku")
    monkeypatch.setenv("NIT_LLM_API_KEY", "env-key")
    cfg = load_llm_config(tmp_path)  # no .nit.yml
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-haiku"
    assert cfg.api_key == "env-key"


def test_load_config_yaml_env_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "real-key")
    nit_yml = tmp_path / ".nit.yml"
    nit_yml.write_text(
        "llm:\n"
        "  provider: anthropic\n"
        "  model: claude-sonnet-4-5-20250514\n"
        "  api_key: ${ANTHROPIC_API_KEY}\n"
    )
    cfg = load_llm_config(tmp_path)
    assert cfg.api_key == "real-key"


def test_load_config_missing_llm_section(tmp_path: Path) -> None:
    nit_yml = tmp_path / ".nit.yml"
    nit_yml.write_text("project:\n  root: .\n")
    cfg = load_llm_config(tmp_path)
    assert cfg.provider == "openai"  # default


def test_load_config_empty_yaml(tmp_path: Path) -> None:
    nit_yml = tmp_path / ".nit.yml"
    nit_yml.write_text("")
    cfg = load_llm_config(tmp_path)
    assert cfg.model == ""


def test_load_config_with_platform_section(tmp_path: Path) -> None:
    nit_yml = tmp_path / ".nit.yml"
    nit_yml.write_text(
        "llm:\n"
        "  provider: openai\n"
        "  model: gpt-4o\n"
        "platform:\n"
        "  url: https://platform.getnit.dev\n"
        "  api_key: nit_key_platform\n"
        "  mode: platform\n"
    )

    cfg = load_llm_config(tmp_path)

    assert cfg.platform_url == "https://platform.getnit.dev"
    assert cfg.platform_api_key == "nit_key_platform"
    assert cfg.resolved_platform_mode == "platform"
    assert cfg.is_configured


def test_load_config_platform_byok_mode(tmp_path: Path) -> None:
    nit_yml = tmp_path / ".nit.yml"
    nit_yml.write_text(
        "llm:\n"
        "  provider: anthropic\n"
        "  model: claude-sonnet-4-5-20250514\n"
        "  api_key: byok_key\n"
        "platform:\n"
        "  url: https://platform.getnit.dev\n"
        "  api_key: nit_key_usage\n"
        "  mode: byok\n"
    )

    cfg = load_llm_config(tmp_path)

    assert cfg.api_key == "byok_key"
    assert cfg.platform_api_key == "nit_key_usage"
    assert cfg.resolved_platform_mode == "byok"
    assert cfg.is_configured


# ── Factory tests ─────────────────────────────────────────────────


def test_factory_creates_builtin() -> None:
    cfg = LLMConfig(model="gpt-4o", api_key="sk-test")
    engine = create_engine(cfg)
    assert isinstance(engine, BuiltinLLM)
    assert engine.model_name == "gpt-4o"


def test_factory_creates_ollama() -> None:
    cfg = LLMConfig(mode="ollama", model="codellama", base_url="http://localhost:11434")
    engine = create_engine(cfg)
    assert isinstance(engine, BuiltinLLM)
    assert engine.model_name == "codellama"


def test_factory_platform_mode_routes_to_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NIT_PLATFORM_URL", raising=False)
    monkeypatch.delenv("NIT_PLATFORM_API_KEY", raising=False)

    cfg = LLMConfig(
        model="gpt-4o",
        provider="openai",
        platform_mode="platform",
        platform_url="https://platform.getnit.dev",
        platform_api_key="nit_key_proxy",
    )
    engine = create_engine(cfg)
    assert isinstance(engine, BuiltinLLM)
    assert engine._base_url == "https://platform.getnit.dev/api/v1/llm-proxy"
    assert engine._api_key == "nit_key_proxy"
    assert os.environ.get("NIT_PLATFORM_URL") == "https://platform.getnit.dev"
    assert get_platform_api_key() == "nit_key_proxy"


def test_factory_byok_mode_keeps_provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NIT_PLATFORM_URL", raising=False)
    monkeypatch.delenv("NIT_PLATFORM_API_KEY", raising=False)

    cfg = LLMConfig(
        model="claude-sonnet-4-5-20250514",
        provider="anthropic",
        api_key="byok_key",
        platform_mode="byok",
        platform_url="https://platform.getnit.dev",
        platform_api_key="nit_key_usage",
    )
    engine = create_engine(cfg)
    assert isinstance(engine, BuiltinLLM)
    assert engine._api_key == "byok_key"
    assert engine._base_url is None
    assert os.environ.get("NIT_PLATFORM_URL") == "https://platform.getnit.dev"
    assert get_platform_api_key() == "nit_key_usage"


def test_factory_raises_on_missing_model() -> None:
    cfg = LLMConfig(mode="builtin", model="")
    with pytest.raises(LLMError, match="No LLM model configured"):
        create_engine(cfg)


def test_factory_raises_on_unknown_mode() -> None:
    cfg = LLMConfig(mode="unknown", model="test")
    with pytest.raises(LLMError, match="Unsupported LLM mode"):
        create_engine(cfg)


# ── _TokenBucket tests ───────────────────────────────────────────


async def test_token_bucket_allows_burst() -> None:
    bucket = _TokenBucket(capacity=10)
    for _ in range(10):
        await bucket.acquire()
    # All 10 should succeed without blocking


# ── RetryConfig / RateLimitConfig defaults ────────────────────────


def test_retry_config_defaults() -> None:
    rc = RetryConfig()
    assert rc.max_retries == 3
    assert rc.base_delay == 1.0
    assert rc.max_delay == 60.0
    assert rc.backoff_factor == 2.0


def test_rate_limit_config_defaults() -> None:
    rl = RateLimitConfig()
    assert rl.requests_per_minute == 60


# ── BuiltinLLM mock tests ────────────────────────────────────────


def _mock_completion(
    text: str = "Hello!", model: str = "gpt-4o", prompt_t: int = 10, comp_t: int = 5
) -> SimpleNamespace:
    """Build a fake LiteLLM completion response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        model=model,
        usage=SimpleNamespace(prompt_tokens=prompt_t, completion_tokens=comp_t),
    )


async def test_builtin_generate_text() -> None:
    engine = BuiltinLLM(BuiltinLLMConfig(model="gpt-4o", api_key="sk-test"))
    mock_resp = _mock_completion(text="Generated test code")

    with patch("nit.llm.builtin.litellm.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.return_value = mock_resp
        result = await engine.generate_text("Write a test", context="You are a test writer")

    assert result == "Generated test code"
    mock_ac.assert_awaited_once()
    call_kwargs = mock_ac.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o"
    assert len(call_kwargs["messages"]) == 2
    assert call_kwargs["messages"][0]["role"] == "system"


async def test_builtin_generate_returns_response() -> None:
    engine = BuiltinLLM(BuiltinLLMConfig(model="gpt-4o", api_key="sk-test"))
    mock_resp = _mock_completion(text="result", prompt_t=20, comp_t=10)

    with patch("nit.llm.builtin.litellm.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.return_value = mock_resp
        response = await engine.generate(
            GenerationRequest(
                messages=[LLMMessage(role="user", content="hello")],
                temperature=0.5,
            )
        )

    assert isinstance(response, LLMResponse)
    assert response.text == "result"
    assert response.prompt_tokens == 20
    assert response.completion_tokens == 10
    assert response.total_tokens == 30


async def test_builtin_generate_no_context() -> None:
    engine = BuiltinLLM(BuiltinLLMConfig(model="gpt-4o", api_key="sk-test"))
    mock_resp = _mock_completion(text="no context")

    with patch("nit.llm.builtin.litellm.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.return_value = mock_resp
        await engine.generate_text("Just a prompt")

    call_kwargs = mock_ac.call_args.kwargs
    assert len(call_kwargs["messages"]) == 1
    assert call_kwargs["messages"][0]["role"] == "user"


def test_builtin_registers_usage_callback() -> None:
    with patch("nit.llm.builtin.ensure_nit_usage_callback_registered") as mock_register:
        BuiltinLLM(BuiltinLLMConfig(model="gpt-4o", api_key="sk-test"))

    mock_register.assert_called_once()


async def test_builtin_generate_model_override() -> None:
    engine = BuiltinLLM(BuiltinLLMConfig(model="gpt-4o", api_key="sk-test"))
    mock_resp = _mock_completion(text="ok", model="gpt-4o-mini")

    with patch("nit.llm.builtin.litellm.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.return_value = mock_resp
        await engine.generate(
            GenerationRequest(
                messages=[LLMMessage(role="user", content="hi")],
                model="gpt-4o-mini",
            )
        )

    call_kwargs = mock_ac.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"


async def test_builtin_adds_metadata_and_estimated_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIT_PLATFORM_USER_ID", "user-abc")
    monkeypatch.setenv("NIT_PLATFORM_PROJECT_ID", "project-xyz")

    engine = BuiltinLLM(
        BuiltinLLMConfig(
            model="gpt-4o",
            provider="openai",
            api_key="sk-test",
            base_url="https://platform.getnit.dev/api/v1/llm-proxy",
        )
    )
    mock_resp = _mock_completion(text="ok", model="gpt-4o")

    with patch("nit.llm.builtin.litellm.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.return_value = mock_resp
        await engine.generate(
            GenerationRequest(
                messages=[LLMMessage(role="user", content="hello world")],
                max_tokens=222,
            )
        )

    call_kwargs = mock_ac.call_args.kwargs
    metadata = call_kwargs["metadata"]
    headers = call_kwargs["extra_headers"]

    assert metadata["nit_usage_source"] == "api"
    assert metadata["nit_usage_emit"] is False
    assert metadata["nit_provider"] == "openai"
    assert metadata["nit_user_id"] == "user-abc"
    assert metadata["nit_project_id"] == "project-xyz"
    assert int(headers["x-nit-estimated-prompt-tokens"]) > 0
    assert headers["x-nit-estimated-completion-tokens"] == "222"


# ── Retry / error handling tests ──────────────────────────────────


async def test_builtin_retries_on_rate_limit() -> None:
    engine = BuiltinLLM(
        BuiltinLLMConfig(
            model="gpt-4o",
            api_key="sk-test",
            retry=RetryConfig(max_retries=2, base_delay=0.01),
        )
    )
    mock_resp = _mock_completion()

    call_count = 0

    async def _side_effect(**kwargs: Any) -> SimpleNamespace:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise LiteLLMRateLimitError(
                message="rate limited",
                llm_provider="openai",
                model="gpt-4o",
            )
        return mock_resp

    with patch("nit.llm.builtin.litellm.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.side_effect = _side_effect
        result = await engine.generate_text("test")

    assert result == "Hello!"
    assert call_count == 3


async def test_builtin_raises_auth_error() -> None:
    engine = BuiltinLLM(BuiltinLLMConfig(model="gpt-4o", api_key="bad-key"))

    with patch("nit.llm.builtin.litellm.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.side_effect = LiteLLMAuthError(
            message="invalid key",
            llm_provider="openai",
            model="gpt-4o",
        )
        with pytest.raises(LLMAuthError):
            await engine.generate_text("test")


async def test_builtin_exhausts_retries_raises_rate_limit() -> None:
    engine = BuiltinLLM(
        BuiltinLLMConfig(
            model="gpt-4o",
            api_key="sk-test",
            retry=RetryConfig(max_retries=1, base_delay=0.01),
        )
    )

    with patch("nit.llm.builtin.litellm.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.side_effect = LiteLLMRateLimitError(
            message="rate limited",
            llm_provider="openai",
            model="gpt-4o",
        )
        with pytest.raises(LLMRateLimitError):
            await engine.generate_text("test")


async def test_builtin_retries_on_connection_error() -> None:
    engine = BuiltinLLM(
        BuiltinLLMConfig(
            model="gpt-4o",
            api_key="sk-test",
            retry=RetryConfig(max_retries=1, base_delay=0.01),
        )
    )
    mock_resp = _mock_completion()

    call_count = 0

    async def _side_effect(**kwargs: Any) -> SimpleNamespace:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LiteLLMConnectionError(
                message="connection refused",
                llm_provider="openai",
                model="gpt-4o",
            )
        return mock_resp

    with patch("nit.llm.builtin.litellm.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.side_effect = _side_effect
        result = await engine.generate_text("test")

    assert result == "Hello!"
    assert call_count == 2


async def test_builtin_connection_error_exhausted() -> None:
    engine = BuiltinLLM(
        BuiltinLLMConfig(
            model="gpt-4o",
            api_key="sk-test",
            retry=RetryConfig(max_retries=0, base_delay=0.01),
        )
    )

    with patch("nit.llm.builtin.litellm.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.side_effect = LiteLLMConnectionError(
            message="connection refused",
            llm_provider="openai",
            model="gpt-4o",
        )
        with pytest.raises(LLMConnectionError):
            await engine.generate_text("test")


# ── Token counting tests ─────────────────────────────────────────


def test_count_tokens_fallback() -> None:
    engine = BuiltinLLM(BuiltinLLMConfig(model="gpt-4o", api_key="sk-test"))
    with patch("nit.llm.builtin.litellm.token_counter", side_effect=Exception("no tokenizer")):
        count = engine.count_tokens("hello world")
    # Fallback: ~4 chars per token -> 11 // 4 = 2
    assert count == 2


def test_count_tokens_uses_litellm() -> None:
    engine = BuiltinLLM(BuiltinLLMConfig(model="gpt-4o", api_key="sk-test"))
    with patch("nit.llm.builtin.litellm.token_counter", return_value=42):
        count = engine.count_tokens("some text")
    assert count == 42


# ── Backoff delay tests ───────────────────────────────────────────


def test_backoff_delay_exponential() -> None:
    engine = BuiltinLLM(
        BuiltinLLMConfig(
            model="gpt-4o",
            api_key="sk-test",
            retry=RetryConfig(base_delay=1.0, backoff_factor=2.0, max_delay=60.0),
        )
    )
    assert engine._backoff_delay(0) == 1.0
    assert engine._backoff_delay(1) == 2.0
    assert engine._backoff_delay(2) == 4.0
    assert engine._backoff_delay(3) == 8.0


def test_backoff_delay_capped() -> None:
    engine = BuiltinLLM(
        BuiltinLLMConfig(
            model="gpt-4o",
            api_key="sk-test",
            retry=RetryConfig(base_delay=1.0, backoff_factor=2.0, max_delay=5.0),
        )
    )
    assert engine._backoff_delay(10) == 5.0
