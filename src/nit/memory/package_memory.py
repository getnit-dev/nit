"""Per-package memory storage for test patterns and issues.

Stores per-package test patterns, known issues, coverage history,
and LLM feedback specific to each package in a project.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

from nit.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# Display constants for markdown export
_MAX_COVERAGE_SNAPSHOTS = 5


class PackageMemory:
    """Per-package memory for test patterns, issues, and coverage history.

    Stores:
    - Test patterns specific to this package
    - Known issues and workarounds
    - Coverage history over time
    - LLM feedback and improvements
    """

    def __init__(self, project_root: Path, package_name: str) -> None:
        """Initialize package memory.

        Args:
            project_root: Root directory of the project.
            package_name: Name of the package (used in filename).
        """
        # Sanitize package name for filename
        safe_name = package_name.replace("/", "_").replace("\\", "_")
        filename = f"packages/package_{safe_name}.json"

        self._store: MemoryStore[dict[str, Any]] = MemoryStore(project_root, filename)
        self._package_name = package_name
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load data from disk into memory."""
        data = self._store.load()
        if data:
            self._data = data
        else:
            # Initialize with empty structure
            self._data = {
                "package_name": self._package_name,
                "test_patterns": {},
                "known_issues": [],
                "coverage_history": [],
                "llm_feedback": [],
            }

    def _save(self) -> None:
        """Save current data to disk."""
        self._store.save(self._data)

    def get_test_patterns(self) -> dict[str, Any]:
        """Get test patterns for this package.

        Returns:
            Dictionary of test patterns.
        """
        return cast("dict[str, Any]", self._data.get("test_patterns", {}))

    def set_test_patterns(self, patterns: dict[str, Any]) -> None:
        """Set test patterns for this package.

        Args:
            patterns: Dictionary of test patterns to store.
        """
        self._data["test_patterns"] = patterns
        self._save()

    def add_known_issue(
        self,
        issue: str,
        workaround: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Add a known issue for this package.

        Args:
            issue: Description of the issue.
            workaround: Optional workaround or solution.
            context: Additional context about the issue.
        """
        known_issues = self._data.get("known_issues", [])

        issue_entry = {
            "issue": issue,
            "workaround": workaround,
            "timestamp": datetime.now(UTC).isoformat(),
            "context": context or {},
        }
        known_issues.append(issue_entry)
        self._data["known_issues"] = known_issues
        self._save()

    def get_known_issues(self) -> list[dict[str, Any]]:
        """Get all known issues for this package.

        Returns:
            List of known issue dictionaries.
        """
        return cast("list[dict[str, Any]]", self._data.get("known_issues", []))

    def add_coverage_snapshot(
        self,
        coverage_percent: float,
        line_coverage: dict[str, Any] | None = None,
        branch_coverage: dict[str, Any] | None = None,
    ) -> None:
        """Add a coverage snapshot to history.

        Args:
            coverage_percent: Overall coverage percentage.
            line_coverage: Optional line coverage details.
            branch_coverage: Optional branch coverage details.
        """
        coverage_history = self._data.get("coverage_history", [])

        snapshot = {
            "timestamp": datetime.now(UTC).isoformat(),
            "coverage_percent": coverage_percent,
            "line_coverage": line_coverage or {},
            "branch_coverage": branch_coverage or {},
        }
        coverage_history.append(snapshot)
        self._data["coverage_history"] = coverage_history
        self._save()

    def get_coverage_history(self) -> list[dict[str, Any]]:
        """Get coverage history for this package.

        Returns:
            List of coverage snapshot dictionaries.
        """
        return cast("list[dict[str, Any]]", self._data.get("coverage_history", []))

    def get_latest_coverage(self) -> dict[str, Any] | None:
        """Get the most recent coverage snapshot.

        Returns:
            Latest coverage snapshot, or None if no history exists.
        """
        history = self.get_coverage_history()
        if history:
            return history[-1]
        return None

    def add_llm_feedback(
        self,
        feedback_type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add LLM feedback for this package.

        Args:
            feedback_type: Type of feedback (e.g., "improvement", "error", "suggestion").
            content: The feedback content.
            metadata: Additional metadata about the feedback.
        """
        llm_feedback = self._data.get("llm_feedback", [])

        feedback_entry = {
            "type": feedback_type,
            "content": content,
            "timestamp": datetime.now(UTC).isoformat(),
            "metadata": metadata or {},
        }
        llm_feedback.append(feedback_entry)
        self._data["llm_feedback"] = llm_feedback
        self._save()

    def get_llm_feedback(self) -> list[dict[str, Any]]:
        """Get all LLM feedback for this package.

        Returns:
            List of LLM feedback dictionaries.
        """
        return cast("list[dict[str, Any]]", self._data.get("llm_feedback", []))

    def clear(self) -> None:
        """Clear all package memory."""
        self._store.clear()
        self._load()

    def to_dict(self) -> dict[str, Any]:
        """Export memory as a dictionary for display or serialization.

        Returns:
            Dictionary containing all memory data.
        """
        return self._data.copy()

    def to_markdown(self) -> str:
        """Export memory as a human-readable markdown report.

        Returns:
            Markdown-formatted string containing all memory data.
        """
        sections = [
            f"# Package Memory Report: {self._package_name}",
            "",
            *self._format_test_patterns_section(),
            *self._format_known_issues_section(),
            *self._format_coverage_history_section(),
            *self._format_llm_feedback_section(),
        ]
        return "\n".join(sections)

    def _format_test_patterns_section(self) -> list[str]:
        """Format test patterns section for markdown export."""
        lines = ["## Test Patterns", ""]
        test_patterns = self.get_test_patterns()
        if test_patterns:
            lines.extend(f"- **{key}**: {value}" for key, value in test_patterns.items())
        else:
            lines.append("*No test patterns recorded*")
        lines.append("")
        return lines

    def _format_known_issues_section(self) -> list[str]:
        """Format known issues section for markdown export."""
        lines = ["## Known Issues", ""]
        known_issues = self.get_known_issues()
        if not known_issues:
            lines.extend(["*No known issues recorded*", ""])
            return lines

        for idx, issue in enumerate(known_issues, start=1):
            lines.append(f"### Issue {idx}")
            lines.append(f"- **Issue**: {issue.get('issue', 'N/A')}")
            if issue.get("workaround"):
                lines.append(f"- **Workaround**: {issue['workaround']}")
            lines.append(f"- **Timestamp**: {issue.get('timestamp', 'Unknown')}")
            if issue.get("context"):
                lines.append(f"- **Context**: {issue['context']}")
            lines.append("")
        return lines

    def _format_coverage_history_section(self) -> list[str]:
        """Format coverage history section for markdown export."""
        lines = ["## Coverage History", ""]
        coverage_history = self.get_coverage_history()
        if not coverage_history:
            lines.extend(["*No coverage history recorded*", ""])
            return lines

        lines.append(f"Total snapshots: {len(coverage_history)}")
        lines.append("")
        # Show latest snapshots
        recent = coverage_history[-_MAX_COVERAGE_SNAPSHOTS:]
        for snapshot in reversed(recent):
            timestamp = snapshot.get("timestamp", "Unknown")
            coverage_pct = snapshot.get("coverage_percent", 0)
            lines.append(f"- **{timestamp}**: {coverage_pct:.1f}%")

        if len(coverage_history) > _MAX_COVERAGE_SNAPSHOTS:
            remaining = len(coverage_history) - _MAX_COVERAGE_SNAPSHOTS
            lines.append(f"- *(and {remaining} more snapshots)*")
        lines.append("")
        return lines

    def _format_llm_feedback_section(self) -> list[str]:
        """Format LLM feedback section for markdown export."""
        lines = ["## LLM Feedback", ""]
        llm_feedback = self.get_llm_feedback()
        if not llm_feedback:
            lines.extend(["*No LLM feedback recorded*", ""])
            return lines

        for idx, feedback in enumerate(llm_feedback, start=1):
            lines.append(f"### Feedback {idx}")
            lines.append(f"- **Type**: {feedback.get('type', 'N/A')}")
            lines.append(f"- **Content**: {feedback.get('content', 'N/A')}")
            lines.append(f"- **Timestamp**: {feedback.get('timestamp', 'Unknown')}")
            if feedback.get("metadata"):
                lines.append(f"- **Metadata**: {feedback['metadata']}")
            lines.append("")
        return lines
