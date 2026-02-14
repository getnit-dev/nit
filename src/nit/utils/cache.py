"""Caching utilities for nit."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


@dataclass(slots=True)
class _Entry(Generic[_T]):
    """A single cache entry with metadata."""

    value: _T
    created_at: float


class MemoryCache(Generic[_T]):
    """In-memory LRU cache with optional TTL.

    Uses a plain ``dict`` (insertion-ordered since Python 3.7) for LRU
    eviction via delete-and-reinsert.  Thread-safe for single-threaded
    asyncio usage.

    Args:
        max_size: Maximum number of entries before LRU eviction.
        ttl_seconds: Time-to-live in seconds.  ``0`` disables TTL.
    """

    def __init__(self, max_size: int = 256, ttl_seconds: float = 0.0) -> None:
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: dict[str, _Entry[_T]] = {}

    def get(self, key: str) -> _T | None:
        """Return cached value or ``None`` if missing/expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if self._ttl > 0 and (time.monotonic() - entry.created_at) > self._ttl:
            del self._store[key]
            return None
        # Move to end for LRU (delete + re-insert preserves insertion order)
        del self._store[key]
        self._store[key] = entry
        return entry.value

    def put(self, key: str, value: _T) -> None:
        """Store a value, evicting the oldest entry if at capacity."""
        if key in self._store:
            del self._store[key]
        elif len(self._store) >= self._max_size:
            # Evict oldest (first) entry
            oldest = next(iter(self._store))
            del self._store[oldest]
        self._store[key] = _Entry(value=value, created_at=time.monotonic())

    def invalidate(self, key: str) -> None:
        """Remove a specific key."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries."""
        self._store.clear()

    @property
    def size(self) -> int:
        """Number of entries currently held."""
        return len(self._store)


class FileContentCache(Generic[_T]):
    """Cache keyed by file path + modification time.

    Automatically invalidates when the underlying file has been modified
    since the value was cached.  Suitable for caching ``ParseResult``,
    tree-sitter ``Tree`` objects, and similar file-derived data.

    Args:
        max_size: Maximum entries.
    """

    def __init__(self, max_size: int = 512) -> None:
        self._cache: MemoryCache[tuple[float, _T]] = MemoryCache(max_size=max_size)

    def get(self, file_path: Path) -> _T | None:
        """Return cached value if the file has not changed since caching."""
        key = str(file_path)
        entry = self._cache.get(key)
        if entry is None:
            return None
        cached_mtime, value = entry
        try:
            current_mtime = file_path.stat().st_mtime
        except OSError:
            self._cache.invalidate(key)
            return None
        if current_mtime != cached_mtime:
            self._cache.invalidate(key)
            return None
        return value

    def put(self, file_path: Path, value: _T) -> None:
        """Store *value* alongside the file's current mtime."""
        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            return  # can't cache a file we can't stat
        self._cache.put(str(file_path), (mtime, value))


def content_hash(text: str) -> str:
    """Compute a stable 16-char hex hash for *text*."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
