"""Platform integration helpers for runtime routing and API uploads."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

import requests

if TYPE_CHECKING:
    from collections.abc import Mapping

_LLM_PROXY_PATH = "/api/v1/llm-proxy"
_REPORTS_PATH = "/api/v1/reports"
_VALID_PLATFORM_MODES = {"platform", "byok", "disabled"}
_HTTP_SUCCESS_MIN = 200
_HTTP_SUCCESS_MAX = 300


class PlatformClientError(RuntimeError):
    """Raised when a platform API request fails."""


@dataclass
class PlatformRuntimeConfig:
    """Resolved platform settings used by CLI and LLM runtime."""

    url: str = ""
    api_key: str = ""
    mode: str = ""
    user_id: str = ""
    project_id: str = ""
    key_hash: str = ""

    @property
    def normalized_mode(self) -> str:
        raw = self.mode.strip().lower()
        if raw in _VALID_PLATFORM_MODES:
            return raw
        if self.url and self.api_key:
            return "platform"
        return "disabled"


def normalize_platform_url(url: str) -> str:
    """Normalize and trim a configured platform URL."""
    return url.strip().rstrip("/")


def _join_platform_path(base_url: str, endpoint_path: str) -> str:
    normalized_base = normalize_platform_url(base_url)
    split = urlsplit(normalized_base)
    base_path = split.path.rstrip("/")
    target_path = endpoint_path

    if base_path.endswith("/api/v1") and endpoint_path.startswith("/api/v1/"):
        target_path = endpoint_path[len("/api/v1") :]
    elif base_path.endswith("/api") and endpoint_path.startswith("/api/"):
        target_path = endpoint_path[len("/api") :]
    elif base_path.endswith("/v1") and endpoint_path.startswith("/v1/"):
        target_path = endpoint_path[len("/v1") :]

    joined_path = f"{base_path}{target_path}" if base_path else target_path
    return urlunsplit((split.scheme, split.netloc, joined_path, split.query, split.fragment))


def build_llm_proxy_base_url(platform_url: str) -> str:
    """Build the OpenAI-compatible proxy base URL for platform key mode."""
    return _join_platform_path(platform_url, _LLM_PROXY_PATH)


def build_reports_url(platform_url: str) -> str:
    """Build the platform reports API URL."""
    return _join_platform_path(platform_url, _REPORTS_PATH)


def configure_platform_environment(config: PlatformRuntimeConfig) -> None:
    """Export platform config into environment variables used by usage reporting."""
    values = {
        "NIT_PLATFORM_URL": normalize_platform_url(config.url),
        "NIT_PLATFORM_API_KEY": config.api_key.strip(),
        "NIT_PLATFORM_USER_ID": config.user_id.strip(),
        "NIT_PLATFORM_PROJECT_ID": config.project_id.strip(),
        "NIT_PLATFORM_KEY_HASH": config.key_hash.strip(),
    }

    for env_name, value in values.items():
        if value:
            os.environ[env_name] = value


def post_platform_report(
    config: PlatformRuntimeConfig,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Upload a report payload to the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for report upload.")

    response = requests.post(
        build_reports_url(platform_url),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=dict(payload),
        timeout=timeout_seconds,
    )
    if response.status_code < _HTTP_SUCCESS_MIN or response.status_code >= _HTTP_SUCCESS_MAX:
        message = response.text.strip()[:300]
        raise PlatformClientError(
            f"Platform report upload failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}
