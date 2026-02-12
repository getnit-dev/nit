"""In-process parallel test execution using sharding."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.sharding.merger import merge_run_results
from nit.sharding.splitter import discover_test_files, split_into_shards

if TYPE_CHECKING:
    from pathlib import Path

    from nit.adapters.base import RunResult, TestFrameworkAdapter

logger = logging.getLogger(__name__)

_DEFAULT_SHARD_COUNT = 4
_MIN_FILES_FOR_SHARDING = 8


@dataclass
class ParallelRunConfig:
    """Configuration for parallel test execution."""

    shard_count: int = _DEFAULT_SHARD_COUNT
    """Number of parallel shards."""

    min_files_for_sharding: int = _MIN_FILES_FOR_SHARDING
    """Minimum test files required to enable sharding."""

    timeout: float = 120.0
    """Timeout per shard in seconds."""


async def run_tests_parallel(
    adapter: TestFrameworkAdapter,
    project_path: Path,
    *,
    config: ParallelRunConfig | None = None,
) -> RunResult:
    """Run tests in parallel using automatic sharding.

    Discovers test files, splits them across *N* shards, runs each shard
    concurrently via ``asyncio.gather()``, and merges the results.

    Falls back to single-run execution when:

    - Fewer test files than *min_files_for_sharding*
    - Only 1 effective shard
    - Test file discovery fails
    """
    run_config = config or ParallelRunConfig()

    patterns = adapter.get_test_pattern()
    try:
        all_files = discover_test_files(project_path, patterns)
    except Exception:
        logger.debug("Test file discovery failed, falling back to single run")
        return await adapter.run_tests(project_path, timeout=run_config.timeout)

    effective_shards = min(run_config.shard_count, len(all_files))
    if len(all_files) < run_config.min_files_for_sharding or effective_shards <= 1:
        return await adapter.run_tests(project_path, timeout=run_config.timeout)

    logger.info(
        "Running %d test files across %d shards",
        len(all_files),
        effective_shards,
    )

    shard_tasks = [
        adapter.run_tests(
            project_path,
            test_files=split_into_shards(all_files, i, effective_shards),
            timeout=run_config.timeout,
        )
        for i in range(effective_shards)
    ]

    shard_results = await asyncio.gather(*shard_tasks, return_exceptions=True)

    successful: list[RunResult] = []
    for i, result in enumerate(shard_results):
        if isinstance(result, BaseException):
            logger.warning("Shard %d failed: %s", i, result)
        else:
            successful.append(result)

    if not successful:
        logger.warning("All shards failed, falling back to single run")
        return await adapter.run_tests(project_path, timeout=run_config.timeout)

    return merge_run_results(successful)
