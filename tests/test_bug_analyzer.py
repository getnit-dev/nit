"""Tests for the BugAnalyzer (agents/analyzers/bug.py).

Covers:
- BugAnalyzer initialization and properties
- Bug type detection from error messages (all pattern categories)
- Confidence calculation
- Location extraction from stack traces (Python, JS, C/C++)
- Code bug vs test bug classification
- Title and description generation
- LLM-based analysis (mock LLM engine)
- LLM response parsing
- Source code reading and language detection
- run() method success, error, and edge cases
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.agents.analyzers.bug import (
    SEVERITY_RULES,
    BugAnalysisTask,
    BugAnalyzer,
    BugLocation,
    BugReport,
    BugSeverity,
    BugType,
    LLMBugAnalysisResult,
)
from nit.agents.base import TaskInput, TaskStatus

# ── Helpers ───────────────────────────────────────────────────────


def _make_task(
    error_message: str = "TypeError: x is not a function",
    stack_trace: str = "",
    source_file: str = "src/app.py",
    target: str = "test_app.py",
) -> BugAnalysisTask:
    return BugAnalysisTask(
        task_type="analyze_bug",
        target=target,
        error_message=error_message,
        stack_trace=stack_trace,
        source_file=source_file,
    )


def _make_analyzer(
    llm_engine: object | None = None,
    *,
    enable_llm_analysis: bool = True,
    project_root: Path | None = None,
) -> BugAnalyzer:
    return BugAnalyzer(
        llm_engine=llm_engine,  # type: ignore[arg-type]
        enable_llm_analysis=enable_llm_analysis,
        project_root=project_root,
    )


# ── Properties ────────────────────────────────────────────────────


class TestBugAnalyzerProperties:
    def test_name(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer.name == "BugAnalyzer"

    def test_description(self) -> None:
        analyzer = _make_analyzer()
        assert "bug" in analyzer.description.lower()

    def test_defaults(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer.enable_llm_analysis is True
        assert analyzer.llm_confidence_threshold == 0.7
        assert analyzer.llm_engine is None


# ── Bug type detection ────────────────────────────────────────────


class TestDetectBugType:
    def test_null_dereference(self) -> None:
        analyzer = _make_analyzer()
        assert (
            analyzer._detect_bug_type("Cannot read property 'x' of null")
            == BugType.NULL_DEREFERENCE
        )

    def test_nonetype_python(self) -> None:
        analyzer = _make_analyzer()
        assert (
            analyzer._detect_bug_type("'NoneType' object has no attribute 'foo'")
            == BugType.NULL_DEREFERENCE
        )

    def test_undefined_variable(self) -> None:
        analyzer = _make_analyzer()
        assert (
            analyzer._detect_bug_type("ReferenceError: foo is not defined")
            == BugType.UNDEFINED_VARIABLE
        )

    def test_name_error(self) -> None:
        analyzer = _make_analyzer()
        assert (
            analyzer._detect_bug_type("NameError: name 'x' is not defined")
            == BugType.UNDEFINED_VARIABLE
        )

    def test_type_error(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer._detect_bug_type("TypeError: expected int") == BugType.TYPE_ERROR

    def test_is_not_a_function(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer._detect_bug_type("x.foo is not a function") == BugType.TYPE_ERROR

    def test_arithmetic_error_nan(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer._detect_bug_type("Result is NaN") == BugType.ARITHMETIC_ERROR

    def test_division_by_zero(self) -> None:
        analyzer = _make_analyzer()
        assert (
            analyzer._detect_bug_type("ZeroDivisionError: division by zero")
            == BugType.ARITHMETIC_ERROR
        )

    def test_index_error(self) -> None:
        analyzer = _make_analyzer()
        assert (
            analyzer._detect_bug_type("IndexError: list index out of range") == BugType.INDEX_ERROR
        )

    def test_assertion_error(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer._detect_bug_type("AssertionError: invariant") == BugType.ASSERTION_ERROR

    def test_uncaught_exception(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer._detect_bug_type("Uncaught ReferenceError") == BugType.UNCAUGHT_EXCEPTION

    def test_security_vulnerability(self) -> None:
        analyzer = _make_analyzer()
        assert (
            analyzer._detect_bug_type("Possible SQL injection detected")
            == BugType.SECURITY_VULNERABILITY
        )

    def test_unknown_bug_type(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer._detect_bug_type("something totally unrelated") == BugType.UNKNOWN


# ── Confidence calculation ────────────────────────────────────────


class TestCalculateConfidence:
    def test_known_pattern_high_confidence(self) -> None:
        analyzer = _make_analyzer()
        confidence = analyzer._calculate_confidence(BugType.NULL_DEREFERENCE, "")
        assert confidence == 0.9

    def test_unknown_bug_low_confidence(self) -> None:
        analyzer = _make_analyzer()
        confidence = analyzer._calculate_confidence(BugType.UNKNOWN, "")
        assert confidence == 0.5

    def test_other_bug_medium_confidence(self) -> None:
        analyzer = _make_analyzer()
        confidence = analyzer._calculate_confidence(BugType.UNCAUGHT_EXCEPTION, "")
        assert confidence == 0.7

    def test_long_stack_trace_increases_confidence(self) -> None:
        analyzer = _make_analyzer()
        long_trace = "a" * 100
        confidence = analyzer._calculate_confidence(BugType.NULL_DEREFERENCE, long_trace)
        assert confidence == 1.0

    def test_short_stack_trace_no_boost(self) -> None:
        analyzer = _make_analyzer()
        short_trace = "abc"
        confidence = analyzer._calculate_confidence(BugType.NULL_DEREFERENCE, short_trace)
        assert confidence == 0.9


# ── Code bug vs test bug ──────────────────────────────────────────


class TestIsCodeBug:
    def test_no_stack_trace_returns_false(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer._is_code_bug("err", "", "app.py") is False

    def test_source_file_in_trace_returns_true(self) -> None:
        analyzer = _make_analyzer()
        trace = "  at Object.calculate (src/app.py:10:5)\n  at test_app.py:20"
        assert analyzer._is_code_bug("err", trace, "src/app.py") is True

    def test_only_test_frames_returns_false(self) -> None:
        analyzer = _make_analyzer()
        trace = "  test_something.py:10\n  test_other.py:20"
        assert analyzer._is_code_bug("err", trace, "app.py") is False

    def test_node_modules_frame_skipped(self) -> None:
        analyzer = _make_analyzer()
        trace = "  node_modules/some-lib/index.js:10\n  src/app.py:20"
        assert analyzer._is_code_bug("err", trace, "src/app.py") is True

    def test_empty_lines_skipped(self) -> None:
        analyzer = _make_analyzer()
        trace = "\n\n  src/app.py:10\n"
        assert analyzer._is_code_bug("err", trace, "src/app.py") is True


# ── Location extraction ──────────────────────────────────────────


class TestExtractLocation:
    def test_empty_stack_trace(self) -> None:
        analyzer = _make_analyzer()
        loc = analyzer._extract_location("", "src/app.py")
        assert loc.file_path == "src/app.py"
        assert loc.line_number is None

    def test_javascript_stack_trace(self) -> None:
        analyzer = _make_analyzer()
        trace = "    at calculate (src/app.js:42:10)"
        loc = analyzer._extract_location(trace, "src/app.js")
        assert loc.function_name == "calculate"
        assert loc.line_number == 42
        assert loc.column_number == 10

    def test_python_stack_trace(self) -> None:
        analyzer = _make_analyzer()
        trace = '  File "src/app.py", line 33, in compute'
        loc = analyzer._extract_location(trace, "src/app.py")
        assert loc.function_name == "compute"
        assert loc.line_number == 33

    def test_cpp_stack_trace(self) -> None:
        analyzer = _make_analyzer()
        trace = "src/app.cpp:55:12: error"
        loc = analyzer._extract_location(trace, "src/app.cpp")
        assert loc.line_number == 55
        assert loc.column_number == 12

    def test_no_matching_source_file(self) -> None:
        analyzer = _make_analyzer()
        trace = "    at helper (lib/other.js:10:5)"
        loc = analyzer._extract_location(trace, "src/app.js")
        assert loc.file_path == "src/app.js"
        assert loc.line_number is None


# ── Title and description generation ──────────────────────────────


class TestGenerateTitleAndDescription:
    def test_title_with_function_name(self) -> None:
        analyzer = _make_analyzer()
        loc = BugLocation(file_path="src/app.py", function_name="compute")
        title = analyzer._generate_title(BugType.TYPE_ERROR, loc)
        assert "compute" in title
        assert "Type Error" in title

    def test_title_with_line_number(self) -> None:
        analyzer = _make_analyzer()
        loc = BugLocation(file_path="src/app.py", line_number=42)
        title = analyzer._generate_title(BugType.NULL_DEREFERENCE, loc)
        assert "app.py:42" in title

    def test_title_with_file_only(self) -> None:
        analyzer = _make_analyzer()
        loc = BugLocation(file_path="src/app.py")
        title = analyzer._generate_title(BugType.INDEX_ERROR, loc)
        assert "app.py" in title

    def test_description_for_known_type(self) -> None:
        analyzer = _make_analyzer()
        desc = analyzer._generate_description("TypeError: x is not a function", BugType.TYPE_ERROR)
        assert "incompatible types" in desc.lower()
        assert "TypeError: x is not a function" in desc

    def test_description_for_unknown_type(self) -> None:
        analyzer = _make_analyzer()
        desc = analyzer._generate_description("weird error", BugType.UNKNOWN)
        assert "error" in desc.lower()


# ── LLM analysis gating ──────────────────────────────────────────


class TestShouldUseLLM:
    def test_disabled_llm_returns_false(self) -> None:
        analyzer = _make_analyzer(enable_llm_analysis=False)
        assert analyzer._should_use_llm(BugType.UNKNOWN, 0.3) is False

    def test_no_engine_returns_false(self) -> None:
        analyzer = _make_analyzer(llm_engine=None, enable_llm_analysis=True)
        assert analyzer._should_use_llm(BugType.UNKNOWN, 0.3) is False

    def test_unknown_bug_type_returns_true(self) -> None:
        engine = MagicMock()
        analyzer = _make_analyzer(llm_engine=engine, enable_llm_analysis=True)
        assert analyzer._should_use_llm(BugType.UNKNOWN, 0.5) is True

    def test_low_confidence_returns_true(self) -> None:
        engine = MagicMock()
        analyzer = _make_analyzer(llm_engine=engine, enable_llm_analysis=True)
        assert analyzer._should_use_llm(BugType.TYPE_ERROR, 0.4) is True

    def test_high_confidence_known_type_returns_false(self) -> None:
        engine = MagicMock()
        analyzer = _make_analyzer(llm_engine=engine, enable_llm_analysis=True)
        assert analyzer._should_use_llm(BugType.TYPE_ERROR, 0.9) is False


# ── Language detection ────────────────────────────────────────────


class TestDetectLanguage:
    def test_python(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer._detect_language("src/app.py") == "python"

    def test_javascript(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer._detect_language("src/app.js") == "javascript"

    def test_typescript(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer._detect_language("src/app.tsx") == "typescript"

    def test_unknown_extension(self) -> None:
        analyzer = _make_analyzer()
        assert analyzer._detect_language("src/app.xyz") == "unknown"


# ── Source code reading ───────────────────────────────────────────


class TestReadSourceCode:
    def test_read_existing_file(self, tmp_path: Path) -> None:
        source = tmp_path / "app.py"
        source.write_text("def hello(): pass")
        analyzer = _make_analyzer(project_root=tmp_path)
        result = analyzer._read_source_code("app.py")
        assert result == "def hello(): pass"

    def test_read_nonexistent_file(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(project_root=tmp_path)
        result = analyzer._read_source_code("nope.py")
        assert result == ""

    def test_read_file_exception(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(project_root=tmp_path)
        with patch.object(Path, "exists", side_effect=PermissionError("nope")):
            result = analyzer._read_source_code("app.py")
        assert result == ""


# ── LLM response parsing ─────────────────────────────────────────


class TestParseBugAnalysisResponse:
    def test_parse_valid_response(self) -> None:
        analyzer = _make_analyzer()
        response = (
            "**Bug Type**: type_error\n"
            "**Is Code Bug**: true\n"
            "**Location**: in calculate function\n"
            "**Root Cause**: Missing type check before arithmetic operation\n"
        )
        result = analyzer._parse_bug_analysis_response(response)
        assert result is not None
        assert result.bug_type == BugType.TYPE_ERROR
        assert result.confidence == 0.8
        assert "Missing type check" in result.root_cause

    def test_parse_not_code_bug(self) -> None:
        analyzer = _make_analyzer()
        response = "**Bug Type**: type_error\n**Is Code Bug**: false\n"
        result = analyzer._parse_bug_analysis_response(response)
        assert result is None

    def test_parse_unknown_bug_type_maps_to_known(self) -> None:
        analyzer = _make_analyzer()
        response = "**Bug Type**: null_issue\n**Is Code Bug**: true\n**Location**: line 42\n"
        result = analyzer._parse_bug_analysis_response(response)
        assert result is not None
        assert result.bug_type == BugType.NULL_DEREFERENCE

    def test_parse_completely_unknown_type(self) -> None:
        analyzer = _make_analyzer()
        response = "**Bug Type**: something_weird\n**Is Code Bug**: true\n**Location**: somewhere\n"
        result = analyzer._parse_bug_analysis_response(response)
        assert result is not None
        assert result.bug_type == BugType.UNKNOWN

    def test_parse_empty_response(self) -> None:
        analyzer = _make_analyzer()
        result = analyzer._parse_bug_analysis_response("")
        # Empty response has no bug_type/is_code_bug matches, so it falls through
        # to producing a default UNKNOWN result
        assert result is not None
        assert result.bug_type == BugType.UNKNOWN

    def test_parse_no_bug_type_match(self) -> None:
        analyzer = _make_analyzer()
        response = "Nothing useful here"
        result = analyzer._parse_bug_analysis_response(response)
        # Without structured markers, the parser produces a default UNKNOWN result
        assert result is not None
        assert result.bug_type == BugType.UNKNOWN
        assert result.title.startswith("unknown:")


# ── run() method ──────────────────────────────────────────────────


class TestBugAnalyzerRun:
    @pytest.mark.asyncio
    async def test_wrong_task_type(self) -> None:
        analyzer = _make_analyzer()
        task = TaskInput(task_type="other", target="x")
        result = await analyzer.run(task)
        assert result.status == TaskStatus.FAILED
        assert result.errors

    @pytest.mark.asyncio
    async def test_test_bug_detected(self) -> None:
        """When no source file found in trace, it's a test bug."""
        analyzer = _make_analyzer()
        task = _make_task(
            error_message="AssertionError",
            stack_trace="  test_something.py:10\n  test_runner.py:50",
            source_file="app.py",
        )
        result = await analyzer.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert result.result["is_code_bug"] is False

    @pytest.mark.asyncio
    async def test_code_bug_pattern_based(self) -> None:
        """Detect a known pattern without LLM."""
        analyzer = _make_analyzer(enable_llm_analysis=False)
        task = _make_task(
            error_message="TypeError: x is not a function",
            stack_trace="  at compute (src/app.py:10:5)",
            source_file="src/app.py",
        )
        result = await analyzer.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert result.result["is_code_bug"] is True
        bug_report: BugReport = result.result["bug_report"]
        assert bug_report.bug_type == BugType.TYPE_ERROR
        assert bug_report.metadata["analysis_method"] == "pattern"

    @pytest.mark.asyncio
    async def test_code_bug_with_llm_analysis(self, tmp_path: Path) -> None:
        """When bug is UNKNOWN, use LLM and accept result."""
        source_file = tmp_path / "app.py"
        source_file.write_text("def compute(x): return x + 1")

        engine = AsyncMock()
        engine.generate.return_value = MagicMock(
            text=(
                "**Bug Type**: type_error\n"
                "**Is Code Bug**: true\n"
                "**Location**: compute function\n"
                "**Root Cause**: Missing type validation\n"
            )
        )
        analyzer = _make_analyzer(
            llm_engine=engine,
            enable_llm_analysis=True,
            project_root=tmp_path,
        )
        task = _make_task(
            error_message="Something weird happened",
            stack_trace="  at compute (app.py:1:5)",
            source_file="app.py",
        )
        result = await analyzer.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert result.result["is_code_bug"] is True
        bug_report: BugReport = result.result["bug_report"]
        assert bug_report.metadata["analysis_method"] == "llm"

    @pytest.mark.asyncio
    async def test_code_bug_llm_not_code_bug_falls_back(self, tmp_path: Path) -> None:
        """When LLM says it's not a code bug (returns None), fall back to pattern."""
        source_file = tmp_path / "app.py"
        source_file.write_text("def compute(x): return x + 1")

        engine = AsyncMock()
        engine.generate.return_value = MagicMock(
            text="**Bug Type**: type_error\n**Is Code Bug**: false\n"
        )
        analyzer = _make_analyzer(
            llm_engine=engine,
            enable_llm_analysis=True,
            project_root=tmp_path,
        )
        task = _make_task(
            error_message="Something weird happened",
            stack_trace="  at compute (app.py:1:5)",
            source_file="app.py",
        )
        result = await analyzer.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert result.result["is_code_bug"] is True
        bug_report: BugReport = result.result["bug_report"]
        assert bug_report.metadata["analysis_method"] == "pattern"

    @pytest.mark.asyncio
    async def test_run_catches_unexpected_exception(self) -> None:
        analyzer = _make_analyzer()
        task = _make_task()
        with patch.object(analyzer, "_is_code_bug", side_effect=RuntimeError("boom")):
            result = await analyzer.run(task)
        assert result.status == TaskStatus.FAILED
        assert any("boom" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_empty_stack_trace_is_test_bug(self) -> None:
        analyzer = _make_analyzer()
        task = _make_task(stack_trace="", source_file="app.py")
        result = await analyzer.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert result.result["is_code_bug"] is False


# ── LLM analysis internal ────────────────────────────────────────


class TestAnalyzeWithLLM:
    @pytest.mark.asyncio
    async def test_no_engine_returns_none(self) -> None:
        analyzer = _make_analyzer(llm_engine=None)
        task = _make_task()
        result = await analyzer._analyze_with_llm(task)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_source_file_returns_none(self, tmp_path: Path) -> None:
        engine = AsyncMock()
        analyzer = _make_analyzer(llm_engine=engine, project_root=tmp_path)
        task = _make_task(source_file="nonexistent.py")
        result = await analyzer._analyze_with_llm(task)
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self, tmp_path: Path) -> None:
        source = tmp_path / "app.py"
        source.write_text("x = 1")
        engine = AsyncMock()
        engine.generate.side_effect = RuntimeError("LLM failed")
        analyzer = _make_analyzer(llm_engine=engine, project_root=tmp_path)
        task = _make_task(source_file="app.py")
        result = await analyzer._analyze_with_llm(task)
        assert result is None


# ── Dataclass smoke tests ─────────────────────────────────────────


class TestDataclasses:
    def test_bug_report_defaults(self) -> None:
        loc = BugLocation(file_path="x.py")
        report = BugReport(
            bug_type=BugType.UNKNOWN,
            severity=BugSeverity.LOW,
            title="test",
            description="desc",
            location=loc,
            error_message="err",
        )
        assert report.is_code_bug is True
        assert report.confidence == 1.0
        assert report.reproduction_steps == []
        assert report.metadata == {}

    def test_llm_bug_analysis_result_defaults(self) -> None:
        result = LLMBugAnalysisResult()
        assert result.bug_type == BugType.UNKNOWN
        assert result.severity == BugSeverity.MEDIUM
        assert result.confidence == 0.7

    def test_severity_rules_all_types_covered(self) -> None:
        for bt in BugType:
            assert bt in SEVERITY_RULES
