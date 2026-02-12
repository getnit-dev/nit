"""Tests for Sentry integration."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nit.config import SentryConfig, _validate_sentry_config, load_config
from nit.telemetry import sentry_integration


@pytest.fixture(autouse=True)
def _reset_sentry_state() -> Generator[None]:
    """Reset Sentry singleton state between tests."""
    sentry_integration._initialized["value"] = False
    yield
    sentry_integration._initialized["value"] = False


# ---------------------------------------------------------------------------
# init_sentry
# ---------------------------------------------------------------------------


def test_init_sentry_disabled_does_not_call_sdk() -> None:
    config = SentryConfig(enabled=False, dsn="https://key@sentry.io/123")
    with patch.object(sentry_integration, "_initialized", {"value": False}):
        init_called = False

        def _fake_init(**kwargs: Any) -> None:
            nonlocal init_called
            init_called = True

        with patch.dict("sys.modules", {"sentry_sdk": MagicMock()}):
            sentry_integration.init_sentry(config)

        assert not init_called
        assert not sentry_integration.is_sentry_enabled()


def test_init_sentry_enabled_no_dsn_warns(caplog: pytest.LogCaptureFixture) -> None:
    config = SentryConfig(enabled=True, dsn="")
    sentry_integration.init_sentry(config)

    assert not sentry_integration.is_sentry_enabled()
    assert "no DSN configured" in caplog.text


def test_init_sentry_valid_config_calls_sdk() -> None:
    config = SentryConfig(
        enabled=True,
        dsn="https://key@sentry.io/123",
        traces_sample_rate=0.5,
        profiles_sample_rate=0.1,
        enable_logs=True,
        environment="test",
    )

    mock_sdk = MagicMock()
    mock_logging_integration = MagicMock()

    with (
        patch.dict(
            "sys.modules",
            {
                "sentry_sdk": mock_sdk,
                "sentry_sdk.integrations": MagicMock(),
                "sentry_sdk.integrations.logging": MagicMock(
                    LoggingIntegration=mock_logging_integration
                ),
            },
        ),
        patch("nit.utils.ci_context.detect_ci_context") as mock_ci,
    ):
        mock_ci.return_value = MagicMock(is_ci=False)
        sentry_integration.init_sentry(config)

    assert sentry_integration.is_sentry_enabled()
    mock_sdk.init.assert_called_once()

    call_kwargs = mock_sdk.init.call_args[1]
    assert call_kwargs["dsn"] == "https://key@sentry.io/123"
    assert call_kwargs["traces_sample_rate"] == 0.5
    assert call_kwargs["profiles_sample_rate"] == 0.1
    assert call_kwargs["send_default_pii"] is False
    assert call_kwargs["server_name"] == ""
    assert call_kwargs["environment"] == "test"
    assert call_kwargs["enable_logs"] is True
    assert "getnit@" in call_kwargs["release"]


def test_init_sentry_is_idempotent() -> None:
    config = SentryConfig(enabled=True, dsn="https://key@sentry.io/123")

    mock_sdk = MagicMock()

    with (
        patch.dict(
            "sys.modules",
            {
                "sentry_sdk": mock_sdk,
                "sentry_sdk.integrations": MagicMock(),
                "sentry_sdk.integrations.logging": MagicMock(LoggingIntegration=MagicMock()),
            },
        ),
        patch("nit.utils.ci_context.detect_ci_context") as mock_ci,
    ):
        mock_ci.return_value = MagicMock(is_ci=False)
        sentry_integration.init_sentry(config)
        sentry_integration.init_sentry(config)

    assert mock_sdk.init.call_count == 1


def test_init_sentry_ci_environment() -> None:
    config = SentryConfig(enabled=True, dsn="https://key@sentry.io/123")

    mock_sdk = MagicMock()

    with (
        patch.dict(
            "sys.modules",
            {
                "sentry_sdk": mock_sdk,
                "sentry_sdk.integrations": MagicMock(),
                "sentry_sdk.integrations.logging": MagicMock(LoggingIntegration=MagicMock()),
            },
        ),
        patch("nit.utils.ci_context.detect_ci_context") as mock_ci,
    ):
        mock_ci.return_value = MagicMock(is_ci=True)
        sentry_integration.init_sentry(config)

    call_kwargs = mock_sdk.init.call_args[1]
    assert call_kwargs["environment"] == "ci"


# ---------------------------------------------------------------------------
# Privacy scrubbing
# ---------------------------------------------------------------------------


def test_scrub_event_removes_frame_vars() -> None:
    event: dict[str, Any] = {
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "nit/cli.py",
                                "vars": {"api_key": "sk-secret123", "x": 42},
                            }
                        ]
                    }
                }
            ]
        }
    }
    scrubbed = sentry_integration._scrub_event(event)
    frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "vars" not in frame


def test_scrub_event_anonymizes_paths() -> None:
    event: dict[str, Any] = {
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "/Users/john/projects/nit/cli.py",
                                "abs_path": "/home/jane/nit/cli.py",
                            }
                        ]
                    }
                }
            ]
        }
    }
    scrubbed = sentry_integration._scrub_event(event)
    frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "/Users/john" not in frame["filename"]
    assert "/home/jane" not in frame["abs_path"]
    assert "/~" in frame["filename"]
    assert "/~" in frame["abs_path"]


def test_scrub_event_removes_server_name() -> None:
    event: dict[str, Any] = {"server_name": "my-macbook.local", "tags": {}}
    scrubbed = sentry_integration._scrub_event(event)
    assert "server_name" not in scrubbed


def test_scrub_dict_redacts_sensitive_keys() -> None:
    redacted = "[REDACTED]"
    data = {
        "api_key": "sk-1234567890",
        "password": "secret",
        "token": "tok_abc",
        "dsn": "https://key@sentry.io/123",
        "normal_key": "visible",
    }
    scrubbed = sentry_integration._scrub_dict(data)
    assert scrubbed["api_key"] == redacted
    assert scrubbed["password"] == redacted
    assert scrubbed["token"] == redacted
    assert scrubbed["dsn"] == redacted
    assert scrubbed["normal_key"] == "visible"


def test_scrub_string_redacts_api_key_patterns() -> None:
    text = "Using api_key=sk-1234567890 for auth"
    scrubbed = sentry_integration._scrub_string(text)
    assert "sk-1234567890" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_scrub_event_handles_breadcrumbs() -> None:
    event: dict[str, Any] = {
        "breadcrumbs": {
            "values": [
                {
                    "message": "Set token=abc123 for auth",
                    "data": {"api_key": "sk-secret", "url": "https://example.com"},
                }
            ]
        }
    }
    scrubbed = sentry_integration._scrub_event(event)
    crumb = scrubbed["breadcrumbs"]["values"][0]
    assert "abc123" not in crumb["message"]
    assert crumb["data"]["api_key"] == "[REDACTED]"
    assert crumb["data"]["url"] == "https://example.com"


def test_before_send_preserves_structure() -> None:
    event: dict[str, Any] = {
        "event_id": "abc123",
        "level": "error",
        "tags": {"version": "1.0"},
        "extra": {"debug_info": "safe data"},
    }
    result = sentry_integration._before_send(event, {})
    assert result is not None
    assert result["event_id"] == "abc123"
    assert result["level"] == "error"


def test_before_send_transaction_scrubs() -> None:
    event: dict[str, Any] = {
        "server_name": "host.local",
        "tags": {"api_key": "secret"},
    }
    result = sentry_integration._before_send_transaction(event, {})
    assert result is not None
    assert "server_name" not in result
    assert result["tags"]["api_key"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# Metrics helpers (no-op when disabled)
# ---------------------------------------------------------------------------


def test_record_metric_count_noop_when_disabled() -> None:
    assert not sentry_integration.is_sentry_enabled()
    # Should not raise
    sentry_integration.record_metric_count("test.metric", value=5)


def test_record_metric_distribution_noop_when_disabled() -> None:
    assert not sentry_integration.is_sentry_enabled()
    sentry_integration.record_metric_distribution("test.metric", 42.0, unit="ms")


def test_record_metric_gauge_noop_when_disabled() -> None:
    assert not sentry_integration.is_sentry_enabled()
    sentry_integration.record_metric_gauge("test.metric", 99.9, unit="percent")


def test_record_metric_count_calls_sdk_when_enabled() -> None:
    sentry_integration._initialized["value"] = True

    with patch("sentry_sdk.metrics.count") as mock_count:
        sentry_integration.record_metric_count("nit.test", value=3, command="pick")

    mock_count.assert_called_once_with("nit.test", 3.0, attributes={"command": "pick"})


# ---------------------------------------------------------------------------
# Tracing helpers
# ---------------------------------------------------------------------------


def test_start_span_returns_noop_when_disabled() -> None:
    span = sentry_integration.start_span(op="test", description="test span")
    assert isinstance(span, sentry_integration._NoOpSpan)


def test_noop_span_context_manager() -> None:
    span = sentry_integration._NoOpSpan()
    with span as s:
        s.set_data("key", "value")
        s.set_status("ok")
    # Should not raise


def test_start_span_calls_sdk_when_enabled() -> None:
    sentry_integration._initialized["value"] = True
    mock_sdk = MagicMock()

    with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
        sentry_integration.start_span(op="cli.command", description="nit pick")

    mock_sdk.start_span.assert_called_once_with(op="cli.command", description="nit pick")


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_validate_sentry_config_enabled_no_dsn() -> None:
    config = SentryConfig(enabled=True, dsn="")
    errors = _validate_sentry_config(config)
    assert any("dsn is required" in e for e in errors)


def test_validate_sentry_config_valid() -> None:
    config = SentryConfig(
        enabled=True,
        dsn="https://key@sentry.io/123",
        traces_sample_rate=0.5,
        profiles_sample_rate=0.1,
    )
    errors = _validate_sentry_config(config)
    assert errors == []


def test_validate_sentry_config_traces_rate_out_of_range() -> None:
    config = SentryConfig(traces_sample_rate=1.5)
    errors = _validate_sentry_config(config)
    assert any("traces_sample_rate" in e for e in errors)


def test_validate_sentry_config_profiles_rate_out_of_range() -> None:
    config = SentryConfig(profiles_sample_rate=-0.1)
    errors = _validate_sentry_config(config)
    assert any("profiles_sample_rate" in e for e in errors)


def test_validate_sentry_config_disabled_no_errors() -> None:
    config = SentryConfig(enabled=False)
    errors = _validate_sentry_config(config)
    assert errors == []


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_sentry_config_defaults() -> None:
    config = SentryConfig()
    assert config.enabled is False
    assert config.dsn == ""
    assert config.traces_sample_rate == 0.0
    assert config.profiles_sample_rate == 0.0
    assert config.enable_logs is False
    assert config.environment == ""
    assert config.send_default_pii is False


def test_parse_sentry_config_from_yaml(tmp_path: Any) -> None:
    nit_yml = tmp_path / ".nit.yml"
    nit_yml.write_text(
        "sentry:\n"
        "  enabled: true\n"
        "  dsn: https://key@sentry.io/123\n"
        "  traces_sample_rate: 0.5\n"
        "  profiles_sample_rate: 0.1\n"
        "  enable_logs: true\n"
        "  environment: staging\n"
    )

    config = load_config(tmp_path)
    assert config.sentry.enabled is True
    assert config.sentry.dsn == "https://key@sentry.io/123"
    assert config.sentry.traces_sample_rate == 0.5
    assert config.sentry.profiles_sample_rate == 0.1
    assert config.sentry.enable_logs is True
    assert config.sentry.environment == "staging"
    assert config.sentry.send_default_pii is False


def test_parse_sentry_config_env_vars(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    nit_yml = tmp_path / ".nit.yml"
    nit_yml.write_text("")

    monkeypatch.setenv("NIT_SENTRY_ENABLED", "true")
    monkeypatch.setenv("NIT_SENTRY_DSN", "https://env@sentry.io/456")
    monkeypatch.setenv("NIT_SENTRY_TRACES_SAMPLE_RATE", "0.3")
    monkeypatch.setenv("NIT_SENTRY_PROFILES_SAMPLE_RATE", "0.05")
    monkeypatch.setenv("NIT_SENTRY_ENABLE_LOGS", "yes")

    config = load_config(tmp_path)
    assert config.sentry.enabled is True
    assert config.sentry.dsn == "https://env@sentry.io/456"
    assert config.sentry.traces_sample_rate == 0.3
    assert config.sentry.profiles_sample_rate == 0.05
    assert config.sentry.enable_logs is True


def test_parse_sentry_config_missing_section(tmp_path: Any) -> None:
    nit_yml = tmp_path / ".nit.yml"
    nit_yml.write_text("project:\n  root: .\n")

    config = load_config(tmp_path)
    assert config.sentry.enabled is False
    assert config.sentry.dsn == ""
