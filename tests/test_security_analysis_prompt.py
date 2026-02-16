"""Tests for security analysis prompt (src/nit/llm/prompts/security_analysis.py)."""

from __future__ import annotations

from nit.llm.prompts.security_analysis import (
    SecurityAnalysisContext,
    SecurityAnalysisPrompt,
)
from tests.test_prompts import _make_context


def test_build_sections_assembled_context_fallback() -> None:
    """_build_sections returns generic section for regular AssembledContext."""
    prompt = SecurityAnalysisPrompt()
    ctx = _make_context()
    sections = prompt._build_sections(ctx)
    assert len(sections) == 1
    assert sections[0].label == "Analysis Request"


def test_build_sections_security_context() -> None:
    """_build_sections routes through isinstance for SecurityAnalysisContext."""
    prompt = SecurityAnalysisPrompt()
    ctx = SecurityAnalysisContext(
        vulnerability_type="sql_injection",
        code_snippet="cursor.execute(f'SELECT * FROM users WHERE id={user_id}')",
        file_path="app/db.py",
        language="python",
        heuristic_description="String interpolation in SQL query",
    )
    sections = prompt._build_sections(ctx)
    assert any(s.label == "Finding" for s in sections)
    assert any(s.label == "Code" for s in sections)


def test_build_sections_with_data_flow() -> None:
    """_build_sections includes data flow section when present."""
    prompt = SecurityAnalysisPrompt()
    ctx = SecurityAnalysisContext(
        vulnerability_type="xss",
        code_snippet="<div>{user_input}</div>",
        file_path="app/views.py",
        language="python",
        heuristic_description="Unescaped user input in template",
        data_flow=["request.GET['q']", "context['query']", "template render"],
    )
    sections = prompt._build_sections(ctx)
    assert any(s.label == "Data Flow" for s in sections)
