"""Tests for E2E test prompt template (src/nit/llm/prompts/e2e_test.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

from nit.llm.prompts.e2e_test import (
    E2ETestTemplate,
    _build_requirements,
    _format_auth_section,
    _format_route_section,
)

# ── Helper to build a minimal mock AssembledContext ──────────────


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

    # Conditionally set route_info / auth_config
    if route_info is not None:
        ctx.route_info = route_info
    else:
        # Simulate attribute missing
        del ctx.route_info

    if auth_config is not None:
        ctx.auth_config = auth_config
    else:
        del ctx.auth_config

    return ctx


# ── E2ETestTemplate Tests ────────────────────────────────────────


def test_e2e_test_template_name() -> None:
    """Test E2ETestTemplate template name."""
    tmpl = E2ETestTemplate()
    assert tmpl.name == "e2e_test"


def test_e2e_system_instruction_mentions_playwright() -> None:
    """Test system instruction mentions Playwright."""
    tmpl = E2ETestTemplate()
    ctx = _make_mock_context()
    system = tmpl._system_instruction(ctx)
    assert "playwright" in system.lower()
    assert "e2e" in system.lower()


def test_build_sections_includes_framework_instructions() -> None:
    """Test that sections include framework instructions."""
    tmpl = E2ETestTemplate()
    ctx = _make_mock_context()
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Framework Instructions" in labels


def test_build_sections_includes_example_test() -> None:
    """Test that sections include an example test."""
    tmpl = E2ETestTemplate()
    ctx = _make_mock_context()
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Example Test" in labels

    example = next(s for s in sections if s.label == "Example Test")
    assert "playwright" in example.content.lower()


def test_build_sections_includes_source_file() -> None:
    """Test that sections include source file information."""
    tmpl = E2ETestTemplate()
    ctx = _make_mock_context()
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Source File" in labels


def test_build_sections_includes_requirements() -> None:
    """Test that sections include requirements."""
    tmpl = E2ETestTemplate()
    ctx = _make_mock_context()
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Requirements" in labels


def test_build_sections_includes_dependencies() -> None:
    """Test that sections include dependencies."""
    tmpl = E2ETestTemplate()
    ctx = _make_mock_context()
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Dependencies" in labels


def test_build_sections_skips_route_info_when_not_present() -> None:
    """Test that route info section is skipped when not available."""
    tmpl = E2ETestTemplate()
    ctx = _make_mock_context(route_info=None)
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Route Information" not in labels


def test_build_sections_includes_route_info_when_present() -> None:
    """Test that route info section is included when available."""
    tmpl = E2ETestTemplate()
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


def test_build_sections_skips_auth_when_not_present() -> None:
    """Test that auth section is skipped when not available."""
    tmpl = E2ETestTemplate()
    ctx = _make_mock_context(auth_config=None)
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Authentication" not in labels


def test_build_sections_includes_auth_when_present() -> None:
    """Test that auth section is included when available."""
    tmpl = E2ETestTemplate()
    auth_config = MagicMock()
    auth_config.strategy = "form"
    auth_config.login_url = "/login"
    ctx = _make_mock_context(auth_config=auth_config)
    sections = tmpl._build_sections(ctx)
    labels = [s.label for s in sections]
    assert "Authentication" in labels


# ── _format_route_section Tests ──────────────────────────────────


def test_format_route_section_with_route_info() -> None:
    """Test _format_route_section with valid route info."""
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
    """Test _format_route_section when route_info is None."""
    ctx = MagicMock()
    ctx.route_info = None

    section = _format_route_section(ctx)
    assert section.label == "Route Information"
    assert "No route info available" in section.content


def test_format_route_section_minimal_route_info() -> None:
    """Test _format_route_section with minimal route info (no params, no auth)."""
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


# ── _format_auth_section Tests ───────────────────────────────────


def test_format_auth_section_form_strategy() -> None:
    """Test _format_auth_section with form-based auth."""
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
    """Test _format_auth_section with token-based auth."""
    ctx = MagicMock()
    auth_config = MagicMock()
    auth_config.strategy = "token"
    auth_config.login_url = ""
    ctx.auth_config = auth_config

    section = _format_auth_section(ctx)
    assert "Token-based" in section.content


def test_format_auth_section_without_auth_config() -> None:
    """Test _format_auth_section when auth_config is None."""
    ctx = MagicMock()
    ctx.auth_config = None

    section = _format_auth_section(ctx)
    assert "No auth config available" in section.content


def test_format_auth_section_unknown_strategy() -> None:
    """Test _format_auth_section with unknown strategy falls back to raw value."""
    ctx = MagicMock()
    auth_config = MagicMock()
    auth_config.strategy = "saml"
    auth_config.login_url = ""
    ctx.auth_config = auth_config

    section = _format_auth_section(ctx)
    assert "saml" in section.content


# ── _build_requirements Tests ────────────────────────────────────


def test_build_requirements_basic() -> None:
    """Test _build_requirements returns basic requirements."""
    ctx = MagicMock()
    del ctx.route_info  # No route info

    requirements = _build_requirements(ctx)
    assert "Playwright E2E test" in requirements
    assert "Happy path" in requirements
    assert "Error cases" in requirements


def test_build_requirements_with_auth_required() -> None:
    """Test _build_requirements adds auth setup when route requires auth."""
    ctx = MagicMock()
    route_info = MagicMock()
    route_info.auth_required = True
    route_info.params = []
    ctx.route_info = route_info

    requirements = _build_requirements(ctx)
    assert "authentication setup" in requirements.lower()


def test_build_requirements_with_route_params() -> None:
    """Test _build_requirements adds param testing when route has params."""
    ctx = MagicMock()
    route_info = MagicMock()
    route_info.auth_required = False
    route_info.params = ["userId", "projectId"]
    ctx.route_info = route_info

    requirements = _build_requirements(ctx)
    assert "userId" in requirements
    assert "projectId" in requirements
