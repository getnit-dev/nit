"""Batched prompt sync to the platform.

Buffers prompt records and periodically flushes them to the platform API.
Only syncs when ``prompts.sync_to_platform`` is enabled in config.
Supports ``redact_source`` mode to hash message content for privacy.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import TYPE_CHECKING, Any

from nit.utils.platform_client import PlatformClientError, post_platform_prompts

if TYPE_CHECKING:
    from nit.memory.prompt_store import PromptRecorder
    from nit.models.prompt_record import PromptRecord
    from nit.utils.platform_client import PlatformRuntimeConfig

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 50


class PromptSyncer:
    """Batched uploader for prompt records to the platform API.

    Records are buffered locally and flushed in batches.
    """

    def __init__(
        self,
        recorder: PromptRecorder,
        platform_config: PlatformRuntimeConfig,
        *,
        redact_source: bool = False,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self._recorder = recorder
        self._platform_config = platform_config
        self._redact_source = redact_source
        self._batch_size = batch_size
        self._lock = threading.Lock()
        self._last_synced_id: str = ""

    def sync(self, *, limit: int = 0) -> int:
        """Push unsynced prompt records to the platform.

        Returns:
            Number of records synced.
        """
        records = self._recorder.read_all(limit=limit or self._batch_size)
        if not records:
            return 0

        # Filter to records after last synced ID
        if self._last_synced_id:
            idx = _find_record_index(records, self._last_synced_id)
            if idx is not None:
                records = records[:idx]

        if not records:
            return 0

        payloads = [self._record_to_payload(r) for r in records]

        with self._lock:
            try:
                post_platform_prompts(
                    self._platform_config,
                    payloads,
                )
                self._last_synced_id = records[0].id
                logger.info("Synced %d prompt records to platform", len(payloads))
                return len(payloads)
            except PlatformClientError:
                logger.exception("Failed to sync prompts to platform")
                return 0

    def _record_to_payload(self, record: PromptRecord) -> dict[str, Any]:
        """Convert a PromptRecord to a platform API payload."""
        data = record.to_dict()

        if self._redact_source:
            data["messages"] = [
                {"role": m["role"], "content": _sha256(m["content"])}
                for m in data.get("messages", [])
            ]
            if data.get("response_text"):
                data["response_text"] = _sha256(data["response_text"])

        return data


def _sha256(text: str) -> str:
    """Hash text with SHA-256 for redaction."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _find_record_index(records: list[PromptRecord], record_id: str) -> int | None:
    """Find the index of a record by ID in a list sorted most-recent-first."""
    for i, r in enumerate(records):
        if r.id == record_id:
            return i
    return None
