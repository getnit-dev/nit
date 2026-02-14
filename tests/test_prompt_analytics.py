"""Tests for prompt analytics queries."""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.llm.engine import GenerationRequest, LLMMessage, LLMResponse
from nit.memory.prompt_analytics import PromptAnalytics
from nit.memory.prompt_store import PromptRecorder


@pytest.fixture
def recorder(tmp_path: Path) -> PromptRecorder:
    return PromptRecorder(tmp_path)


def _make_request(
    *,
    metadata: dict[str, object] | None = None,
) -> GenerationRequest:
    return GenerationRequest(
        messages=[LLMMessage(role="user", content="generate test")],
        temperature=0.2,
        max_tokens=4096,
        metadata=metadata or {},  # type: ignore[arg-type]
    )


def _make_response(
    *,
    text: str = "test code",
    model: str = "gpt-4o",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> LLMResponse:
    return LLMResponse(
        text=text,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


class TestPromptAnalytics:
    """Tests for PromptAnalytics.summary()."""

    def test_empty_history_returns_zeros(self, recorder: PromptRecorder) -> None:
        analytics = PromptAnalytics(recorder)
        stats = analytics.summary(days=30)

        assert stats["total_prompts"] == 0
        assert stats["success_rate"] == 0.0
        assert stats["total_tokens"] == 0
        assert stats["avg_duration_ms"] == 0.0
        assert stats["by_model"] == {}
        assert stats["by_template"] == {}

    def test_single_record_summary(self, recorder: PromptRecorder) -> None:
        request = _make_request()
        response = _make_response(model="gpt-4o", prompt_tokens=80, completion_tokens=40)
        record_id = recorder.record(request, response, 250)
        recorder.update_outcome(record_id, "success")

        analytics = PromptAnalytics(recorder)
        stats = analytics.summary(days=30)

        assert stats["total_prompts"] == 1
        assert stats["success_rate"] == 1.0
        assert stats["total_tokens"] == 120
        assert stats["avg_duration_ms"] == 250.0
        assert "gpt-4o" in stats["by_model"]
        assert stats["by_model"]["gpt-4o"]["count"] == 1

    def test_multiple_models(self, recorder: PromptRecorder) -> None:
        # Record two prompts with different models
        req = _make_request()
        r1 = recorder.record(req, _make_response(model="gpt-4o"), 200)
        recorder.update_outcome(r1, "success")

        r2 = recorder.record(req, _make_response(model="claude-sonnet"), 300)
        recorder.update_outcome(r2, "syntax_error")

        analytics = PromptAnalytics(recorder)
        stats = analytics.summary(days=30)

        assert stats["total_prompts"] == 2
        assert stats["success_rate"] == 0.5
        assert "gpt-4o" in stats["by_model"]
        assert "claude-sonnet" in stats["by_model"]
        assert stats["by_model"]["gpt-4o"]["success_rate"] == 1.0
        assert stats["by_model"]["claude-sonnet"]["success_rate"] == 0.0

    def test_by_template_grouping(self, recorder: PromptRecorder) -> None:
        req_pytest = _make_request(
            metadata={
                "nit_source_file": "app.py",
                "nit_template_name": "pytest_prompt",
                "nit_builder_name": "unit_builder",
                "nit_framework": "pytest",
            }
        )
        req_vitest = _make_request(
            metadata={
                "nit_source_file": "app.ts",
                "nit_template_name": "vitest",
                "nit_builder_name": "unit_builder",
                "nit_framework": "vitest",
            }
        )

        r1 = recorder.record(req_pytest, _make_response(), 100)
        recorder.update_outcome(r1, "success")

        r2 = recorder.record(req_vitest, _make_response(), 150)
        recorder.update_outcome(r2, "success")

        r3 = recorder.record(req_vitest, _make_response(), 200)
        recorder.update_outcome(r3, "syntax_error")

        analytics = PromptAnalytics(recorder)
        stats = analytics.summary(days=30)

        assert "pytest_prompt" in stats["by_template"]
        assert "vitest" in stats["by_template"]
        assert stats["by_template"]["pytest_prompt"]["count"] == 1
        assert stats["by_template"]["pytest_prompt"]["success_rate"] == 1.0
        assert stats["by_template"]["vitest"]["count"] == 2
        assert stats["by_template"]["vitest"]["success_rate"] == 0.5

    def test_token_averaging(self, recorder: PromptRecorder) -> None:
        req = _make_request()
        recorder.record(req, _make_response(prompt_tokens=100, completion_tokens=100), 100)
        recorder.record(req, _make_response(prompt_tokens=200, completion_tokens=200), 300)

        analytics = PromptAnalytics(recorder)
        stats = analytics.summary(days=30)

        assert stats["total_tokens"] == 600
        assert stats["avg_duration_ms"] == 200.0
        assert stats["by_model"]["gpt-4o"]["avg_tokens"] == 300

    def test_records_without_lineage_excluded_from_by_template(
        self, recorder: PromptRecorder
    ) -> None:
        req = _make_request()  # no lineage metadata
        recorder.record(req, _make_response(), 100)

        analytics = PromptAnalytics(recorder)
        stats = analytics.summary(days=30)

        assert stats["total_prompts"] == 1
        assert stats["by_template"] == {}
