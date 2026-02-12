"""Built-in LLM adapter using LiteLLM for multi-provider support."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import litellm
from litellm.exceptions import (
    APIConnectionError as LiteLLMConnectionError,
)
from litellm.exceptions import (
    APIError as LiteLLMAPIError,
)
from litellm.exceptions import (
    AuthenticationError as LiteLLMAuthError,
)
from litellm.exceptions import (
    RateLimitError as LiteLLMRateLimitError,
)

from nit.llm.engine import (
    GenerationRequest,
    LLMAuthError,
    LLMConnectionError,
    LLMEngine,
    LLMError,
    LLMMessage,
    LLMRateLimitError,
    LLMResponse,
)
from nit.llm.usage_callback import (
    MetadataParams,
    build_litellm_metadata,
    ensure_nit_usage_callback_registered,
)
from nit.utils.cache import MemoryCache, content_hash

logger = logging.getLogger(__name__)

# Suppress litellm's noisy default logging
litellm.suppress_debug_info = True


@dataclass
class RetryConfig:
    """Configuration for retry behaviour on transient failures."""

    max_retries: int = 3
    """Maximum number of retry attempts."""

    base_delay: float = 1.0
    """Base delay in seconds for exponential backoff."""

    max_delay: float = 60.0
    """Maximum delay cap in seconds."""

    backoff_factor: float = 2.0
    """Multiplier applied to the delay on each retry."""


@dataclass
class RateLimitConfig:
    """Token-bucket rate limiter configuration."""

    requests_per_minute: int = 60
    """Maximum requests allowed per minute."""


@dataclass
class BuiltinLLMConfig:
    """Configuration for ``BuiltinLLM``."""

    model: str
    """LiteLLM model string (e.g. ``"gpt-4o"``, ``"claude-sonnet-4-5-20250514"``)."""

    provider: str | None = None
    """Optional LLM provider override."""

    api_key: str | None = None
    """Optional API key for the provider."""

    base_url: str | None = None
    """Optional base URL for the API endpoint."""

    retry: RetryConfig = field(default_factory=RetryConfig)
    """Retry configuration for transient failures."""

    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    """Rate limiter configuration."""


@dataclass
class _TokenBucket:
    """Simple token-bucket rate limiter."""

    capacity: int
    tokens: float = 0.0
    last_refill: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.tokens = float(self.capacity)

    async def acquire(self) -> None:
        """Wait until a token is available, then consume one."""
        while True:
            self._refill()
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            # Sleep until at least one token refills
            wait = (1.0 - self.tokens) / (self.capacity / 60.0)
            await asyncio.sleep(min(wait, 1.0))

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.last_refill = now
        self.tokens = min(float(self.capacity), self.tokens + elapsed * (self.capacity / 60.0))


class BuiltinLLM(LLMEngine):
    """LiteLLM-backed engine supporting OpenAI, Anthropic, Ollama, and more.

    This adapter delegates all provider-specific logic to LiteLLM so that
    users can configure any supported provider via a single ``model`` string
    (e.g. ``"gpt-4o"``, ``"claude-sonnet-4-5-20250514"``, ``"ollama/codellama"``).
    """

    def __init__(self, config: BuiltinLLMConfig) -> None:
        self._model = config.model
        self._provider = config.provider
        self._api_key = config.api_key
        self._base_url = config.base_url
        self._retry = config.retry
        self._bucket = _TokenBucket(capacity=config.rate_limit.requests_per_minute)
        self._response_cache: MemoryCache[LLMResponse] = MemoryCache(
            max_size=128, ttl_seconds=1800.0
        )
        ensure_nit_usage_callback_registered()

    # ── Public API ────────────────────────────────────────────────

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, request: GenerationRequest) -> LLMResponse:
        # Check response cache first
        cache_key = self._build_cache_key(request)
        cached = self._response_cache.get(cache_key)
        if cached is not None:
            logger.debug("LLM cache hit for key %s", cache_key[:8])
            return cached

        model = request.model or self._model
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        extra = dict(request.extra)
        metadata_overrides: dict[str, str | int | float | bool] = {}
        metadata_overrides.update(request.metadata)
        extra_metadata = extra.get("metadata")
        if isinstance(extra_metadata, dict):
            metadata_overrides.update(extra_metadata)
            extra.pop("metadata", None)

        usage_source = "byok"
        emit_usage = True

        metadata = build_litellm_metadata(
            MetadataParams(
                source=usage_source,
                mode="builtin",
                provider=self._provider,
                model=model,
                emit_usage=emit_usage,
                overrides=metadata_overrides or None,
            )
        )

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "metadata": metadata,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["api_base"] = self._base_url

        # Note: user_id is extracted from the token on the backend (if proxying)
        # LLM providers can use the token to identify users for rate limiting

        extra_headers_raw = extra.pop("extra_headers", None)
        extra_headers: dict[str, Any] = (
            extra_headers_raw if isinstance(extra_headers_raw, dict) else {}
        )
        extra_headers.setdefault(
            "x-nit-estimated-prompt-tokens",
            str(self._estimate_prompt_tokens(request.messages, model)),
        )
        extra_headers.setdefault(
            "x-nit-estimated-completion-tokens",
            str(max(request.max_tokens, 0)),
        )
        kwargs["extra_headers"] = extra_headers

        kwargs.update(extra)

        raw = await self._call_with_retry(kwargs)
        response = self._parse_response(raw, model)
        self._response_cache.put(cache_key, response)
        return response

    async def generate_text(self, prompt: str, *, context: str = "") -> str:
        messages: list[LLMMessage] = []
        if context:
            messages.append(LLMMessage(role="system", content=context))
        messages.append(LLMMessage(role="user", content=prompt))

        response = await self.generate(GenerationRequest(messages=messages))
        return response.text

    # ── Cache key ─────────────────────────────────────────────────

    def _build_cache_key(self, request: GenerationRequest) -> str:
        """Build a deterministic cache key from the generation request."""
        model = request.model or self._model
        msg_content = "|".join(f"{m.role}:{m.content}" for m in request.messages)
        return content_hash(f"{model}:{request.temperature}:{msg_content}")

    # ── Token counting ────────────────────────────────────────────

    def count_tokens(self, text: str, *, model: str | None = None) -> int:
        """Estimate the token count for *text* using LiteLLM's tokeniser."""
        try:
            count: int = litellm.token_counter(model=model or self._model, text=text)
            return count
        except Exception:
            # Rough fallback: ~4 chars per token
            return len(text) // 4

    # ── Internal helpers ──────────────────────────────────────────

    async def _call_with_retry(self, kwargs: dict[str, Any]) -> Any:
        """Call ``litellm.acompletion`` with rate limiting and retries."""
        last_exc: Exception | None = None

        for attempt in range(self._retry.max_retries + 1):
            await self._bucket.acquire()

            try:
                return await litellm.acompletion(**kwargs)
            except LiteLLMAuthError as exc:
                raise LLMAuthError(str(exc)) from exc
            except LiteLLMRateLimitError as exc:
                last_exc = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Rate limit hit (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    self._retry.max_retries + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            except LiteLLMConnectionError as exc:
                last_exc = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Connection error (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    self._retry.max_retries + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            except LiteLLMAPIError as exc:
                last_exc = exc
                if _is_transient(exc):
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        "Transient API error (attempt %d/%d), retrying in %.1fs",
                        attempt + 1,
                        self._retry.max_retries + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise LLMError(str(exc)) from exc

        # All retries exhausted
        if isinstance(last_exc, LiteLLMRateLimitError):
            raise LLMRateLimitError(str(last_exc)) from last_exc
        if isinstance(last_exc, LiteLLMConnectionError):
            raise LLMConnectionError(str(last_exc)) from last_exc
        raise LLMError(str(last_exc)) from last_exc

    def _backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay for the given attempt."""
        delay = self._retry.base_delay * (self._retry.backoff_factor**attempt)
        return min(delay, self._retry.max_delay)

    def _estimate_prompt_tokens(self, messages: list[LLMMessage], model: str) -> int:
        joined = "\n".join(f"{message.role}: {message.content}" for message in messages)
        return max(self.count_tokens(joined, model=model), 0)

    @staticmethod
    def _parse_response(raw: Any, model: str) -> LLMResponse:
        """Extract an ``LLMResponse`` from a LiteLLM completion result."""
        choice = raw.choices[0]
        usage = raw.usage

        return LLMResponse(
            text=choice.message.content or "",
            model=raw.model or model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )


_SERVER_ERROR_THRESHOLD = 500


def _is_transient(exc: Exception) -> bool:
    """Return ``True`` if the API error looks transient (5xx or timeout)."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status >= _SERVER_ERROR_THRESHOLD:
        return True
    msg = str(exc).lower()
    return "timeout" in msg or "overloaded" in msg
