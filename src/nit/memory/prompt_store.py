"""Prompt recording and retrieval using append-only JSONL storage.

Stores full LLM prompt/response records in `.nit/history/prompts.jsonl`.
Thread-safe with a singleton pattern per project root.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from typing import TYPE_CHECKING, Any

from nit.models.prompt_record import OutcomeUpdate, PromptLineage, PromptRecord

if TYPE_CHECKING:
    from pathlib import Path

    from nit.llm.engine import GenerationRequest, LLMResponse

logger = logging.getLogger(__name__)

_PROMPTS_FILE = "prompts.jsonl"


class PromptRecorder:
    """Thread-safe, append-only JSONL recorder for prompt records.

    Records are written to `.nit/history/prompts.jsonl`.
    Outcome updates are appended as separate lines with ``type: outcome_update``
    and merged with their parent record on read.
    """

    def __init__(self, project_root: Path) -> None:
        self._history_dir = project_root / ".nit" / "history"
        self._history_dir.mkdir(parents=True, exist_ok=True)
        self._file_path = self._history_dir / _PROMPTS_FILE
        self._lock = threading.Lock()
        self._session_id = os.environ.get("NIT_SESSION_ID", "").strip() or str(uuid.uuid4())

    @property
    def session_id(self) -> str:
        """Session identifier for grouping prompts from one CLI invocation."""
        return self._session_id

    def record(
        self,
        request: GenerationRequest,
        response: LLMResponse,
        duration_ms: int,
        *,
        comparison_group_id: str | None = None,
    ) -> str:
        """Record a successful prompt/response pair.

        Returns:
            The generated record ID.
        """
        lineage = _extract_lineage(request.metadata)
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        prompt_record = PromptRecord(
            id=PromptRecord.new_id(),
            timestamp=PromptRecord.now_iso(),
            session_id=self._session_id,
            model=response.model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            metadata=_filter_non_lineage_metadata(request.metadata),
            response_text=response.text,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            duration_ms=duration_ms,
            lineage=lineage,
            comparison_group_id=comparison_group_id,
        )

        self._append_json(prompt_record.to_dict())
        return prompt_record.id

    def record_failure(
        self,
        request: GenerationRequest,
        duration_ms: int,
        error_message: str = "",
    ) -> str:
        """Record a failed LLM call.

        Returns:
            The generated record ID.
        """
        lineage = _extract_lineage(request.metadata)
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        prompt_record = PromptRecord(
            id=PromptRecord.new_id(),
            timestamp=PromptRecord.now_iso(),
            session_id=self._session_id,
            model=request.model or "unknown",
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            metadata=_filter_non_lineage_metadata(request.metadata),
            duration_ms=duration_ms,
            lineage=lineage,
            outcome="error",
            error_message=error_message,
        )

        self._append_json(prompt_record.to_dict())
        return prompt_record.id

    def update_outcome(
        self,
        record_id: str,
        outcome: str,
        validation_attempts: int = 0,
        error_message: str = "",
    ) -> None:
        """Append an outcome update for a previously recorded prompt."""
        update = OutcomeUpdate(
            record_id=record_id,
            outcome=outcome,
            validation_attempts=validation_attempts,
            error_message=error_message,
        )
        self._append_json(update.to_dict())

    def read_all(
        self,
        *,
        limit: int = 0,
        since: str | None = None,
        model: str | None = None,
        template: str | None = None,
        outcome: str | None = None,
    ) -> list[PromptRecord]:
        """Read prompt records with optional filters, most recent first.

        Args:
            limit: Maximum number of records to return (0 = unlimited).
            since: Only include records after this ISO timestamp.
            model: Filter by model name (substring match).
            template: Filter by template name (substring match).
            outcome: Filter by outcome value.

        Returns:
            List of PromptRecord instances, most recent first.
        """
        records, updates = self._read_raw()

        # Apply outcome updates to their parent records
        for update in updates:
            record_id = update.record_id
            for rec in records:
                if rec.id == record_id:
                    rec.outcome = update.outcome
                    rec.validation_attempts = update.validation_attempts
                    rec.error_message = update.error_message
                    break

        # Apply filters
        filtered = records
        if since:
            filtered = [r for r in filtered if r.timestamp >= since]
        if model:
            lower_model = model.lower()
            filtered = [r for r in filtered if lower_model in r.model.lower()]
        if template:
            lower_template = template.lower()
            filtered = [
                r
                for r in filtered
                if r.lineage and lower_template in r.lineage.template_name.lower()
            ]
        if outcome:
            filtered = [r for r in filtered if r.outcome == outcome]

        # Sort most recent first
        filtered.sort(key=lambda r: r.timestamp, reverse=True)

        if limit > 0:
            filtered = filtered[:limit]

        return filtered

    def get_by_id(self, record_id: str) -> PromptRecord | None:
        """Find a prompt record by ID."""
        records, updates = self._read_raw()

        target = None
        for rec in records:
            if rec.id == record_id:
                target = rec
                break

        if target is None:
            return None

        # Apply any outcome updates
        for update in updates:
            if update.record_id == target.id:
                target.outcome = update.outcome
                target.validation_attempts = update.validation_attempts
                target.error_message = update.error_message

        return target

    def _read_raw(self) -> tuple[list[PromptRecord], list[OutcomeUpdate]]:
        """Read all JSONL lines, separating records from updates."""
        records: list[PromptRecord] = []
        updates: list[OutcomeUpdate] = []

        if not self._file_path.exists():
            return records, updates

        try:
            with self._file_path.open("r", encoding="utf-8") as f:
                for line_num, raw_line in enumerate(f, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        data: dict[str, Any] = json.loads(line)
                        if data.get("type") == "outcome_update":
                            updates.append(OutcomeUpdate.from_dict(data))
                        else:
                            records.append(PromptRecord.from_dict(data))
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                        logger.warning(
                            "Skipping malformed line %d in %s: %s",
                            line_num,
                            _PROMPTS_FILE,
                            exc,
                        )
        except OSError as exc:
            logger.error("Failed to read %s: %s", self._file_path, exc)

        return records, updates

    def _append_json(self, data: dict[str, Any]) -> None:
        """Append a JSON-serialized line to the prompts file."""
        json_line = json.dumps(data, ensure_ascii=False)
        with self._lock:
            try:
                with self._file_path.open("a", encoding="utf-8") as f:
                    f.write(json_line)
                    f.write("\n")
            except OSError as exc:
                logger.error("Failed to append to %s: %s", self._file_path, exc)


# ── Singleton management ────────────────────────────────────────

_RECORDER_LOCK = threading.Lock()
_RECORDERS: dict[str, PromptRecorder] = {}


def get_prompt_recorder(project_root: Path) -> PromptRecorder:
    """Get or create a singleton PromptRecorder for the given project root."""
    key = str(project_root.resolve())
    with _RECORDER_LOCK:
        if key not in _RECORDERS:
            _RECORDERS[key] = PromptRecorder(project_root)
        return _RECORDERS[key]


# ── Helpers ─────────────────────────────────────────────────────

_LINEAGE_PREFIX = "nit_"
_LINEAGE_KEYS = {
    "nit_source_file": "source_file",
    "nit_template_name": "template_name",
    "nit_builder_name": "builder_name",
    "nit_framework": "framework",
    "nit_context_tokens": "context_tokens",
}


def _extract_lineage(metadata: dict[str, Any]) -> PromptLineage | None:
    """Extract PromptLineage from request metadata if lineage keys are present."""
    if not any(k in metadata for k in _LINEAGE_KEYS):
        return None

    context_sections_raw = metadata.get("nit_context_sections")
    context_sections: list[str] = (
        list(context_sections_raw) if isinstance(context_sections_raw, (list, tuple)) else []
    )

    context_tokens_raw = metadata.get("nit_context_tokens", 0)
    context_tokens = int(context_tokens_raw) if isinstance(context_tokens_raw, (int, float)) else 0

    return PromptLineage(
        source_file=str(metadata.get("nit_source_file", "")),
        template_name=str(metadata.get("nit_template_name", "")),
        builder_name=str(metadata.get("nit_builder_name", "")),
        framework=str(metadata.get("nit_framework", "")),
        context_tokens=context_tokens,
        context_sections=context_sections,
    )


def _filter_non_lineage_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return metadata dict without the lineage-specific keys."""
    return {k: v for k, v in metadata.items() if not k.startswith(_LINEAGE_PREFIX)}
