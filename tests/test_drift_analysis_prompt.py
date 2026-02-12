"""Tests for drift analysis prompt templates (src/nit/llm/prompts/drift_analysis.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

from nit.llm.prompts.base import RenderedPrompt
from nit.llm.prompts.drift_analysis import (
    DriftAnalysisContext,
    DriftAnalysisPrompt,
    PromptImprovementSuggestion,
)

# ── DriftAnalysisContext Tests ───────────────────────────────────


def test_drift_analysis_context_defaults() -> None:
    """Test DriftAnalysisContext default field values."""
    ctx = DriftAnalysisContext(
        test_id="drift-001",
        test_name="Greeting test",
        baseline_output="Hello, World!",
        current_output="Hi, World!",
    )
    assert ctx.similarity_score is None
    assert ctx.comparison_type == "semantic"
    assert ctx.prompt_used == ""
    assert ctx.model == ""


def test_drift_analysis_context_all_fields() -> None:
    """Test DriftAnalysisContext with all fields populated."""
    ctx = DriftAnalysisContext(
        test_id="drift-002",
        test_name="JSON output test",
        baseline_output='{"key": "value"}',
        current_output='{"key": "new_value"}',
        similarity_score=0.85,
        comparison_type="exact",
        prompt_used="Generate JSON with key/value pair",
        model="gpt-4o",
    )
    assert ctx.similarity_score == 0.85
    assert ctx.comparison_type == "exact"
    assert ctx.model == "gpt-4o"


# ── DriftAnalysisPrompt Tests ───────────────────────────────────


def test_drift_analysis_prompt_name() -> None:
    """Test DriftAnalysisPrompt template name."""
    prompt = DriftAnalysisPrompt()
    assert prompt.name == "drift_analysis"


def test_drift_analysis_system_instruction() -> None:
    """Test system instruction mentions drift analysis."""
    prompt = DriftAnalysisPrompt()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
    )
    system = prompt._system_instruction(ctx)
    assert "drift" in system.lower()
    assert "llm" in system.lower()


def test_build_drift_sections_includes_test_info() -> None:
    """Test that _build_drift_sections includes test information."""
    prompt = DriftAnalysisPrompt()
    ctx = DriftAnalysisContext(
        test_id="drift-003",
        test_name="Summary generation",
        baseline_output="Original summary",
        current_output="Changed summary",
        comparison_type="semantic",
    )
    sections = prompt._build_drift_sections(ctx)
    labels = [s.label for s in sections]
    assert "Test Information" in labels

    test_info = next(s for s in sections if s.label == "Test Information")
    assert "Summary generation" in test_info.content
    assert "drift-003" in test_info.content
    assert "semantic" in test_info.content


def test_build_drift_sections_includes_similarity_score() -> None:
    """Test that similarity score is included when present."""
    prompt = DriftAnalysisPrompt()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
        similarity_score=0.723,
    )
    sections = prompt._build_drift_sections(ctx)
    test_info = next(s for s in sections if s.label == "Test Information")
    assert "0.723" in test_info.content


def test_build_drift_sections_omits_similarity_when_none() -> None:
    """Test that similarity score line is omitted when None."""
    prompt = DriftAnalysisPrompt()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
        similarity_score=None,
    )
    sections = prompt._build_drift_sections(ctx)
    test_info = next(s for s in sections if s.label == "Test Information")
    assert "Similarity Score" not in test_info.content


def test_build_drift_sections_includes_model_when_present() -> None:
    """Test that model info is included when specified."""
    prompt = DriftAnalysisPrompt()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
        model="gpt-4o-mini",
    )
    sections = prompt._build_drift_sections(ctx)
    test_info = next(s for s in sections if s.label == "Test Information")
    assert "gpt-4o-mini" in test_info.content


def test_build_drift_sections_omits_model_when_empty() -> None:
    """Test that model line is omitted when model is empty."""
    prompt = DriftAnalysisPrompt()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
        model="",
    )
    sections = prompt._build_drift_sections(ctx)
    test_info = next(s for s in sections if s.label == "Test Information")
    assert "Model" not in test_info.content


def test_build_drift_sections_includes_output_comparison() -> None:
    """Test that output comparison section is always included."""
    prompt = DriftAnalysisPrompt()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="Expected output text",
        current_output="Actual drifted text",
    )
    sections = prompt._build_drift_sections(ctx)
    labels = [s.label for s in sections]
    assert "Output Comparison" in labels

    comparison = next(s for s in sections if s.label == "Output Comparison")
    assert "Expected output text" in comparison.content
    assert "Actual drifted text" in comparison.content


def test_build_drift_sections_includes_prompt_when_present() -> None:
    """Test that prompt section is included when prompt_used is non-empty."""
    prompt = DriftAnalysisPrompt()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
        prompt_used="Generate a greeting message",
    )
    sections = prompt._build_drift_sections(ctx)
    labels = [s.label for s in sections]
    assert "Prompt Used" in labels


def test_build_drift_sections_omits_prompt_when_empty() -> None:
    """Test that prompt section is omitted when prompt_used is empty."""
    prompt = DriftAnalysisPrompt()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
        prompt_used="",
    )
    sections = prompt._build_drift_sections(ctx)
    labels = [s.label for s in sections]
    assert "Prompt Used" not in labels


def test_build_sections_with_assembled_context_fallback() -> None:
    """Test _build_sections returns fallback for non-DriftAnalysisContext."""
    prompt = DriftAnalysisPrompt()
    mock_context = MagicMock()
    sections = prompt._build_sections(mock_context)
    assert len(sections) == 1
    assert sections[0].label == "Analysis Request"


def test_render_drift_analysis_returns_rendered_prompt() -> None:
    """Test render_drift_analysis returns a proper RenderedPrompt."""
    prompt = DriftAnalysisPrompt()
    ctx = DriftAnalysisContext(
        test_id="drift-010",
        test_name="Code review output",
        baseline_output="The code looks correct.",
        current_output="The code has issues.",
        similarity_score=0.45,
        comparison_type="semantic",
        prompt_used="Review this code",
        model="gpt-4o",
    )
    result = prompt.render_drift_analysis(ctx)
    assert isinstance(result, RenderedPrompt)
    assert len(result.messages) == 2
    assert result.messages[0].role == "system"
    assert result.messages[1].role == "user"


def test_render_drift_analysis_user_message_content() -> None:
    """Test that the rendered user message contains analysis structure."""
    prompt = DriftAnalysisPrompt()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
    )
    result = prompt.render_drift_analysis(ctx)
    user_msg = result.messages[1].content
    assert "Key Differences" in user_msg
    assert "Drift Severity" in user_msg
    assert "Root Cause" in user_msg
    assert "Recommendations" in user_msg


# ── PromptImprovementSuggestion Tests ────────────────────────────


def test_prompt_improvement_name() -> None:
    """Test PromptImprovementSuggestion template name."""
    prompt = PromptImprovementSuggestion()
    assert prompt.name == "prompt_improvement"


def test_prompt_improvement_system_instruction() -> None:
    """Test system instruction mentions prompt engineering."""
    prompt = PromptImprovementSuggestion()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
    )
    system = prompt._system_instruction(ctx)
    assert "prompt engineering" in system.lower()
    assert "stability" in system.lower()


def test_prompt_improvement_build_sections_with_prompt() -> None:
    """Test _build_sections when prompt_used is available."""
    prompt = PromptImprovementSuggestion()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
        prompt_used="Generate a summary",
        similarity_score=0.7,
    )
    sections = prompt._build_sections(ctx)
    assert len(sections) == 2
    assert sections[0].label == "Current Prompt"
    assert sections[1].label == "Observed Drift"
    assert "0.7" in sections[1].content


def test_prompt_improvement_build_sections_without_prompt() -> None:
    """Test _build_sections returns empty when prompt_used is empty."""
    prompt = PromptImprovementSuggestion()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
        prompt_used="",
    )
    sections = prompt._build_sections(ctx)
    assert sections == []


def test_prompt_improvement_build_sections_non_drift_context() -> None:
    """Test _build_sections returns empty for non-DriftAnalysisContext."""
    prompt = PromptImprovementSuggestion()
    mock_context = MagicMock()
    sections = prompt._build_sections(mock_context)
    assert sections == []


def test_prompt_improvement_similarity_na_when_none() -> None:
    """Test that similarity shows N/A when score is None."""
    prompt = PromptImprovementSuggestion()
    ctx = DriftAnalysisContext(
        test_id="t1",
        test_name="test",
        baseline_output="a",
        current_output="b",
        prompt_used="some prompt",
        similarity_score=None,
    )
    sections = prompt._build_sections(ctx)
    drift_section = next(s for s in sections if s.label == "Observed Drift")
    assert "N/A" in drift_section.content
