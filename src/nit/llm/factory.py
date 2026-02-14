"""Factory for creating an ``LLMEngine`` from configuration."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from nit.llm.builtin import BuiltinLLM, BuiltinLLMConfig, RateLimitConfig, RetryConfig
from nit.llm.cli_adapter import (
    ClaudeCodeAdapter,
    CLIToolConfig,
    CodexAdapter,
    CustomCommandAdapter,
)
from nit.llm.engine import LLMEngine, LLMError
from nit.llm.tracked_engine import TrackedLLMEngine
from nit.memory.prompt_store import get_prompt_recorder
from nit.utils.platform_client import (
    PlatformRuntimeConfig,
    configure_platform_environment,
)

if TYPE_CHECKING:
    from pathlib import Path

    from nit.llm.config import LLMConfig


def create_engine(
    config: LLMConfig,
    *,
    project_root: Path | None = None,
    enable_tracking: bool | None = None,
) -> LLMEngine:
    """Instantiate the correct ``LLMEngine`` from an ``LLMConfig``.

    Supports modes:
    - ``builtin``: LiteLLM-based engine for API providers
    - ``ollama``: LiteLLM with Ollama configuration
    - ``cli``: Delegates to external CLI tools (claude, codex)
    - ``custom``: User-defined custom command

    Args:
        config: LLM configuration.
        project_root: Project root for prompt tracking storage.
        enable_tracking: Explicitly enable/disable prompt tracking.
            When ``None``, checks ``NIT_PROMPT_TRACKING`` env var (default: enabled).

    Raises:
        LLMError: If the configuration is insufficient or the mode is unknown.
    """
    resolved_config = _apply_platform_runtime(config)

    engine: LLMEngine

    if resolved_config.mode in {"builtin", "ollama"}:
        engine = _create_builtin(resolved_config)
    elif resolved_config.mode == "cli":
        engine = _create_cli(resolved_config)
    elif resolved_config.mode == "custom":
        engine = _create_custom(resolved_config)
    else:
        raise LLMError(f"Unsupported LLM mode: {resolved_config.mode!r}")

    if _tracking_enabled(override=enable_tracking) and project_root is not None:
        recorder = get_prompt_recorder(project_root)
        engine = TrackedLLMEngine(engine, recorder)

    return engine


def _tracking_enabled(*, override: bool | None) -> bool:
    """Determine whether prompt tracking should be enabled."""
    if override is not None:
        return override
    env_val = os.environ.get("NIT_PROMPT_TRACKING", "").strip().lower()
    return env_val not in {"0", "false", "no", "off"}


def _apply_platform_runtime(config: LLMConfig) -> LLMConfig:
    platform = PlatformRuntimeConfig(
        url=config.platform_url,
        api_key=config.platform_api_key,
        mode=config.platform_mode,
        project_id=config.platform_project_id,
        key_hash=config.platform_key_hash,
    )
    configure_platform_environment(platform)

    return config


def _create_builtin(config: LLMConfig) -> BuiltinLLM:
    """Create a ``BuiltinLLM`` from config."""
    model = config.model
    if not model:
        raise LLMError("No LLM model configured. Set 'llm.model' in .nit.yml or NIT_LLM_MODEL.")

    return BuiltinLLM(
        BuiltinLLMConfig(
            model=model,
            provider=config.provider or None,
            api_key=config.api_key or None,
            base_url=config.base_url or None,
            retry=RetryConfig(max_retries=config.max_retries),
            rate_limit=RateLimitConfig(requests_per_minute=config.requests_per_minute),
        )
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
