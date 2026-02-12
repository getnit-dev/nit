"""Usage tracking via LiteLLM callbacks and CLI wrapper reporting.

This module batches usage events and ships them to the platform ingest API.
It is intentionally resilient: failures are logged and dropped after retries,
never raising into generation flow.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import litellm
import requests
from litellm.integrations.custom_logger import CustomLogger

from nit.memory.analytics_collector import get_analytics_collector
from nit.utils.platform_client import build_usage_url, get_platform_api_key

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 20
_DEFAULT_FLUSH_INTERVAL_SECONDS = 5.0
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 8.0
_HTTP_SUCCESS_MIN = 200
_HTTP_SUCCESS_MAX = 300

_ALLOWED_SOURCES = {"api", "platform", "byok", "cli"}


@dataclass
class UsageReporterConfig:
    """Runtime configuration for posting usage events to the platform."""

    platform_url: str
    ingest_token: str
    user_id: str
    project_id: str | None
    key_hash: str | None
    batch_size: int
    flush_interval_seconds: float
    max_retries: int
    request_timeout_seconds: float

    @property
    def enabled(self) -> bool:
        # Note: user_id and project_id are extracted from the token on the backend
        return bool(self.platform_url and self.ingest_token)

    @classmethod
    def from_env(cls) -> UsageReporterConfig:
        platform_url = os.environ.get("NIT_PLATFORM_URL", "").strip().rstrip("/")
        ingest_token = (
            os.environ.get("NIT_PLATFORM_INGEST_TOKEN", "").strip() or get_platform_api_key()
        )
        user_id = os.environ.get("NIT_PLATFORM_USER_ID", "").strip()
        project_id = os.environ.get("NIT_PLATFORM_PROJECT_ID", "").strip() or None
        key_hash = os.environ.get("NIT_PLATFORM_KEY_HASH", "").strip() or None

        batch_size = _parse_int_env("NIT_USAGE_BATCH_SIZE", _DEFAULT_BATCH_SIZE, minimum=1)
        flush_interval = _parse_float_env(
            "NIT_USAGE_FLUSH_INTERVAL_SECONDS",
            _DEFAULT_FLUSH_INTERVAL_SECONDS,
            minimum=0.1,
        )
        max_retries = _parse_int_env(
            "NIT_USAGE_RETRY_MAX_ATTEMPTS", _DEFAULT_MAX_RETRIES, minimum=1
        )
        request_timeout = _parse_float_env(
            "NIT_USAGE_REQUEST_TIMEOUT_SECONDS",
            _DEFAULT_REQUEST_TIMEOUT_SECONDS,
            minimum=1.0,
        )

        return cls(
            platform_url=platform_url,
            ingest_token=ingest_token,
            user_id=user_id,
            project_id=project_id,
            key_hash=key_hash,
            batch_size=batch_size,
            flush_interval_seconds=flush_interval,
            max_retries=max_retries,
            request_timeout_seconds=request_timeout,
        )


def _parse_int_env(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default

    try:
        parsed = int(raw)
    except ValueError:
        return default

    return max(parsed, minimum)


def _parse_float_env(name: str, default: float, *, minimum: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default

    try:
        parsed = float(raw)
    except ValueError:
        return default

    return max(parsed, minimum)


def _safe_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    if hasattr(value, "__dict__"):
        return cast("dict[str, Any]", vars(value))
    return {}


def _safe_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default

    if parsed < 0:
        return 0.0

    return parsed


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default

    return max(parsed, 0)


def _safe_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value != 0

    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "hit"}:
            return True
        if lowered in {"0", "false", "no", "miss"}:
            return False

    return default


def _safe_iso_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()

    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(UTC).isoformat()
        except ValueError:
            pass

    return datetime.now(UTC).isoformat()


def _infer_provider(model: str, fallback: str = "unknown") -> str:
    lower_model = model.lower()

    if "/" in lower_model:
        provider = lower_model.split("/", 1)[0]
        if provider:
            return provider

    if "claude" in lower_model:
        return "anthropic"

    if "gpt" in lower_model or "o1" in lower_model or "o3" in lower_model:
        return "openai"

    if "gemini" in lower_model:
        return "google"

    if "mistral" in lower_model:
        return "mistral"

    return fallback


def _normalize_source(value: str | None) -> str:
    source = (value or "").strip().lower()
    return source if source in _ALLOWED_SOURCES else "byok"


def _pick_metadata_value(metadata: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pick_scalar_metadata(value: Any) -> str | int | float | bool | None:
    if isinstance(value, (str, int, float, bool)):
        return value
    return None


@dataclass
class MetadataParams:
    """Parameters for building LiteLLM metadata."""

    source: str
    """Usage source identifier (e.g. ``"api"``, ``"byok"``, ``"cli"``)."""

    mode: str
    """Usage mode (e.g. ``"builtin"``)."""

    provider: str | None = None
    """Optional LLM provider name."""

    model: str | None = None
    """Optional model name."""

    emit_usage: bool = True
    """Whether to emit usage events for this request."""

    overrides: Mapping[str, Any] | None = None
    """Optional metadata overrides."""


@dataclass
class CLIUsageEvent:
    """Parameters for a CLI-originated usage event."""

    provider: str
    """LLM provider name."""

    model: str
    """Model name."""

    prompt_tokens: int
    """Number of prompt tokens."""

    completion_tokens: int
    """Number of completion tokens."""

    cost_usd: float = 0.0
    """Cost in USD."""

    cache_hit: bool = False
    """Whether this was a cache hit."""

    source: str = "cli"
    """Usage source identifier."""

    key_hash: str | None = None
    """Optional key hash."""

    duration_ms: int | None = None
    """Optional duration in milliseconds."""

    metadata: Mapping[str, Any] | None = None
    """Optional metadata."""

    timestamp: str | None = None
    """Optional ISO timestamp."""


class BatchedUsageReporter:
    """Buffers usage events and POSTs them in batches to the platform."""

    def __init__(self, config: UsageReporterConfig) -> None:
        self._config = config
        self._session_id = os.environ.get("NIT_SESSION_ID", "").strip() or str(uuid.uuid4())
        self._lock = threading.Lock()
        self._buffer: list[dict[str, Any]] = []
        self._last_flush = time.monotonic()

        if self._config.enabled:
            atexit.register(self.flush)

    @property
    def session_id(self) -> str:
        return self._session_id

    def build_metadata(
        self,
        params: MetadataParams,
    ) -> dict[str, str | int | float | bool]:
        metadata: dict[str, str | int | float | bool] = {
            "nit_session_id": self._session_id,
            "nit_usage_source": _normalize_source(params.source),
            "nit_usage_mode": params.mode,
            "nit_usage_emit": params.emit_usage,
        }

        # Include user_id and project_id if available from config
        if self._config.user_id:
            metadata["nit_user_id"] = self._config.user_id

        if self._config.project_id:
            metadata["nit_project_id"] = self._config.project_id

        if self._config.key_hash:
            metadata["nit_key_hash"] = self._config.key_hash

        if params.provider:
            metadata["nit_provider"] = params.provider

        if params.model:
            metadata["nit_model"] = params.model

        if params.overrides:
            for key, value in params.overrides.items():
                scalar = _pick_scalar_metadata(value)
                if scalar is not None:
                    metadata[str(key)] = scalar

        return metadata

    def enqueue(self, event: dict[str, Any]) -> None:
        if not self._config.enabled:
            return

        batch: list[dict[str, Any]] = []
        with self._lock:
            self._buffer.append(event)
            should_flush = (
                len(self._buffer) >= self._config.batch_size
                or (time.monotonic() - self._last_flush) >= self._config.flush_interval_seconds
            )
            if should_flush:
                batch = self._drain_unlocked()

        if batch:
            self._post_batch(batch)

    def flush(self) -> None:
        if not self._config.enabled:
            return

        with self._lock:
            batch = self._drain_unlocked()

        if batch:
            self._post_batch(batch)

    def _drain_unlocked(self) -> list[dict[str, Any]]:
        if not self._buffer:
            self._last_flush = time.monotonic()
            return []

        drained = self._buffer
        self._buffer = []
        self._last_flush = time.monotonic()
        return drained

    def _post_batch(self, events: list[dict[str, Any]]) -> None:
        endpoint = build_usage_url(self._config.platform_url)
        headers = {
            "Authorization": f"Bearer {self._config.ingest_token}",
            "Content-Type": "application/json",
        }
        payload = {"events": events}

        last_error: str | None = None
        for attempt in range(self._config.max_retries):
            try:
                response = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self._config.request_timeout_seconds,
                )
                if _HTTP_SUCCESS_MIN <= response.status_code < _HTTP_SUCCESS_MAX:
                    return

                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            except requests.RequestException as exc:
                last_error = str(exc)

            if attempt + 1 < self._config.max_retries:
                backoff = min(0.5 * (2**attempt), 4.0)
                time.sleep(backoff)

        logger.warning(
            "Dropping %d usage events after %d attempts: %s",
            len(events),
            self._config.max_retries,
            last_error or "unknown error",
        )


_REPORTER_LOCK = threading.Lock()


@dataclass
class SessionUsageStats:
    """Tracks aggregated LLM usage for the current session."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    request_count: int = 0

    def add_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
    ) -> None:
        """Add usage from a single LLM request."""
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += prompt_tokens + completion_tokens
        self.total_cost_usd += cost_usd
        self.request_count += 1

    def reset(self) -> None:
        """Reset all counters to zero."""
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0
        self.request_count = 0


@dataclass
class _SingletonState:
    reporter: BatchedUsageReporter | None = None
    callback: NitUsageCallback | None = None
    session_stats: SessionUsageStats = field(default_factory=SessionUsageStats)


_SINGLETONS = _SingletonState()


def get_usage_reporter() -> BatchedUsageReporter:
    with _REPORTER_LOCK:
        if _SINGLETONS.reporter is None:
            _SINGLETONS.reporter = BatchedUsageReporter(UsageReporterConfig.from_env())
        return _SINGLETONS.reporter


def build_litellm_metadata(
    params: MetadataParams,
) -> dict[str, str | int | float | bool]:
    """Build metadata payload for LiteLLM request kwargs."""
    reporter = get_usage_reporter()
    return reporter.build_metadata(params)


def report_cli_usage_event(usage: CLIUsageEvent) -> None:
    """Record a usage event originating from a CLI wrapper call."""
    reporter = get_usage_reporter()
    if not reporter._config.enabled:
        return

    # Include userId and projectId if available from config
    event: dict[str, Any] = {
        "keyHash": usage.key_hash or reporter._config.key_hash,
        "model": usage.model,
        "provider": usage.provider,
        "promptTokens": max(usage.prompt_tokens, 0),
        "completionTokens": max(usage.completion_tokens, 0),
        "costUsd": max(usage.cost_usd, 0.0),
        "marginUsd": 0.0,
        "cacheHit": bool(usage.cache_hit),
        "source": _normalize_source(usage.source),
        "timestamp": _safe_iso_timestamp(usage.timestamp),
    }

    if reporter._config.user_id:
        event["userId"] = reporter._config.user_id

    if reporter._config.project_id:
        event["projectId"] = reporter._config.project_id

    if usage.duration_ms is not None and usage.duration_ms >= 0:
        event["durationMs"] = int(usage.duration_ms)

    if usage.metadata:
        event["metadata"] = {
            key: value
            for key, value in usage.metadata.items()
            if isinstance(value, (str, int, float, bool))
        }

    reporter.enqueue(event)


class NitUsageCallback(CustomLogger):
    """LiteLLM CustomLogger that emits normalized usage events."""

    def __init__(
        self,
        reporter: BatchedUsageReporter | None = None,
        project_root: Path | None = None,
    ) -> None:
        super().__init__()
        self._reporter = reporter or get_usage_reporter()
        self._project_root = project_root

    def log_success_event(
        self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        event = self._build_event(kwargs, response_obj, start_time, end_time)
        if event is not None:
            self._reporter.enqueue(event)
            # Track session stats
            with _REPORTER_LOCK:
                _SINGLETONS.session_stats.add_usage(
                    prompt_tokens=event.get("promptTokens", 0),
                    completion_tokens=event.get("completionTokens", 0),
                    cost_usd=event.get("costUsd", 0.0),
                )

            # NEW: Record to local analytics history
            if self._project_root:
                try:
                    collector = get_analytics_collector(self._project_root)
                    collector.record_llm_usage(
                        provider=event.get("provider", "unknown"),
                        model=event.get("model", "unknown"),
                        prompt_tokens=event.get("promptTokens", 0),
                        completion_tokens=event.get("completionTokens", 0),
                        cost_usd=event.get("costUsd"),
                        duration_ms=event.get("durationMs"),
                        cached_tokens=0,  # Could extract from usage if available
                        metadata={
                            "source": event.get("source"),
                            "session_id": event.get("sessionId"),
                            "cache_hit": event.get("cacheHit", False),
                        },
                    )
                except Exception:
                    logger.exception("Failed to record LLM usage to local analytics")

            self._emit_sentry_metrics(event)

    async def async_log_success_event(
        self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        event = self._build_event(kwargs, response_obj, start_time, end_time)
        if event is not None:
            await asyncio.to_thread(self._reporter.enqueue, event)
            # Track session stats
            with _REPORTER_LOCK:
                _SINGLETONS.session_stats.add_usage(
                    prompt_tokens=event.get("promptTokens", 0),
                    completion_tokens=event.get("completionTokens", 0),
                    cost_usd=event.get("costUsd", 0.0),
                )

            # NEW: Record to local analytics history
            if self._project_root:
                try:
                    collector = get_analytics_collector(self._project_root)
                    await asyncio.to_thread(
                        collector.record_llm_usage,
                        provider=event.get("provider", "unknown"),
                        model=event.get("model", "unknown"),
                        prompt_tokens=event.get("promptTokens", 0),
                        completion_tokens=event.get("completionTokens", 0),
                        cost_usd=event.get("costUsd"),
                        duration_ms=event.get("durationMs"),
                        cached_tokens=0,
                        metadata={
                            "source": event.get("source"),
                            "session_id": event.get("sessionId"),
                            "cache_hit": event.get("cacheHit", False),
                        },
                    )
                except Exception:
                    logger.exception("Failed to record LLM usage to local analytics")

            self._emit_sentry_metrics(event)

    @staticmethod
    def _emit_sentry_metrics(event: dict[str, Any]) -> None:
        """Emit Sentry metrics for an LLM usage event. No-op if Sentry is disabled."""
        from nit.telemetry.sentry_integration import (
            record_metric_count,
            record_metric_distribution,
        )

        provider = event.get("provider", "unknown")
        model = event.get("model", "unknown")

        record_metric_count("nit.llm.requests", provider=provider, model=model)

        prompt_tokens = event.get("promptTokens", 0)
        if prompt_tokens:
            record_metric_distribution(
                "nit.llm.prompt_tokens",
                float(prompt_tokens),
                unit="token",
                provider=provider,
                model=model,
            )

        completion_tokens = event.get("completionTokens", 0)
        if completion_tokens:
            record_metric_distribution(
                "nit.llm.completion_tokens",
                float(completion_tokens),
                unit="token",
                provider=provider,
                model=model,
            )

        duration_ms = event.get("durationMs")
        if duration_ms:
            record_metric_distribution(
                "nit.llm.latency_ms",
                float(duration_ms),
                unit="millisecond",
                provider=provider,
                model=model,
            )

    def _build_event(
        self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any
    ) -> dict[str, Any] | None:
        if not isinstance(kwargs, dict):
            return None

        metadata = _safe_record(kwargs.get("metadata"))
        litellm_params = _safe_record(kwargs.get("litellm_params"))
        litellm_metadata = _safe_record(litellm_params.get("metadata"))
        if litellm_metadata:
            metadata = {**metadata, **litellm_metadata}

        if not _safe_bool(metadata.get("nit_usage_emit", True), default=True):
            return None

        model = (
            _safe_str(_get_field(response_obj, "model"))
            or _safe_str(kwargs.get("model"))
            or _safe_str(metadata.get("nit_model"))
            or "unknown"
        )

        provider = (
            _safe_str(kwargs.get("custom_llm_provider"))
            or _safe_str(litellm_params.get("custom_llm_provider"))
            or _safe_str(metadata.get("nit_provider"))
            or _infer_provider(model)
        )

        usage = _safe_record(_get_field(response_obj, "usage"))
        prompt_tokens = _safe_int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
        completion_tokens = _safe_int(usage.get("completion_tokens", usage.get("output_tokens", 0)))

        response_cost = _safe_float(kwargs.get("response_cost"), default=-1.0)
        if response_cost < 0:
            response_cost = _safe_float(usage.get("cost", usage.get("cost_usd", 0.0)))

        cache_hit = _safe_bool(
            kwargs.get(
                "cache_hit", _get_field(response_obj, "_hidden_params", {}).get("cache_hit")
            ),
            default=False,
        )

        # Extract userId and projectId from metadata or config
        source = _normalize_source(
            _pick_metadata_value(metadata, "nit_usage_source", "source")
            or kwargs.get("source")
            or "byok"
        )

        end_ts = _safe_iso_timestamp(end_time)

        duration_ms = _compute_duration_ms(start_time, end_time)

        event: dict[str, Any] = {
            "keyHash": (
                _pick_metadata_value(metadata, "nit_key_hash", "key_hash")
                or self._reporter._config.key_hash
            ),
            "model": model,
            "provider": provider,
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "costUsd": response_cost,
            "marginUsd": 0.0,
            "cacheHit": cache_hit,
            "source": source,
            "timestamp": end_ts,
            "durationMs": duration_ms,
        }

        # Include userId and projectId if available
        user_id = (
            _pick_metadata_value(metadata, "nit_user_id", "user_id")
            or self._reporter._config.user_id
        )
        if user_id:
            event["userId"] = user_id

        project_id = (
            _pick_metadata_value(metadata, "nit_project_id", "project_id")
            or self._reporter._config.project_id
        )
        if project_id:
            event["projectId"] = project_id

        session_id = _pick_metadata_value(metadata, "nit_session_id") or self._reporter.session_id
        if session_id:
            event["sessionId"] = session_id

        return event


def _get_field(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)

    return getattr(value, field, default)


def _compute_duration_ms(start_time: Any, end_time: Any) -> int:
    start = _to_datetime(start_time)
    end = _to_datetime(end_time)
    if start is None or end is None:
        return 0

    duration = (end - start).total_seconds() * 1000
    return max(int(duration), 0)


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC)

    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(UTC)
        except ValueError:
            return None

    return None


def ensure_nit_usage_callback_registered(
    project_root: Path | None = None,
) -> NitUsageCallback:
    """Register the singleton callback in ``litellm.callbacks`` if needed.

    Args:
        project_root: Optional project root for local analytics tracking.

    Returns:
        The registered NitUsageCallback instance.
    """
    with _REPORTER_LOCK:
        if _SINGLETONS.reporter is None:
            _SINGLETONS.reporter = BatchedUsageReporter(UsageReporterConfig.from_env())

        if _SINGLETONS.callback is None:
            _SINGLETONS.callback = NitUsageCallback(
                reporter=_SINGLETONS.reporter,
                project_root=project_root,
            )

        if all(existing is not _SINGLETONS.callback for existing in litellm.callbacks):
            litellm.callbacks.append(_SINGLETONS.callback)

        callback = _SINGLETONS.callback
        if callback is None:
            raise RuntimeError("Failed to initialize Nit usage callback")
        return callback


def get_session_usage_stats() -> SessionUsageStats:
    """Get the current session's aggregated LLM usage statistics."""
    with _REPORTER_LOCK:
        return SessionUsageStats(
            prompt_tokens=_SINGLETONS.session_stats.prompt_tokens,
            completion_tokens=_SINGLETONS.session_stats.completion_tokens,
            total_tokens=_SINGLETONS.session_stats.total_tokens,
            total_cost_usd=_SINGLETONS.session_stats.total_cost_usd,
            request_count=_SINGLETONS.session_stats.request_count,
        )


def reset_session_usage_stats() -> None:
    """Reset the session usage statistics to zero."""
    with _REPORTER_LOCK:
        _SINGLETONS.session_stats.reset()


def teardown_usage_singletons() -> None:
    """Flush pending events and reset all singleton state.

    Call this at the end of a CLI invocation to ensure buffered events
    are shipped and no stale state leaks across invocations in long-lived
    processes (e.g. test suites, daemon mode).
    """
    with _REPORTER_LOCK:
        if _SINGLETONS.reporter is not None:
            _SINGLETONS.reporter.flush()

        # Remove callback from litellm if registered
        if _SINGLETONS.callback is not None:
            litellm.callbacks = [cb for cb in litellm.callbacks if cb is not _SINGLETONS.callback]

        _SINGLETONS.reporter = None
        _SINGLETONS.callback = None
        _SINGLETONS.session_stats.reset()


__all__ = [
    "CLIUsageEvent",
    "MetadataParams",
    "NitUsageCallback",
    "SessionUsageStats",
    "build_litellm_metadata",
    "ensure_nit_usage_callback_registered",
    "get_session_usage_stats",
    "get_usage_reporter",
    "report_cli_usage_event",
    "reset_session_usage_stats",
    "teardown_usage_singletons",
]
