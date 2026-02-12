"""Tests for the RootCauseAnalyzer agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nit.agents.analyzers.bug import BugLocation, BugReport, BugSeverity, BugType
from nit.agents.base import TaskInput, TaskStatus
from nit.agents.debuggers.root_cause import (
    DataFlowPath,
    RootCause,
    RootCauseAnalysisTask,
    RootCauseAnalyzer,
)
from nit.llm.engine import LLMResponse
from nit.parsing.treesitter import ClassInfo, FunctionInfo, ParameterInfo, ParseResult

# ── Helpers ──────────────────────────────────────────────────────


def _make_bug_report(
    *,
    bug_type: BugType = BugType.NULL_DEREFERENCE,
    severity: BugSeverity = BugSeverity.HIGH,
    error_message: str = "Cannot read property 'x' of null",
    file_path: str = "src/app.py",
    line_number: int | None = 10,
    function_name: str | None = "process_data",
) -> BugReport:
    return BugReport(
        bug_type=bug_type,
        severity=severity,
        title=f"{bug_type.value} in {function_name or file_path}",
        description="Test bug description",
        location=BugLocation(
            file_path=file_path,
            line_number=line_number,
            function_name=function_name,
        ),
        error_message=error_message,
    )


def _make_parse_result(
    *,
    functions: list[FunctionInfo] | None = None,
    classes: list[ClassInfo] | None = None,
) -> ParseResult:
    return ParseResult(
        language="python",
        functions=functions or [],
        classes=classes or [],
    )


def _make_function_info(
    *,
    name: str = "process_data",
    start_line: int = 5,
    end_line: int = 20,
    body_text: str = "result = data.get('key')\nreturn result",
    parameters: list[ParameterInfo] | None = None,
) -> FunctionInfo:
    return FunctionInfo(
        name=name,
        start_line=start_line,
        end_line=end_line,
        body_text=body_text,
        parameters=parameters or [ParameterInfo(name="data")],
    )


def _make_llm_engine(response_text: str = "Category: logic_error\nDescription: Test") -> AsyncMock:
    engine = AsyncMock()
    engine.generate.return_value = LLMResponse(
        text=response_text,
        model="test-model",
    )
    return engine


# ── Agent basics ─────────────────────────────────────────────────


class TestRootCauseAnalyzerProperties:
    def test_name(self, tmp_path: Path) -> None:
        engine = _make_llm_engine()
        agent = RootCauseAnalyzer(llm_engine=engine, project_root=tmp_path)
        assert agent.name == "RootCauseAnalyzer"

    def test_description(self, tmp_path: Path) -> None:
        engine = _make_llm_engine()
        agent = RootCauseAnalyzer(llm_engine=engine, project_root=tmp_path)
        assert "root cause" in agent.description.lower()


# ── run() validation ─────────────────────────────────────────────


class TestRootCauseAnalyzerRunValidation:
    @pytest.mark.asyncio
    async def test_rejects_wrong_task_type(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        wrong_task = TaskInput(task_type="wrong", target="test")
        result = await agent.run(wrong_task)
        assert result.status == TaskStatus.FAILED
        assert "RootCauseAnalysisTask" in result.errors[0]

    @pytest.mark.asyncio
    async def test_rejects_missing_bug_report(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        task = RootCauseAnalysisTask(target="test.py", bug_report=None)
        result = await agent.run(task)
        assert result.status == TaskStatus.FAILED
        assert "Bug report is required" in result.errors[0]


# ── run() success path ───────────────────────────────────────────


class TestRootCauseAnalyzerRunSuccess:
    @pytest.mark.asyncio
    async def test_successful_analysis(self, tmp_path: Path) -> None:
        llm_text = (
            "Category: missing_validation\n"
            "Description: Missing null check before access\n"
            "Affected Code: result = data.get('key')\n"
            "Incorrect Assumptions: data is always non-null\n"
            "Contributing Factors: no input validation"
        )
        engine = _make_llm_engine(llm_text)
        agent = RootCauseAnalyzer(llm_engine=engine, project_root=tmp_path)

        func = _make_function_info()
        parse_result = _make_parse_result(functions=[func])

        bug = _make_bug_report()
        src = "def process_data(data):\n    result = data.get('key')\n    return result\n"
        task = RootCauseAnalysisTask(
            target="src/app.py",
            bug_report=bug,
            source_code=src,
        )

        with patch(
            "nit.agents.debuggers.root_cause.extract_from_file",
            return_value=parse_result,
        ):
            result = await agent.run(task)

        assert result.status == TaskStatus.COMPLETED
        root_cause = result.result["root_cause"]
        assert isinstance(root_cause, RootCause)
        assert root_cause.category == "missing_validation"
        assert root_cause.confidence == 0.8

    @pytest.mark.asyncio
    async def test_run_catches_exception(self, tmp_path: Path) -> None:
        engine = _make_llm_engine()
        agent = RootCauseAnalyzer(llm_engine=engine, project_root=tmp_path)
        bug = _make_bug_report()
        task = RootCauseAnalysisTask(
            target="src/app.py",
            bug_report=bug,
            source_code="x = 1",
        )
        with patch(
            "nit.agents.debuggers.root_cause.extract_from_file",
            side_effect=RuntimeError("parse boom"),
        ):
            result = await agent.run(task)
        assert result.status == TaskStatus.FAILED
        assert "Root cause analysis error" in result.errors[0]


# ── _parse_source_code ───────────────────────────────────────────


class TestParseSourceCode:
    @pytest.mark.asyncio
    async def test_writes_temp_file_when_source_provided(self, tmp_path: Path) -> None:
        engine = _make_llm_engine()
        agent = RootCauseAnalyzer(llm_engine=engine, project_root=tmp_path)
        parse_result = _make_parse_result()

        with patch(
            "nit.agents.debuggers.root_cause.extract_from_file",
            return_value=parse_result,
        ) as mock_extract:
            await agent._parse_source_code("nonexistent.py", "x = 1\n")
            # Should have written a temp file and called extract_from_file
            assert mock_extract.called
            call_path = mock_extract.call_args[0][0]
            assert ".nit" in call_path

    @pytest.mark.asyncio
    async def test_uses_file_path_when_exists(self, tmp_path: Path) -> None:
        src = tmp_path / "real.py"
        src.write_text("x = 1\n", encoding="utf-8")
        engine = _make_llm_engine()
        agent = RootCauseAnalyzer(llm_engine=engine, project_root=tmp_path)
        parse_result = _make_parse_result()

        with patch(
            "nit.agents.debuggers.root_cause.extract_from_file",
            return_value=parse_result,
        ) as mock_extract:
            await agent._parse_source_code(str(src), "x = 1\n")
            mock_extract.assert_called_once_with(str(src))


# ── _find_function_at_location ───────────────────────────────────


class TestFindFunctionAtLocation:
    def test_finds_function_at_line(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        func = _make_function_info(start_line=5, end_line=20)
        pr = _make_parse_result(functions=[func])
        assert agent._find_function_at_location(pr, 10) == func

    def test_returns_none_when_no_match(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        func = _make_function_info(start_line=5, end_line=10)
        pr = _make_parse_result(functions=[func])
        assert agent._find_function_at_location(pr, 50) is None

    def test_returns_first_function_when_no_line_number(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        func = _make_function_info()
        pr = _make_parse_result(functions=[func])
        assert agent._find_function_at_location(pr, None) == func

    def test_returns_none_when_no_functions_and_no_line(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        pr = _make_parse_result()
        assert agent._find_function_at_location(pr, None) is None

    def test_finds_class_method(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        method = _make_function_info(name="do_stuff", start_line=10, end_line=25)
        cls = ClassInfo(name="MyClass", start_line=5, end_line=30, methods=[method])
        pr = _make_parse_result(classes=[cls])
        assert agent._find_function_at_location(pr, 15) == method


# ── _extract_variables_from_function ─────────────────────────────


class TestExtractVariables:
    def test_extracts_assignments_and_params(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        func = _make_function_info(
            body_text="total = a + b\nresult = total * 2",
            parameters=[ParameterInfo(name="a"), ParameterInfo(name="b")],
        )
        variables = agent._extract_variables_from_function(func)
        assert "total" in variables
        assert "result" in variables
        assert "a" in variables
        assert "b" in variables


# ── _find_assignments / _find_conditions / _find_usages ──────────


class TestDataFlowHelpers:
    def test_find_assignments(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        code = "x = 10; y = 20; x = x + 1"
        assignments = agent._find_assignments(code, "x")
        assert len(assignments) == 2
        assert any("10" in a for a in assignments)
        assert any("x + 1" in a for a in assignments)

    def test_find_conditions(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        code = "if (x > 0)\nwhile (x < 10)"
        conditions = agent._find_conditions(code, "x")
        assert len(conditions) == 2

    def test_find_usages(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        code = "x = 10\nprint(x)\nreturn x"
        usages = agent._find_usages(code, "x")
        # Should skip the assignment line
        assert len(usages) == 2
        assert any("print(x)" in u for u in usages)

    def test_find_usages_respects_max(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        code = "\n".join(f"foo(x, {i})" for i in range(20))
        usages = agent._find_usages(code, "x")
        assert len(usages) <= 5


# ── _analyze_data_flow ───────────────────────────────────────────


class TestAnalyzeDataFlow:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_function(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        pr = _make_parse_result()
        bug = _make_bug_report(line_number=999)
        result = await agent._analyze_data_flow(pr, bug, "")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_flows_for_variables(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        func = _make_function_info(
            body_text="val = data.get('k')\nif (val > 0)\nprint(val)",
            parameters=[ParameterInfo(name="data")],
        )
        pr = _make_parse_result(functions=[func])
        bug = _make_bug_report(line_number=10)
        flows = await agent._analyze_data_flow(pr, bug, "")
        assert len(flows) > 0
        var_names = [f.variable_name for f in flows]
        assert "val" in var_names


# ── _identify_missing_checks ────────────────────────────────────


class TestIdentifyMissingChecks:
    def test_null_dereference_missing_check(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        pr = _make_parse_result()
        bug = _make_bug_report(bug_type=BugType.NULL_DEREFERENCE)
        flow = DataFlowPath(
            variable_name="data",
            usages=["print(data.x)"],
            conditions=[],
        )
        missing = agent._identify_missing_checks(pr, bug, [flow])
        assert len(missing) == 1
        assert "null" in missing[0].lower() or "undefined" in missing[0].lower()

    def test_null_dereference_with_check_present(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        pr = _make_parse_result()
        bug = _make_bug_report(bug_type=BugType.NULL_DEREFERENCE)
        flow = DataFlowPath(
            variable_name="data",
            usages=["print(data.x)"],
            conditions=["if (data != null)"],
        )
        missing = agent._identify_missing_checks(pr, bug, [flow])
        assert missing == []

    def test_type_error_missing_check(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        pr = _make_parse_result()
        bug = _make_bug_report(bug_type=BugType.TYPE_ERROR)
        flow = DataFlowPath(
            variable_name="val",
            usages=["val.strip()"],
            conditions=[],
        )
        missing = agent._identify_missing_checks(pr, bug, [flow])
        assert len(missing) == 1
        assert "type check" in missing[0].lower()

    def test_arithmetic_error_missing_zero_check(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        pr = _make_parse_result()
        bug = _make_bug_report(bug_type=BugType.ARITHMETIC_ERROR)
        flow = DataFlowPath(
            variable_name="divisor",
            usages=["result = total / divisor"],
            conditions=[],
        )
        missing = agent._identify_missing_checks(pr, bug, [flow])
        assert len(missing) == 1
        assert "zero" in missing[0].lower()

    def test_index_error_missing_bounds_check(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        pr = _make_parse_result()
        bug = _make_bug_report(bug_type=BugType.INDEX_ERROR)
        flow = DataFlowPath(
            variable_name="idx",
            usages=["items[idx]"],
            conditions=[],
        )
        missing = agent._identify_missing_checks(pr, bug, [flow])
        assert len(missing) == 1
        assert "bounds" in missing[0].lower()


# ── _parse_llm_response ─────────────────────────────────────────


class TestParseLLMResponse:
    def test_parses_full_response(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        text = (
            "Category: missing_validation\n"
            "Description: The variable is not validated before use\n"
            "Affected Code: x = data.value\n"
            "Incorrect Assumptions: data is always valid\n"
            "Contributing Factors: no input checking"
        )
        bug = _make_bug_report()
        flows = [DataFlowPath(variable_name="x")]
        missing = ["Missing null check"]
        root_cause = agent._parse_llm_response(text, bug, flows, missing)
        assert root_cause.category == "missing_validation"
        assert "not validated" in root_cause.description
        assert "x = data.value" in root_cause.affected_code
        assert root_cause.data_flow == flows
        assert root_cause.missing_checks == missing
        assert root_cause.confidence == 0.8

    def test_defaults_when_no_match(self, tmp_path: Path) -> None:
        agent = RootCauseAnalyzer(llm_engine=_make_llm_engine(), project_root=tmp_path)
        text = "some unstructured response text"
        bug = _make_bug_report()
        root_cause = agent._parse_llm_response(text, bug, [], [])
        assert root_cause.category == "logic_error"  # default
        assert root_cause.description  # should fall back to text slice


# ── DataFlowPath dataclass ──────────────────────────────────────


class TestDataFlowPath:
    def test_defaults(self) -> None:
        flow = DataFlowPath(variable_name="x")
        assert flow.variable_name == "x"
        assert flow.assignments == []
        assert flow.conditions == []
        assert flow.usages == []


# ── RootCause dataclass ─────────────────────────────────────────


class TestRootCauseDataclass:
    def test_defaults(self) -> None:
        rc = RootCause(
            category="logic_error",
            description="test",
            affected_code="x = 1",
        )
        assert rc.confidence == 0.7
        assert rc.data_flow == []
        assert rc.missing_checks == []
        assert rc.incorrect_assumptions == []
        assert rc.contributing_factors == []
