"""Analytics data models for local and remote tracking.

All analytics data is saved locally in `.nit/history/` as JSONL files.
If analytics platform is enabled, data is also sent to the platform.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class EventType(Enum):
    """Types of analytics events."""

    TEST_GENERATION = "test_generation"
    TEST_EXECUTION = "test_execution"
    COVERAGE_RUN = "coverage_run"
    BUG_DISCOVERED = "bug_discovered"
    BUG_FIXED = "bug_fixed"
    DRIFT_TEST = "drift_test"
    LLM_REQUEST = "llm_request"
    PR_CREATED = "pr_created"
    ISSUE_CREATED = "issue_created"


@dataclass
class LLMUsage:
    """LLM usage metrics for a single request."""

    provider: str
    """LLM provider (e.g., 'openai', 'anthropic', 'ollama')."""

    model: str
    """Model name (e.g., 'gpt-4', 'claude-3-opus')."""

    prompt_tokens: int
    """Number of tokens in the prompt."""

    completion_tokens: int
    """Number of tokens in the completion."""

    total_tokens: int
    """Total tokens (prompt + completion)."""

    cost_usd: float | None = None
    """Estimated cost in USD (None for local models)."""

    duration_ms: float | None = None
    """Request duration in milliseconds."""

    cached_tokens: int = 0
    """Number of cached tokens (if applicable)."""


@dataclass
class CoverageSnapshot:
    """Coverage snapshot at a point in time."""

    timestamp: str
    """ISO timestamp of the snapshot."""

    overall_line_coverage: float
    """Overall line coverage (0.0 to 1.0)."""

    overall_branch_coverage: float
    """Overall branch coverage (0.0 to 1.0)."""

    overall_function_coverage: float
    """Overall function coverage (0.0 to 1.0)."""

    per_package: dict[str, dict[str, float]] = field(default_factory=dict)
    """Coverage per package: {package_name: {line: 0.8, branch: 0.7, function: 0.9}}."""


@dataclass
class TestExecutionSnapshot:
    """Test execution snapshot at a point in time."""

    timestamp: str
    """ISO timestamp of the snapshot."""

    total_tests: int
    """Total number of tests."""

    passed_tests: int
    """Number of passed tests."""

    failed_tests: int
    """Number of failed tests."""

    skipped_tests: int = 0
    """Number of skipped tests."""

    total_duration_ms: float | None = None
    """Total execution time in milliseconds."""

    flaky_tests: list[str] = field(default_factory=list)
    """List of flaky test names."""


@dataclass
class BugSnapshot:
    """Bug discovered or fixed."""

    timestamp: str
    """ISO timestamp of discovery/fix."""

    bug_type: str
    """Type of bug (from BugType enum)."""

    severity: str
    """Severity level (from BugSeverity enum)."""

    status: str
    """Bug status: 'discovered', 'fixed', 'ignored'."""

    file_path: str
    """File where bug was found."""

    line_number: int | None = None
    """Line number of bug."""

    title: str = ""
    """Short bug description."""

    pr_url: str | None = None
    """URL of PR that fixed the bug (if fixed)."""


@dataclass
class DriftSnapshot:
    """Drift test result snapshot."""

    timestamp: str
    """ISO timestamp of drift test."""

    test_id: str
    """ID of the drift test."""

    test_name: str
    """Name of the drift test."""

    similarity_score: float
    """Similarity score (0.0 to 1.0)."""

    passed: bool
    """Whether drift test passed."""

    drift_detected: bool
    """Whether drift was detected."""


@dataclass
class AnalyticsEvent:
    """A single analytics event with full context.

    This is the primary data structure saved to history files.
    """

    event_type: EventType
    """Type of event."""

    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    """ISO timestamp of the event."""

    # Test generation fields
    tests_generated: int | None = None
    """Number of tests generated (for test_generation events)."""

    tests_passing: int | None = None
    """Number of tests passing (for test_generation events)."""

    tests_failing: int | None = None
    """Number of tests failing (for test_generation events)."""

    # Coverage fields
    coverage: CoverageSnapshot | None = None
    """Coverage snapshot (for coverage_run events)."""

    coverage_delta: float | None = None
    """Coverage improvement (for test_generation events with before/after)."""

    # Test execution fields
    test_execution: TestExecutionSnapshot | None = None
    """Test execution snapshot (for test_execution events)."""

    # Bug fields
    bug: BugSnapshot | None = None
    """Bug details (for bug_discovered/bug_fixed events)."""

    # Drift fields
    drift: DriftSnapshot | None = None
    """Drift test result (for drift_test events)."""

    # LLM usage fields
    llm_usage: LLMUsage | None = None
    """LLM usage metrics (for llm_request events, or attached to other events)."""

    # PR/Issue fields
    pr_url: str | None = None
    """URL of created PR (for pr_created events)."""

    issue_url: str | None = None
    """URL of created issue (for issue_created events)."""

    # Files affected
    files: list[str] = field(default_factory=list)
    """List of files affected by this event."""

    # Package/context
    package_name: str | None = None
    """Package name if event is package-specific."""

    # Additional metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional event-specific metadata."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation of the event.
        """
        data = asdict(self)
        # Convert enum to string
        data["event_type"] = self.event_type.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalyticsEvent:
        """Create from dictionary.

        Args:
            data: Dictionary representation.

        Returns:
            AnalyticsEvent instance.
        """
        # Convert event_type string to enum
        event_type_str = data.pop("event_type")
        event_type = EventType(event_type_str)

        # Convert nested objects
        if data.get("coverage"):
            data["coverage"] = CoverageSnapshot(**data["coverage"])
        if data.get("test_execution"):
            data["test_execution"] = TestExecutionSnapshot(**data["test_execution"])
        if data.get("bug"):
            data["bug"] = BugSnapshot(**data["bug"])
        if data.get("drift"):
            data["drift"] = DriftSnapshot(**data["drift"])
        if data.get("llm_usage"):
            data["llm_usage"] = LLMUsage(**data["llm_usage"])

        return cls(event_type=event_type, **data)
