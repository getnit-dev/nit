"""Tests for semantic gap analysis prompt (src/nit/llm/prompts/semantic_gap.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

from nit.llm.prompts.base import RenderedPrompt
from nit.llm.prompts.semantic_gap import SemanticGapContext, SemanticGapPrompt

# ── SemanticGapContext Tests ─────────────────────────────────────


def test_semantic_gap_context_defaults() -> None:
    """Test SemanticGapContext default field values."""
    ctx = SemanticGapContext(
        source_code="def foo(): pass",
        language="python",
        file_path="src/foo.py",
        function_name="foo",
        complexity=1,
        coverage_percentage=50.0,
    )
    assert ctx.existing_test_patterns == []
    assert ctx.related_tests == ""
    assert ctx.ast_structure == ""


def test_semantic_gap_context_all_fields() -> None:
    """Test SemanticGapContext with all fields populated."""
    ctx = SemanticGapContext(
        source_code="def calculate(x, y): return x / y",
        language="python",
        file_path="src/math.py",
        function_name="calculate",
        complexity=5,
        coverage_percentage=75.5,
        existing_test_patterns=["happy path", "negative inputs"],
        related_tests="def test_calculate(): assert calculate(4, 2) == 2",
        ast_structure="if-else with 3 branches",
    )
    assert ctx.complexity == 5
    assert ctx.coverage_percentage == 75.5
    assert len(ctx.existing_test_patterns) == 2
    assert ctx.related_tests != ""
    assert ctx.ast_structure != ""


# ── SemanticGapPrompt Tests ──────────────────────────────────────


def test_semantic_gap_prompt_name() -> None:
    """Test SemanticGapPrompt template name."""
    prompt = SemanticGapPrompt()
    assert prompt.name == "semantic_gap"


def test_semantic_gap_system_instruction() -> None:
    """Test system instruction mentions test coverage analysis."""
    prompt = SemanticGapPrompt()
    ctx = SemanticGapContext(
        source_code="code",
        language="python",
        file_path="f.py",
        function_name="fn",
        complexity=1,
        coverage_percentage=50.0,
    )
    system = prompt._system_instruction(ctx)
    assert "coverage" in system.lower()
    assert "edge case" in system.lower()
    assert "error path" in system.lower()


def test_build_gap_sections_includes_metadata() -> None:
    """Test that _build_gap_sections includes function metadata."""
    prompt = SemanticGapPrompt()
    ctx = SemanticGapContext(
        source_code="def calc(x): return x * 2",
        language="python",
        file_path="src/calc.py",
        function_name="calc",
        complexity=3,
        coverage_percentage=60.0,
    )
    sections = prompt._build_gap_sections(ctx)
    labels = [s.label for s in sections]
    assert "Function Metadata" in labels

    metadata = next(s for s in sections if s.label == "Function Metadata")
    assert "calc" in metadata.content
    assert "60.0%" in metadata.content
    assert "3" in metadata.content


def test_build_gap_sections_includes_source_code() -> None:
    """Test that source code section is always included."""
    prompt = SemanticGapPrompt()
    ctx = SemanticGapContext(
        source_code="def foo(): return 42",
        language="python",
        file_path="src/foo.py",
        function_name="foo",
        complexity=1,
        coverage_percentage=100.0,
    )
    sections = prompt._build_gap_sections(ctx)
    labels = [s.label for s in sections]
    assert "Source Code" in labels


def test_build_gap_sections_includes_ast_structure_when_present() -> None:
    """Test that AST structure section is included when non-empty."""
    prompt = SemanticGapPrompt()
    ctx = SemanticGapContext(
        source_code="code",
        language="python",
        file_path="f.py",
        function_name="fn",
        complexity=5,
        coverage_percentage=50.0,
        ast_structure="3 if-branches, 1 for-loop",
    )
    sections = prompt._build_gap_sections(ctx)
    labels = [s.label for s in sections]
    assert "Control Flow Summary" in labels
    flow_section = next(s for s in sections if s.label == "Control Flow Summary")
    assert "if-branches" in flow_section.content


def test_build_gap_sections_omits_ast_when_empty() -> None:
    """Test that AST structure section is omitted when empty."""
    prompt = SemanticGapPrompt()
    ctx = SemanticGapContext(
        source_code="code",
        language="python",
        file_path="f.py",
        function_name="fn",
        complexity=1,
        coverage_percentage=80.0,
        ast_structure="",
    )
    sections = prompt._build_gap_sections(ctx)
    labels = [s.label for s in sections]
    assert "Control Flow Summary" not in labels


def test_build_gap_sections_includes_existing_patterns() -> None:
    """Test that existing test patterns are included when present."""
    prompt = SemanticGapPrompt()
    ctx = SemanticGapContext(
        source_code="code",
        language="python",
        file_path="f.py",
        function_name="fn",
        complexity=2,
        coverage_percentage=70.0,
        existing_test_patterns=["happy path", "empty input", "negative numbers"],
    )
    sections = prompt._build_gap_sections(ctx)
    labels = [s.label for s in sections]
    assert "Already Tested Scenarios" in labels
    patterns_section = next(s for s in sections if s.label == "Already Tested Scenarios")
    assert "happy path" in patterns_section.content
    assert "empty input" in patterns_section.content


def test_build_gap_sections_omits_patterns_when_empty() -> None:
    """Test that existing patterns section is omitted when empty."""
    prompt = SemanticGapPrompt()
    ctx = SemanticGapContext(
        source_code="code",
        language="python",
        file_path="f.py",
        function_name="fn",
        complexity=1,
        coverage_percentage=50.0,
        existing_test_patterns=[],
    )
    sections = prompt._build_gap_sections(ctx)
    labels = [s.label for s in sections]
    assert "Already Tested Scenarios" not in labels


def test_build_gap_sections_includes_related_tests() -> None:
    """Test that related tests section is included when present."""
    prompt = SemanticGapPrompt()
    ctx = SemanticGapContext(
        source_code="code",
        language="python",
        file_path="f.py",
        function_name="fn",
        complexity=1,
        coverage_percentage=50.0,
        related_tests="def test_fn(): assert fn() == 42",
    )
    sections = prompt._build_gap_sections(ctx)
    labels = [s.label for s in sections]
    assert "Related Test Code" in labels


def test_build_gap_sections_omits_related_tests_when_empty() -> None:
    """Test that related tests section is omitted when empty."""
    prompt = SemanticGapPrompt()
    ctx = SemanticGapContext(
        source_code="code",
        language="python",
        file_path="f.py",
        function_name="fn",
        complexity=1,
        coverage_percentage=50.0,
        related_tests="",
    )
    sections = prompt._build_gap_sections(ctx)
    labels = [s.label for s in sections]
    assert "Related Test Code" not in labels


def test_build_sections_with_assembled_context_fallback() -> None:
    """Test _build_sections returns fallback for non-SemanticGapContext."""
    prompt = SemanticGapPrompt()
    mock_context = MagicMock()
    sections = prompt._build_sections(mock_context)
    assert len(sections) == 1
    assert sections[0].label == "Analysis Request"


def test_render_gap_analysis_returns_rendered_prompt() -> None:
    """Test render_gap_analysis returns a proper RenderedPrompt."""
    prompt = SemanticGapPrompt()
    ctx = SemanticGapContext(
        source_code="def divide(a, b): return a / b",
        language="python",
        file_path="src/math.py",
        function_name="divide",
        complexity=2,
        coverage_percentage=50.0,
    )
    result = prompt.render_gap_analysis(ctx)
    assert isinstance(result, RenderedPrompt)
    assert len(result.messages) == 2
    assert result.messages[0].role == "system"
    assert result.messages[1].role == "user"


def test_render_gap_analysis_user_message_content() -> None:
    """Test that the rendered user message contains analysis structure."""
    prompt = SemanticGapPrompt()
    ctx = SemanticGapContext(
        source_code="code",
        language="python",
        file_path="f.py",
        function_name="fn",
        complexity=3,
        coverage_percentage=40.0,
    )
    result = prompt.render_gap_analysis(ctx)
    user_msg = result.messages[1].content
    assert "CATEGORY" in user_msg
    assert "SEVERITY" in user_msg
    assert "TEST_CASES" in user_msg
    assert "CONFIDENCE" in user_msg
    assert "REASONING" in user_msg
