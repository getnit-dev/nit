"""Factory for creating an ``LLMEngine`` from configuration."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from nit.llm.builtin import BuiltinLLM, RateLimitConfig, RetryConfig
from nit.llm.cli_adapter import (
    ClaudeCodeAdapter,
    CLIToolConfig,
    CodexAdapter,
    CustomCommandAdapter,
)
from nit.llm.engine import LLMEngine, LLMError
from nit.utils.platform_client import (
    PlatformRuntimeConfig,
    build_llm_proxy_base_url,
    configure_platform_environment,
)

if TYPE_CHECKING:
    from nit.llm.config import LLMConfig


def create_engine(config: LLMConfig) -> LLMEngine:
    """Instantiate the correct ``LLMEngine`` from an ``LLMConfig``.

    Supports modes:
    - ``builtin``: LiteLLM-based engine for API providers
    - ``ollama``: LiteLLM with Ollama configuration
    - ``cli``: Delegates to external CLI tools (claude, codex)
    - ``custom``: User-defined custom command

    Raises:
        LLMError: If the configuration is insufficient or the mode is unknown.
    """
    resolved_config = _apply_platform_runtime(config)

    if resolved_config.mode == "builtin":
        return _create_builtin(resolved_config)

    if resolved_config.mode == "ollama":
        return _create_builtin(resolved_config)

    if resolved_config.mode == "cli":
        return _create_cli(resolved_config)

    if resolved_config.mode == "custom":
        return _create_custom(resolved_config)

    raise LLMError(f"Unsupported LLM mode: {resolved_config.mode!r}")


def _apply_platform_runtime(config: LLMConfig) -> LLMConfig:
    platform = PlatformRuntimeConfig(
        url=config.platform_url,
        api_key=config.platform_api_key,
        mode=config.platform_mode,
        user_id=config.platform_user_id,
        project_id=config.platform_project_id,
        key_hash=config.platform_key_hash,
    )
    configure_platform_environment(platform)

    resolved_mode = config.resolved_platform_mode
    if resolved_mode == "disabled":
        return config

    if resolved_mode == "byok":
        return config

    if resolved_mode != "platform":
        raise LLMError("Invalid platform.mode value. Expected one of: platform, byok, disabled.")

    if config.mode not in {"builtin", "ollama"}:
        raise LLMError("platform.mode=platform requires llm.mode to be 'builtin' or 'ollama'.")

    if not config.platform_url:
        raise LLMError("platform.mode=platform requires platform.url to be configured.")

    if not config.platform_api_key:
        raise LLMError("platform.mode=platform requires platform.api_key to be configured.")

    return replace(
        config,
        base_url=build_llm_proxy_base_url(config.platform_url),
        api_key=config.platform_api_key,
    )


def _create_builtin(config: LLMConfig) -> BuiltinLLM:
    """Create a ``BuiltinLLM`` from config."""
    model = config.model
    if not model:
        raise LLMError("No LLM model configured. Set 'llm.model' in .nit.yml or NIT_LLM_MODEL.")

    return BuiltinLLM(
        model=model,
        provider=config.provider or None,
        api_key=config.api_key or None,
        base_url=config.base_url or None,
        retry=RetryConfig(max_retries=config.max_retries),
        rate_limit=RateLimitConfig(requests_per_minute=config.requests_per_minute),
    )


def _create_cli(config: LLMConfig) -> LLMEngine:
    """Create a CLI tool adapter (Claude Code or Codex) from config."""
    model = config.model
    if not model:
        raise LLMError("No LLM model configured. Set 'llm.model' in .nit.yml or NIT_LLM_MODEL.")

    cli_command = config.cli_command
    if not cli_command:
        raise LLMError(
            "No CLI command configured for 'cli' mode. "
            "Set 'llm.cli_command' in .nit.yml (e.g., 'claude' or 'codex')."
        )

    tool_config = CLIToolConfig(
        command=cli_command,
        model=model,
        timeout=config.cli_timeout,
        extra_args=config.cli_extra_args or [],
    )

    # Choose adapter based on command name
    cmd_lower = cli_command.lower()
    if "claude" in cmd_lower:
        return ClaudeCodeAdapter(tool_config)
    if "codex" in cmd_lower:
        return CodexAdapter(tool_config)

    # Default to Claude Code adapter for unknown CLI tools
    return ClaudeCodeAdapter(tool_config)


def _create_custom(config: LLMConfig) -> CustomCommandAdapter:
    """Create a custom command adapter from config."""
    model = config.model
    if not model:
        raise LLMError("No LLM model configured. Set 'llm.model' in .nit.yml or NIT_LLM_MODEL.")

    cli_command = config.cli_command
    if not cli_command:
        raise LLMError(
            "No CLI command configured for 'custom' mode. "
            "Set 'llm.cli_command' in .nit.yml with template placeholders."
        )

    tool_config = CLIToolConfig(
        command=cli_command,
        model=model,
        timeout=config.cli_timeout,
        extra_args=config.cli_extra_args or [],
    )

    return CustomCommandAdapter(tool_config)
