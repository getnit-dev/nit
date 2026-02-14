"""Tests for TrackedLLMEngine wrapper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.llm.engine import GenerationRequest, LLMError, LLMMessage, LLMResponse
from nit.llm.tracked_engine import TrackedLLMEngine
from nit.memory.prompt_store import PromptRecorder


@pytest.fixture
def recorder(tmp_path: Path) -> PromptRecorder:
    return PromptRecorder(tmp_path)


def _make_mock_engine(
    *,
    response_text: str = "generated code",
    model: str = "gpt-4o",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> MagicMock:
    engine = MagicMock()
    engine.model_name = model
    engine.count_tokens.return_value = 25

    response = LLMResponse(
        text=response_text,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    engine.generate = AsyncMock(return_value=response)
    return engine


def _make_request(
    metadata: dict[str, object] | None = None,
) -> GenerationRequest:
    return GenerationRequest(
        messages=[
            LLMMessage(role="system", content="System prompt"),
            LLMMessage(role="user", content="User prompt"),
        ],
        temperature=0.2,
        max_tokens=4096,
        metadata=metadata or {},  # type: ignore[arg-type]
    )


class TestTrackedLLMEngine:
    """Tests for the TrackedLLMEngine wrapper."""

    @pytest.mark.asyncio
    async def test_delegates_generate_to_inner(self, recorder: PromptRecorder) -> None:
        inner = _make_mock_engine()
        engine = TrackedLLMEngine(inner, recorder)
        request = _make_request()

        response = await engine.generate(request)

        inner.generate.assert_awaited_once_with(request)
        assert response.text == "generated code"
        assert response.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_records_prompt_on_success(self, recorder: PromptRecorder) -> None:
        inner = _make_mock_engine()
        engine = TrackedLLMEngine(inner, recorder)
        request = _make_request()

        await engine.generate(request)

        records = recorder.read_all()
        assert len(records) == 1
        assert records[0].model == "gpt-4o"
        assert records[0].response_text == "generated code"
        assert records[0].prompt_tokens == 100
        assert records[0].completion_tokens == 50
        assert records[0].duration_ms >= 0

    @pytest.mark.asyncio
    async def test_records_failure_on_error(self, recorder: PromptRecorder) -> None:
        inner = _make_mock_engine()
        inner.generate = AsyncMock(side_effect=LLMError("API failed"))
        engine = TrackedLLMEngine(inner, recorder)
        request = _make_request()

        with pytest.raises(LLMError, match="API failed"):
            await engine.generate(request)

        records = recorder.read_all()
        assert len(records) == 1
        assert records[0].outcome == "error"
        assert records[0].error_message == "API failed"

    @pytest.mark.asyncio
    async def test_extracts_lineage_from_metadata(self, recorder: PromptRecorder) -> None:
        inner = _make_mock_engine()
        engine = TrackedLLMEngine(inner, recorder)
        request = _make_request(
            metadata={
                "nit_source_file": "src/app.py",
                "nit_template_name": "pytest_prompt",
                "nit_builder_name": "unit_builder",
                "nit_framework": "pytest",
            }
        )

        await engine.generate(request)

        records = recorder.read_all()
        assert len(records) == 1
        assert records[0].lineage is not None
        assert records[0].lineage.source_file == "src/app.py"
        assert records[0].lineage.template_name == "pytest_prompt"

    @pytest.mark.asyncio
    async def test_generate_text_delegates_through_generate(self, recorder: PromptRecorder) -> None:
        inner = _make_mock_engine(response_text="hello world")
        engine = TrackedLLMEngine(inner, recorder)

        result = await engine.generate_text("say hello", context="be friendly")

        assert result == "hello world"
        records = recorder.read_all()
        assert len(records) == 1

    def test_model_name_delegates(self, recorder: PromptRecorder) -> None:
        inner = _make_mock_engine(model="claude-opus")
        engine = TrackedLLMEngine(inner, recorder)
        assert engine.model_name == "claude-opus"

    def test_count_tokens_delegates(self, recorder: PromptRecorder) -> None:
        inner = _make_mock_engine()
        engine = TrackedLLMEngine(inner, recorder)
        result = engine.count_tokens("some text")
        assert result == 25
        inner.count_tokens.assert_called_once_with("some text")

    def test_recorder_property(self, recorder: PromptRecorder) -> None:
        inner = _make_mock_engine()
        engine = TrackedLLMEngine(inner, recorder)
        assert engine.recorder is recorder

    @pytest.mark.asyncio
    async def test_recording_failure_does_not_break_generation(
        self, recorder: PromptRecorder
    ) -> None:
        inner = _make_mock_engine()
        engine = TrackedLLMEngine(inner, recorder)
        request = _make_request()

        # Make recording fail
        with patch.object(recorder, "record", side_effect=OSError("disk full")):
            response = await engine.generate(request)

        # Generation should still succeed
        assert response.text == "generated code"
