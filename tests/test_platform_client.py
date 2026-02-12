"""Tests for platform integration helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
import requests as req_mod

from nit.llm.usage_callback import BatchedUsageReporter, UsageReporterConfig
from nit.utils.platform_client import (
    PlatformClientError,
    PlatformRuntimeConfig,
    build_bugs_url,
    build_llm_proxy_base_url,
    build_memory_url,
    build_reports_url,
    build_usage_url,
    post_platform_bug,
    post_platform_report,
    pull_platform_memory,
    push_platform_memory,
)

# ── URL builders ──────────────────────────────────────────────────


def test_build_llm_proxy_base_url_default_path() -> None:
    assert (
        build_llm_proxy_base_url("https://platform.getnit.dev")
        == "https://platform.getnit.dev/api/v1/llm-proxy"
    )


def test_build_reports_url_handles_api_base_path() -> None:
    assert (
        build_reports_url("https://platform.getnit.dev/api")
        == "https://platform.getnit.dev/api/v1/reports"
    )


def test_build_bugs_url_default_path() -> None:
    assert (
        build_bugs_url("https://platform.getnit.dev") == "https://platform.getnit.dev/api/v1/bugs"
    )


def test_build_bugs_url_handles_api_base_path() -> None:
    assert (
        build_bugs_url("https://platform.getnit.dev/api")
        == "https://platform.getnit.dev/api/v1/bugs"
    )


def test_build_usage_url_default_path() -> None:
    assert (
        build_usage_url("https://platform.getnit.dev") == "https://platform.getnit.dev/api/v1/usage"
    )


def test_build_usage_url_handles_api_base_path() -> None:
    assert (
        build_usage_url("https://platform.getnit.dev/api")
        == "https://platform.getnit.dev/api/v1/usage"
    )


# ── post_platform_report ─────────────────────────────────────────


def test_post_platform_report_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_post(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(status_code=401, text="Unauthorized")

    monkeypatch.setattr("nit.utils.platform_client.requests.post", _fake_post)

    with pytest.raises(PlatformClientError, match="HTTP 401"):
        post_platform_report(
            PlatformRuntimeConfig(url="https://platform.getnit.dev", api_key="nit_key"),
            {"runMode": "pick"},
        )


def test_post_platform_report_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_post(url: str, **kwargs: Any) -> SimpleNamespace:
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        return SimpleNamespace(
            status_code=201,
            text=json.dumps({"reportId": "r-1"}),
            json=lambda: {"reportId": "r-1"},
        )

    monkeypatch.setattr("nit.utils.platform_client.requests.post", _fake_post)

    result = post_platform_report(
        PlatformRuntimeConfig(url="https://platform.getnit.dev", api_key="nit_key"),
        {"runMode": "pick", "testsPassed": 5},
    )

    assert result == {"reportId": "r-1"}
    assert captured["url"] == "https://platform.getnit.dev/api/v1/reports"
    assert captured["headers"]["Authorization"] == "Bearer nit_key"
    assert captured["json"]["runMode"] == "pick"


# ── post_platform_bug ────────────────────────────────────────────


def test_post_platform_bug_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_post(url: str, **kwargs: Any) -> SimpleNamespace:
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        return SimpleNamespace(
            status_code=201,
            text=json.dumps({"bugId": "bug-1"}),
            json=lambda: {"bugId": "bug-1"},
        )

    monkeypatch.setattr("nit.utils.platform_client.requests.post", _fake_post)

    result = post_platform_bug(
        PlatformRuntimeConfig(url="https://platform.getnit.dev", api_key="nit_key"),
        {
            "filePath": "src/app.py",
            "description": "Null dereference",
            "severity": "high",
            "status": "open",
        },
    )

    assert result == {"bugId": "bug-1"}
    assert captured["url"] == "https://platform.getnit.dev/api/v1/bugs"
    assert captured["headers"]["Authorization"] == "Bearer nit_key"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["json"]["filePath"] == "src/app.py"
    assert captured["json"]["description"] == "Null dereference"
    assert captured["json"]["severity"] == "high"
    assert captured["json"]["status"] == "open"


def test_post_platform_bug_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_post(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(status_code=403, text="Project access denied")

    monkeypatch.setattr("nit.utils.platform_client.requests.post", _fake_post)

    with pytest.raises(PlatformClientError, match="HTTP 403"):
        post_platform_bug(
            PlatformRuntimeConfig(url="https://platform.getnit.dev", api_key="nit_key"),
            {"filePath": "f.py", "description": "bug"},
        )


def test_post_platform_bug_requires_url_and_key() -> None:
    with pytest.raises(PlatformClientError, match="required"):
        post_platform_bug(PlatformRuntimeConfig(), {"filePath": "f.py"})


# ── Usage URL in batched reporter ────────────────────────────────


def test_batched_reporter_posts_to_usage_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the batched usage reporter posts to /api/v1/usage."""
    captured: dict[str, Any] = {}

    def _fake_post(url: str, **kwargs: Any) -> SimpleNamespace:
        captured["url"] = url
        return SimpleNamespace(status_code=200, text="ok")

    monkeypatch.setattr(req_mod, "post", _fake_post)

    monkeypatch.setenv("NIT_PLATFORM_URL", "https://platform.getnit.dev")
    monkeypatch.setenv("NIT_PLATFORM_INGEST_TOKEN", "test-ingest-token")
    monkeypatch.setenv("NIT_PLATFORM_USER_ID", "u")
    config = UsageReporterConfig.from_env()
    reporter = BatchedUsageReporter(config)
    reporter._post_batch([{"model": "gpt-4o", "provider": "openai"}])

    assert captured["url"] == "https://platform.getnit.dev/api/v1/usage"


# ── Memory URL builder ──────────────────────────────────────────


def test_build_memory_url_default_path() -> None:
    assert (
        build_memory_url("https://platform.getnit.dev")
        == "https://platform.getnit.dev/api/v1/memory"
    )


def test_build_memory_url_handles_api_base_path() -> None:
    assert (
        build_memory_url("https://platform.getnit.dev/api")
        == "https://platform.getnit.dev/api/v1/memory"
    )


# ── push_platform_memory ────────────────────────────────────────


def test_push_platform_memory_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_post(url: str, **kwargs: Any) -> SimpleNamespace:
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        return SimpleNamespace(
            status_code=201,
            text=json.dumps({"version": 3, "merged": True}),
            json=lambda: {"version": 3, "merged": True},
        )

    monkeypatch.setattr("nit.utils.platform_client.requests.post", _fake_post)

    result = push_platform_memory(
        PlatformRuntimeConfig(url="https://platform.getnit.dev", api_key="nit_key"),
        {"baseVersion": 0, "source": "local", "global": {"conventions": {}}},
    )

    assert result == {"version": 3, "merged": True}
    assert captured["url"] == "https://platform.getnit.dev/api/v1/memory"
    assert captured["headers"]["Authorization"] == "Bearer nit_key"
    assert captured["json"]["source"] == "local"


def test_push_platform_memory_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_post(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(status_code=500, text="Internal Server Error")

    monkeypatch.setattr("nit.utils.platform_client.requests.post", _fake_post)

    with pytest.raises(PlatformClientError, match="HTTP 500"):
        push_platform_memory(
            PlatformRuntimeConfig(url="https://platform.getnit.dev", api_key="nit_key"),
            {"baseVersion": 0, "source": "local"},
        )


def test_push_platform_memory_requires_url_and_key() -> None:
    with pytest.raises(PlatformClientError, match="required"):
        push_platform_memory(PlatformRuntimeConfig(), {"baseVersion": 0})


# ── pull_platform_memory ────────────────────────────────────────


def test_pull_platform_memory_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_get(url: str, **kwargs: Any) -> SimpleNamespace:
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["params"] = kwargs["params"]
        response_data = {
            "version": 5,
            "global": {"conventions": {"lang": "python"}, "knownPatterns": []},
            "packages": {},
        }
        return SimpleNamespace(
            status_code=200,
            text=json.dumps(response_data),
            json=lambda: response_data,
        )

    monkeypatch.setattr("nit.utils.platform_client.requests.get", _fake_get)

    result = pull_platform_memory(
        PlatformRuntimeConfig(url="https://platform.getnit.dev", api_key="nit_key"),
        "proj-123",
    )

    assert result["version"] == 5
    assert result["global"]["conventions"]["lang"] == "python"
    assert captured["url"] == "https://platform.getnit.dev/api/v1/memory"
    assert captured["headers"]["Authorization"] == "Bearer nit_key"
    assert captured["params"]["projectId"] == "proj-123"


def test_pull_platform_memory_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_get(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(status_code=404, text="Not Found")

    monkeypatch.setattr("nit.utils.platform_client.requests.get", _fake_get)

    with pytest.raises(PlatformClientError, match="HTTP 404"):
        pull_platform_memory(
            PlatformRuntimeConfig(url="https://platform.getnit.dev", api_key="nit_key"),
            "proj-unknown",
        )


def test_pull_platform_memory_requires_url_and_key() -> None:
    with pytest.raises(PlatformClientError, match="required"):
        pull_platform_memory(PlatformRuntimeConfig(), "proj-123")
