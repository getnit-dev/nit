"""Tests for nit.sharding.parallel_runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from nit.adapters.base import RunResult
from nit.sharding.parallel_runner import ParallelRunConfig, run_tests_parallel


def _make_result(passed: int = 5, failed: int = 0) -> RunResult:
    return RunResult(
        passed=passed,
        failed=failed,
        duration_ms=100.0,
        success=failed == 0 and passed > 0,
    )


def _mock_adapter(result: RunResult | Exception | None = None) -> Mock:
    adapter = Mock()
    adapter.name = "mock"
    adapter.get_test_pattern.return_value = ["**/*_test.py"]
    # run_tests is async — use AsyncMock explicitly
    adapter.run_tests = AsyncMock()
    if isinstance(result, Exception):
        adapter.run_tests.side_effect = result
    else:
        adapter.run_tests.return_value = result or _make_result()
    return adapter


class TestRunTestsParallel:
    async def test_shards_and_merges(self, tmp_path: Path) -> None:
        """With enough files, tests are split into shards and merged."""
        for i in range(10):
            (tmp_path / f"test_{i}_test.py").write_text(f"# test {i}")

        adapter = _mock_adapter()
        config = ParallelRunConfig(shard_count=2, min_files_for_sharding=4)
        result = await run_tests_parallel(adapter, tmp_path, config=config)

        # run_tests should be called once per shard
        assert adapter.run_tests.call_count == 2
        # Results merged: 5 passed * 2 shards = 10
        assert result.passed == 10

    async def test_fallback_few_files(self, tmp_path: Path) -> None:
        """Falls back to single run when fewer files than threshold."""
        for i in range(3):
            (tmp_path / f"test_{i}_test.py").write_text(f"# test {i}")

        adapter = _mock_adapter()
        config = ParallelRunConfig(shard_count=4, min_files_for_sharding=8)
        result = await run_tests_parallel(adapter, tmp_path, config=config)

        assert adapter.run_tests.call_count == 1
        assert result.passed == 5

    async def test_fallback_on_discovery_failure(self, tmp_path: Path) -> None:
        """Falls back to single run when file discovery fails."""
        adapter = _mock_adapter()

        with patch(
            "nit.sharding.parallel_runner.discover_test_files",
            side_effect=RuntimeError("boom"),
        ):
            result = await run_tests_parallel(adapter, tmp_path)

        assert adapter.run_tests.call_count == 1
        assert result.passed == 5

    async def test_handles_shard_failure(self, tmp_path: Path) -> None:
        """One failing shard doesn't block the others."""
        for i in range(10):
            (tmp_path / f"test_{i}_test.py").write_text(f"# test {i}")

        adapter = _mock_adapter()
        call_count = 0

        async def _run_tests(*args: object, **kwargs: object) -> RunResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("shard 0 died")
            return _make_result()

        adapter.run_tests = AsyncMock(side_effect=_run_tests)
        config = ParallelRunConfig(shard_count=2, min_files_for_sharding=4)
        result = await run_tests_parallel(adapter, tmp_path, config=config)

        # One shard failed, one succeeded
        assert result.passed == 5

    async def test_all_shards_fail_fallback(self, tmp_path: Path) -> None:
        """When all shards fail, falls back to a single run."""
        for i in range(10):
            (tmp_path / f"test_{i}_test.py").write_text(f"# test {i}")

        adapter = _mock_adapter()
        call_count = 0

        async def _run_tests(*args: object, **kwargs: object) -> RunResult:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("shard died")
            return _make_result(passed=1)

        adapter.run_tests = AsyncMock(side_effect=_run_tests)
        config = ParallelRunConfig(shard_count=2, min_files_for_sharding=4)
        result = await run_tests_parallel(adapter, tmp_path, config=config)

        # Both shards failed (calls 1+2), fallback single run (call 3)
        assert call_count == 3
        assert result.passed == 1

    async def test_single_shard_runs_directly(self, tmp_path: Path) -> None:
        """With only 1 effective shard, runs directly without sharding."""
        (tmp_path / "test_one_test.py").write_text("# only one")

        adapter = _mock_adapter()
        config = ParallelRunConfig(shard_count=4, min_files_for_sharding=1)
        await run_tests_parallel(adapter, tmp_path, config=config)

        # Single file => effective shards = 1 => direct run
        assert adapter.run_tests.call_count == 1

    async def test_default_config(self, tmp_path: Path) -> None:
        """Works with default config (no explicit config argument)."""
        adapter = _mock_adapter()
        result = await run_tests_parallel(adapter, tmp_path)

        # No test files found => fallback to single run
        assert adapter.run_tests.call_count == 1
        assert result.passed == 5
