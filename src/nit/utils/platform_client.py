"""Platform integration helpers for runtime routing and API uploads."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

import requests

if TYPE_CHECKING:
    from collections.abc import Mapping

_REPORTS_PATH = "/api/v1/reports"
_BUGS_PATH = "/api/v1/bugs"
_USAGE_PATH = "/api/v1/usage"
_MEMORY_PATH = "/api/v1/memory"
_DRIFT_PATH = "/api/v1/drift"
_SECURITY_PATH = "/api/v1/security"
_RISK_PATH = "/api/v1/risk"
_COVERAGE_GAPS_PATH = "/api/v1/coverage-gaps"
_FIXES_PATH = "/api/v1/fixes"
_ROUTES_PATH = "/api/v1/routes"
_DOC_COVERAGE_PATH = "/api/v1/doc-coverage"
_PROMPTS_PATH = "/api/v1/prompts"
_VALID_PLATFORM_MODES = {"byok", "disabled"}
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
            return "byok"
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


def build_drift_url(platform_url: str) -> str:
    """Build the platform drift API URL."""
    return _join_platform_path(platform_url, _DRIFT_PATH)


def build_security_url(platform_url: str) -> str:
    """Build the platform security API URL."""
    return _join_platform_path(platform_url, _SECURITY_PATH)


def build_risk_url(platform_url: str) -> str:
    """Build the platform risk API URL."""
    return _join_platform_path(platform_url, _RISK_PATH)


def build_coverage_gaps_url(platform_url: str) -> str:
    """Build the platform coverage-gaps API URL."""
    return _join_platform_path(platform_url, _COVERAGE_GAPS_PATH)


def build_fixes_url(platform_url: str) -> str:
    """Build the platform fixes API URL."""
    return _join_platform_path(platform_url, _FIXES_PATH)


def build_routes_url(platform_url: str) -> str:
    """Build the platform routes API URL."""
    return _join_platform_path(platform_url, _ROUTES_PATH)


def build_doc_coverage_url(platform_url: str) -> str:
    """Build the platform doc-coverage API URL."""
    return _join_platform_path(platform_url, _DOC_COVERAGE_PATH)


def configure_platform_environment(config: PlatformRuntimeConfig) -> None:
    """Store platform config for usage reporting.

    Non-secret values are set as environment variables for external tool
    compatibility.  The API key is kept in an in-process store to avoid
    leaking through child processes, crash dumps, or ``/proc/*/environ``.
    """
    # Non-secret values can live in env vars (used by external tools)
    non_secret = {
        "NIT_PLATFORM_URL": normalize_platform_url(config.url),
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


def post_platform_drift(
    config: PlatformRuntimeConfig,
    results: list[dict[str, Any]],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Upload drift test results to the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for drift upload.")

    response = requests.post(
        build_drift_url(platform_url),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=results,
        timeout=timeout_seconds,
    )
    if response.status_code < _HTTP_SUCCESS_MIN or response.status_code >= _HTTP_SUCCESS_MAX:
        message = response.text.strip()[:300]
        raise PlatformClientError(
            f"Platform drift upload failed (HTTP {response.status_code}): {message}"
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


def post_platform_security(
    config: PlatformRuntimeConfig,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Upload a security payload to the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for security upload.")

    response = requests.post(
        build_security_url(platform_url),
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
            f"Platform security upload failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}


def post_platform_risk(
    config: PlatformRuntimeConfig,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Upload a risk payload to the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for risk upload.")

    response = requests.post(
        build_risk_url(platform_url),
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
            f"Platform risk upload failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}


def post_platform_coverage_gaps(
    config: PlatformRuntimeConfig,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Upload a coverage-gaps payload to the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for coverage-gaps upload.")

    response = requests.post(
        build_coverage_gaps_url(platform_url),
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
            f"Platform coverage-gaps upload failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}


def post_platform_fix(
    config: PlatformRuntimeConfig,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Upload a fix payload to the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for fix upload.")

    response = requests.post(
        build_fixes_url(platform_url),
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
            f"Platform fix upload failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}


def post_platform_routes(
    config: PlatformRuntimeConfig,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Upload a routes payload to the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for routes upload.")

    response = requests.post(
        build_routes_url(platform_url),
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
            f"Platform routes upload failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}


def post_platform_doc_coverage(
    config: PlatformRuntimeConfig,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Upload a doc-coverage payload to the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for doc-coverage upload.")

    response = requests.post(
        build_doc_coverage_url(platform_url),
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
            f"Platform doc-coverage upload failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}


def build_prompts_url(platform_url: str) -> str:
    """Build the platform prompts API URL."""
    return _join_platform_path(platform_url, _PROMPTS_PATH)


def post_platform_prompts(
    config: PlatformRuntimeConfig,
    records: list[dict[str, Any]],
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Upload prompt records to the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for prompts upload.")

    response = requests.post(
        build_prompts_url(platform_url),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"records": records},
        timeout=timeout_seconds,
    )
    if response.status_code < _HTTP_SUCCESS_MIN or response.status_code >= _HTTP_SUCCESS_MAX:
        message = response.text.strip()[:300]
        raise PlatformClientError(
            f"Platform prompts upload failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {}


def get_platform_prompts(
    config: PlatformRuntimeConfig,
    *,
    limit: int = 50,
    model: str | None = None,
    template: str | None = None,
    timeout_seconds: float = 15.0,
) -> list[dict[str, Any]]:
    """Query prompt records from the platform API."""
    platform_url = normalize_platform_url(config.url)
    api_key = config.api_key.strip()
    if not platform_url or not api_key:
        raise PlatformClientError("Platform URL and API key are required for prompts query.")

    params: dict[str, str | int] = {"limit": limit}
    if model:
        params["model"] = model
    if template:
        params["template"] = template

    response = requests.get(
        build_prompts_url(platform_url),
        headers={"Authorization": f"Bearer {api_key}"},
        params=params,
        timeout=timeout_seconds,
    )
    if response.status_code < _HTTP_SUCCESS_MIN or response.status_code >= _HTTP_SUCCESS_MAX:
        message = response.text.strip()[:300]
        raise PlatformClientError(
            f"Platform prompts query failed (HTTP {response.status_code}): {message}"
        )

    try:
        body = response.json()
    except ValueError:
        return []

    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        records = body.get("records", [])
        return records if isinstance(records, list) else []
    return []
