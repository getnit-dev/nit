"""Tests for bug analysis prompt templates (src/nit/llm/prompts/bug_analysis.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

from nit.llm.prompts.base import RenderedPrompt
from nit.llm.prompts.bug_analysis import (
    BugAnalysisContext,
    BugAnalysisPrompt,
    BugReproductionPrompt,
    RootCauseAnalysisPrompt,
)

# ── BugAnalysisContext Tests ─────────────────────────────────────


def test_bug_analysis_context_defaults() -> None:
    """Test BugAnalysisContext default field values."""
    ctx = BugAnalysisContext(
        error_message="NullPointerException",
        stack_trace="at Main.java:10",
        source_code="int x = null;",
    )
    assert ctx.language == "unknown"
    assert ctx.file_path == ""
    assert ctx.test_code == ""


def test_bug_analysis_context_all_fields() -> None:
    """Test BugAnalysisContext with all fields populated."""
    ctx = BugAnalysisContext(
        error_message="TypeError: cannot add str and int",
        stack_trace="  File app.py, line 5",
        source_code="result = x + y",
        test_code="assert add('a', 1) == 'a1'",
        language="python",
        file_path="src/app.py",
    )
    assert ctx.language == "python"
    assert ctx.file_path == "src/app.py"
    assert ctx.test_code == "assert add('a', 1) == 'a1'"


# ── BugAnalysisPrompt Tests ─────────────────────────────────────


def test_bug_analysis_prompt_name() -> None:
    """Test BugAnalysisPrompt template name."""
    prompt = BugAnalysisPrompt()
    assert prompt.name == "bug_analysis"


def test_bug_analysis_prompt_system_instruction() -> None:
    """Test that system instruction mentions debugging."""
    prompt = BugAnalysisPrompt()
    ctx = BugAnalysisContext(
        error_message="err",
        stack_trace="trace",
        source_code="code",
    )
    system = prompt._system_instruction(ctx)
    assert "debugger" in system.lower()
    assert "root cause" in system.lower()


def test_build_bug_sections_includes_error_info() -> None:
    """Test that _build_bug_sections includes error information."""
    prompt = BugAnalysisPrompt()
    ctx = BugAnalysisContext(
        error_message="IndexError",
        stack_trace="at line 42",
        source_code="items[10]",
        language="python",
        file_path="src/foo.py",
    )
    sections = prompt._build_bug_sections(ctx)
    labels = [s.label for s in sections]
    assert "Error Information" in labels
    # Error section should contain the error message
    error_section = next(s for s in sections if s.label == "Error Information")
    assert "IndexError" in error_section.content
    assert "at line 42" in error_section.content


def test_build_bug_sections_includes_source_code() -> None:
    """Test that source code section is included."""
    prompt = BugAnalysisPrompt()
    ctx = BugAnalysisContext(
        error_message="err",
        stack_trace="",
        source_code="def foo(): pass",
        language="python",
        file_path="src/foo.py",
    )
    sections = prompt._build_bug_sections(ctx)
    labels = [s.label for s in sections]
    assert any("Source Code" in label for label in labels)


def test_build_bug_sections_includes_test_code_when_present() -> None:
    """Test that test code section is included when test_code is non-empty."""
    prompt = BugAnalysisPrompt()
    ctx = BugAnalysisContext(
        error_message="err",
        stack_trace="",
        source_code="def foo(): pass",
        test_code="def test_foo(): assert foo() is None",
        language="python",
    )
    sections = prompt._build_bug_sections(ctx)
    labels = [s.label for s in sections]
    assert "Test Code" in labels


def test_build_bug_sections_omits_test_code_when_empty() -> None:
    """Test that test code section is omitted when test_code is empty."""
    prompt = BugAnalysisPrompt()
    ctx = BugAnalysisContext(
        error_message="err",
        stack_trace="",
        source_code="def foo(): pass",
        test_code="",
    )
    sections = prompt._build_bug_sections(ctx)
    labels = [s.label for s in sections]
    assert "Test Code" not in labels


def test_build_sections_with_assembled_context_fallback() -> None:
    """Test _build_sections returns fallback for non-BugAnalysisContext."""
    prompt = BugAnalysisPrompt()
    mock_context = MagicMock()
    # The isinstance check will fail for MagicMock, triggering fallback
    sections = prompt._build_sections(mock_context)
    assert len(sections) == 1
    assert sections[0].label == "Analysis Request"


def test_render_bug_analysis_returns_rendered_prompt() -> None:
    """Test render_bug_analysis returns a proper RenderedPrompt."""
    prompt = BugAnalysisPrompt()
    ctx = BugAnalysisContext(
        error_message="ValueError: invalid literal",
        stack_trace="  File main.py, line 10",
        source_code='x = int("abc")',
        language="python",
        file_path="main.py",
    )
    result = prompt.render_bug_analysis(ctx)
    assert isinstance(result, RenderedPrompt)
    assert len(result.messages) == 2
    assert result.messages[0].role == "system"
    assert result.messages[1].role == "user"


def test_render_bug_analysis_user_message_contains_analysis_request() -> None:
    """Test that the rendered user message contains the analysis request."""
    prompt = BugAnalysisPrompt()
    ctx = BugAnalysisContext(
        error_message="NameError: name 'x' is not defined",
        stack_trace="at script.py:1",
        source_code="print(x)",
        language="python",
    )
    result = prompt.render_bug_analysis(ctx)
    user_msg = result.messages[1].content
    assert "Bug Type" in user_msg
    assert "Root Cause" in user_msg
    assert "Missing Validations" in user_msg


def test_render_bug_analysis_includes_stack_trace() -> None:
    """Test that stack trace appears in the rendered prompt."""
    prompt = BugAnalysisPrompt()
    ctx = BugAnalysisContext(
        error_message="Exception",
        stack_trace="  File /app/main.py, line 5\n    raise Exception()",
        source_code="raise Exception()",
    )
    result = prompt.render_bug_analysis(ctx)
    user_msg = result.messages[1].content
    assert "Stack Trace" in user_msg


# ── RootCauseAnalysisPrompt Tests ────────────────────────────────


def test_root_cause_analysis_prompt_name() -> None:
    """Test RootCauseAnalysisPrompt template name."""
    prompt = RootCauseAnalysisPrompt()
    assert prompt.name == "root_cause_analysis"


def test_root_cause_analysis_system_instruction() -> None:
    """Test system instruction mentions root cause analysis."""
    prompt = RootCauseAnalysisPrompt()
    ctx = BugAnalysisContext(
        error_message="err",
        stack_trace="",
        source_code="code",
    )
    system = prompt._system_instruction(ctx)
    assert "root cause" in system.lower()


def test_root_cause_build_bug_sections() -> None:
    """Test _build_bug_sections for root cause analysis."""
    prompt = RootCauseAnalysisPrompt()
    ctx = BugAnalysisContext(
        error_message="NullPointerException",
        stack_trace="",
        source_code="obj.method()",
        language="java",
    )
    sections = prompt._build_bug_sections(ctx)
    assert len(sections) == 2
    assert sections[0].label == "Error"
    assert sections[1].label == "Source Code"


def test_root_cause_build_sections_non_bug_context() -> None:
    """Test _build_sections returns empty for non-BugAnalysisContext."""
    prompt = RootCauseAnalysisPrompt()
    mock_context = MagicMock()
    sections = prompt._build_sections(mock_context)
    assert sections == []


# ── BugReproductionPrompt Tests ──────────────────────────────────


def test_bug_reproduction_prompt_name() -> None:
    """Test BugReproductionPrompt template name."""
    prompt = BugReproductionPrompt()
    assert prompt.name == "bug_reproduction"


def test_bug_reproduction_system_instruction() -> None:
    """Test system instruction mentions reproduction tests."""
    prompt = BugReproductionPrompt()
    ctx = BugAnalysisContext(
        error_message="err",
        stack_trace="",
        source_code="code",
    )
    system = prompt._system_instruction(ctx)
    assert "reproduction" in system.lower()
    assert "minimal" in system.lower()


def test_bug_reproduction_build_sections_with_bug_context() -> None:
    """Test _build_sections for bug reproduction with BugAnalysisContext."""
    prompt = BugReproductionPrompt()
    ctx = BugAnalysisContext(
        error_message="OverflowError",
        stack_trace="",
        source_code="x = 2**1000 * 2**1000",
        language="python",
    )
    sections = prompt._build_sections(ctx)
    assert len(sections) == 2
    assert sections[0].label == "Bug to Reproduce"
    assert "OverflowError" in sections[0].content


def test_bug_reproduction_build_sections_non_bug_context() -> None:
    """Test _build_sections returns empty for non-BugAnalysisContext."""
    prompt = BugReproductionPrompt()
    mock_context = MagicMock()
    sections = prompt._build_sections(mock_context)
    assert sections == []
