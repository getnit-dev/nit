"""Test file discovery and shard splitting."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def discover_test_files(project_path: Path, patterns: list[str]) -> list[Path]:
    """Discover test files matching the given glob patterns.

    Args:
        project_path: Root of the project.
        patterns: Glob patterns from adapter.get_test_pattern().

    Returns:
        Sorted list of unique test file paths (relative to project_path).
    """
    files: set[Path] = set()
    for pattern in patterns:
        files.update(project_path.glob(pattern))
    return sorted(files)


def split_into_shards(
    files: list[Path],
    shard_index: int,
    shard_count: int,
) -> list[Path]:
    """Split files into shards using round-robin assignment.

    Args:
        files: Sorted list of all test files.
        shard_index: Zero-based index of this shard.
        shard_count: Total number of shards.

    Returns:
        Subset of files assigned to this shard.

    Raises:
        ValueError: If shard_index or shard_count is invalid.
    """
    if shard_count < 1:
        msg = f"shard_count must be >= 1, got {shard_count}"
        raise ValueError(msg)
    if shard_index < 0 or shard_index >= shard_count:
        msg = f"shard_index must be in [0, {shard_count}), got {shard_index}"
        raise ValueError(msg)
    return [f for i, f in enumerate(files) if i % shard_count == shard_index]
