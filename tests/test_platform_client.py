"""Tests for platform integration helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nit.utils.platform_client import (
    PlatformClientError,
    PlatformRuntimeConfig,
    build_llm_proxy_base_url,
    build_reports_url,
    post_platform_report,
)


def test_build_llm_proxy_base_url_default_path() -> None:
    assert (
        build_llm_proxy_base_url("https://api.getnit.dev")
        == "https://api.getnit.dev/api/v1/llm-proxy"
    )


def test_build_reports_url_handles_api_base_path() -> None:
    assert (
        build_reports_url("https://api.getnit.dev/api") == "https://api.getnit.dev/api/v1/reports"
    )


def test_post_platform_report_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_post(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(status_code=401, text="Unauthorized")

    monkeypatch.setattr("nit.utils.platform_client.requests.post", _fake_post)

    with pytest.raises(PlatformClientError, match="HTTP 401"):
        post_platform_report(
            PlatformRuntimeConfig(url="https://api.getnit.dev", api_key="nit_key"),
            {"runMode": "hunt"},
        )
