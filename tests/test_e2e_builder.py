"""Tests for the E2EBuilder agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.base import RunResult, ValidationResult
from nit.agents.base import TaskInput, TaskStatus
from nit.agents.builders.e2e import E2EBuilder, E2ETask
from nit.agents.healers.self_healing import HealingResult
from nit.llm.context import AssembledContext
from nit.llm.engine import GenerationRequest, LLMMessage, LLMResponse
from nit.llm.prompts.base import RenderedPrompt
from nit.parsing.treesitter import ParseResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_engine(text: str = "test code") -> MagicMock:
    """Create a mock LLM engine that returns *text*."""
    engine = MagicMock()
    engine.generate = AsyncMock(
        return_value=LLMResponse(
            text=text,
            model="mock-model",
            prompt_tokens=100,
            completion_tokens=50,
        )
    )
    return engine


def _make_adapter(
    *,
    valid: bool = True,
    errors: list[str] | None = None,
    detect: bool = True,
) -> MagicMock:
    """Create a mock Playwright adapter."""
    adapter = MagicMock()
    adapter.name = "playwright"
    adapter.detect.return_value = detect
    adapter.validate_test.return_value = ValidationResult(
        valid=valid,
        errors=errors or [],
    )
    rendered = RenderedPrompt(messages=[LLMMessage(role="user", content="generate e2e test")])
    adapter.get_prompt_template.return_value.render.return_value = rendered
    adapter.run_tests = AsyncMock(
        return_value=RunResult(passed=1, success=True),
    )
    return adapter


def _make_registry(adapter: MagicMock | None = None) -> MagicMock:
    """Create a mock adapter registry returning *adapter*."""
    registry = MagicMock()
    registry.get_test_adapter.return_value = adapter
    return registry


# ---------------------------------------------------------------------------
# E2ETask
# ---------------------------------------------------------------------------


class TestE2ETask:
    def test_post_init_sets_target_from_route_path(self) -> None:
        task = E2ETask(route_path="/users/:id")
        assert task.target == "/users/:id"

    def test_post_init_does_not_overwrite_explicit_target(self) -> None:
        task = E2ETask(target="custom", route_path="/api/health")
        assert task.target == "custom"

    def test_post_init_empty_route_path_keeps_empty_target(self) -> None:
        task = E2ETask()
        assert task.target == ""

    def test_default_task_type(self) -> None:
        task = E2ETask()
        assert task.task_type == "build_e2e_test"

    def test_flow_description_field(self) -> None:
        task = E2ETask(flow_description="login -> dashboard")
        assert task.flow_description == "login -> dashboard"


# ---------------------------------------------------------------------------
# E2EBuilder.__init__
# ---------------------------------------------------------------------------


class TestE2EBuilderInit:
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_defaults(
        self,
        mock_assembler_cls: MagicMock,
        mock_memory_cls: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        engine = _make_llm_engine()
        builder = E2EBuilder(engine, tmp_path)

        assert builder._enable_memory is True
        assert builder._enable_self_healing is True
        assert builder._enable_validation is True
        assert builder._max_retries == 3
        mock_assembler_cls.assert_called_once_with(root=tmp_path, max_context_tokens=8000)
        mock_memory_cls.assert_called_once_with(tmp_path)

    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_custom_config(
        self,
        mock_assembler_cls: MagicMock,
        mock_memory_cls: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        engine = _make_llm_engine()
        builder = E2EBuilder(
            engine,
            tmp_path,
            config={
                "max_context_tokens": 4000,
                "enable_memory": False,
                "enable_self_healing": False,
                "validation": {"enabled": False, "max_retries": 5},
            },
        )

        assert builder._enable_memory is False
        assert builder._memory is None
        assert builder._enable_self_healing is False
        assert builder._enable_validation is False
        assert builder._max_retries == 5
        mock_assembler_cls.assert_called_once_with(root=tmp_path, max_context_tokens=4000)

    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_non_int_max_context_defaults_to_8000(
        self,
        mock_assembler_cls: MagicMock,
        mock_memory_cls: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        engine = _make_llm_engine()
        bad_config: Any = {"max_context_tokens": "not_int"}
        E2EBuilder(engine, tmp_path, config=bad_config)
        mock_assembler_cls.assert_called_once_with(root=tmp_path, max_context_tokens=8000)

    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_validation_cfg_not_dict_uses_defaults(
        self,
        mock_assembler_cls: MagicMock,
        mock_memory_cls: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        engine = _make_llm_engine()
        bad_config: Any = {"validation": "bad"}
        builder = E2EBuilder(engine, tmp_path, config=bad_config)
        assert builder._enable_validation is True
        assert builder._max_retries == 3

    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_non_int_max_retries_defaults(
        self,
        mock_assembler_cls: MagicMock,
        mock_memory_cls: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        engine = _make_llm_engine()
        bad_config: Any = {"validation": {"max_retries": "nope"}}
        builder = E2EBuilder(engine, tmp_path, config=bad_config)
        assert builder._max_retries == 3


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestE2EBuilderProperties:
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_name(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        assert builder.name == "e2e_builder"

    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_description(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        assert "E2E" in builder.description


# ---------------------------------------------------------------------------
# _clean_code_blocks
# ---------------------------------------------------------------------------


class TestCleanCodeBlocks:
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_removes_typescript_fence(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        raw = "```typescript\nconst x = 1;\n```"
        assert builder._clean_code_blocks(raw) == "const x = 1;"

    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_no_fence_unchanged(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        code = "const x = 1;"
        assert builder._clean_code_blocks(code) == code

    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_opening_fence_without_closing(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        raw = "```\nconst x = 1;"
        assert builder._clean_code_blocks(raw) == "const x = 1;"


# ---------------------------------------------------------------------------
# _resolve_path
# ---------------------------------------------------------------------------


class TestResolvePath:
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_relative_path(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        result = builder._resolve_path("src/handler.ts")
        assert result == tmp_path / "src/handler.ts"

    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    def test_absolute_path(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        abs_path = str(Path("/abs/handler.ts").resolve())
        result = builder._resolve_path(abs_path)
        assert result == Path(abs_path)


# ---------------------------------------------------------------------------
# _assemble_e2e_context
# ---------------------------------------------------------------------------


class TestAssembleE2EContext:
    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_without_handler_file(
        self,
        mock_assembler_cls: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        task = E2ETask(route_path="/api/users", base_url="http://localhost:3000")

        context = await builder._assemble_e2e_context(task)

        assert context.language == "typescript"
        assert context.source_code == ""
        assert context.base_url == "http://localhost:3000"

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_with_handler_file(
        self,
        mock_assembler_cls: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_ctx = AssembledContext(
            source_path="src/handler.ts",
            source_code="export default handler;",
            language="typescript",
            parse_result=ParseResult(language="typescript", functions=[], classes=[], imports=[]),
            related_files=[],
            total_tokens=100,
        )
        mock_assembler_cls.return_value.assemble.return_value = mock_ctx

        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        task = E2ETask(
            route_path="/api/users",
            handler_file="src/handler.ts",
            base_url="http://localhost:3000",
        )

        context = await builder._assemble_e2e_context(task)

        assert context.source_code == "export default handler;"
        assert context.base_url == "http://localhost:3000"

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_attaches_route_info(
        self,
        mock_assembler_cls: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        route_info = MagicMock()
        task = E2ETask(route_path="/api/users", route_info=route_info)

        context = await builder._assemble_e2e_context(task)

        assert context.route_info is route_info

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_attaches_auth_config(
        self,
        mock_assembler_cls: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        auth_config = MagicMock()
        task = E2ETask(route_path="/secure", auth_config=auth_config)

        context = await builder._assemble_e2e_context(task)

        assert context.auth_config is auth_config

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_attaches_flow_description(
        self,
        mock_assembler_cls: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        task = E2ETask(
            route_path="/app",
            flow_description="login -> dashboard -> logout",
        )

        context = await builder._assemble_e2e_context(task)

        assert context.flow_description == "login -> dashboard -> logout"


# ---------------------------------------------------------------------------
# run() — full pipeline
# ---------------------------------------------------------------------------


class TestE2EBuilderRun:
    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_rejects_non_e2e_task(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        wrong_task = TaskInput(task_type="unit", target="foo.py")

        result = await builder.run(wrong_task)

        assert result.status == TaskStatus.FAILED
        assert "E2ETask" in result.errors[0]

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_fails_when_adapter_not_found(
        self,
        _a: MagicMock,
        _b: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_get_registry.return_value.get_test_adapter.return_value = None

        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        task = E2ETask(route_path="/api/users")

        result = await builder.run(task)

        assert result.status == TaskStatus.FAILED
        assert "Playwright adapter not found" in result.errors[0]

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_successful_generation_without_validation(
        self,
        _a: MagicMock,
        mock_memory_cls: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter()
        mock_get_registry.return_value.get_test_adapter.return_value = adapter
        engine = _make_llm_engine("const test = true;")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"validation": {"enabled": False}},
        )
        task = E2ETask(route_path="/api/users", base_url="http://localhost:3000")

        result = await builder.run(task)

        assert result.status == TaskStatus.COMPLETED
        assert result.result["test_code"] == "const test = true;"
        assert result.result["route_path"] == "/api/users"
        assert result.result["validation_enabled"] is False
        assert result.result["model"] == "mock-model"

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_successful_generation_with_validation_pass(
        self,
        _a: MagicMock,
        mock_memory_cls: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter(valid=True)
        mock_get_registry.return_value.get_test_adapter.return_value = adapter
        engine = _make_llm_engine("valid test code")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"enable_self_healing": False},
        )
        task = E2ETask(route_path="/api/users")

        result = await builder.run(task)

        assert result.status == TaskStatus.COMPLETED
        assert result.result["validation_passed"] is True

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_validation_fails_returns_failed_status(
        self,
        _a: MagicMock,
        mock_memory_cls: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter(valid=False, errors=["syntax error line 1"])
        mock_get_registry.return_value.get_test_adapter.return_value = adapter
        engine = _make_llm_engine("bad code")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"enable_self_healing": False},
        )
        task = E2ETask(route_path="/api/users")

        result = await builder.run(task)

        assert result.status == TaskStatus.FAILED
        assert result.result["validation_passed"] is False
        assert "syntax error line 1" in result.errors

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_memory_updated_on_success(
        self,
        _a: MagicMock,
        mock_memory_cls: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter(valid=True)
        mock_get_registry.return_value.get_test_adapter.return_value = adapter
        mock_memory = MagicMock()
        mock_memory_cls.return_value = mock_memory
        engine = _make_llm_engine("test code")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"enable_self_healing": False},
        )
        task = E2ETask(route_path="/api/users")

        await builder.run(task)

        mock_memory.update_stats.assert_called_once_with(
            successful=True,
            tests_generated=1,
        )

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_memory_not_updated_when_disabled(
        self,
        _a: MagicMock,
        mock_memory_cls: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter(valid=True)
        mock_get_registry.return_value.get_test_adapter.return_value = adapter
        engine = _make_llm_engine("test code")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"enable_memory": False, "enable_self_healing": False},
        )
        task = E2ETask(route_path="/api/users")

        result = await builder.run(task)

        assert result.status == TaskStatus.COMPLETED
        # Memory class should not have been instantiated at all
        assert builder._memory is None

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_exception_returns_failed_output(
        self,
        _a: MagicMock,
        _b: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter()
        mock_get_registry.return_value.get_test_adapter.return_value = adapter
        engine = _make_llm_engine()
        engine.generate = AsyncMock(side_effect=RuntimeError("LLM down"))

        builder = E2EBuilder(engine, tmp_path)
        task = E2ETask(route_path="/api/users")

        result = await builder.run(task)

        assert result.status == TaskStatus.FAILED
        assert "LLM down" in result.errors[0]

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_code_block_stripping_in_pipeline(
        self,
        _a: MagicMock,
        _b: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter(valid=True)
        mock_get_registry.return_value.get_test_adapter.return_value = adapter
        engine = _make_llm_engine("```typescript\nconst x = 1;\n```")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"enable_self_healing": False},
        )
        task = E2ETask(route_path="/api/users")

        result = await builder.run(task)

        assert result.status == TaskStatus.COMPLETED
        assert result.result["test_code"] == "const x = 1;"

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_playwright_not_detected_still_continues(
        self,
        _a: MagicMock,
        _b: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter(detect=False, valid=True)
        mock_get_registry.return_value.get_test_adapter.return_value = adapter
        engine = _make_llm_engine("test code")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"enable_self_healing": False},
        )
        task = E2ETask(route_path="/api/users")

        result = await builder.run(task)

        # Should still succeed even if Playwright not detected
        assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_flow_description_included_in_result(
        self,
        _a: MagicMock,
        _b: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter(valid=True)
        mock_get_registry.return_value.get_test_adapter.return_value = adapter
        engine = _make_llm_engine("test code")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"enable_self_healing": False},
        )
        task = E2ETask(
            route_path="/app",
            flow_description="login -> dashboard",
        )

        result = await builder.run(task)

        assert result.result["flow_description"] == "login -> dashboard"

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_token_usage_in_result(
        self,
        _a: MagicMock,
        _b: MagicMock,
        mock_get_registry: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter(valid=True)
        mock_get_registry.return_value.get_test_adapter.return_value = adapter
        engine = _make_llm_engine("test code")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"enable_self_healing": False},
        )
        task = E2ETask(route_path="/api/users")

        result = await builder.run(task)

        assert result.result["tokens_used"] == 150  # 100 + 50
        assert result.result["prompt_tokens"] == 100
        assert result.result["completion_tokens"] == 50


# ---------------------------------------------------------------------------
# _validate_and_retry
# ---------------------------------------------------------------------------


class TestValidateAndRetry:
    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_passes_first_attempt_no_self_healing(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter(valid=True)
        engine = _make_llm_engine()

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"enable_self_healing": False},
        )

        request = GenerationRequest(messages=[LLMMessage(role="user", content="generate")])
        task = E2ETask(route_path="/api/users")

        code, result = await builder._validate_and_retry("good code", adapter, request, task)

        assert code == "good code"
        assert result.valid is True

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_retries_on_validation_failure(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = MagicMock()
        # First call fails, second call succeeds
        adapter.validate_test.side_effect = [
            ValidationResult(valid=False, errors=["syntax error"]),
            ValidationResult(valid=True),
        ]

        engine = _make_llm_engine("fixed code")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"enable_self_healing": False},
        )

        request = GenerationRequest(messages=[LLMMessage(role="user", content="generate")])
        task = E2ETask(route_path="/api/users")

        code, result = await builder._validate_and_retry("bad code", adapter, request, task)

        assert result.valid is True
        assert code == "fixed code"
        assert engine.generate.await_count == 1

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_exhausts_retries(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = MagicMock()
        adapter.validate_test.return_value = ValidationResult(
            valid=False, errors=["persistent error"]
        )
        engine = _make_llm_engine("still bad")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={
                "enable_self_healing": False,
                "validation": {"max_retries": 2},
            },
        )

        request = GenerationRequest(messages=[LLMMessage(role="user", content="generate")])
        task = E2ETask(route_path="/api/users")

        _code, result = await builder._validate_and_retry("bad code", adapter, request, task)

        assert result.valid is False
        # First attempt fail + retry fail = 1 LLM generate call (between attempts)
        assert engine.generate.await_count == 1

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_retry_includes_error_feedback(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = MagicMock()
        adapter.validate_test.side_effect = [
            ValidationResult(valid=False, errors=["missing import"]),
            ValidationResult(valid=True),
        ]
        engine = _make_llm_engine("fixed code")

        builder = E2EBuilder(
            engine,
            tmp_path,
            config={"enable_self_healing": False},
        )

        original_messages = [LLMMessage(role="user", content="generate")]
        request = GenerationRequest(messages=original_messages)
        task = E2ETask(route_path="/api/users")

        await builder._validate_and_retry("bad code", adapter, request, task)

        # Verify the retry request includes error feedback
        call_args = engine.generate.call_args
        retry_request: GenerationRequest = call_args[0][0]
        last_msg = retry_request.messages[-1]
        assert "missing import" in last_msg.content
        assert last_msg.role == "user"

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_self_healing_triggered_on_runtime_failure(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter(valid=True)
        # Runtime test run fails
        adapter.run_tests = AsyncMock(
            return_value=RunResult(failed=1, success=False, raw_output="selector not found"),
        )

        engine = _make_llm_engine()

        builder = E2EBuilder(engine, tmp_path, config={"enable_self_healing": True})

        # Mock _apply_self_healing
        healed = HealingResult(
            healed=True,
            original_code="bad code",
            healed_code="healed code",
        )
        mock_heal = AsyncMock(return_value=healed)

        request = GenerationRequest(messages=[LLMMessage(role="user", content="generate")])
        task = E2ETask(route_path="/api/users", output_file="tests/e2e/test.spec.ts")

        # Write the output file so _try_run_test can succeed
        test_dir = tmp_path / "tests" / "e2e"
        test_dir.mkdir(parents=True)

        with patch.object(builder, "_apply_self_healing", mock_heal):
            code, _result = await builder._validate_and_retry("bad code", adapter, request, task)

        mock_heal.assert_awaited_once()
        assert code == "healed code"

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_flaky_test_recorded_in_memory(
        self,
        _a: MagicMock,
        mock_memory_cls: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter(valid=True)
        adapter.run_tests = AsyncMock(
            return_value=RunResult(failed=1, success=False),
        )

        mock_memory = MagicMock()
        mock_memory_cls.return_value = mock_memory

        engine = _make_llm_engine()

        builder = E2EBuilder(engine, tmp_path, config={"enable_self_healing": True})

        healed = HealingResult(
            healed=False,
            original_code="bad code",
            is_flaky=True,
            messages=["flaky"],
        )
        mock_heal = AsyncMock(return_value=healed)

        request = GenerationRequest(messages=[LLMMessage(role="user", content="generate")])
        task = E2ETask(route_path="/api/users", output_file="tests/e2e/test.spec.ts")
        test_dir = tmp_path / "tests" / "e2e"
        test_dir.mkdir(parents=True)

        with patch.object(builder, "_apply_self_healing", mock_heal):
            await builder._validate_and_retry("code", adapter, request, task)

        mock_memory.add_failed_pattern.assert_called_once()
        call_kwargs = mock_memory.add_failed_pattern.call_args
        assert call_kwargs[1]["pattern"] == "flaky_test"


# ---------------------------------------------------------------------------
# _try_run_test
# ---------------------------------------------------------------------------


class TestTryRunTest:
    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_returns_none_without_output_file(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        adapter = _make_adapter()
        task = E2ETask(route_path="/api/users")

        result = await builder._try_run_test("code", adapter, task)

        assert result is None

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_writes_and_runs_test(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter()
        adapter.run_tests = AsyncMock(
            return_value=RunResult(passed=1, success=True),
        )

        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        task = E2ETask(route_path="/api/users", output_file="tests/e2e/test.spec.ts")

        result = await builder._try_run_test("const x = 1;", adapter, task)

        assert result is not None
        assert result.success is True

        # Verify file was written
        test_file = tmp_path / "tests" / "e2e" / "test.spec.ts"
        assert test_file.exists()
        assert test_file.read_text() == "const x = 1;"

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_returns_none_on_exception(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        tmp_path: Path,
    ) -> None:
        adapter = _make_adapter()
        adapter.run_tests = AsyncMock(side_effect=RuntimeError("crash"))

        builder = E2EBuilder(_make_llm_engine(), tmp_path)
        task = E2ETask(route_path="/api/users", output_file="tests/e2e/test.spec.ts")

        result = await builder._try_run_test("code", adapter, task)

        assert result is None


# ---------------------------------------------------------------------------
# _apply_self_healing
# ---------------------------------------------------------------------------


class TestApplySelfHealing:
    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.SelfHealingEngine")
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_initializes_engine_lazily(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        mock_healing_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        engine = _make_llm_engine()
        adapter = _make_adapter()
        run_result = RunResult(failed=1, success=False)
        request = GenerationRequest(messages=[LLMMessage(role="user", content="generate")])
        task = E2ETask(route_path="/api/users", output_file="test.spec.ts")

        mock_heal_result = HealingResult(
            healed=True,
            original_code="old",
            healed_code="new",
            messages=["healed!"],
        )
        mock_healing_cls.return_value.heal_test = AsyncMock(return_value=mock_heal_result)

        builder = E2EBuilder(engine, tmp_path)
        assert builder._self_healing_engine is None

        result = await builder._apply_self_healing("old code", run_result, request, adapter, task)

        assert result.healed is True
        assert result.healed_code == "new"
        mock_healing_cls.assert_called_once_with(
            llm_engine=engine,
            adapter=adapter,
            flaky_test_retries=3,
            max_healing_attempts=2,
        )

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.SelfHealingEngine")
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_reuses_existing_engine(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        mock_healing_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        engine = _make_llm_engine()
        adapter = _make_adapter()
        run_result = RunResult(failed=1, success=False)
        request = GenerationRequest(messages=[LLMMessage(role="user", content="generate")])
        task = E2ETask(route_path="/api/users")

        mock_heal_result = HealingResult(
            healed=False,
            original_code="code",
            messages=["no fix"],
        )
        mock_healing_cls.return_value.heal_test = AsyncMock(return_value=mock_heal_result)

        builder = E2EBuilder(engine, tmp_path)

        # Call twice — engine should only be created once
        await builder._apply_self_healing("code", run_result, request, adapter, task)
        await builder._apply_self_healing("code", run_result, request, adapter, task)

        assert mock_healing_cls.call_count == 1

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.SelfHealingEngine")
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_passes_test_file_path_to_heal_test(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        mock_healing_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        engine = _make_llm_engine()
        adapter = _make_adapter()
        run_result = RunResult(failed=1, success=False)
        request = GenerationRequest(messages=[LLMMessage(role="user", content="generate")])
        task = E2ETask(route_path="/api/users", output_file="tests/e2e/login.spec.ts")

        mock_heal_result = HealingResult(
            healed=False,
            original_code="code",
            messages=[],
        )
        mock_healing_cls.return_value.heal_test = AsyncMock(return_value=mock_heal_result)

        builder = E2EBuilder(engine, tmp_path)

        await builder._apply_self_healing("code", run_result, request, adapter, task)

        call_kwargs = mock_healing_cls.return_value.heal_test.call_args[1]
        assert call_kwargs["test_file"] == Path("tests/e2e/login.spec.ts")

    @pytest.mark.asyncio
    @patch("nit.agents.builders.e2e.SelfHealingEngine")
    @patch("nit.agents.builders.e2e.get_registry")
    @patch("nit.agents.builders.e2e.GlobalMemory")
    @patch("nit.agents.builders.e2e.ContextAssembler")
    async def test_no_output_file_passes_none(
        self,
        _a: MagicMock,
        _b: MagicMock,
        _c: MagicMock,
        mock_healing_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        engine = _make_llm_engine()
        adapter = _make_adapter()
        run_result = RunResult(failed=1, success=False)
        request = GenerationRequest(messages=[LLMMessage(role="user", content="generate")])
        task = E2ETask(route_path="/api/users")

        mock_heal_result = HealingResult(
            healed=False,
            original_code="code",
            messages=[],
        )
        mock_healing_cls.return_value.heal_test = AsyncMock(return_value=mock_heal_result)

        builder = E2EBuilder(engine, tmp_path)

        await builder._apply_self_healing("code", run_result, request, adapter, task)

        call_kwargs = mock_healing_cls.return_value.heal_test.call_args[1]
        assert call_kwargs["test_file"] is None
