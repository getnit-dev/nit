"""Tests for PromptRecord, PromptLineage, and OutcomeUpdate data models."""

from __future__ import annotations

from nit.models.prompt_record import OutcomeUpdate, PromptLineage, PromptRecord


class TestPromptLineage:
    """Tests for PromptLineage serialization."""

    def test_round_trip(self) -> None:
        lineage = PromptLineage(
            source_file="src/main.py",
            template_name="pytest_prompt",
            builder_name="unit_builder",
            framework="pytest",
            context_tokens=1200,
            context_sections=["Source File", "Signatures"],
        )
        restored = PromptLineage(
            source_file=lineage.source_file,
            template_name=lineage.template_name,
            builder_name=lineage.builder_name,
            framework=lineage.framework,
            context_tokens=lineage.context_tokens,
            context_sections=list(lineage.context_sections),
        )
        assert restored.source_file == "src/main.py"
        assert restored.template_name == "pytest_prompt"
        assert restored.builder_name == "unit_builder"
        assert restored.framework == "pytest"
        assert restored.context_tokens == 1200
        assert restored.context_sections == ["Source File", "Signatures"]

    def test_defaults(self) -> None:
        lineage = PromptLineage(
            source_file="x.py",
            template_name="t",
            builder_name="b",
        )
        assert lineage.framework == ""
        assert lineage.context_tokens == 0
        assert lineage.context_sections == []


class TestPromptRecord:
    """Tests for PromptRecord serialization and factory."""

    def _make_record(self, **overrides: object) -> PromptRecord:
        defaults: dict[str, object] = {
            "id": "abc-123",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "session_id": "sess-1",
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are a test generator."},
                {"role": "user", "content": "Generate tests for foo.py"},
            ],
            "temperature": 0.2,
            "max_tokens": 4096,
            "metadata": {"custom": "value"},
            "response_text": "def test_foo(): pass",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "duration_ms": 2500,
            "outcome": "success",
            "validation_attempts": 1,
            "error_message": "",
        }
        defaults.update(overrides)
        return PromptRecord(**defaults)  # type: ignore[arg-type]

    def test_to_dict_round_trip(self) -> None:
        record = self._make_record()
        data = record.to_dict()
        restored = PromptRecord.from_dict(data)

        assert restored.id == "abc-123"
        assert restored.model == "gpt-4o"
        assert restored.temperature == 0.2
        assert restored.prompt_tokens == 100
        assert restored.completion_tokens == 50
        assert restored.total_tokens == 150
        assert restored.outcome == "success"
        assert len(restored.messages) == 2

    def test_to_dict_omits_none_lineage(self) -> None:
        record = self._make_record()
        data = record.to_dict()
        assert "lineage" not in data

    def test_to_dict_includes_lineage_when_set(self) -> None:
        lineage = PromptLineage(
            source_file="src/app.py",
            template_name="vitest",
            builder_name="unit_builder",
            framework="vitest",
        )
        record = self._make_record(lineage=lineage)
        data = record.to_dict()
        assert "lineage" in data
        assert data["lineage"]["source_file"] == "src/app.py"

    def test_round_trip_with_lineage(self) -> None:
        lineage = PromptLineage(
            source_file="src/app.py",
            template_name="vitest",
            builder_name="unit_builder",
            framework="vitest",
            context_tokens=500,
        )
        record = self._make_record(lineage=lineage)
        data = record.to_dict()
        restored = PromptRecord.from_dict(data)

        assert restored.lineage is not None
        assert restored.lineage.source_file == "src/app.py"
        assert restored.lineage.template_name == "vitest"
        assert restored.lineage.context_tokens == 500

    def test_comparison_group_id_omitted_when_none(self) -> None:
        record = self._make_record()
        data = record.to_dict()
        assert "comparison_group_id" not in data

    def test_comparison_group_id_included_when_set(self) -> None:
        record = self._make_record(comparison_group_id="group-1")
        data = record.to_dict()
        assert data["comparison_group_id"] == "group-1"

    def test_short_id(self) -> None:
        record = self._make_record(id="abcdefgh-1234-5678")
        assert record.short_id == "abcdefgh"

    def test_new_id_generates_uuid(self) -> None:
        record_id = PromptRecord.new_id()
        assert len(record_id) == 36  # UUID format

    def test_now_iso_returns_timestamp(self) -> None:
        ts = PromptRecord.now_iso()
        assert "T" in ts  # ISO 8601 format


class TestOutcomeUpdate:
    """Tests for OutcomeUpdate serialization."""

    def test_round_trip(self) -> None:
        update = OutcomeUpdate(
            record_id="abc-123",
            outcome="success",
            validation_attempts=2,
            error_message="",
        )
        data = update.to_dict()
        restored = OutcomeUpdate.from_dict(data)

        assert restored.type == "outcome_update"
        assert restored.record_id == "abc-123"
        assert restored.outcome == "success"
        assert restored.validation_attempts == 2

    def test_default_type(self) -> None:
        update = OutcomeUpdate(record_id="x", outcome="error")
        assert update.type == "outcome_update"
