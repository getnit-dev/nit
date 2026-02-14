"""TrackedLLMEngine — wrapper that records prompt/response pairs.

Wraps any LLMEngine implementation to transparently capture full prompt
records into JSONL storage via PromptRecorder.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from nit.llm.engine import GenerationRequest, LLMEngine, LLMMessage, LLMResponse

if TYPE_CHECKING:
    from nit.memory.prompt_store import PromptRecorder

logger = logging.getLogger(__name__)


class TrackedLLMEngine(LLMEngine):
    """Decorator that records all LLM calls to a PromptRecorder.

    Wraps any ``LLMEngine`` (both ``BuiltinLLM`` and ``CLIToolAdapter``)
    and intercepts ``generate()`` calls to capture prompt/response pairs.
    """

    def __init__(self, inner: LLMEngine, recorder: PromptRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    @property
    def recorder(self) -> PromptRecorder:
        """Access the underlying recorder (used by builders for outcome updates)."""
        return self._recorder

    @property
    def model_name(self) -> str:
        """Return the default model identifier from the wrapped engine."""
        return self._inner.model_name

    async def generate(self, request: GenerationRequest) -> LLMResponse:
        """Delegate to the inner engine and record the prompt/response pair."""
        started = time.monotonic()
        try:
            response = await self._inner.generate(request)
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                self._recorder.record(request, response, duration_ms)
            except Exception:
                logger.exception("Failed to record prompt")
            return response
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                self._recorder.record_failure(request, duration_ms, error_message=str(exc))
            except Exception:
                logger.exception("Failed to record prompt failure")
            raise

    async def generate_text(self, prompt: str, *, context: str = "") -> str:
        """Convenience method that delegates to ``generate()`` (already tracked)."""
        messages: list[LLMMessage] = []
        if context:
            messages.append(LLMMessage(role="system", content=context))
        messages.append(LLMMessage(role="user", content=prompt))

        response = await self.generate(GenerationRequest(messages=messages))
        return response.text

    def count_tokens(self, text: str) -> int:
        """Delegate token counting to the wrapped engine."""
        return self._inner.count_tokens(text)
