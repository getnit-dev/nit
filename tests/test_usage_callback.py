"""Tests for LiteLLM usage callback + batched reporter."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from nit.llm import usage_callback


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset reporter/callback singleton state between tests."""
    usage_callback._SINGLETONS.reporter = None
    usage_callback._SINGLETONS.callback = None

    monkeypatch.setenv("NIT_PLATFORM_URL", "https://platform.example")
    monkeypatch.setenv("NIT_PLATFORM_INGEST_TOKEN", "ingest-token")
    monkeypatch.setenv("NIT_PLATFORM_USER_ID", "user-123")
    monkeypatch.setenv("NIT_PLATFORM_PROJECT_ID", "project-456")
    monkeypatch.setenv("NIT_USAGE_BATCH_SIZE", "1")
    monkeypatch.setenv("NIT_USAGE_FLUSH_INTERVAL_SECONDS", "999")


def test_report_cli_usage_event_posts_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(
        url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float
    ) -> Any:
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return SimpleNamespace(status_code=200, text="ok")

    monkeypatch.setattr(requests, "post", _fake_post)

    usage_callback.report_cli_usage_event(
        provider="anthropic",
        model="claude-sonnet-4-5",
        prompt_tokens=120,
        completion_tokens=80,
        cost_usd=0.034,
        cache_hit=False,
        source="cli",
        duration_ms=410,
        metadata={"nit_cli_command": "claude --print"},
    )

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert "events" in payload

    event = payload["events"][0]
    assert event["userId"] == "user-123"
    assert event["projectId"] == "project-456"
    assert event["provider"] == "anthropic"
    assert event["model"] == "claude-sonnet-4-5"
    assert event["promptTokens"] == 120
    assert event["completionTokens"] == 80
    assert event["costUsd"] == pytest.approx(0.034)
    assert event["source"] == "cli"


def test_callback_extracts_litellm_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(
        url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float
    ) -> Any:
        captured["json"] = json
        return SimpleNamespace(status_code=200, text="ok")

    monkeypatch.setattr(requests, "post", _fake_post)

    callback = usage_callback.NitUsageCallback()

    response_obj = SimpleNamespace(
        model="anthropic/claude-sonnet-4-5",
        usage=SimpleNamespace(prompt_tokens=45, completion_tokens=30),
        _hidden_params={"cache_hit": True},
    )

    kwargs = {
        "model": "anthropic/claude-sonnet-4-5",
        "response_cost": 0.016,
        "cache_hit": True,
        "litellm_params": {
            "metadata": {
                "nit_user_id": "user-callback",
                "nit_project_id": "project-callback",
                "nit_usage_source": "byok",
                "nit_usage_emit": True,
            }
        },
    }

    start = datetime(2026, 2, 10, 10, 30, 0, tzinfo=UTC)
    end = datetime(2026, 2, 10, 10, 30, 1, tzinfo=UTC)
    callback.log_success_event(kwargs, response_obj, start, end)

    payload = captured["json"]
    assert isinstance(payload, dict)
    event = payload["events"][0]

    assert event["userId"] == "user-callback"
    assert event["projectId"] == "project-callback"
    assert event["provider"] == "anthropic"
    assert event["promptTokens"] == 45
    assert event["completionTokens"] == 30
    assert event["costUsd"] == pytest.approx(0.016)
    assert event["cacheHit"] is True
    assert event["source"] == "byok"


def test_callback_respects_emit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    posted = {"count": 0}

    def _fake_post(
        url: str, *, headers: dict[str, str], json: dict[str, object], timeout: float
    ) -> Any:
        posted["count"] += 1
        return SimpleNamespace(status_code=200, text="ok")

    monkeypatch.setattr(requests, "post", _fake_post)

    callback = usage_callback.NitUsageCallback()

    response_obj = SimpleNamespace(
        model="gpt-4o",
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=6),
        _hidden_params={},
    )

    callback.log_success_event(
        {
            "litellm_params": {
                "metadata": {
                    "nit_user_id": "user-x",
                    "nit_usage_source": "api",
                    "nit_usage_emit": False,
                }
            }
        },
        response_obj,
        datetime.now(UTC),
        datetime.now(UTC),
    )

    assert posted["count"] == 0
