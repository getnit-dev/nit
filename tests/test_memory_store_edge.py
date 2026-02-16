"""Edge-case tests for memory stores (conventions.py, memory/store.py)."""

from __future__ import annotations

from pathlib import Path

from nit.memory.conventions import ConventionStore
from nit.memory.store import MemoryStore

# ── MemoryStore.load exception path ─────────────────────────────


def test_memory_store_load_corrupt_json(tmp_path: Path) -> None:
    """MemoryStore.load returns None for corrupt JSON."""
    store: MemoryStore[dict[str, object]] = MemoryStore(tmp_path, "test.json")
    store._file_path.parent.mkdir(parents=True, exist_ok=True)
    store._file_path.write_text("{corrupt json!!!", encoding="utf-8")
    assert store.load() is None


# ── ConventionStore.load exception path ──────────────────────────


def test_convention_store_load_corrupt_json(tmp_path: Path) -> None:
    """ConventionStore.load returns None for corrupt JSON."""
    store = ConventionStore(tmp_path)
    store._memory_dir.mkdir(parents=True, exist_ok=True)
    store._conventions_file.write_text("{bad json}", encoding="utf-8")
    assert store.load() is None


def test_convention_store_load_invalid_schema(tmp_path: Path) -> None:
    """ConventionStore.load returns None when JSON doesn't match ConventionProfile."""
    store = ConventionStore(tmp_path)
    store._memory_dir.mkdir(parents=True, exist_ok=True)
    # Valid JSON but wrong structure for ConventionProfile
    store._conventions_file.write_text('{"unexpected_field": true}', encoding="utf-8")
    assert store.load() is None
