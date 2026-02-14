"""Sentry SDK integration for nit.

Handles initialization, data scrubbing, metrics, tracing, and logging
integration with Sentry. All Sentry functionality is strictly OPT-IN:
no data is sent without explicit user consent via ``sentry.enabled: true``
in ``.nit.yml`` or ``NIT_SENTRY_ENABLED=true``.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import TYPE_CHECKING, Any

from nit import __version__
from nit.utils.ci_context import detect_ci_context

try:
    import sentry_sdk
    import sentry_sdk.metrics
    from sentry_sdk.integrations.logging import LoggingIntegration as _LoggingIntegration

    _sentry_available = True
except ImportError:
    _sentry_available = False

if TYPE_CHECKING:
    from types import TracebackType

    from nit.config import SentryConfig

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()
_initialized: dict[str, bool] = {"value": False}

# Patterns to scrub from event data
_SENSITIVE_PATTERN = re.compile(
    r"(api[_-]?key|password|secret|token|dsn|authorization|cookie)\s*[:=]\s*\S+",
    re.IGNORECASE,
)

_PATH_HOME_RE = re.compile(r"/(?:home|Users)/[^/]+")

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "password",
        "secret",
        "token",
        "dsn",
        "authorization",
        "cookie",
        "session_id",
        "key_hash",
        "ingest_token",
        "slack_webhook",
        "cookie_value",
    }
)


def init_sentry(config: SentryConfig) -> None:
    """Initialize Sentry SDK if enabled and configured.

    This function is idempotent and thread-safe. Calling it multiple
    times is a no-op after the first successful initialization.
    """
    with _init_lock:
        if _initialized["value"]:
            return
        if not config.enabled:
            logger.debug("Sentry disabled (sentry.enabled is false)")
            return
        if not config.dsn:
            logger.warning("Sentry enabled but no DSN configured")
            return
        if not _sentry_available:
            logger.warning("Sentry enabled but sentry_sdk is not installed")
            return

        ci_ctx = detect_ci_context()
        environment = config.environment or ("ci" if ci_ctx.is_ci else "local")

        init_kwargs: dict[str, Any] = {
            "dsn": config.dsn,
            "release": f"getnit@{__version__}",
            "environment": environment,
            "traces_sample_rate": config.traces_sample_rate,
            "profiles_sample_rate": config.profiles_sample_rate,
            "send_default_pii": False,
            "server_name": "",
            "before_send": _before_send,
            "before_send_transaction": _before_send_transaction,
            "in_app_include": ["nit"],
            "in_app_exclude": ["litellm", "sentry_sdk"],
            "integrations": [
                _LoggingIntegration(
                    level=logging.INFO,
                    event_level=logging.ERROR,
                ),
            ],
        }

        if config.enable_logs:
            init_kwargs["enable_logs"] = True

        sentry_sdk.init(**init_kwargs)

        _initialized["value"] = True
        logger.info(
            "Sentry initialized (env=%s, tracing=%.2f, profiling=%.2f, logs=%s)",
            environment,
            config.traces_sample_rate,
            config.profiles_sample_rate,
            config.enable_logs,
        )


def is_sentry_enabled() -> bool:
    """Return whether Sentry has been successfully initialized."""
    return _initialized["value"]


# ---------------------------------------------------------------------------
# Privacy scrubbing
# ---------------------------------------------------------------------------


def _scrub_path(path: str) -> str:
    """Replace user home directory in paths."""
    return _PATH_HOME_RE.sub("/~", path)


def _scrub_string(value: str) -> str:
    """Remove sensitive patterns from a string."""
    return _SENSITIVE_PATTERN.sub("[REDACTED]", value)


def _scrub_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Scrub sensitive keys and values from a dict."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _SENSITIVE_KEYS:
            result[key] = "[REDACTED]"
        elif isinstance(value, str):
            result[key] = _scrub_string(value)
        elif isinstance(value, dict):
            result[key] = _scrub_dict(value)
        else:
            result[key] = value
    return result


def _scrub_event(event: dict[str, Any]) -> dict[str, Any]:
    """Deep-scrub an event dict for sensitive data."""
    exception = event.get("exception")
    if isinstance(exception, dict):
        for value in exception.get("values", []):
            stacktrace = value.get("stacktrace")
            if isinstance(stacktrace, dict):
                for frame in stacktrace.get("frames", []):
                    # Remove local variables (may contain source code/keys)
                    frame.pop("vars", None)
                    filename = frame.get("filename")
                    if isinstance(filename, str):
                        frame["filename"] = _scrub_path(filename)
                    abs_path = frame.get("abs_path")
                    if isinstance(abs_path, str):
                        frame["abs_path"] = _scrub_path(abs_path)

    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        for crumb in breadcrumbs.get("values", []):
            msg = crumb.get("message")
            if isinstance(msg, str):
                crumb["message"] = _scrub_string(msg)
            crumb_data = crumb.get("data")
            if isinstance(crumb_data, dict):
                crumb["data"] = _scrub_dict(crumb_data)

    tags = event.get("tags")
    if isinstance(tags, dict):
        event["tags"] = _scrub_dict(tags)

    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = _scrub_dict(extra)

    # Never send hostname
    event.pop("server_name", None)

    return event


def _before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Scrub sensitive data from error events before sending."""
    return _scrub_event(event)


def _before_send_transaction(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Scrub sensitive data from transaction events before sending."""
    return _scrub_event(event)


# ---------------------------------------------------------------------------
# Metrics helpers (no-op when disabled)
# ---------------------------------------------------------------------------


def record_metric_count(name: str, value: int = 1, **attrs: str | int | float) -> None:
    """Emit a Sentry counter metric. No-op if Sentry is disabled."""
    if not _initialized["value"]:
        return
    sentry_sdk.metrics.count(name, float(value), attributes=dict(attrs) if attrs else None)


def record_metric_distribution(
    name: str, value: float, unit: str = "", **attrs: str | int | float
) -> None:
    """Emit a Sentry distribution metric. No-op if Sentry is disabled."""
    if not _initialized["value"]:
        return
    sentry_sdk.metrics.distribution(
        name, value, unit=unit or None, attributes=dict(attrs) if attrs else None
    )


def record_metric_gauge(
    name: str, value: float, unit: str = "", **attrs: str | int | float
) -> None:
    """Emit a Sentry gauge metric. No-op if Sentry is disabled."""
    if not _initialized["value"]:
        return
    sentry_sdk.metrics.gauge(
        name, value, unit=unit or None, attributes=dict(attrs) if attrs else None
    )


# ---------------------------------------------------------------------------
# Tracing helpers
# ---------------------------------------------------------------------------


class _NoOpSpan:
    """Context manager that does nothing when Sentry is disabled."""

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    def set_data(self, key: str, value: Any) -> None:
        """No-op data setter."""

    def set_status(self, status: str) -> None:
        """No-op status setter."""


def start_span(op: str, description: str) -> Any:
    """Start a new Sentry span. Returns a context manager.

    Returns a no-op context manager if Sentry is disabled.
    """
    if not _initialized["value"]:
        return _NoOpSpan()
    return sentry_sdk.start_span(op=op, description=description)
