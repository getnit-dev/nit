"""Tests for fix generation prompt templates (src/nit/llm/prompts/fix_generation.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

from nit.llm.prompts.base import RenderedPrompt
from nit.llm.prompts.fix_generation import (
    FixGenerationContext,
    FixGenerationPrompt,
    MinimalFixPrompt,
    SafeFixPrompt,
)

# ── FixGenerationContext Tests ───────────────────────────────────


def test_fix_generation_context_defaults() -> None:
    """Test FixGenerationContext default field values."""
    ctx = FixGenerationContext(
        bug_type="null_dereference",
        bug_description="Null pointer when accessing user.name",
        root_cause="User object may be None after lookup",
        source_code="user = lookup(id)\nprint(user.name)",
        missing_checks=[],
        incorrect_assumptions=[],
    )
    assert ctx.language == "unknown"
    assert ctx.file_path == ""


def test_fix_generation_context_all_fields() -> None:
    """Test FixGenerationContext with all fields populated."""
    ctx = FixGenerationContext(
        bug_type="type_error",
        bug_description="Cannot add string and int",
        root_cause="Input not validated",
        source_code="result = x + y",
        missing_checks=["Type check on input"],
        incorrect_assumptions=["All inputs are integers"],
        language="python",
        file_path="src/math.py",
    )
    assert ctx.language == "python"
    assert ctx.file_path == "src/math.py"
    assert len(ctx.missing_checks) == 1
    assert len(ctx.incorrect_assumptions) == 1


# ── FixGenerationPrompt Tests ───────────────────────────────────


def test_fix_generation_prompt_name() -> None:
    """Test FixGenerationPrompt template name."""
    prompt = FixGenerationPrompt()
    assert prompt.name == "fix_generation"


def test_fix_generation_system_instruction() -> None:
    """Test system instruction mentions bug fixes."""
    prompt = FixGenerationPrompt()
    ctx = FixGenerationContext(
        bug_type="err",
        bug_description="desc",
        root_cause="cause",
        source_code="code",
        missing_checks=[],
        incorrect_assumptions=[],
    )
    system = prompt._system_instruction(ctx)
    assert "bug fix" in system.lower()
    assert "minimal" in system.lower()


def test_build_fix_sections_includes_bug_info() -> None:
    """Test that _build_fix_sections includes bug information."""
    prompt = FixGenerationPrompt()
    ctx = FixGenerationContext(
        bug_type="logic_error",
        bug_description="Off-by-one in loop",
        root_cause="Loop iterates one time too many",
        source_code="for i in range(len(items) + 1):",
        missing_checks=[],
        incorrect_assumptions=[],
        language="python",
    )
    sections = prompt._build_fix_sections(ctx)
    labels = [s.label for s in sections]
    assert "Bug Information" in labels
    assert "Root Cause Analysis" in labels
    assert "Original Source Code" in labels

    bug_section = next(s for s in sections if s.label == "Bug Information")
    assert "logic_error" in bug_section.content
    assert "Off-by-one" in bug_section.content


def test_build_fix_sections_includes_missing_checks() -> None:
    """Test that missing checks are included when present."""
    prompt = FixGenerationPrompt()
    ctx = FixGenerationContext(
        bug_type="null_dereference",
        bug_description="Null access",
        root_cause="Missing null check",
        source_code="obj.method()",
        missing_checks=["Check if obj is None", "Validate input type"],
        incorrect_assumptions=[],
    )
    sections = prompt._build_fix_sections(ctx)
    labels = [s.label for s in sections]
    assert "Missing Validation Checks" in labels
    checks_section = next(s for s in sections if s.label == "Missing Validation Checks")
    assert "Check if obj is None" in checks_section.content
    assert "Validate input type" in checks_section.content


def test_build_fix_sections_includes_incorrect_assumptions() -> None:
    """Test that incorrect assumptions are included when present."""
    prompt = FixGenerationPrompt()
    ctx = FixGenerationContext(
        bug_type="logic_error",
        bug_description="Wrong result",
        root_cause="Bad assumption",
        source_code="x = 1 / y",
        missing_checks=[],
        incorrect_assumptions=["y is never zero", "y is always positive"],
    )
    sections = prompt._build_fix_sections(ctx)
    labels = [s.label for s in sections]
    assert "Incorrect Assumptions to Address" in labels
    assumptions_section = next(s for s in sections if s.label == "Incorrect Assumptions to Address")
    assert "y is never zero" in assumptions_section.content


def test_build_fix_sections_omits_empty_checks_and_assumptions() -> None:
    """Test that empty checks and assumptions are omitted."""
    prompt = FixGenerationPrompt()
    ctx = FixGenerationContext(
        bug_type="type_error",
        bug_description="Type mismatch",
        root_cause="Missing conversion",
        source_code="x + y",
        missing_checks=[],
        incorrect_assumptions=[],
    )
    sections = prompt._build_fix_sections(ctx)
    labels = [s.label for s in sections]
    assert "Missing Validation Checks" not in labels
    assert "Incorrect Assumptions to Address" not in labels


def test_build_sections_with_assembled_context_fallback() -> None:
    """Test _build_sections returns fallback for non-FixGenerationContext."""
    prompt = FixGenerationPrompt()
    mock_context = MagicMock()
    sections = prompt._build_sections(mock_context)
    assert len(sections) == 1
    assert sections[0].label == "Fix Request"


def test_render_fix_generation_returns_rendered_prompt() -> None:
    """Test render_fix_generation returns a proper RenderedPrompt."""
    prompt = FixGenerationPrompt()
    ctx = FixGenerationContext(
        bug_type="index_error",
        bug_description="List index out of range",
        root_cause="No bounds checking",
        source_code="items[idx]",
        missing_checks=["Check idx < len(items)"],
        incorrect_assumptions=["idx is always valid"],
        language="python",
        file_path="src/list_ops.py",
    )
    result = prompt.render_fix_generation(ctx)
    assert isinstance(result, RenderedPrompt)
    assert len(result.messages) == 2
    assert result.messages[0].role == "system"
    assert result.messages[1].role == "user"


def test_render_fix_generation_user_message_content() -> None:
    """Test that the rendered user message contains fix instructions."""
    prompt = FixGenerationPrompt()
    ctx = FixGenerationContext(
        bug_type="null_dereference",
        bug_description="NullPointerException",
        root_cause="Uninitialized variable",
        source_code="obj.method()",
        missing_checks=["Null check"],
        incorrect_assumptions=[],
        language="java",
    )
    result = prompt.render_fix_generation(ctx)
    user_msg = result.messages[1].content
    assert "Fix Instructions" in user_msg
    assert "COMPLETE fixed source code" in user_msg
    assert "Explanation" in user_msg


# ── MinimalFixPrompt Tests ───────────────────────────────────────


def test_minimal_fix_prompt_name() -> None:
    """Test MinimalFixPrompt template name."""
    prompt = MinimalFixPrompt()
    assert prompt.name == "minimal_fix"


def test_minimal_fix_system_instruction() -> None:
    """Test system instruction mentions surgical/minimal fixes."""
    prompt = MinimalFixPrompt()
    ctx = FixGenerationContext(
        bug_type="err",
        bug_description="desc",
        root_cause="cause",
        source_code="code",
        missing_checks=[],
        incorrect_assumptions=[],
    )
    system = prompt._system_instruction(ctx)
    assert "minimal" in system.lower()
    assert "surgical" in system.lower()


def test_minimal_fix_build_sections_with_fix_context() -> None:
    """Test _build_sections with FixGenerationContext."""
    prompt = MinimalFixPrompt()
    ctx = FixGenerationContext(
        bug_type="division_by_zero",
        bug_description="Division by zero",
        root_cause="Missing zero check",
        source_code="result = a / b",
        missing_checks=[],
        incorrect_assumptions=[],
        language="python",
    )
    sections = prompt._build_sections(ctx)
    assert len(sections) == 2
    assert sections[0].label == "Bug"
    assert "division_by_zero" in sections[0].content
    assert sections[1].label == "Code"


def test_minimal_fix_build_sections_non_fix_context() -> None:
    """Test _build_sections returns empty for non-FixGenerationContext."""
    prompt = MinimalFixPrompt()
    mock_context = MagicMock()
    sections = prompt._build_sections(mock_context)
    assert sections == []


# ── SafeFixPrompt Tests ──────────────────────────────────────────


def test_safe_fix_prompt_name() -> None:
    """Test SafeFixPrompt template name."""
    prompt = SafeFixPrompt()
    assert prompt.name == "safe_fix"


def test_safe_fix_system_instruction() -> None:
    """Test system instruction mentions robust/production-ready."""
    prompt = SafeFixPrompt()
    ctx = FixGenerationContext(
        bug_type="err",
        bug_description="desc",
        root_cause="cause",
        source_code="code",
        missing_checks=[],
        incorrect_assumptions=[],
    )
    system = prompt._system_instruction(ctx)
    assert "robust" in system.lower()
    assert "production-ready" in system.lower()


def test_safe_fix_build_sections_with_fix_context() -> None:
    """Test _build_sections with FixGenerationContext."""
    prompt = SafeFixPrompt()
    ctx = FixGenerationContext(
        bug_type="race_condition",
        bug_description="Data race on shared counter",
        root_cause="No synchronization",
        source_code="counter += 1",
        missing_checks=["Lock acquisition", "Atomic operation"],
        incorrect_assumptions=[],
        language="python",
    )
    sections = prompt._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Bug Analysis" in labels
    assert "Source Code" in labels
    assert "Required Validations" in labels

    validations = next(s for s in sections if s.label == "Required Validations")
    assert "Lock acquisition" in validations.content


def test_safe_fix_build_sections_omits_validations_when_empty() -> None:
    """Test _build_sections omits validations when missing_checks is empty."""
    prompt = SafeFixPrompt()
    ctx = FixGenerationContext(
        bug_type="logic_error",
        bug_description="desc",
        root_cause="cause",
        source_code="code",
        missing_checks=[],
        incorrect_assumptions=[],
    )
    sections = prompt._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Required Validations" not in labels


def test_safe_fix_build_sections_non_fix_context() -> None:
    """Test _build_sections returns empty for non-FixGenerationContext."""
    prompt = SafeFixPrompt()
    mock_context = MagicMock()
    sections = prompt._build_sections(mock_context)
    assert sections == []
