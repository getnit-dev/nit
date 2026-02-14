"""Tests for PromptRecorder (JSONL prompt storage)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nit.llm.engine import GenerationRequest, LLMMessage, LLMResponse
from nit.memory.prompt_store import PromptRecorder, get_prompt_recorder


@pytest.fixture
def recorder(tmp_path: Path) -> PromptRecorder:
    return PromptRecorder(tmp_path)


def _make_request(
    *,
    messages: list[LLMMessage] | None = None,
    metadata: dict[str, object] | None = None,
) -> GenerationRequest:
    return GenerationRequest(
        messages=messages
        or [
            LLMMessage(role="system", content="You are a test generator."),
            LLMMessage(role="user", content="Generate tests."),
        ],
        temperature=0.2,
        max_tokens=4096,
        metadata=metadata or {},  # type: ignore[arg-type]
    )


def _make_response(
    *,
    text: str = "def test_foo(): pass",
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


class TestPromptRecorder:
    """Tests for basic recording and retrieval."""

    def test_record_creates_jsonl_file(self, recorder: PromptRecorder) -> None:
        request = _make_request()
        response = _make_response()
        record_id = recorder.record(request, response, duration_ms=1000)

        assert record_id
        prompts_file = recorder._history_dir / "prompts.jsonl"
        assert prompts_file.exists()

        lines = prompts_file.read_text().strip().splitlines()
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["id"] == record_id
        assert data["model"] == "gpt-4o"
        assert data["prompt_tokens"] == 100
        assert data["completion_tokens"] == 50

    def test_record_extracts_lineage_from_metadata(self, recorder: PromptRecorder) -> None:
        request = _make_request(
            metadata={
                "nit_source_file": "src/app.py",
                "nit_template_name": "pytest_prompt",
                "nit_builder_name": "unit_builder",
                "nit_framework": "pytest",
            }
        )
        response = _make_response()
        record_id = recorder.record(request, response, duration_ms=500)

        record = recorder.get_by_id(record_id)
        assert record is not None
        assert record.lineage is not None
        assert record.lineage.source_file == "src/app.py"
        assert record.lineage.template_name == "pytest_prompt"
        assert record.lineage.builder_name == "unit_builder"

    def test_record_filters_lineage_from_stored_metadata(self, recorder: PromptRecorder) -> None:
        request = _make_request(
            metadata={
                "nit_source_file": "x.py",
                "nit_template_name": "t",
                "nit_builder_name": "b",
                "custom_key": "custom_value",
            }
        )
        response = _make_response()
        record_id = recorder.record(request, response, duration_ms=100)

        record = recorder.get_by_id(record_id)
        assert record is not None
        assert "custom_key" in record.metadata
        assert "nit_source_file" not in record.metadata

    def test_record_failure(self, recorder: PromptRecorder) -> None:
        request = _make_request()
        record_id = recorder.record_failure(request, duration_ms=100, error_message="API error")

        record = recorder.get_by_id(record_id)
        assert record is not None
        assert record.outcome == "error"
        assert record.error_message == "API error"
        assert record.response_text == ""

    def test_read_all_returns_most_recent_first(self, recorder: PromptRecorder) -> None:
        request = _make_request()
        ids = []
        for _ in range(3):
            response = _make_response()
            ids.append(recorder.record(request, response, duration_ms=100))

        records = recorder.read_all()
        assert len(records) == 3
        # Most recent first
        assert records[0].id == ids[2]
        assert records[2].id == ids[0]

    def test_read_all_with_limit(self, recorder: PromptRecorder) -> None:
        request = _make_request()
        for _ in range(5):
            recorder.record(request, _make_response(), duration_ms=100)

        records = recorder.read_all(limit=2)
        assert len(records) == 2

    def test_read_all_filter_by_model(self, recorder: PromptRecorder) -> None:
        request = _make_request()
        recorder.record(request, _make_response(model="gpt-4o"), duration_ms=100)
        recorder.record(request, _make_response(model="claude-sonnet"), duration_ms=100)

        records = recorder.read_all(model="claude")
        assert len(records) == 1
        assert records[0].model == "claude-sonnet"

    def test_read_all_filter_by_template(self, recorder: PromptRecorder) -> None:
        req1 = _make_request(
            metadata={
                "nit_template_name": "pytest_prompt",
                "nit_source_file": "a.py",
                "nit_builder_name": "b",
            }
        )
        req2 = _make_request(
            metadata={
                "nit_template_name": "vitest",
                "nit_source_file": "b.py",
                "nit_builder_name": "b",
            }
        )
        recorder.record(req1, _make_response(), duration_ms=100)
        recorder.record(req2, _make_response(), duration_ms=100)

        records = recorder.read_all(template="vitest")
        assert len(records) == 1
        assert records[0].lineage is not None
        assert records[0].lineage.template_name == "vitest"

    def test_read_all_filter_by_outcome(self, recorder: PromptRecorder) -> None:
        request = _make_request()
        id1 = recorder.record(request, _make_response(), duration_ms=100)
        recorder.record(request, _make_response(), duration_ms=100)

        recorder.update_outcome(id1, "success")

        records = recorder.read_all(outcome="success")
        assert len(records) == 1
        assert records[0].id == id1

    def test_get_by_id_not_found(self, recorder: PromptRecorder) -> None:
        assert recorder.get_by_id("nonexistent") is None

    def test_empty_file_returns_empty(self, recorder: PromptRecorder) -> None:
        records = recorder.read_all()
        assert records == []


class TestOutcomeUpdates:
    """Tests for outcome update mechanism."""

    def test_update_outcome_merges_on_read(self, recorder: PromptRecorder) -> None:
        request = _make_request()
        record_id = recorder.record(request, _make_response(), duration_ms=100)

        # Initially pending
        record = recorder.get_by_id(record_id)
        assert record is not None
        assert record.outcome == "pending"

        # Update outcome
        recorder.update_outcome(record_id, "success", validation_attempts=2)

        record = recorder.get_by_id(record_id)
        assert record is not None
        assert record.outcome == "success"
        assert record.validation_attempts == 2

    def test_update_outcome_in_read_all(self, recorder: PromptRecorder) -> None:
        request = _make_request()
        record_id = recorder.record(request, _make_response(), duration_ms=100)
        recorder.update_outcome(record_id, "test_failure", error_message="assert failed")

        records = recorder.read_all()
        assert len(records) == 1
        assert records[0].outcome == "test_failure"
        assert records[0].error_message == "assert failed"


class TestSingleton:
    """Tests for singleton management."""

    def test_get_prompt_recorder_returns_same_instance(self, tmp_path: Path) -> None:
        r1 = get_prompt_recorder(tmp_path)
        r2 = get_prompt_recorder(tmp_path)
        assert r1 is r2
