"""Prompt replay engine — replay prompts against different models and compare outputs."""

from __future__ import annotations

import asyncio
import difflib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.llm.engine import GenerationRequest, LLMMessage
from nit.llm.factory import create_engine

if TYPE_CHECKING:
    from nit.llm.config import LLMConfig
    from nit.memory.prompt_store import PromptRecorder
    from nit.models.prompt_record import PromptRecord


@dataclass
class ReplayResult:
    """Result of replaying a prompt with a different model."""

    original: PromptRecord
    replay: PromptRecord
    diff: str


class PromptReplayer:
    """Replays recorded prompts against different models."""

    def __init__(
        self,
        recorder: PromptRecorder,
        llm_config: LLMConfig,
    ) -> None:
        self._recorder = recorder
        self._llm_config = llm_config

    async def replay(
        self,
        record_id: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> ReplayResult:
        """Replay a recorded prompt, optionally with a different model."""
        original = self._recorder.get_by_id(record_id)
        if original is None:
            msg = f"Prompt record not found: {record_id}"
            raise ValueError(msg)

        messages = [LLMMessage(role=m["role"], content=m["content"]) for m in original.messages]

        resolved_model = model or original.model
        resolved_temp = temperature if temperature is not None else original.temperature

        request = GenerationRequest(
            messages=messages,
            model=resolved_model,
            temperature=resolved_temp,
            max_tokens=original.max_tokens,
        )

        # Create engine for the target model (tracking disabled for replays)
        engine = create_engine(
            self._llm_config,
            enable_tracking=False,
        )

        started = time.monotonic()
        response = await engine.generate(request)
        duration_ms = int((time.monotonic() - started) * 1000)

        # Build replay record
        comparison_group_id = original.comparison_group_id or original.id
        replay_record_id = self._recorder.record(
            request,
            response,
            duration_ms,
            comparison_group_id=comparison_group_id,
        )

        replay_record = self._recorder.get_by_id(replay_record_id)
        if replay_record is None:
            msg = "Failed to retrieve replay record"
            raise RuntimeError(msg)

        response_diff = compute_diff(
            original.response_text,
            response.text,
            f"original ({original.model})",
            f"replay ({resolved_model})",
        )

        return ReplayResult(
            original=original,
            replay=replay_record,
            diff=response_diff,
        )

    async def arena(
        self,
        record_id: str,
        models: list[str],
    ) -> list[ReplayResult]:
        """Run the same prompt against multiple models concurrently."""
        tasks = [self.replay(record_id, model=m) for m in models]
        return list(await asyncio.gather(*tasks, return_exceptions=False))


def compute_diff(
    text_a: str,
    text_b: str,
    label_a: str = "a",
    label_b: str = "b",
) -> str:
    """Compute a unified diff between two texts."""
    lines_a = text_a.splitlines(keepends=True)
    lines_b = text_b.splitlines(keepends=True)

    diff_lines = difflib.unified_diff(lines_a, lines_b, fromfile=label_a, tofile=label_b)
    return "".join(diff_lines)
