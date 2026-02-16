"""Tests for Cypress prompt template (src/nit/llm/prompts/cypress_prompt.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

from nit.llm.prompts.cypress_prompt import (
    CypressTemplate,
    _build_requirements,
    _format_auth_section,
    _format_route_section,
)

# ── Helper ──────────────────────────────────────────────────────


def _make_mock_context(
    *,
    route_info: object | None = None,
    auth_config: object | None = None,
) -> MagicMock:
    """Create a MagicMock that behaves like AssembledContext."""
    ctx = MagicMock()
    ctx.source_path = "src/routes/dashboard.ts"
    ctx.source_code = "export function handler(req, res) { res.json({ok: true}); }"
    ctx.language = "typescript"
    ctx.parse_result.imports = []
    ctx.function_signatures = []
    ctx.class_signatures = []
    ctx.related_files = []
    ctx.test_patterns = None

    if route_info is not None:
        ctx.route_info = route_info
    else:
        del ctx.route_info

    if auth_config is not None:
        ctx.auth_config = auth_config
    else:
        del ctx.auth_config

    return ctx


# ── CypressTemplate Tests ───────────────────────────────────────


def test_cypress_template_name() -> None:
    assert CypressTemplate().name == "cypress_e2e"


def test_cypress_system_instruction_mentions_cypress() -> None:
    tmpl = CypressTemplate()
    ctx = _make_mock_context()
    system = tmpl._system_instruction(ctx)
    assert "cypress" in system.lower()
    assert "e2e" in system.lower()


def test_build_sections_includes_framework_instructions() -> None:
    tmpl = CypressTemplate()
    ctx = _make_mock_context()
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Framework Instructions" in labels


def test_build_sections_includes_example() -> None:
    tmpl = CypressTemplate()
    ctx = _make_mock_context()
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Cypress Example" in labels

    example = next(s for s in sections if s.label == "Cypress Example")
    assert "cy.visit" in example.content


def test_build_sections_includes_source_file() -> None:
    tmpl = CypressTemplate()
    ctx = _make_mock_context()
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Source File" in labels


def test_build_sections_includes_requirements() -> None:
    tmpl = CypressTemplate()
    ctx = _make_mock_context()
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Requirements" in labels


def test_build_sections_includes_dependencies() -> None:
    tmpl = CypressTemplate()
    ctx = _make_mock_context()
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Dependencies" in labels


def test_build_sections_skips_route_info_when_absent() -> None:
    tmpl = CypressTemplate()
    ctx = _make_mock_context(route_info=None)
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Route Information" not in labels


def test_build_sections_includes_route_info_when_present() -> None:
    tmpl = CypressTemplate()
    route_info = MagicMock()
    route_info.path = "/dashboard"
    route_info.methods = [MagicMock(value="GET")]
    route_info.route_type = MagicMock(value="page")
    route_info.params = []
    route_info.auth_required = False
    route_info.middleware = []
    ctx = _make_mock_context(route_info=route_info)
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Route Information" in labels


def test_build_sections_skips_auth_when_absent() -> None:
    tmpl = CypressTemplate()
    ctx = _make_mock_context(auth_config=None)
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Authentication" not in labels


def test_build_sections_includes_auth_when_present() -> None:
    tmpl = CypressTemplate()
    auth_config = MagicMock()
    auth_config.strategy = "form"
    auth_config.login_url = "/login"
    ctx = _make_mock_context(auth_config=auth_config)
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Authentication" in labels


# ── _format_route_section Tests ─────────────────────────────────


def test_format_route_section_with_full_route_info() -> None:
    ctx = MagicMock()
    route_info = MagicMock()
    route_info.path = "/api/users/:id"
    route_info.methods = [MagicMock(value="GET"), MagicMock(value="POST")]
    route_info.route_type = MagicMock(value="api")
    route_info.params = ["id"]
    route_info.auth_required = True
    route_info.middleware = ["auth", "rateLimit"]
    ctx.route_info = route_info

    section = _format_route_section(ctx)
    assert section.label == "Route Information"
    assert "/api/users/:id" in section.content
    assert "GET" in section.content
    assert "POST" in section.content
    assert "id" in section.content
    assert "Authentication required" in section.content
    assert "auth" in section.content
    assert "rateLimit" in section.content


def test_format_route_section_without_route_info() -> None:
    ctx = MagicMock()
    ctx.route_info = None

    section = _format_route_section(ctx)
    assert "No route info available" in section.content


def test_format_route_section_minimal() -> None:
    ctx = MagicMock()
    route_info = MagicMock()
    route_info.path = "/home"
    route_info.methods = [MagicMock(value="GET")]
    route_info.route_type = MagicMock(value="page")
    route_info.params = []
    route_info.auth_required = False
    route_info.middleware = []
    ctx.route_info = route_info

    section = _format_route_section(ctx)
    assert "/home" in section.content
    assert "Dynamic parameters" not in section.content
    assert "Authentication required" not in section.content
    assert "Middleware" not in section.content


# ── _format_auth_section Tests ──────────────────────────────────


def test_format_auth_section_form_strategy() -> None:
    ctx = MagicMock()
    auth_config = MagicMock()
    auth_config.strategy = "form"
    auth_config.login_url = "/auth/login"
    ctx.auth_config = auth_config

    section = _format_auth_section(ctx)
    assert section.label == "Authentication"
    assert "Form-based" in section.content
    assert "/auth/login" in section.content
    assert "environment variables" in section.content


def test_format_auth_section_token_strategy() -> None:
    ctx = MagicMock()
    auth_config = MagicMock()
    auth_config.strategy = "token"
    auth_config.login_url = ""
    ctx.auth_config = auth_config

    section = _format_auth_section(ctx)
    assert "Token-based" in section.content


def test_format_auth_section_oauth_strategy() -> None:
    ctx = MagicMock()
    auth_config = MagicMock()
    auth_config.strategy = "oauth"
    auth_config.login_url = ""
    ctx.auth_config = auth_config

    section = _format_auth_section(ctx)
    assert "OAuth" in section.content


def test_format_auth_section_cookie_strategy() -> None:
    ctx = MagicMock()
    auth_config = MagicMock()
    auth_config.strategy = "cookie"
    auth_config.login_url = ""
    ctx.auth_config = auth_config

    section = _format_auth_section(ctx)
    assert "Cookie-based" in section.content


def test_format_auth_section_custom_strategy() -> None:
    ctx = MagicMock()
    auth_config = MagicMock()
    auth_config.strategy = "custom"
    auth_config.login_url = ""
    ctx.auth_config = auth_config

    section = _format_auth_section(ctx)
    assert "Custom" in section.content


def test_format_auth_section_without_auth_config() -> None:
    ctx = MagicMock()
    ctx.auth_config = None

    section = _format_auth_section(ctx)
    assert "No auth config available" in section.content


def test_format_auth_section_unknown_strategy() -> None:
    ctx = MagicMock()
    auth_config = MagicMock()
    auth_config.strategy = "saml"
    auth_config.login_url = ""
    ctx.auth_config = auth_config

    section = _format_auth_section(ctx)
    assert "saml" in section.content


# ── _build_requirements Tests ───────────────────────────────────


def test_build_requirements_basic() -> None:
    ctx = MagicMock()
    del ctx.route_info

    requirements = _build_requirements(ctx)
    assert "Cypress E2E test" in requirements
    assert "Happy path" in requirements
    assert "Error cases" in requirements


def test_build_requirements_with_auth_required() -> None:
    ctx = MagicMock()
    route_info = MagicMock()
    route_info.auth_required = True
    route_info.params = []
    ctx.route_info = route_info

    requirements = _build_requirements(ctx)
    assert "authentication setup" in requirements.lower()


def test_build_requirements_with_route_params() -> None:
    ctx = MagicMock()
    route_info = MagicMock()
    route_info.auth_required = False
    route_info.params = ["userId", "projectId"]
    ctx.route_info = route_info

    requirements = _build_requirements(ctx)
    assert "userId" in requirements
    assert "projectId" in requirements
