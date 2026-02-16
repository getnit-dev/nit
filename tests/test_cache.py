"""Tests for nit.utils.cache."""

from __future__ import annotations

import time
from pathlib import Path

from nit.utils.cache import FileContentCache, MemoryCache, content_hash


class TestMemoryCache:
    def test_put_and_get(self) -> None:
        cache: MemoryCache[str] = MemoryCache()
        cache.put("k1", "v1")
        assert cache.get("k1") == "v1"

    def test_get_missing_returns_none(self) -> None:
        cache: MemoryCache[str] = MemoryCache()
        assert cache.get("missing") is None

    def test_ttl_expiry(self) -> None:
        cache: MemoryCache[str] = MemoryCache(ttl_seconds=0.1)
        cache.put("k1", "v1")
        assert cache.get("k1") == "v1"
        time.sleep(0.2)
        assert cache.get("k1") is None

    def test_lru_eviction(self) -> None:
        cache: MemoryCache[int] = MemoryCache(max_size=3)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        # Access "a" to make it most-recently-used
        cache.get("a")
        # Adding "d" should evict "b" (oldest after "a" was refreshed)
        cache.put("d", 4)
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_put_overwrites_existing(self) -> None:
        cache: MemoryCache[str] = MemoryCache()
        cache.put("k1", "old")
        cache.put("k1", "new")
        assert cache.get("k1") == "new"
        assert cache.size == 1

    def test_invalidate(self) -> None:
        cache: MemoryCache[str] = MemoryCache()
        cache.put("k1", "v1")
        cache.invalidate("k1")
        assert cache.get("k1") is None

    def test_invalidate_missing_key_is_noop(self) -> None:
        cache: MemoryCache[str] = MemoryCache()
        cache.invalidate("nope")
        assert cache.size == 0

    def test_clear(self) -> None:
        cache: MemoryCache[str] = MemoryCache()
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.clear()
        assert cache.size == 0
        assert cache.get("k1") is None

    def test_size_property(self) -> None:
        cache: MemoryCache[int] = MemoryCache()
        assert cache.size == 0
        cache.put("a", 1)
        assert cache.size == 1
        cache.put("b", 2)
        assert cache.size == 2
        cache.invalidate("a")
        assert cache.size == 1

    def test_no_ttl_entries_persist(self) -> None:
        cache: MemoryCache[str] = MemoryCache(ttl_seconds=0)
        cache.put("k1", "v1")
        assert cache.get("k1") == "v1"


class TestFileContentCache:
    def test_cache_hit_unchanged_file(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.py"
        f.write_text("print('hello')")
        cache: FileContentCache[str] = FileContentCache()
        cache.put(f, "parsed")
        assert cache.get(f) == "parsed"

    def test_cache_miss_on_mtime_change(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.py"
        f.write_text("v1")
        cache: FileContentCache[str] = FileContentCache()
        cache.put(f, "parsed-v1")

        # Simulate file modification (force new mtime)
        time.sleep(0.01)
        f.write_text("v2")
        assert cache.get(f) is None

    def test_cache_miss_for_deleted_file(self, tmp_path: Path) -> None:
        f = tmp_path / "gone.py"
        f.write_text("data")
        cache: FileContentCache[str] = FileContentCache()
        cache.put(f, "parsed")
        f.unlink()
        assert cache.get(f) is None

    def test_put_nonexistent_file_is_noop(self, tmp_path: Path) -> None:
        f = tmp_path / "nope.py"
        cache: FileContentCache[str] = FileContentCache()
        cache.put(f, "value")
        assert cache.get(f) is None

    def test_get_never_cached_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "fresh.py"
        f.write_text("code")
        cache: FileContentCache[str] = FileContentCache()
        assert cache.get(f) is None


class TestContentHash:
    def test_deterministic(self) -> None:
        assert content_hash("hello") == content_hash("hello")

    def test_different_inputs_differ(self) -> None:
        assert content_hash("hello") != content_hash("world")

    def test_length_is_16(self) -> None:
        assert len(content_hash("anything")) == 16
