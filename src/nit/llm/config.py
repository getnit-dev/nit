"""LLM configuration parsing from ``.nit.yml``."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_ENV_VAR_RE = re.compile(r"\$\{(\w+)}")


def _resolve_env_vars(value: str) -> str:
    """Replace ``${VAR_NAME}`` placeholders with environment variable values."""

    def _replace(match: re.Match[str]) -> str:
        var = match.group(1)
        return os.environ.get(var, "")

    return _ENV_VAR_RE.sub(_replace, value)


@dataclass
class LLMConfig:
    """Parsed LLM configuration from ``.nit.yml``."""

    provider: str = "openai"
    """LLM provider name (``openai``, ``anthropic``, ``ollama``, etc.)."""

    model: str = ""
    """Model identifier (e.g. ``gpt-4o``, ``claude-sonnet-4-5-20250514``)."""

    api_key: str = ""
    """API key for the provider (supports ``${ENV_VAR}`` expansion)."""

    base_url: str = ""
    """Custom base URL (useful for Ollama or proxied endpoints)."""

    mode: str = "builtin"
    """Execution mode: ``builtin`` (LiteLLM), ``cli``, ``custom``, or ``ollama``."""

    temperature: float = 0.2
    """Default sampling temperature."""

    max_tokens: int = 4096
    """Default maximum tokens to generate."""

    requests_per_minute: int = 60
    """Rate limit: maximum requests per minute."""

    max_retries: int = 3
    """Maximum number of retry attempts on transient failures."""

    # CLI mode settings
    cli_command: str = ""
    """CLI command to execute (e.g., 'claude', 'codex', or custom script path)."""

    cli_timeout: int = 300
    """Timeout in seconds for CLI command execution."""

    cli_extra_args: list[str] | None = None
    """Additional command-line arguments to pass to the CLI tool."""

    platform_url: str = ""
    """Platform base URL (e.g. ``https://api.getnit.dev``)."""

    platform_api_key: str = ""
    """Platform virtual key used for proxy mode and usage ingestion."""

    platform_mode: str = ""
    """Platform integration mode: ``platform`` | ``byok`` | ``disabled``."""

    platform_user_id: str = ""
    """Optional platform user ID for usage metadata."""

    platform_project_id: str = ""
    """Optional platform project ID for usage metadata/report uploads."""

    platform_key_hash: str = ""
    """Optional key hash override for usage metadata."""

    @property
    def resolved_platform_mode(self) -> str:
        """Resolved platform mode with sane defaults."""
        mode = self.platform_mode.strip().lower()
        if mode in {"platform", "byok", "disabled"}:
            return mode
        if self.platform_url and self.platform_api_key:
            return "platform"
        return "disabled"

    @property
    def is_configured(self) -> bool:
        """Return ``True`` when enough info is present for generation."""
        if self.mode == "ollama":
            return bool(self.model)
        if self.mode in ("cli", "custom"):
            return bool(self.model and self.cli_command)
        if self.resolved_platform_mode == "platform":
            return bool(self.model and self.platform_url and self.platform_api_key)
        return bool(self.model and self.api_key)


def load_llm_config(root: str | Path) -> LLMConfig:
    """Load and return the ``llm`` section from ``.nit.yml``.

    Falls back to environment variables (``NIT_LLM_API_KEY``,
    ``NIT_LLM_MODEL``, ``NIT_LLM_PROVIDER``) when the YAML file is missing
    or lacks the ``llm`` section.
    """
    root_path = Path(root)
    nit_yml = root_path / ".nit.yml"

    raw: dict[str, Any] = {}
    platform_raw: dict[str, Any] = {}
    if nit_yml.is_file():
        text = nit_yml.read_text(encoding="utf-8")
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict):
            llm_section = parsed.get("llm")
            if isinstance(llm_section, dict):
                raw = llm_section
            platform_section = parsed.get("platform")
            if isinstance(platform_section, dict):
                platform_raw = platform_section

    return _build_config(raw, platform_raw)


def _build_config(raw: dict[str, Any], platform_raw: dict[str, Any]) -> LLMConfig:
    """Build an ``LLMConfig`` from a raw dict, applying env var resolution."""
    provider = str(raw.get("provider", os.environ.get("NIT_LLM_PROVIDER", "openai")))
    model = str(raw.get("model", os.environ.get("NIT_LLM_MODEL", "")))
    api_key = str(raw.get("api_key", os.environ.get("NIT_LLM_API_KEY", "")))
    base_url = str(raw.get("base_url", os.environ.get("NIT_LLM_BASE_URL", "")))
    mode = str(raw.get("mode", "builtin"))

    platform_url = str(platform_raw.get("url", os.environ.get("NIT_PLATFORM_URL", "")))
    platform_api_key = str(platform_raw.get("api_key", os.environ.get("NIT_PLATFORM_API_KEY", "")))
    platform_mode = str(platform_raw.get("mode", os.environ.get("NIT_PLATFORM_MODE", "")))
    platform_user_id = str(platform_raw.get("user_id", os.environ.get("NIT_PLATFORM_USER_ID", "")))
    platform_project_id = str(
        platform_raw.get("project_id", os.environ.get("NIT_PLATFORM_PROJECT_ID", ""))
    )
    platform_key_hash = str(
        platform_raw.get("key_hash", os.environ.get("NIT_PLATFORM_KEY_HASH", ""))
    )

    # Resolve ${ENV_VAR} placeholders
    api_key = _resolve_env_vars(api_key)
    base_url = _resolve_env_vars(base_url)
    platform_url = _resolve_env_vars(platform_url)
    platform_api_key = _resolve_env_vars(platform_api_key)
    platform_user_id = _resolve_env_vars(platform_user_id)
    platform_project_id = _resolve_env_vars(platform_project_id)
    platform_key_hash = _resolve_env_vars(platform_key_hash)

    # Parse CLI mode settings
    cli_command = str(raw.get("cli_command", ""))
    cli_timeout = int(raw.get("cli_timeout", 300))
    cli_extra_args_raw = raw.get("cli_extra_args")
    cli_extra_args = None
    if isinstance(cli_extra_args_raw, list):
        cli_extra_args = [str(arg) for arg in cli_extra_args_raw]

    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        mode=mode,
        temperature=float(raw.get("temperature", 0.2)),
        max_tokens=int(raw.get("max_tokens", 4096)),
        requests_per_minute=int(raw.get("requests_per_minute", 60)),
        max_retries=int(raw.get("max_retries", 3)),
        cli_command=cli_command,
        cli_timeout=cli_timeout,
        cli_extra_args=cli_extra_args,
        platform_url=platform_url,
        platform_api_key=platform_api_key,
        platform_mode=platform_mode,
        platform_user_id=platform_user_id,
        platform_project_id=platform_project_id,
        platform_key_hash=platform_key_hash,
    )
