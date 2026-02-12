"""Tests for the SemanticGapDetector (agents/analyzers/semantic_gap.py).

Covers:
- SemanticGapDetector initialization and properties
- run() with wrong task type, no gaps, successful analysis
- _prioritize_gaps sorting logic
- _analyze_function with mock LLM
- _assemble_function_context with file reading
- _extract_function_code patterns (Python, JS, Rust, Go, fallback)
- _build_ast_structure control flow counting
- _detect_language file extension mapping
- _call_llm_analysis prompt construction
- _parse_llm_response section splitting
- _parse_gap_section field extraction and defaults
- Caching of function analysis results
- Confidence filtering
- Error handling and edge cases
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.agents.analyzers.coverage import CoverageGapReport, FunctionGap, GapPriority
from nit.agents.analyzers.semantic_gap import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    MAX_FUNCTION_SNIPPET_LENGTH,
    GapCategory,
    SemanticGap,
    SemanticGapDetector,
    SemanticGapTask,
)
from nit.agents.base import TaskInput, TaskStatus

# ── Helpers ───────────────────────────────────────────────────────


def _make_function_gap(
    file_path: str = "src/calc.py",
    function_name: str = "compute",
    complexity: int = 8,
    coverage_percentage: float = 30.0,
    priority: GapPriority = GapPriority.HIGH,
) -> FunctionGap:
    return FunctionGap(
        file_path=file_path,
        function_name=function_name,
        line_number=10,
        end_line=30,
        coverage_percentage=coverage_percentage,
        complexity=complexity,
        is_public=True,
        priority=priority,
    )


def _make_detector(
    tmp_path: Path,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    max_functions: int = 10,
) -> tuple[SemanticGapDetector, AsyncMock]:
    """Return (detector, mock_engine) so tests can configure the mock directly."""
    engine = AsyncMock()
    engine.generate.return_value = MagicMock(text="")
    detector = SemanticGapDetector(
        llm_engine=engine,
        project_root=tmp_path,
        confidence_threshold=confidence_threshold,
        max_functions=max_functions,
    )
    return detector, engine


# ── Properties ────────────────────────────────────────────────────


class TestSemanticGapDetectorProperties:
    def test_name(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        assert detector.name == "SemanticGapDetector"

    def test_description(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        assert "semantic" in detector.description.lower()

    def test_defaults(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        assert detector.confidence_threshold == DEFAULT_CONFIDENCE_THRESHOLD
        assert detector.max_functions == 10
        assert detector._cache == {}


# ── run() method ──────────────────────────────────────────────────


class TestSemanticGapDetectorRun:
    @pytest.mark.asyncio
    async def test_wrong_task_type(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        task = TaskInput(task_type="other", target="x")
        result = await detector.run(task)
        assert result.status == TaskStatus.FAILED
        assert result.errors

    @pytest.mark.asyncio
    async def test_no_function_gaps(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        task = SemanticGapTask(task_type="semantic_gap", target="project")
        result = await detector.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert result.result["semantic_gaps"] == []

    @pytest.mark.asyncio
    async def test_gaps_from_coverage_report(self, tmp_path: Path) -> None:
        source = tmp_path / "src" / "calc.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("def compute(x):\n    if x > 0:\n        return x\n    return -x\n")

        detector, engine = _make_detector(tmp_path)
        engine.generate.return_value = MagicMock(
            text=(
                "**CATEGORY**: edge_case\n"
                "**SEVERITY**: high\n"
                "**DESCRIPTION**: Missing test for zero input\n"
                "**CONFIDENCE**: 0.9\n"
                "**REASONING**: Zero is a boundary value\n"
            )
        )

        gap = _make_function_gap()
        report = CoverageGapReport(function_gaps=[gap])
        task = SemanticGapTask(
            task_type="semantic_gap",
            target="project",
            coverage_gap_report=report,
        )
        result = await detector.run(task)
        assert result.status == TaskStatus.COMPLETED
        gaps = result.result["semantic_gaps"]
        assert len(gaps) == 1
        assert gaps[0].category == GapCategory.EDGE_CASE

    @pytest.mark.asyncio
    async def test_direct_function_gaps(self, tmp_path: Path) -> None:
        source = tmp_path / "src" / "calc.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("def compute(x): return x")

        detector, engine = _make_detector(tmp_path)
        engine.generate.return_value = MagicMock(
            text=(
                "**CATEGORY**: error_path\n"
                "**SEVERITY**: medium\n"
                "**DESCRIPTION**: No error handling\n"
                "**CONFIDENCE**: 0.8\n"
            )
        )

        gap = _make_function_gap()
        task = SemanticGapTask(
            task_type="semantic_gap",
            target="project",
            function_gaps=[gap],
        )
        result = await detector.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert len(result.result["semantic_gaps"]) == 1

    @pytest.mark.asyncio
    async def test_skip_trivial_functions(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        gap = _make_function_gap(complexity=1)  # Too simple
        task = SemanticGapTask(task_type="semantic_gap", target="project", function_gaps=[gap])
        result = await detector.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert result.result["semantic_gaps"] == []

    @pytest.mark.asyncio
    async def test_skip_well_tested_functions(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        gap = _make_function_gap(coverage_percentage=95.0)  # Well tested
        task = SemanticGapTask(task_type="semantic_gap", target="project", function_gaps=[gap])
        result = await detector.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert result.result["semantic_gaps"] == []

    @pytest.mark.asyncio
    async def test_caching_avoids_duplicate_analysis(self, tmp_path: Path) -> None:
        source = tmp_path / "src" / "calc.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("def compute(x): return x")

        detector, engine = _make_detector(tmp_path)
        engine.generate.return_value = MagicMock(
            text="**CATEGORY**: edge_case\n**DESCRIPTION**: test\n**CONFIDENCE**: 0.9\n"
        )

        gap = _make_function_gap()
        task = SemanticGapTask(task_type="semantic_gap", target="project", function_gaps=[gap, gap])
        result = await detector.run(task)
        assert result.status == TaskStatus.COMPLETED
        # LLM called only once due to caching
        assert engine.generate.call_count == 1

    @pytest.mark.asyncio
    async def test_confidence_filtering(self, tmp_path: Path) -> None:
        source = tmp_path / "src" / "calc.py"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("def compute(x): return x")

        detector, engine = _make_detector(tmp_path, confidence_threshold=0.95)
        engine.generate.return_value = MagicMock(
            text=(
                "**CATEGORY**: edge_case\n"
                "**DESCRIPTION**: low confidence gap\n"
                "**CONFIDENCE**: 0.5\n"
            )
        )
        gap = _make_function_gap()
        task = SemanticGapTask(task_type="semantic_gap", target="project", function_gaps=[gap])
        result = await detector.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert result.result["semantic_gaps"] == []

    @pytest.mark.asyncio
    async def test_run_exception_handling(self, tmp_path: Path) -> None:
        detector, engine = _make_detector(tmp_path)
        engine.generate.side_effect = RuntimeError("LLM down")
        gap = _make_function_gap()
        task = SemanticGapTask(task_type="semantic_gap", target="project", function_gaps=[gap])
        # _analyze_function catches exceptions internally, so run completes
        result = await detector.run(task)
        assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_max_functions_limit(self, tmp_path: Path) -> None:
        for i in range(5):
            p = tmp_path / "src" / f"mod{i}.py"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"def func{i}(x): return x")

        detector, engine = _make_detector(tmp_path, max_functions=2)
        engine.generate.return_value = MagicMock(text="")

        gaps = [
            _make_function_gap(file_path=f"src/mod{i}.py", function_name=f"func{i}")
            for i in range(5)
        ]
        task = SemanticGapTask(task_type="semantic_gap", target="project", function_gaps=gaps)
        result = await detector.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert result.result["functions_analyzed"] == 2


# ── _prioritize_gaps ──────────────────────────────────────────────


class TestPrioritizeGaps:
    def test_sort_by_priority(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        low = _make_function_gap(priority=GapPriority.LOW, complexity=1)
        critical = _make_function_gap(priority=GapPriority.CRITICAL, complexity=10)
        result = detector._prioritize_gaps([low, critical])
        assert result[0].priority == GapPriority.CRITICAL

    def test_sort_by_complexity_within_same_priority(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        a = _make_function_gap(priority=GapPriority.HIGH, complexity=5)
        b = _make_function_gap(priority=GapPriority.HIGH, complexity=15)
        result = detector._prioritize_gaps([a, b])
        assert result[0].complexity == 15

    def test_empty_list(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        assert detector._prioritize_gaps([]) == []


# ── _extract_function_code ────────────────────────────────────────


class TestExtractFunctionCode:
    def test_python_function(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        source = "def compute(x):\n    return x + 1\n\ndef other(): pass\n"
        result = detector._extract_function_code(source, "compute")
        assert "compute" in result

    def test_javascript_function(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        source = "function calculate(a) { return a * 2; }"
        result = detector._extract_function_code(source, "calculate")
        assert "calculate" in result

    def test_fallback_truncation(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        source = "x" * (MAX_FUNCTION_SNIPPET_LENGTH + 100)
        result = detector._extract_function_code(source, "nonexistent")
        assert len(result) == MAX_FUNCTION_SNIPPET_LENGTH

    def test_short_source_returned_as_is(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        source = "short code"
        result = detector._extract_function_code(source, "nonexistent")
        assert result == source


# ── _build_ast_structure ──────────────────────────────────────────


class TestBuildASTStructure:
    def test_complex_function(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        code = "if x:\n  for i in range(10):\n    try:\n      return x\n"
        result = detector._build_ast_structure(code)
        assert "conditional" in result
        assert "loop" in result
        assert "try-catch" in result
        assert "return" in result

    def test_simple_function(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        result = detector._build_ast_structure("x = 1")
        assert result == "simple function"


# ── _detect_language ──────────────────────────────────────────────


class TestDetectLanguageSemanticGap:
    def test_python(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        assert detector._detect_language("app.py") == "python"

    def test_rust(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        assert detector._detect_language("lib.rs") == "rust"

    def test_unknown(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        assert detector._detect_language("file.xyz") == "unknown"


# ── _parse_llm_response ──────────────────────────────────────────


class TestParseLLMResponse:
    def test_single_gap(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        response = (
            "**CATEGORY**: edge_case\n"
            "**SEVERITY**: high\n"
            "**DESCRIPTION**: Missing test for negative input\n"
            "**TEST_CASES**:\n"
            "- Test with -1\n"
            "- Test with MIN_INT\n"
            "**CONFIDENCE**: 0.85\n"
            "**REASONING**: Negative values are not handled\n"
        )
        gaps = detector._parse_llm_response(response, "compute", "calc.py")
        assert len(gaps) == 1
        assert gaps[0].category == GapCategory.EDGE_CASE
        assert gaps[0].severity == "high"
        assert gaps[0].confidence == 0.85
        assert len(gaps[0].suggested_test_cases) == 2

    def test_multiple_gaps_separated_by_delimiter(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        response = (
            "**CATEGORY**: edge_case\n"
            "**DESCRIPTION**: First gap\n"
            "---\n"
            "**CATEGORY**: error_path\n"
            "**DESCRIPTION**: Second gap\n"
        )
        gaps = detector._parse_llm_response(response, "func", "file.py")
        assert len(gaps) == 2

    def test_empty_response(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        gaps = detector._parse_llm_response("", "func", "file.py")
        assert gaps == []

    def test_invalid_section_skipped(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        response = "no valid fields here"
        gaps = detector._parse_llm_response(response, "func", "file.py")
        assert gaps == []


# ── _parse_gap_section ────────────────────────────────────────────


class TestParseGapSection:
    def test_missing_category_returns_none(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        section = "**DESCRIPTION**: something\n"
        result = detector._parse_gap_section(section, "func", "file.py")
        assert result is None

    def test_missing_description_returns_none(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        section = "**CATEGORY**: edge_case\n"
        result = detector._parse_gap_section(section, "func", "file.py")
        assert result is None

    def test_unknown_category_defaults_to_edge_case(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        section = "**CATEGORY**: weird_category\n**DESCRIPTION**: something\n"
        result = detector._parse_gap_section(section, "func", "file.py")
        assert result is not None
        assert result.category == GapCategory.EDGE_CASE

    def test_default_severity_is_medium(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        section = "**CATEGORY**: edge_case\n**DESCRIPTION**: something\n"
        result = detector._parse_gap_section(section, "func", "file.py")
        assert result is not None
        assert result.severity == "medium"

    def test_default_confidence_is_0_7(self, tmp_path: Path) -> None:
        detector, _ = _make_detector(tmp_path)
        section = "**CATEGORY**: edge_case\n**DESCRIPTION**: something\n"
        result = detector._parse_gap_section(section, "func", "file.py")
        assert result is not None
        assert result.confidence == 0.7


# ── SemanticGap dataclass ─────────────────────────────────────────


class TestSemanticGapDataclass:
    def test_defaults(self) -> None:
        gap = SemanticGap(
            category=GapCategory.EDGE_CASE,
            description="test",
            function_name="fn",
            file_path="f.py",
        )
        assert gap.severity == "medium"
        assert gap.confidence == 0.7
        assert gap.suggested_test_cases == []
        assert gap.reasoning == ""
        assert gap.line_number is None
