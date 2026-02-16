"""Tests for module integration wiring.

Verifies that all new modules are properly reachable through their
__init__.py re-exports, registry entries, builder prompt templates,
and CLI dispatch points.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nit.adapters.mutation.base import MutationTestingAdapter
from nit.adapters.registry import AdapterRegistry
from nit.agents.builders.accessibility import AccessibilityTestBuilder
from nit.agents.builders.api import APITestBuilder
from nit.agents.builders.contract import ContractTestBuilder
from nit.agents.builders.graphql import GraphQLTestBuilder
from nit.agents.builders.migration import MigrationTestBuilder
from nit.agents.builders.snapshot import SnapshotTestBuilder
from nit.agents.pipelines.pick import PickPipelineResult
from nit.agents.watchers.file_watch_ui import FileWatchUI
from nit.agents.watchers.file_watcher import FileWatchConfig, FileWatcher
from nit.cli import (
    _display_pick_result_formatted,
    _pick_result_to_extra,
    _run_specialized_generate,
)
from nit.llm.prompts.accessibility_test_prompt import (
    JestAxeTemplate,
    PlaywrightAxeTemplate,
)
from nit.llm.prompts.api_test_prompt import APITestTemplate
from nit.llm.prompts.contract_test_prompt import (
    JestPactTemplate,
    PytestPactTemplate,
    VitestPactTemplate,
)
from nit.llm.prompts.graphql_test_prompt import GraphQLTestTemplate
from nit.llm.prompts.migration_test_prompt import (
    AlembicMigrationTemplate,
    DjangoMigrationTemplate,
)
from nit.llm.prompts.snapshot_test_prompt import (
    JestSnapshotTemplate,
    PytestSyrupyTemplate,
)
from nit.memory.prompt_sync import PromptSyncer

# ── __init__.py re-export tests ──────────────────────────────────


class TestAnalyzerReExports:
    """Verify all analyzer symbols are importable from the package."""

    @pytest.mark.parametrize(
        "name",
        [
            "AccessibilityAnalysisResult",
            "AccessibilityReport",
            "AccessibilityViolation",
            "analyze_accessibility",
            "detect_frontend_project",
            "ContractAnalysisResult",
            "PactContract",
            "PactInteraction",
            "analyze_contracts",
            "detect_contract_files",
            "Migration",
            "MigrationAnalysisResult",
            "analyze_migrations",
            "detect_migration_framework",
            "discover_migrations",
            "GraphQLField",
            "GraphQLOperation",
            "GraphQLSchemaAnalysis",
            "GraphQLTypeInfo",
            "analyze_graphql_schema",
            "detect_graphql_schemas",
            "MutationAnalysisResult",
            "MutationTestAnalyzer",
            "OpenAPIAnalysisResult",
            "OpenAPIEndpoint",
            "OpenAPIParameter",
            "analyze_openapi_spec",
            "detect_openapi_specs",
            "SnapshotAnalysisResult",
            "SnapshotFile",
            "analyze_snapshots",
            "detect_snapshot_framework",
            "discover_snapshots",
            "TestMapper",
            "TestMapping",
        ],
    )
    def test_analyzer_symbol_importable(self, name: str) -> None:
        mod = importlib.import_module("nit.agents.analyzers")
        assert hasattr(mod, name), f"{name} not found in nit.agents.analyzers"


class TestBuilderReExports:
    """Verify all builder symbols are importable from the package."""

    @pytest.mark.parametrize(
        "name",
        [
            "AccessibilityTestBuilder",
            "AccessibilityTestCase",
            "APITestBuilder",
            "APITestCase",
            "ContractTestBuilder",
            "ContractTestCase",
            "GraphQLTestBuilder",
            "GraphQLTestCase",
            "MigrationTestBuilder",
            "MigrationTestCase",
            "MutationTestBuilder",
            "MutationTestCase",
            "SnapshotTestBuilder",
            "SnapshotTestCase",
        ],
    )
    def test_builder_symbol_importable(self, name: str) -> None:
        mod = importlib.import_module("nit.agents.builders")
        assert hasattr(mod, name), f"{name} not found in nit.agents.builders"


class TestReporterReExports:
    """Verify all reporter symbols are importable from the package."""

    @pytest.mark.parametrize(
        "name",
        [
            "JSONReporter",
            "JUnitXMLReporter",
            "MarkdownReporter",
            "SARIFReporter",
        ],
    )
    def test_reporter_symbol_importable(self, name: str) -> None:
        mod = importlib.import_module("nit.agents.reporters")
        assert hasattr(mod, name), f"{name} not found in nit.agents.reporters"


class TestWatcherReExports:
    """Verify all watcher symbols are importable from the package."""

    @pytest.mark.parametrize(
        "name",
        [
            "FileWatcher",
            "FileWatchUI",
            "FileChange",
            "WatchEvent",
            "FileWatchConfig",
        ],
    )
    def test_watcher_symbol_importable(self, name: str) -> None:
        mod = importlib.import_module("nit.agents.watchers")
        assert hasattr(mod, name), f"{name} not found in nit.agents.watchers"


class TestPromptReExports:
    """Verify all prompt symbols are importable from the package."""

    @pytest.mark.parametrize(
        "name",
        [
            "AccessibilityTestTemplate",
            "PlaywrightAxeTemplate",
            "JestAxeTemplate",
            "APITestTemplate",
            "ContractTestTemplate",
            "PytestPactTemplate",
            "JestPactTemplate",
            "VitestPactTemplate",
            "CypressTemplate",
            "GraphQLTestTemplate",
            "JestTemplate",
            "MigrationTestTemplate",
            "AlembicMigrationTemplate",
            "DjangoMigrationTemplate",
            "MochaTemplate",
            "MutationTestPromptContext",
            "build_mutation_test_messages",
            "SnapshotTestTemplate",
            "JestSnapshotTemplate",
            "PytestSyrupyTemplate",
        ],
    )
    def test_prompt_symbol_importable(self, name: str) -> None:
        mod = importlib.import_module("nit.llm.prompts")
        assert hasattr(mod, name), f"{name} not found in nit.llm.prompts"


class TestLLMReExports:
    """Verify LLM module re-exports."""

    def test_tracked_engine_importable(self) -> None:
        mod = importlib.import_module("nit.llm")
        assert hasattr(mod, "TrackedLLMEngine")


class TestMemoryReExports:
    """Verify memory module re-exports."""

    @pytest.mark.parametrize(
        "name",
        [
            "PromptAnalytics",
            "PromptRecorder",
            "get_prompt_recorder",
            "PromptSyncer",
        ],
    )
    def test_memory_symbol_importable(self, name: str) -> None:
        mod = importlib.import_module("nit.memory")
        assert hasattr(mod, name), f"{name} not found in nit.memory"


class TestModelReExports:
    """Verify model module re-exports."""

    @pytest.mark.parametrize(
        "name",
        [
            "PromptRecord",
            "PromptLineage",
            "OutcomeUpdate",
        ],
    )
    def test_model_symbol_importable(self, name: str) -> None:
        mod = importlib.import_module("nit.models")
        assert hasattr(mod, name), f"{name} not found in nit.models"


class TestShardingReExports:
    """Verify sharding module re-exports."""

    @pytest.mark.parametrize(
        "name",
        [
            "RiskScore",
            "PrioritizedTestPlan",
            "prioritize_test_files_by_risk",
            "distribute_prioritized_shards",
        ],
    )
    def test_sharding_symbol_importable(self, name: str) -> None:
        mod = importlib.import_module("nit.sharding")
        assert hasattr(mod, name), f"{name} not found in nit.sharding"


# ── Mutation adapter registry tests ─────────────────────────────


class TestMutationAdapterRegistry:
    """Verify mutation adapters are discovered by the registry."""

    def test_registry_discovers_mutation_adapters(self) -> None:
        reg = AdapterRegistry()
        adapters = reg.list_mutation_adapters()
        assert "mutmut" in adapters
        assert "pitest" in adapters
        assert "stryker" in adapters

    def test_registry_get_mutation_adapter(self) -> None:
        reg = AdapterRegistry()
        adapter = reg.get_mutation_adapter("mutmut")
        assert adapter is not None
        assert isinstance(adapter, MutationTestingAdapter)

    def test_registry_get_unknown_mutation_adapter(self) -> None:
        reg = AdapterRegistry()
        adapter = reg.get_mutation_adapter("nonexistent")
        assert adapter is None


# ── Builder prompt template tests ────────────────────────────────


class TestBuilderPromptTemplates:
    """Verify builder prompt template wiring."""

    def test_accessibility_builder_playwright_template(self) -> None:
        builder = AccessibilityTestBuilder()
        template = builder.get_prompt_template("playwright")
        assert isinstance(template, PlaywrightAxeTemplate)

    def test_accessibility_builder_jest_template(self) -> None:
        builder = AccessibilityTestBuilder()
        template = builder.get_prompt_template("jest")
        assert isinstance(template, JestAxeTemplate)

    def test_api_builder_template(self) -> None:
        builder = APITestBuilder()
        template = builder.get_prompt_template()
        assert isinstance(template, APITestTemplate)

    def test_contract_builder_pytest_template(self) -> None:
        builder = ContractTestBuilder()
        template = builder.get_prompt_template("pytest")
        assert isinstance(template, PytestPactTemplate)

    def test_contract_builder_jest_template(self) -> None:
        builder = ContractTestBuilder()
        template = builder.get_prompt_template("jest")
        assert isinstance(template, JestPactTemplate)

    def test_contract_builder_vitest_template(self) -> None:
        builder = ContractTestBuilder()
        template = builder.get_prompt_template("vitest")
        assert isinstance(template, VitestPactTemplate)

    def test_graphql_builder_template(self) -> None:
        builder = GraphQLTestBuilder()
        template = builder.get_prompt_template()
        assert isinstance(template, GraphQLTestTemplate)

    def test_migration_builder_alembic_template(self) -> None:
        builder = MigrationTestBuilder()
        template = builder.get_prompt_template("alembic")
        assert isinstance(template, AlembicMigrationTemplate)

    def test_migration_builder_django_template(self) -> None:
        builder = MigrationTestBuilder()
        template = builder.get_prompt_template("django")
        assert isinstance(template, DjangoMigrationTemplate)

    def test_snapshot_builder_jest_template(self) -> None:
        builder = SnapshotTestBuilder()
        template = builder.get_prompt_template("jest")
        assert isinstance(template, JestSnapshotTemplate)

    def test_snapshot_builder_pytest_template(self) -> None:
        builder = SnapshotTestBuilder()
        template = builder.get_prompt_template("pytest")
        assert isinstance(template, PytestSyrupyTemplate)


# ── CLI format dispatch tests ────────────────────────────────────


class TestCLIFormatDispatch:
    """Verify CLI --format dispatch wiring."""

    def test_pick_result_to_extra_basic(self) -> None:
        result = PickPipelineResult(
            tests_run=10,
            tests_passed=8,
            tests_failed=1,
            tests_errors=1,
            success=True,
        )
        extra = _pick_result_to_extra(result)
        assert extra["summary"]["tests_run"] == 10
        assert extra["summary"]["tests_passed"] == 8
        assert extra["summary"]["success"] is True
        assert "bugs" not in extra

    def test_display_pick_result_formatted_terminal(self) -> None:
        """Terminal format should call _display_pick_results without error."""
        result = PickPipelineResult(
            tests_run=5,
            tests_passed=5,
            success=True,
        )
        with patch("nit.cli._display_pick_results") as mock_display:
            _display_pick_result_formatted(result, fix_enabled=False, output_format="terminal")
            mock_display.assert_called_once()
            call_args = mock_display.call_args[0]
            assert call_args[0] is result
            assert call_args[1] is False

    def test_display_pick_result_formatted_json(self) -> None:
        """JSON format should produce valid JSON."""
        result = PickPipelineResult(
            tests_run=3,
            tests_passed=3,
            success=True,
        )
        with patch("nit.cli.click.echo") as mock_echo:
            _display_pick_result_formatted(result, fix_enabled=False, output_format="json")
            mock_echo.assert_called_once()
            output = mock_echo.call_args[0][0]
            parsed = json.loads(output)
            assert parsed["summary"]["tests_run"] == 3

    def test_display_pick_result_formatted_markdown(self) -> None:
        """Markdown format should produce markdown content."""
        result = PickPipelineResult(
            tests_run=2,
            tests_passed=2,
            success=True,
        )
        with patch("nit.cli.click.echo") as mock_echo:
            _display_pick_result_formatted(result, fix_enabled=False, output_format="markdown")
            mock_echo.assert_called_once()
            output = mock_echo.call_args[0][0]
            assert "# nit Test Report" in output

    def test_display_pick_result_formatted_junit(self) -> None:
        """JUnit format should produce XML content."""
        result = PickPipelineResult(
            tests_run=1,
            tests_passed=1,
            success=True,
        )
        with patch("nit.cli.click.echo") as mock_echo:
            _display_pick_result_formatted(result, fix_enabled=False, output_format="junit")
            mock_echo.assert_called_once()
            output = mock_echo.call_args[0][0]
            assert "<testsuites" in output


# ── CLI generate --type tests ────────────────────────────────────


class TestCLIGenerateTypes:
    """Verify specialized generate --type dispatch."""

    @pytest.mark.parametrize(
        "test_type",
        [
            "accessibility",
            "api",
            "contract",
            "graphql",
            "migration",
            "mutation",
            "snapshot",
        ],
    )
    def test_specialized_generate_dispatch(self, test_type: str, tmp_path: Path) -> None:
        with patch("nit.cli.reporter") as mock_reporter:
            _run_specialized_generate(test_type, tmp_path, ci_mode=False)
            assert mock_reporter.print_info.called

    def test_specialized_generate_unknown_type(self, tmp_path: Path) -> None:
        with patch("nit.cli.reporter") as mock_reporter:
            _run_specialized_generate("nonexistent", tmp_path, ci_mode=False)
            mock_reporter.print_error.assert_called_once()


# ── CLI watch --file-watch tests ─────────────────────────────────


class TestCLIFileWatch:
    """Verify file-watch mode wiring."""

    def test_file_watch_mode_imports(self, tmp_path: Path) -> None:
        """Verify the file-watch modules are importable and constructible."""
        config = FileWatchConfig()
        assert config.poll_interval > 0
        assert len(config.watch_patterns) > 0

        ui = FileWatchUI()
        assert ui._status == "IDLE"

        watcher = FileWatcher(tmp_path, config)
        assert not watcher.running


# ── PickPipelineResult specialized fields ────────────────────────


class TestPickPipelineResultFields:
    """Verify PickPipelineResult has specialized analysis fields."""

    def test_result_has_specialized_fields(self) -> None:
        result = PickPipelineResult()
        assert result.accessibility_report is None
        assert result.openapi_report is None
        assert result.graphql_report is None
        assert result.contract_report is None
        assert result.migration_report is None
        assert result.snapshot_report is None
        assert result.mutation_report is None


# ── Prompt sync CLI tests ────────────────────────────────────────


class TestPromptSyncIntegration:
    """Verify PromptSyncer is importable and wired."""

    def test_prompt_syncer_importable(self) -> None:
        assert PromptSyncer is not None

    def test_prompt_syncer_from_memory_package(self) -> None:
        mod = importlib.import_module("nit.memory")
        assert hasattr(mod, "PromptSyncer")
        assert mod.PromptSyncer is PromptSyncer
