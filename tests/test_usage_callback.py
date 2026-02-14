"""Tests for LiteLLM usage callback + batched reporter."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import litellm
import pytest
import requests

from nit.llm import usage_callback

_TEST_INGEST_TOKEN = "test-ingest-" + "token"


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
        usage_callback.CLIUsageEvent(
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
    )

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert "events" in payload

    event = payload["events"][0]
    assert "userId" not in event
    assert "projectId" not in event
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

    assert "userId" not in event
    assert "projectId" not in event
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
                    "nit_usage_source": "byok",
                    "nit_usage_emit": False,
                }
            }
        },
        response_obj,
        datetime.now(UTC),
        datetime.now(UTC),
    )

    assert posted["count"] == 0


# ── Helper function tests ─────────────────────────────────────────────


class TestSafeFunctions:
    """Tests for _safe_* helper functions."""

    def test_safe_str_with_string(self) -> None:
        assert usage_callback._safe_str("  hello  ") == "hello"

    def test_safe_str_with_nonstring(self) -> None:
        assert usage_callback._safe_str(42) == ""

    def test_safe_float_valid(self) -> None:
        assert usage_callback._safe_float("3.14") == pytest.approx(3.14)

    def test_safe_float_negative_clamps_to_zero(self) -> None:
        assert usage_callback._safe_float(-5.0) == 0.0

    def test_safe_float_invalid(self) -> None:
        assert usage_callback._safe_float("not_a_number") == 0.0

    def test_safe_float_invalid_with_default(self) -> None:
        assert usage_callback._safe_float("bad", default=99.0) == 99.0

    def test_safe_int_valid(self) -> None:
        assert usage_callback._safe_int("42") == 42

    def test_safe_int_negative_clamps_to_zero(self) -> None:
        assert usage_callback._safe_int(-10) == 0

    def test_safe_int_invalid(self) -> None:
        assert usage_callback._safe_int("bad") == 0

    def test_safe_int_from_float_string(self) -> None:
        assert usage_callback._safe_int("3.7") == 3

    @pytest.mark.parametrize(
        "value",
        [1, "true", "yes", "1", "hit"],
    )
    def test_safe_bool_true_values(self, value: object) -> None:
        assert usage_callback._safe_bool(value) is True

    @pytest.mark.parametrize(
        "value",
        [0, "false", "no", "0", "miss"],
    )
    def test_safe_bool_false_values(self, value: object) -> None:
        assert usage_callback._safe_bool(value) is False

    def test_safe_bool_default(self) -> None:
        assert usage_callback._safe_bool(None, default=True) is True
        assert usage_callback._safe_bool(None, default=False) is False


class TestSafeIsoTimestamp:
    """Tests for _safe_iso_timestamp."""

    def test_datetime_input(self) -> None:
        dt = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = usage_callback._safe_iso_timestamp(dt)
        assert "2026-01-15" in result

    def test_string_input(self) -> None:
        result = usage_callback._safe_iso_timestamp("2026-01-15T10:30:00Z")
        assert "2026-01-15" in result

    def test_invalid_string(self) -> None:
        result = usage_callback._safe_iso_timestamp("not-a-date")
        # Falls back to now
        assert "T" in result

    def test_none_input(self) -> None:
        result = usage_callback._safe_iso_timestamp(None)
        assert "T" in result


class TestInferProvider:
    """Tests for _infer_provider."""

    def test_anthropic_from_claude(self) -> None:
        assert usage_callback._infer_provider("claude-sonnet-4-5") == "anthropic"

    def test_openai_from_gpt(self) -> None:
        assert usage_callback._infer_provider("gpt-4o") == "openai"

    def test_openai_from_o1(self) -> None:
        assert usage_callback._infer_provider("o1-preview") == "openai"

    def test_google_from_gemini(self) -> None:
        assert usage_callback._infer_provider("gemini-1.5-pro") == "google"

    def test_mistral_from_name(self) -> None:
        assert usage_callback._infer_provider("mistral-large") == "mistral"

    def test_provider_from_slash(self) -> None:
        assert usage_callback._infer_provider("anthropic/claude-3-opus") == "anthropic"

    def test_fallback(self) -> None:
        assert usage_callback._infer_provider("unknown-model") == "unknown"

    def test_custom_fallback(self) -> None:
        assert usage_callback._infer_provider("unknown-model", "custom") == "custom"


class TestNormalizeSource:
    """Tests for _normalize_source."""

    def test_valid_sources(self) -> None:
        assert usage_callback._normalize_source("byok") == "byok"
        assert usage_callback._normalize_source("cli") == "cli"

    def test_invalid_source_defaults_to_byok(self) -> None:
        assert usage_callback._normalize_source("invalid") == "byok"

    def test_none_defaults_to_byok(self) -> None:
        assert usage_callback._normalize_source(None) == "byok"


class TestPickMetadataValue:
    """Tests for _pick_metadata_value."""

    def test_finds_first_matching_key(self) -> None:
        metadata = {"key_a": "  ", "key_b": "value_b"}
        result = usage_callback._pick_metadata_value(metadata, "key_a", "key_b")
        assert result == "value_b"

    def test_returns_none_when_no_match(self) -> None:
        result = usage_callback._pick_metadata_value({}, "missing")
        assert result is None


class TestSafeRecord:
    """Tests for _safe_record."""

    def test_dict_input(self) -> None:
        d = {"a": 1}
        assert usage_callback._safe_record(d) == {"a": 1}

    def test_object_with_dict(self) -> None:
        result = usage_callback._safe_record(SimpleNamespace(x=10))
        assert result == {"x": 10}

    def test_non_object(self) -> None:
        assert usage_callback._safe_record(42) == {}


class TestPickScalarMetadata:
    """Tests for _pick_scalar_metadata."""

    def test_string_is_scalar(self) -> None:
        assert usage_callback._pick_scalar_metadata("hello") == "hello"

    def test_int_is_scalar(self) -> None:
        assert usage_callback._pick_scalar_metadata(42) == 42

    def test_dict_is_not_scalar(self) -> None:
        assert usage_callback._pick_scalar_metadata({"a": 1}) is None


# ── SessionUsageStats tests ───────────────────────────────────────────


class TestSessionUsageStats:
    """Tests for SessionUsageStats."""

    def test_add_usage(self) -> None:
        stats = usage_callback.SessionUsageStats()
        stats.add_usage(prompt_tokens=10, completion_tokens=5, cost_usd=0.01)
        assert stats.prompt_tokens == 10
        assert stats.completion_tokens == 5
        assert stats.total_tokens == 15
        assert stats.total_cost_usd == pytest.approx(0.01)
        assert stats.request_count == 1

    def test_add_usage_accumulates(self) -> None:
        stats = usage_callback.SessionUsageStats()
        stats.add_usage(prompt_tokens=10, completion_tokens=5, cost_usd=0.01)
        stats.add_usage(prompt_tokens=20, completion_tokens=10, cost_usd=0.02)
        assert stats.prompt_tokens == 30
        assert stats.total_tokens == 45
        assert stats.request_count == 2

    def test_reset(self) -> None:
        stats = usage_callback.SessionUsageStats()
        stats.add_usage(prompt_tokens=10, completion_tokens=5, cost_usd=0.01)
        stats.reset()
        assert stats.prompt_tokens == 0
        assert stats.total_tokens == 0
        assert stats.request_count == 0


# ── Config tests ──────────────────────────────────────────────────────


class TestUsageReporterConfig:
    """Tests for UsageReporterConfig."""

    def test_enabled_when_url_and_token(self) -> None:
        config = usage_callback.UsageReporterConfig(
            platform_url="https://example.com",
            ingest_token=_TEST_INGEST_TOKEN,
            user_id="",
            project_id=None,
            key_hash=None,
            batch_size=20,
            flush_interval_seconds=5.0,
            max_retries=3,
            request_timeout_seconds=8.0,
        )
        assert config.enabled is True

    def test_disabled_when_no_url(self) -> None:
        config = usage_callback.UsageReporterConfig(
            platform_url="",
            ingest_token=_TEST_INGEST_TOKEN,
            user_id="",
            project_id=None,
            key_hash=None,
            batch_size=20,
            flush_interval_seconds=5.0,
            max_retries=3,
            request_timeout_seconds=8.0,
        )
        assert config.enabled is False


class TestParseEnvHelpers:
    """Tests for _parse_int_env and _parse_float_env."""

    def test_parse_int_env_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_INT_VAR", raising=False)
        assert usage_callback._parse_int_env("TEST_INT_VAR", 42, minimum=1) == 42

    def test_parse_int_env_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_INT_VAR", "10")
        assert usage_callback._parse_int_env("TEST_INT_VAR", 42, minimum=1) == 10

    def test_parse_int_env_below_minimum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_INT_VAR", "-5")
        assert usage_callback._parse_int_env("TEST_INT_VAR", 42, minimum=1) == 1

    def test_parse_int_env_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_INT_VAR", "bad")
        assert usage_callback._parse_int_env("TEST_INT_VAR", 42, minimum=1) == 42

    def test_parse_float_env_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_FLOAT_VAR", raising=False)
        assert usage_callback._parse_float_env("TEST_FLOAT_VAR", 5.0, minimum=0.1) == 5.0

    def test_parse_float_env_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_FLOAT_VAR", "2.5")
        assert usage_callback._parse_float_env("TEST_FLOAT_VAR", 5.0, minimum=0.1) == 2.5

    def test_parse_float_env_below_minimum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_FLOAT_VAR", "0.001")
        assert usage_callback._parse_float_env("TEST_FLOAT_VAR", 5.0, minimum=0.1) == 0.1

    def test_parse_float_env_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_FLOAT_VAR", "abc")
        assert usage_callback._parse_float_env("TEST_FLOAT_VAR", 5.0, minimum=0.1) == 5.0


# ── BatchedUsageReporter tests ────────────────────────────────────────


class TestBatchedUsageReporter:
    """Tests for BatchedUsageReporter."""

    def test_enqueue_disabled(self) -> None:
        config = usage_callback.UsageReporterConfig(
            platform_url="",
            ingest_token="",
            user_id="",
            project_id=None,
            key_hash=None,
            batch_size=1,
            flush_interval_seconds=999,
            max_retries=1,
            request_timeout_seconds=5.0,
        )
        reporter = usage_callback.BatchedUsageReporter(config)
        # Should not raise
        reporter.enqueue({"test": True})

    def test_flush_disabled(self) -> None:
        config = usage_callback.UsageReporterConfig(
            platform_url="",
            ingest_token="",
            user_id="",
            project_id=None,
            key_hash=None,
            batch_size=1,
            flush_interval_seconds=999,
            max_retries=1,
            request_timeout_seconds=5.0,
        )
        reporter = usage_callback.BatchedUsageReporter(config)
        # Should not raise
        reporter.flush()

    def test_build_metadata_includes_key_hash(self) -> None:
        config = usage_callback.UsageReporterConfig(
            platform_url="https://example.com",
            ingest_token=_TEST_INGEST_TOKEN,
            user_id="",
            project_id=None,
            key_hash="kh",
            batch_size=20,
            flush_interval_seconds=5.0,
            max_retries=3,
            request_timeout_seconds=8.0,
        )
        reporter = usage_callback.BatchedUsageReporter(config)
        meta = reporter.build_metadata(usage_callback.MetadataParams(source="byok", mode="builtin"))
        assert meta["nit_key_hash"] == "kh"
        assert meta["nit_usage_source"] == "byok"
        assert "nit_user_id" not in meta
        assert "nit_project_id" not in meta

    def test_build_metadata_with_overrides(self) -> None:
        config = usage_callback.UsageReporterConfig(
            platform_url="https://example.com",
            ingest_token=_TEST_INGEST_TOKEN,
            user_id="",
            project_id=None,
            key_hash=None,
            batch_size=20,
            flush_interval_seconds=5.0,
            max_retries=3,
            request_timeout_seconds=8.0,
        )
        reporter = usage_callback.BatchedUsageReporter(config)
        meta = reporter.build_metadata(
            usage_callback.MetadataParams(
                source="byok",
                mode="builtin",
                provider="openai",
                model="gpt-4o",
                overrides={"custom_key": "custom_val", "nested": {"ignored": True}},
            )
        )
        assert meta["nit_provider"] == "openai"
        assert meta["nit_model"] == "gpt-4o"
        assert meta["custom_key"] == "custom_val"
        # nested dict is not scalar, should not appear
        assert "nested" not in meta


# ── ComputeDurationMs + ToDatetime tests ──────────────────────────────


class TestComputeDurationMs:
    """Tests for _compute_duration_ms."""

    def test_datetime_objects(self) -> None:
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
        assert usage_callback._compute_duration_ms(start, end) == 1000

    def test_string_datetimes(self) -> None:
        result = usage_callback._compute_duration_ms("2026-01-01T00:00:00Z", "2026-01-01T00:00:02Z")
        assert result == 2000

    def test_none_returns_zero(self) -> None:
        assert usage_callback._compute_duration_ms(None, None) == 0

    def test_invalid_string_returns_zero(self) -> None:
        assert usage_callback._compute_duration_ms("bad", "bad") == 0


class TestGetField:
    """Tests for _get_field."""

    def test_dict_input(self) -> None:
        assert usage_callback._get_field({"a": 1}, "a") == 1

    def test_object_input(self) -> None:
        assert usage_callback._get_field(SimpleNamespace(a=1), "a") == 1

    def test_missing_returns_default(self) -> None:
        assert usage_callback._get_field({}, "missing", "default") == "default"


# ── BatchedUsageReporter flush / post_batch tests ─────────────────────


class TestBatchedUsageReporterFlushAndPost:
    """Tests for flush, enqueue, and _post_batch internals."""

    def _make_config(
        self,
        *,
        enabled: bool = True,
        batch_size: int = 1,
        max_retries: int = 1,
    ) -> usage_callback.UsageReporterConfig:
        _token = "test-" + "tok"
        return usage_callback.UsageReporterConfig(
            platform_url="https://example.com" if enabled else "",
            ingest_token=_token if enabled else "",
            user_id="",
            project_id=None,
            key_hash=None,
            batch_size=batch_size,
            flush_interval_seconds=999,
            max_retries=max_retries,
            request_timeout_seconds=5.0,
        )

    def test_flush_posts_batch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        posted: list[dict[str, Any]] = []

        def _fake_post(
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, Any],
            timeout: float,
        ) -> SimpleNamespace:
            posted.append(json)
            return SimpleNamespace(status_code=200, text="ok")

        monkeypatch.setattr(requests, "post", _fake_post)

        config = self._make_config(batch_size=100)
        reporter = usage_callback.BatchedUsageReporter(config)
        reporter.enqueue({"test": 1})
        reporter.enqueue({"test": 2})
        # Not yet posted (batch_size=100)
        assert len(posted) == 0
        reporter.flush()
        assert len(posted) == 1
        assert len(posted[0]["events"]) == 2

    def test_post_batch_retries_on_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = {"n": 0}

        def _fake_post(
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
            timeout: float,
        ) -> SimpleNamespace:
            call_count["n"] += 1
            if call_count["n"] < 3:
                return SimpleNamespace(status_code=500, text="error")
            return SimpleNamespace(status_code=200, text="ok")

        monkeypatch.setattr(requests, "post", _fake_post)
        monkeypatch.setattr("time.sleep", lambda _: None)

        config = self._make_config(max_retries=3)
        reporter = usage_callback.BatchedUsageReporter(config)
        reporter._post_batch([{"e": 1}])
        assert call_count["n"] == 3

    def test_post_batch_retries_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_post(*args: object, **kwargs: object) -> None:
            raise requests.RequestException("timeout")

        monkeypatch.setattr(requests, "post", _fake_post)
        monkeypatch.setattr("time.sleep", lambda _: None)

        config = self._make_config(max_retries=2)
        reporter = usage_callback.BatchedUsageReporter(config)
        # Should not raise
        reporter._post_batch([{"e": 1}])

    def test_drain_empty_buffer(self) -> None:
        config = self._make_config()
        reporter = usage_callback.BatchedUsageReporter(config)
        batch = reporter._drain_unlocked()
        assert batch == []

    def test_enqueue_triggers_batch_by_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        posted: list[dict[str, object]] = []

        def _fake_post(
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
            timeout: float,
        ) -> SimpleNamespace:
            posted.append(json)
            return SimpleNamespace(status_code=200, text="ok")

        monkeypatch.setattr(requests, "post", _fake_post)

        config = self._make_config(batch_size=100)
        reporter = usage_callback.BatchedUsageReporter(config)
        # Force interval flush by setting last_flush far in past
        reporter._last_flush = 0.0
        _token = "test-" + "tok"
        reporter._config = usage_callback.UsageReporterConfig(
            platform_url="https://example.com",
            ingest_token=_token,
            user_id="",
            project_id=None,
            key_hash=None,
            batch_size=100,
            flush_interval_seconds=0.0,
            max_retries=1,
            request_timeout_seconds=5.0,
        )
        reporter.enqueue({"test": 1})
        assert len(posted) == 1


# ── report_cli_usage_event edge cases ─────────────────────────────────


class TestReportCliUsageEventEdgeCases:
    """Test edge cases in report_cli_usage_event."""

    def test_cli_event_no_duration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, Any],
            timeout: float,
        ) -> SimpleNamespace:
            captured["json"] = json
            return SimpleNamespace(status_code=200, text="ok")

        monkeypatch.setattr(requests, "post", _fake_post)

        usage_callback.report_cli_usage_event(
            usage_callback.CLIUsageEvent(
                provider="openai",
                model="gpt-4o",
                prompt_tokens=10,
                completion_tokens=5,
                cost_usd=0.01,
            )
        )
        event = captured["json"]["events"][0]
        assert "durationMs" not in event

    def test_cli_event_no_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_post(
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, Any],
            timeout: float,
        ) -> SimpleNamespace:
            captured["json"] = json
            return SimpleNamespace(status_code=200, text="ok")

        monkeypatch.setattr(requests, "post", _fake_post)

        usage_callback.report_cli_usage_event(
            usage_callback.CLIUsageEvent(
                provider="openai",
                model="gpt-4o",
                prompt_tokens=10,
                completion_tokens=5,
            )
        )
        event = captured["json"]["events"][0]
        assert "metadata" not in event

    def test_cli_event_disabled_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NIT_PLATFORM_URL", "")
        monkeypatch.setenv("NIT_PLATFORM_INGEST_TOKEN", "")
        usage_callback._SINGLETONS.reporter = None
        # Should return immediately without posting
        usage_callback.report_cli_usage_event(
            usage_callback.CLIUsageEvent(
                provider="openai",
                model="gpt-4o",
                prompt_tokens=10,
                completion_tokens=5,
            )
        )


# ── NitUsageCallback async_log_success_event tests ────────────────────


class TestNitUsageCallbackAsync:
    """Test async_log_success_event."""

    @pytest.mark.asyncio
    async def test_async_log_success_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def _fake_post(
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, object],
            timeout: float,
        ) -> SimpleNamespace:
            captured["json"] = json
            return SimpleNamespace(status_code=200, text="ok")

        monkeypatch.setattr(requests, "post", _fake_post)

        callback = usage_callback.NitUsageCallback()

        response_obj = SimpleNamespace(
            model="gpt-4o",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=6),
            _hidden_params={},
        )

        start = datetime(2026, 2, 10, 10, 30, 0, tzinfo=UTC)
        end = datetime(2026, 2, 10, 10, 30, 1, tzinfo=UTC)
        await callback.async_log_success_event(
            {"model": "gpt-4o", "metadata": {"nit_usage_emit": True}},
            response_obj,
            start,
            end,
        )

        assert "json" in captured

    @pytest.mark.asyncio
    async def test_async_log_none_event_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """async_log_success_event does nothing when event is None."""
        callback = usage_callback.NitUsageCallback()
        # Pass non-dict kwargs to make _build_event return None
        await callback.async_log_success_event("not-a-dict", None, None, None)


# ── ensure_nit_usage_callback_registered tests ────────────────────────


class TestEnsureCallbackRegistered:
    """Test ensure_nit_usage_callback_registered."""

    def _save_and_clear(self) -> tuple[
        list[Any],
        usage_callback.BatchedUsageReporter | None,
        usage_callback.NitUsageCallback | None,
    ]:
        saved_callbacks = litellm.callbacks[:]
        saved_reporter = usage_callback._SINGLETONS.reporter
        saved_callback = usage_callback._SINGLETONS.callback
        litellm.callbacks.clear()
        return saved_callbacks, saved_reporter, saved_callback

    def _restore(
        self,
        saved_callbacks: list[Any],
        saved_reporter: usage_callback.BatchedUsageReporter | None,
        saved_callback: usage_callback.NitUsageCallback | None,
    ) -> None:
        litellm.callbacks.clear()
        litellm.callbacks.extend(saved_callbacks)
        usage_callback._SINGLETONS.reporter = saved_reporter
        usage_callback._SINGLETONS.callback = saved_callback

    def test_cold_start_creates_reporter_and_callback(self) -> None:
        """When both singletons are None, creates both without deadlocking."""
        saved_callbacks, saved_reporter, saved_callback = self._save_and_clear()
        usage_callback._SINGLETONS.reporter = None
        usage_callback._SINGLETONS.callback = None
        try:
            cb = usage_callback.ensure_nit_usage_callback_registered()
            assert isinstance(cb, usage_callback.NitUsageCallback)
            assert cb in litellm.callbacks
            assert usage_callback._SINGLETONS.reporter is not None
        finally:
            self._restore(saved_callbacks, saved_reporter, saved_callback)

    def test_existing_callback_reused(self) -> None:
        """When callback already exists, it is reused."""
        saved_callbacks, saved_reporter, saved_callback = self._save_and_clear()
        reporter = usage_callback.BatchedUsageReporter(
            usage_callback.UsageReporterConfig.from_env()
        )
        existing_cb = usage_callback.NitUsageCallback(reporter=reporter)
        usage_callback._SINGLETONS.callback = existing_cb
        usage_callback._SINGLETONS.reporter = reporter
        try:
            cb = usage_callback.ensure_nit_usage_callback_registered()
            assert cb is existing_cb
            assert cb in litellm.callbacks
        finally:
            self._restore(saved_callbacks, saved_reporter, saved_callback)

    def test_idempotent_append(self) -> None:
        """Calling twice does not duplicate callback in litellm.callbacks."""
        saved_callbacks, saved_reporter, saved_callback = self._save_and_clear()
        reporter = usage_callback.BatchedUsageReporter(
            usage_callback.UsageReporterConfig.from_env()
        )
        existing_cb = usage_callback.NitUsageCallback(reporter=reporter)
        usage_callback._SINGLETONS.callback = existing_cb
        usage_callback._SINGLETONS.reporter = reporter
        try:
            cb1 = usage_callback.ensure_nit_usage_callback_registered()
            cb2 = usage_callback.ensure_nit_usage_callback_registered()
            assert cb1 is cb2
            count = sum(1 for c in litellm.callbacks if c is cb1)
            assert count == 1
        finally:
            self._restore(saved_callbacks, saved_reporter, saved_callback)


# ── get_session_usage_stats / reset_session_usage_stats tests ─────────


class TestSessionStatsGetAndReset:
    """Test get_session_usage_stats and reset_session_usage_stats."""

    def test_get_returns_copy(self) -> None:
        usage_callback._SINGLETONS.session_stats.reset()
        usage_callback._SINGLETONS.session_stats.add_usage(
            prompt_tokens=10, completion_tokens=5, cost_usd=0.01
        )
        stats = usage_callback.get_session_usage_stats()
        assert stats.prompt_tokens == 10
        assert stats.total_cost_usd == pytest.approx(0.01)

    def test_reset_clears_stats(self) -> None:
        usage_callback._SINGLETONS.session_stats.add_usage(
            prompt_tokens=10, completion_tokens=5, cost_usd=0.01
        )
        usage_callback.reset_session_usage_stats()
        stats = usage_callback.get_session_usage_stats()
        assert stats.prompt_tokens == 0
        assert stats.request_count == 0


# ── _build_event edge cases ───────────────────────────────────────────


class TestBuildEventEdgeCases:
    """Test _build_event edge cases."""

    def test_non_dict_kwargs_returns_none(self) -> None:
        callback = usage_callback.NitUsageCallback()
        assert callback._build_event("not-a-dict", None, None, None) is None

    def test_emit_false_returns_none(self) -> None:
        callback = usage_callback.NitUsageCallback()
        result = callback._build_event(
            {
                "metadata": {"nit_usage_emit": False},
            },
            None,
            None,
            None,
        )
        assert result is None

    def test_build_event_response_cost_negative(self) -> None:
        """Negative response_cost is clamped to 0.0 by _safe_float."""
        callback = usage_callback.NitUsageCallback()
        response_obj = SimpleNamespace(
            model="gpt-4o",
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                cost=0.05,
            ),
            _hidden_params={},
        )
        event = callback._build_event(
            {
                "model": "gpt-4o",
                "response_cost": -1.0,
                "metadata": {"nit_usage_emit": True},
            },
            response_obj,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        )
        assert event is not None
        # _safe_float clamps negative values to 0.0
        assert event["costUsd"] == pytest.approx(0.0)
