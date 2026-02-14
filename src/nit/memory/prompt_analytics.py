"""Analytics queries for prompt tracking data.

Aggregates prompt records to surface success rates, token usage,
and efficiency metrics — grouped by model, template, and time period.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nit.memory.prompt_store import PromptRecorder
    from nit.models.prompt_record import PromptRecord


class PromptAnalytics:
    """Computes efficiency and cost statistics from recorded prompts."""

    def __init__(self, recorder: PromptRecorder) -> None:
        self._recorder = recorder

    def summary(self, *, days: int = 30) -> dict[str, Any]:
        """Aggregate prompt statistics for the last *days* days.

        Returns a dict with:
            total_prompts, success_rate, total_tokens, avg_duration_ms,
            by_model  — per-model  {count, success_rate, avg_tokens},
            by_template — per-template {count, success_rate, avg_tokens}.
        """
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        records = self._recorder.read_all(since=since)

        if not records:
            return {
                "total_prompts": 0,
                "success_rate": 0.0,
                "total_tokens": 0,
                "avg_duration_ms": 0.0,
                "by_model": {},
                "by_template": {},
            }

        total = len(records)
        successes = sum(1 for r in records if r.outcome == "success")
        total_tokens = sum(r.total_tokens for r in records)
        total_duration = sum(r.duration_ms for r in records)

        by_model = _group_stats(records, key_fn=lambda r: r.model)
        by_template = _group_stats(
            [r for r in records if r.lineage],
            key_fn=lambda r: r.lineage.template_name if r.lineage else "",
        )

        return {
            "total_prompts": total,
            "success_rate": successes / total if total else 0.0,
            "total_tokens": total_tokens,
            "avg_duration_ms": total_duration / total if total else 0.0,
            "by_model": by_model,
            "by_template": by_template,
        }


def _group_stats(
    records: list[PromptRecord],
    key_fn: Any,
) -> dict[str, dict[str, Any]]:
    """Group records by *key_fn* and compute per-group stats."""
    groups: dict[str, list[PromptRecord]] = defaultdict(list)
    for rec in records:
        key = key_fn(rec)
        if key:
            groups[key].append(rec)

    result: dict[str, dict[str, Any]] = {}
    for name, group in sorted(groups.items()):
        count = len(group)
        successes = sum(1 for r in group if r.outcome == "success")
        tokens = sum(r.total_tokens for r in group)
        result[name] = {
            "count": count,
            "success_rate": successes / count if count else 0.0,
            "avg_tokens": tokens // count if count else 0,
        }
    return result
