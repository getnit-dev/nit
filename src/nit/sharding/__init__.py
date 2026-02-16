"""Test sharding support for parallel test execution."""

from nit.sharding.merger import merge_coverage_reports, merge_run_results
from nit.sharding.parallel_runner import ParallelRunConfig, run_tests_parallel
from nit.sharding.prioritizer import (
    PrioritizedTestPlan,
    RiskScore,
    distribute_prioritized_shards,
    prioritize_test_files_by_risk,
)
from nit.sharding.shard_result import read_shard_result, write_shard_result
from nit.sharding.splitter import discover_test_files, split_into_shards

__all__ = [
    "ParallelRunConfig",
    "PrioritizedTestPlan",
    "RiskScore",
    "discover_test_files",
    "distribute_prioritized_shards",
    "merge_coverage_reports",
    "merge_run_results",
    "prioritize_test_files_by_risk",
    "read_shard_result",
    "run_tests_parallel",
    "split_into_shards",
    "write_shard_result",
]
