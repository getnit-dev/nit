"""Tests for security analysis prompt template (llm/prompts/security_analysis.py).

Covers:
- SecurityAnalysisContext data model
- SecurityAnalysisPrompt rendering
- Validation prompt structure (system + user messages)
"""

from __future__ import annotations

from nit.llm.prompts.security_analysis import (
    SecurityAnalysisContext,
    SecurityAnalysisPrompt,
)

# ── SecurityAnalysisContext ──────────────────────────────────────


class TestSecurityAnalysisContext:
    """SecurityAnalysisContext data model."""

    def test_defaults(self) -> None:
        ctx = SecurityAnalysisContext(
            vulnerability_type="sql_injection",
            code_snippet="cursor.execute(f'...')",
            file_path="app.py",
            language="python",
            heuristic_description="SQL injection via f-string",
        )
        assert ctx.data_flow == []

    def test_all_fields(self) -> None:
        ctx = SecurityAnalysisContext(
            vulnerability_type="xss",
            code_snippet="innerHTML = data",
            file_path="view.js",
            language="javascript",
            heuristic_description="XSS via innerHTML",
            data_flow=["req.query.name", "render(name)", "innerHTML"],
        )
        assert len(ctx.data_flow) == 3
        assert ctx.language == "javascript"


# ── SecurityAnalysisPrompt ───────────────────────────────────────


class TestSecurityAnalysisPrompt:
    """SecurityAnalysisPrompt rendering."""

    def test_prompt_name(self) -> None:
        prompt = SecurityAnalysisPrompt()
        assert prompt.name == "security_analysis"

    def test_render_validation_has_system_message(self) -> None:
        prompt = SecurityAnalysisPrompt()
        ctx = SecurityAnalysisContext(
            vulnerability_type="sql_injection",
            code_snippet="cursor.execute(f'...')",
            file_path="app.py",
            language="python",
            heuristic_description="SQL injection via f-string",
        )
        rendered = prompt.render_validation(ctx)
        assert len(rendered.messages) == 2
        assert rendered.messages[0].role == "system"
        assert rendered.messages[1].role == "user"

    def test_system_message_mentions_security(self) -> None:
        prompt = SecurityAnalysisPrompt()
        ctx = SecurityAnalysisContext(
            vulnerability_type="xss",
            code_snippet="innerHTML = x",
            file_path="app.js",
            language="javascript",
            heuristic_description="XSS",
        )
        rendered = prompt.render_validation(ctx)
        system_msg = rendered.messages[0].content
        assert "security" in system_msg.lower()
        assert "false positive" in system_msg.lower()

    def test_user_message_contains_code(self) -> None:
        prompt = SecurityAnalysisPrompt()
        ctx = SecurityAnalysisContext(
            vulnerability_type="sql_injection",
            code_snippet="db.query(f'SELECT ...')",
            file_path="app.py",
            language="python",
            heuristic_description="SQL injection via f-string",
        )
        rendered = prompt.render_validation(ctx)
        user_msg = rendered.messages[1].content
        assert "db.query" in user_msg
        assert "python" in user_msg

    def test_user_message_requests_validation(self) -> None:
        prompt = SecurityAnalysisPrompt()
        ctx = SecurityAnalysisContext(
            vulnerability_type="command_injection",
            code_snippet="os.system(cmd)",
            file_path="run.py",
            language="python",
            heuristic_description="Command injection via os.system",
        )
        rendered = prompt.render_validation(ctx)
        user_msg = rendered.messages[1].content
        assert "IS_VALID" in user_msg
        assert "CONFIDENCE" in user_msg
        assert "REASONING" in user_msg

    def test_data_flow_included_when_present(self) -> None:
        prompt = SecurityAnalysisPrompt()
        ctx = SecurityAnalysisContext(
            vulnerability_type="ssrf",
            code_snippet="requests.get(url)",
            file_path="api.py",
            language="python",
            heuristic_description="SSRF",
            data_flow=["request.args['url']", "fetch(url)"],
        )
        rendered = prompt.render_validation(ctx)
        user_msg = rendered.messages[1].content
        assert "Data Flow" in user_msg
        assert "request.args" in user_msg

    def test_data_flow_omitted_when_empty(self) -> None:
        prompt = SecurityAnalysisPrompt()
        ctx = SecurityAnalysisContext(
            vulnerability_type="weak_crypto",
            code_snippet="hashlib.md5(data)",
            file_path="hash.py",
            language="python",
            heuristic_description="Weak crypto",
            data_flow=[],
        )
        rendered = prompt.render_validation(ctx)
        user_msg = rendered.messages[1].content
        assert "Data Flow" not in user_msg

    def test_finding_section_contains_metadata(self) -> None:
        prompt = SecurityAnalysisPrompt()
        ctx = SecurityAnalysisContext(
            vulnerability_type="path_traversal",
            code_snippet="open(user_path)",
            file_path="files.py",
            language="python",
            heuristic_description="Path traversal",
        )
        rendered = prompt.render_validation(ctx)
        user_msg = rendered.messages[1].content
        assert "path_traversal" in user_msg
        assert "files.py" in user_msg
        assert "python" in user_msg
