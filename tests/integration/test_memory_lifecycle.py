"""Integration tests for the memory system lifecycle.

Tests GlobalMemory and PackageMemory write -> read -> verify roundtrips,
persistence across simulated runs, and interaction between the two.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nit.memory.global_memory import GlobalMemory
from nit.memory.package_memory import PackageMemory

# ── GlobalMemory lifecycle ───────────────────────────────────────


@pytest.mark.integration
class TestGlobalMemoryLifecycle:
    """Test GlobalMemory write -> read -> verify roundtrip."""

    def test_conventions_roundtrip(self, tmp_path: Path) -> None:
        """Conventions survive write -> reload."""
        mem = GlobalMemory(tmp_path)
        conventions = {
            "naming": "snake_case",
            "assertion_style": "assert",
            "fixture_pattern": "conftest.py",
        }
        mem.set_conventions(conventions)

        # Reload from disk
        mem2 = GlobalMemory(tmp_path)
        loaded = mem2.get_conventions()
        assert loaded == conventions

    def test_known_patterns_roundtrip(self, tmp_path: Path) -> None:
        """Known patterns survive write -> reload and accumulate correctly."""
        mem = GlobalMemory(tmp_path)
        mem.add_known_pattern("arrange-act-assert", {"scope": "unit"})
        mem.add_known_pattern("builder-pattern", {"scope": "integration"})
        # Add same pattern again to test counter increment
        mem.add_known_pattern("arrange-act-assert", {"scope": "unit"})

        # Reload from disk
        mem2 = GlobalMemory(tmp_path)
        patterns = mem2.get_known_patterns()

        assert len(patterns) == 2
        aaa_pattern = next(p for p in patterns if p["pattern"] == "arrange-act-assert")
        assert aaa_pattern["success_count"] == 2
        assert aaa_pattern["context"] == {"scope": "unit"}

        builder_pattern = next(p for p in patterns if p["pattern"] == "builder-pattern")
        assert builder_pattern["success_count"] == 1

    def test_failed_patterns_roundtrip(self, tmp_path: Path) -> None:
        """Failed patterns survive write -> reload."""
        mem = GlobalMemory(tmp_path)
        mem.add_failed_pattern("mock-everything", "leads to brittle tests")
        mem.add_failed_pattern("test-private-methods", "violates encapsulation")

        # Reload from disk
        mem2 = GlobalMemory(tmp_path)
        failed = mem2.get_failed_patterns()

        assert len(failed) == 2
        names = [f["pattern"] for f in failed]
        assert "mock-everything" in names
        assert "test-private-methods" in names
        mock_pattern = next(f for f in failed if f["pattern"] == "mock-everything")
        assert mock_pattern["reason"] == "leads to brittle tests"

    def test_stats_roundtrip(self, tmp_path: Path) -> None:
        """Generation stats accumulate and survive reload."""
        mem = GlobalMemory(tmp_path)
        mem.update_stats(successful=True, tests_generated=5, tests_passing=4)
        mem.update_stats(successful=False, tests_generated=3, tests_passing=0)
        mem.update_stats(successful=True, tests_generated=2, tests_passing=2)

        # Reload from disk
        mem2 = GlobalMemory(tmp_path)
        stats = mem2.get_stats()

        assert stats["total_runs"] == 3
        assert stats["successful_generations"] == 2
        assert stats["failed_generations"] == 1
        assert stats["total_tests_generated"] == 10
        assert stats["total_tests_passing"] == 6
        assert stats["last_run"] != ""

    def test_persistence_across_simulated_runs(self, tmp_path: Path) -> None:
        """Multiple GlobalMemory instances (simulating separate runs) accumulate data."""
        # Run 1
        run1 = GlobalMemory(tmp_path)
        run1.set_conventions({"style": "pytest"})
        run1.add_known_pattern("fixture-injection")
        run1.update_stats(successful=True, tests_generated=10, tests_passing=8)

        # Run 2 (new instance, reads from disk)
        run2 = GlobalMemory(tmp_path)
        assert run2.get_conventions() == {"style": "pytest"}
        assert len(run2.get_known_patterns()) == 1
        run2.add_known_pattern("parametrize")
        run2.update_stats(successful=True, tests_generated=5, tests_passing=5)

        # Run 3 (verify accumulated state)
        run3 = GlobalMemory(tmp_path)
        assert len(run3.get_known_patterns()) == 2
        stats = run3.get_stats()
        assert stats["total_runs"] == 2
        assert stats["total_tests_generated"] == 15
        assert stats["total_tests_passing"] == 13

    def test_clear_resets_all_data(self, tmp_path: Path) -> None:
        """clear() removes all data and reinitializes empty structure."""
        mem = GlobalMemory(tmp_path)
        mem.set_conventions({"style": "pytest"})
        mem.add_known_pattern("some-pattern")
        mem.add_failed_pattern("bad-pattern", "reason")
        mem.update_stats(successful=True, tests_generated=5, tests_passing=5)

        mem.clear()

        assert mem.get_conventions() == {}
        assert mem.get_known_patterns() == []
        assert mem.get_failed_patterns() == []
        stats = mem.get_stats()
        assert stats["total_runs"] == 0

    def test_to_dict_and_to_markdown(self, tmp_path: Path) -> None:
        """to_dict() and to_markdown() produce valid output."""
        mem = GlobalMemory(tmp_path)
        mem.set_conventions({"style": "pytest"})
        mem.add_known_pattern("aaa-pattern")
        mem.update_stats(successful=True, tests_generated=3, tests_passing=3)

        data = mem.to_dict()
        assert isinstance(data, dict)
        assert "conventions" in data
        assert "known_patterns" in data
        assert "generation_stats" in data

        markdown = mem.to_markdown()
        assert isinstance(markdown, str)
        assert "# Global Memory Report" in markdown
        assert "aaa-pattern" in markdown


# ── PackageMemory lifecycle ──────────────────────────────────────


@pytest.mark.integration
class TestPackageMemoryLifecycle:
    """Test PackageMemory write -> read -> verify roundtrip."""

    def test_test_patterns_roundtrip(self, tmp_path: Path) -> None:
        """Test patterns survive write -> reload."""
        mem = PackageMemory(tmp_path, "my-package")
        patterns: dict[str, Any] = {
            "naming": "test_<function>_<scenario>",
            "imports": ["pytest", "unittest.mock"],
        }
        mem.set_test_patterns(patterns)

        # Reload from disk
        mem2 = PackageMemory(tmp_path, "my-package")
        loaded = mem2.get_test_patterns()
        assert loaded == patterns

    def test_known_issues_roundtrip(self, tmp_path: Path) -> None:
        """Known issues survive write -> reload."""
        mem = PackageMemory(tmp_path, "my-package")
        mem.add_known_issue(
            "flaky database test",
            workaround="add retry logic",
            context={"file": "test_db.py"},
        )
        mem.add_known_issue("slow integration test", workaround="use mock")

        # Reload from disk
        mem2 = PackageMemory(tmp_path, "my-package")
        issues = mem2.get_known_issues()

        assert len(issues) == 2
        db_issue = next(i for i in issues if "flaky" in i["issue"])
        assert db_issue["workaround"] == "add retry logic"
        assert db_issue["context"] == {"file": "test_db.py"}

    def test_coverage_history_roundtrip(self, tmp_path: Path) -> None:
        """Coverage snapshots survive write -> reload."""
        mem = PackageMemory(tmp_path, "web-app")
        mem.add_coverage_snapshot(65.5, line_coverage={"total": 100, "covered": 65})
        mem.add_coverage_snapshot(72.3, line_coverage={"total": 100, "covered": 72})
        mem.add_coverage_snapshot(80.0, line_coverage={"total": 100, "covered": 80})

        # Reload from disk
        mem2 = PackageMemory(tmp_path, "web-app")
        history = mem2.get_coverage_history()

        assert len(history) == 3
        assert history[0]["coverage_percent"] == 65.5
        assert history[2]["coverage_percent"] == 80.0

        latest = mem2.get_latest_coverage()
        assert latest is not None
        assert latest["coverage_percent"] == 80.0

    def test_llm_feedback_roundtrip(self, tmp_path: Path) -> None:
        """LLM feedback entries survive write -> reload."""
        mem = PackageMemory(tmp_path, "core-lib")
        mem.add_llm_feedback(
            "improvement",
            "Consider using parameterized tests",
            metadata={"model": "claude", "run_id": "abc123"},
        )
        mem.add_llm_feedback("error", "Generated code had syntax errors")

        # Reload from disk
        mem2 = PackageMemory(tmp_path, "core-lib")
        feedback = mem2.get_llm_feedback()

        assert len(feedback) == 2
        improvement = next(f for f in feedback if f["type"] == "improvement")
        assert "parameterized" in improvement["content"]
        assert improvement["metadata"]["model"] == "claude"

    def test_persistence_across_simulated_runs(self, tmp_path: Path) -> None:
        """Multiple PackageMemory instances accumulate data correctly."""
        # Run 1
        run1 = PackageMemory(tmp_path, "api-service")
        run1.set_test_patterns({"style": "bdd"})
        run1.add_coverage_snapshot(50.0)
        run1.add_known_issue("missing auth tests")

        # Run 2
        run2 = PackageMemory(tmp_path, "api-service")
        assert run2.get_test_patterns() == {"style": "bdd"}
        run2.add_coverage_snapshot(65.0)
        run2.add_known_issue("missing edge case tests")

        # Run 3 (verify accumulated state)
        run3 = PackageMemory(tmp_path, "api-service")
        assert len(run3.get_coverage_history()) == 2
        assert len(run3.get_known_issues()) == 2
        assert run3.get_test_patterns() == {"style": "bdd"}

    def test_clear_resets_all_data(self, tmp_path: Path) -> None:
        """clear() removes all package memory data."""
        mem = PackageMemory(tmp_path, "my-pkg")
        mem.set_test_patterns({"style": "tdd"})
        mem.add_known_issue("some issue")
        mem.add_coverage_snapshot(90.0)
        mem.add_llm_feedback("suggestion", "use mocks")

        mem.clear()

        assert mem.get_test_patterns() == {}
        assert mem.get_known_issues() == []
        assert mem.get_coverage_history() == []
        assert mem.get_llm_feedback() == []

    def test_to_dict_and_to_markdown(self, tmp_path: Path) -> None:
        """to_dict() and to_markdown() produce valid output."""
        mem = PackageMemory(tmp_path, "test-pkg")
        mem.set_test_patterns({"naming": "test_*"})
        mem.add_coverage_snapshot(75.0)

        data = mem.to_dict()
        assert isinstance(data, dict)
        assert "test_patterns" in data
        assert "coverage_history" in data

        markdown = mem.to_markdown()
        assert isinstance(markdown, str)
        assert "# Package Memory Report: test-pkg" in markdown
        assert "75.0%" in markdown


# ── Cross-memory interaction ─────────────────────────────────────


@pytest.mark.integration
class TestMemoryCrossInteraction:
    """Test GlobalMemory and PackageMemory coexisting for the same project."""

    def test_global_and_package_memory_coexist(self, tmp_path: Path) -> None:
        """Both memory types use the same project root without conflicts."""
        global_mem = GlobalMemory(tmp_path)
        pkg_mem_a = PackageMemory(tmp_path, "package-a")
        pkg_mem_b = PackageMemory(tmp_path, "package-b")

        # Write to all three
        global_mem.set_conventions({"style": "pytest"})
        pkg_mem_a.set_test_patterns({"naming": "test_*"})
        pkg_mem_b.set_test_patterns({"naming": "*_test"})

        # Reload all from disk
        g2 = GlobalMemory(tmp_path)
        a2 = PackageMemory(tmp_path, "package-a")
        b2 = PackageMemory(tmp_path, "package-b")

        # Each has its own data
        assert g2.get_conventions() == {"style": "pytest"}
        assert a2.get_test_patterns() == {"naming": "test_*"}
        assert b2.get_test_patterns() == {"naming": "*_test"}

    def test_package_names_with_slashes_are_sanitized(self, tmp_path: Path) -> None:
        """Package names with path separators are safely sanitized for filenames."""
        mem = PackageMemory(tmp_path, "packages/web/frontend")
        mem.set_test_patterns({"framework": "vitest"})

        # Reload
        mem2 = PackageMemory(tmp_path, "packages/web/frontend")
        assert mem2.get_test_patterns() == {"framework": "vitest"}

    def test_clearing_one_memory_does_not_affect_others(self, tmp_path: Path) -> None:
        """Clearing global memory does not affect package memory and vice versa."""
        global_mem = GlobalMemory(tmp_path)
        pkg_mem = PackageMemory(tmp_path, "my-pkg")

        global_mem.set_conventions({"style": "pytest"})
        pkg_mem.set_test_patterns({"naming": "test_*"})

        # Clear global only
        global_mem.clear()
        assert global_mem.get_conventions() == {}

        # Package memory should be unaffected
        pkg_reload = PackageMemory(tmp_path, "my-pkg")
        assert pkg_reload.get_test_patterns() == {"naming": "test_*"}

    def test_multiple_packages_independent(self, tmp_path: Path) -> None:
        """Different packages maintain independent memory stores."""
        mem_a = PackageMemory(tmp_path, "pkg-a")
        mem_b = PackageMemory(tmp_path, "pkg-b")

        mem_a.add_coverage_snapshot(80.0)
        mem_a.add_coverage_snapshot(85.0)
        mem_b.add_coverage_snapshot(60.0)

        # Reload
        a2 = PackageMemory(tmp_path, "pkg-a")
        b2 = PackageMemory(tmp_path, "pkg-b")

        assert len(a2.get_coverage_history()) == 2
        assert len(b2.get_coverage_history()) == 1

        # Clear one, other is unaffected
        a2.clear()
        b3 = PackageMemory(tmp_path, "pkg-b")
        assert len(b3.get_coverage_history()) == 1
