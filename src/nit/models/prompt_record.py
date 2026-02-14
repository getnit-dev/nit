"""Data models for prompt tracking and replay.

Captures full LLM prompt/response cycles with lineage information
tracing back to the source file, template, and builder that triggered them.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class PromptLineage:
    """Tracks the full origin of a prompt — which builder, template, and source file produced it."""

    source_file: str
    """Path to the source file being analyzed/tested."""

    template_name: str
    """Name of the PromptTemplate used (e.g. 'pytest_prompt', 'vitest')."""

    builder_name: str
    """Name of the agent/builder (e.g. 'unit_builder', 'doc_builder')."""

    framework: str = ""
    """Test framework used (e.g. 'pytest', 'vitest'). Empty for non-test prompts."""

    context_tokens: int = 0
    """Token count of assembled context."""

    context_sections: list[str] = field(default_factory=list)
    """Names of context sections included in the prompt."""


@dataclass
class PromptRecord:
    """Complete record of a single LLM prompt/response cycle.

    Stored as JSONL in `.nit/history/prompts.jsonl`.
    """

    id: str
    """Unique identifier (UUID)."""

    timestamp: str
    """ISO 8601 timestamp of the LLM call."""

    session_id: str
    """Links all prompts from one CLI invocation."""

    # Request
    model: str
    """Model used (resolved, not 'default')."""

    messages: list[dict[str, str]]
    """Full LLM messages: [{role, content}, ...]."""

    temperature: float
    """Sampling temperature used."""

    max_tokens: int
    """Maximum tokens requested."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Metadata from GenerationRequest."""

    # Response
    response_text: str = ""
    """Raw LLM response text."""

    prompt_tokens: int = 0
    """Number of tokens in the prompt."""

    completion_tokens: int = 0
    """Number of tokens in the completion."""

    total_tokens: int = 0
    """Total tokens consumed."""

    duration_ms: int = 0
    """Request duration in milliseconds."""

    # Lineage
    lineage: PromptLineage | None = None
    """Full origin chain. Populated when builders set metadata."""

    # Outcome
    outcome: str = "pending"
    """One of: 'pending', 'success', 'syntax_error', 'test_failure', 'error'."""

    validation_attempts: int = 0
    """Number of self-healing iterations."""

    error_message: str = ""
    """Error message if outcome is not 'success'."""

    # Comparison
    comparison_group_id: str | None = None
    """Links replays together for comparison."""

    @property
    def short_id(self) -> str:
        """First 8 characters of the ID for display."""
        return self.id[:8]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Remove None lineage to keep JSONL compact
        if data.get("lineage") is None:
            del data["lineage"]
        if data.get("comparison_group_id") is None:
            del data["comparison_group_id"]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptRecord:
        """Create from dictionary (parsed from JSONL line)."""
        lineage_data = data.pop("lineage", None)
        lineage = PromptLineage(**lineage_data) if lineage_data else None

        return cls(lineage=lineage, **data)

    @staticmethod
    def new_id() -> str:
        """Generate a new unique record ID."""
        return str(uuid.uuid4())

    @staticmethod
    def now_iso() -> str:
        """Return the current UTC timestamp in ISO 8601 format."""
        return datetime.now(UTC).isoformat()


@dataclass
class OutcomeUpdate:
    """Appended as a separate JSONL line to update a record's outcome after validation."""

    type: str = "outcome_update"
    """Discriminator for JSONL line parsing."""

    record_id: str = ""
    """ID of the PromptRecord to update."""

    outcome: str = ""
    """New outcome value."""

    validation_attempts: int = 0
    """Number of self-healing iterations."""

    error_message: str = ""
    """Error message if outcome is not 'success'."""

    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    """When the update was recorded."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutcomeUpdate:
        """Create from dictionary."""
        return cls(**data)
