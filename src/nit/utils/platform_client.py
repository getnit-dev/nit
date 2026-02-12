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
_BUGS_PATH = "/api/v1/bugs"
_USAGE_PATH = "/api/v1/usage"
_MEMORY_PATH = "/api/v1/memory"
_VALID_PLATFORM_MODES = {"platform", "byok", "disabled"}
_HTTP_SUCCESS_MIN = 200
_HTTP_SUCCESS_MAX = 300

# Module-level store for platform config — avoids leaking API keys via os.environ.
_platform_config_store: dict[str, str] = {}


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


def build_bugs_url(platform_url: str) -> str:
    """Build the platform bugs API URL."""
    return _join_platform_path(platform_url, _BUGS_PATH)


def build_usage_url(platform_url: str) -> str:
    """Build the platform usage API URL."""
    return _join_platform_path(platform_url, _USAGE_PATH)


def build_memory_url(platform_url: str) -> str:
    """Build the platform memory API URL."""
    return _join_platform_path(platform_url, _MEMORY_PATH)


def configure_platform_environment(config: PlatformRuntimeConfig) -> None:
    """Store platform config for usage reporting.

    Non-secret values are set as environment variables for external tool
    compatibility.  The API key is kept in an in-process store to avoid
    leaking through child processes, crash dumps, or ``/proc/*/environ``.
    """
    # Non-secret values can live in env vars (used by external tools)
    non_secret = {
        "NIT_PLATFORM_URL": normalize_platform_url(config.url),
        "NIT_PLATFORM_USER_ID": config.user_id.strip(),
        "NIT_PLATFORM_PROJECT_ID": config.project_id.strip(),
        "NIT_PLATFORM_KEY_HASH": config.key_hash.strip(),
    }
    for env_name, value in non_secret.items():
        if value:
            os.environ[env_name] = value

    # Secret value — module-level store only
    api_key = config.api_key.strip()
    if api_key:
        _platform_config_store["NIT_PLATFORM_API_KEY"] = api_key


def get_platform_api_key() -> str:
    """Retrieve the platform API key from the in-process store (preferred) or env."""
    return (
        _platform_config_store.get("NIT_PLATFORM_API_KEY", "")
        or os.environ.get("NIT_PLATFORM_API_KEY", "").strip()
    )


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


def post_platform_bug(
    config: PlatformRuntimeConfig,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Upload a single bug payload to the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for bug upload.")

    response = requests.post(
        build_bugs_url(platform_url),
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
            f"Platform bug upload failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}


def push_platform_memory(
    config: PlatformRuntimeConfig,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Push memory payload to the platform API for server-side merge."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for memory sync.")

    response = requests.post(
        build_memory_url(platform_url),
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
            f"Platform memory push failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}


def pull_platform_memory(
    config: PlatformRuntimeConfig,
    project_id: str,
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Pull merged memory from the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for memory sync.")

    url = build_memory_url(platform_url)
    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
        },
        params={"projectId": project_id},
        timeout=timeout_seconds,
    )
    if response.status_code < _HTTP_SUCCESS_MIN or response.status_code >= _HTTP_SUCCESS_MAX:
        message = response.text.strip()[:300]
        raise PlatformClientError(
            f"Platform memory pull failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}
