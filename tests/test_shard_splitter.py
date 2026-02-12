"""Tests for nit.sharding.splitter."""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.sharding.splitter import discover_test_files, split_into_shards


class TestDiscoverTestFiles:
    def test_discovers_matching_files(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").write_text("")
        (tmp_path / "tests" / "test_bar.py").write_text("")
        (tmp_path / "src" / "main.py").mkdir(parents=True, exist_ok=True)

        result = discover_test_files(tmp_path, ["tests/test_*.py"])
        assert len(result) == 2
        assert all(f.name.startswith("test_") for f in result)

    def test_returns_sorted_list(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_z.py").write_text("")
        (tmp_path / "tests" / "test_a.py").write_text("")
        (tmp_path / "tests" / "test_m.py").write_text("")

        result = discover_test_files(tmp_path, ["tests/test_*.py"])
        names = [f.name for f in result]
        assert names == ["test_a.py", "test_m.py", "test_z.py"]

    def test_deduplicates_across_patterns(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_foo.py").write_text("")

        result = discover_test_files(tmp_path, ["tests/test_*.py", "tests/*.py"])
        assert len(result) == 1

    def test_no_matches_returns_empty(self, tmp_path: Path) -> None:
        result = discover_test_files(tmp_path, ["**/*.test.ts"])
        assert result == []

    def test_multiple_patterns(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_unit.py").write_text("")
        (tmp_path / "tests" / "spec_integration.ts").write_text("")

        result = discover_test_files(tmp_path, ["tests/test_*.py", "tests/spec_*.ts"])
        assert len(result) == 2


class TestSplitIntoShards:
    def test_single_shard_returns_all(self) -> None:
        files = [Path("a"), Path("b"), Path("c")]
        assert split_into_shards(files, 0, 1) == files

    def test_two_shards_round_robin(self) -> None:
        files = [Path("a"), Path("b"), Path("c"), Path("d")]
        shard_0 = split_into_shards(files, 0, 2)
        shard_1 = split_into_shards(files, 1, 2)
        assert shard_0 == [Path("a"), Path("c")]
        assert shard_1 == [Path("b"), Path("d")]

    def test_three_shards_uneven(self) -> None:
        files = [Path(str(i)) for i in range(7)]
        shard_0 = split_into_shards(files, 0, 3)
        shard_1 = split_into_shards(files, 1, 3)
        shard_2 = split_into_shards(files, 2, 3)
        # Round-robin: 0,3,6 | 1,4 | 2,5
        assert len(shard_0) == 3
        assert len(shard_1) == 2
        assert len(shard_2) == 2
        # All files covered, no duplicates
        combined = shard_0 + shard_1 + shard_2
        assert sorted(combined, key=str) == files

    def test_more_shards_than_files(self) -> None:
        files = [Path("a"), Path("b")]
        assert split_into_shards(files, 0, 5) == [Path("a")]
        assert split_into_shards(files, 1, 5) == [Path("b")]
        assert split_into_shards(files, 2, 5) == []
        assert split_into_shards(files, 3, 5) == []
        assert split_into_shards(files, 4, 5) == []

    def test_empty_file_list(self) -> None:
        assert split_into_shards([], 0, 3) == []

    def test_invalid_shard_count_zero(self) -> None:
        with pytest.raises(ValueError, match="shard_count must be >= 1"):
            split_into_shards([], 0, 0)

    def test_invalid_shard_count_negative(self) -> None:
        with pytest.raises(ValueError, match="shard_count must be >= 1"):
            split_into_shards([], 0, -1)

    def test_invalid_shard_index_negative(self) -> None:
        with pytest.raises(ValueError, match="shard_index must be in"):
            split_into_shards([], -1, 2)

    def test_invalid_shard_index_too_large(self) -> None:
        with pytest.raises(ValueError, match="shard_index must be in"):
            split_into_shards([], 3, 3)
