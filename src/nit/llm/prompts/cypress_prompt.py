"""Cypress-specific prompt template for E2E tests.

Extends the generic E2E test template with Cypress conventions:
``cy.visit()``, ``cy.get()``, ``cy.contains()``, ``cy.intercept()``,
and Cypress-specific assertion chains.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import (
    PromptSection,
    PromptTemplate,
    format_dependencies_section,
    format_source_section,
)

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_CYPRESS_SYSTEM_INSTRUCTION = """\
You are an expert E2E test engineer specializing in Cypress for TypeScript/JavaScript.

Your task is to generate robust, maintainable end-to-end tests that verify \
user workflows and critical paths through the application.

Key principles:
1. **Stability**: Use proper assertions and retry-ability built into Cypress commands.
2. **Maintainability**: Use data-testid or data-cy attributes for selectors when available; \
fall back to accessible selectors.
3. **Readability**: Write clear test descriptions that explain what user action is being tested.
4. **Isolation**: Each test should be independent and not rely on state from other tests.
5. **Coverage**: Test happy paths, error cases, and edge cases.

Output only the test code in a single file. \
Do NOT include explanations or markdown formatting.
"""

_CYPRESS_INSTRUCTIONS = """\
Framework: Cypress (TypeScript / JavaScript)

Cypress-specific rules:
- Structure tests with ``describe()`` blocks and ``it()`` blocks.
- Use ``cy.visit('/path')`` for navigation.
- Use ``cy.get('[data-cy="..."]')`` or ``cy.get('[data-testid="..."]')`` for element selection.
- Use ``cy.contains('text')`` to find elements by text content.
- Chain assertions with ``.should('be.visible')``, ``.should('have.text', '...')``, \
``.should('exist')``, ``.should('not.exist')``, etc.
- Use ``cy.intercept()`` to stub or spy on network requests.
- Use ``cy.wait('@alias')`` to wait for intercepted requests.
- Use ``beforeEach()`` for shared setup (navigation, auth).
- Use ``cy.fixture('file.json')`` for test data.
- For form interactions: ``cy.get('input').type('text')``, \
``cy.get('select').select('option')``, ``cy.get('button').click()``.
- Never use ``cy.wait(ms)`` for arbitrary delays — use assertions or intercepts instead.
- Use ``cy.url().should('include', '/path')`` for URL assertions.
- Use ``cy.request()`` for API-level setup/teardown.

Authentication best practices:
- Use ``cy.session()`` for caching login state across tests.
- Use ``cy.request()`` for programmatic login (faster than UI login).
- Store credentials in ``cypress.env.json`` or environment variables.
"""

_CYPRESS_EXAMPLE = """\
describe('User Authentication', () => {
  it('should login successfully with valid credentials', () => {
    cy.visit('/login');

    // Fill login form
    cy.get('[data-cy="username"]').type('testuser@example.com');
    cy.get('[data-cy="password"]').type('password123');

    // Submit form
    cy.get('[data-cy="login-button"]').click();

    // Verify navigation and success
    cy.url().should('include', '/dashboard');
    cy.get('[data-cy="user-menu"]').should('be.visible');
    cy.get('[data-cy="welcome-message"]').should('contain', 'Welcome');
  });

  it('should show error message with invalid credentials', () => {
    cy.visit('/login');

    cy.get('[data-cy="username"]').type('invalid@example.com');
    cy.get('[data-cy="password"]').type('wrongpassword');
    cy.get('[data-cy="login-button"]').click();

    // Verify error message appears
    cy.get('[data-cy="error-message"]')
      .should('be.visible')
      .and('contain', 'Invalid credentials');

    // Verify still on login page
    cy.url().should('include', '/login');
  });
});

describe('Dashboard', () => {
  beforeEach(() => {
    // Programmatic login for speed
    cy.request('POST', '/api/login', {
      username: 'testuser@example.com',
      password: 'password123',
    });
    cy.visit('/dashboard');
  });

  it('should display user statistics', () => {
    cy.get('[data-cy="stats-widget"]').should('be.visible');
    cy.get('[data-cy="total-users"]')
      .should('be.visible')
      .invoke('text')
      .should('match', /\\d+/);
  });

  it('should navigate to settings page', () => {
    cy.get('[data-cy="settings-link"]').click();
    cy.url().should('include', '/settings');
    cy.get('h1').should('contain', 'Settings');
  });
});
"""


class CypressTemplate(PromptTemplate):
    """Cypress-specific E2E test prompt template."""

    @property
    def name(self) -> str:
        return "cypress_e2e"

    def _system_instruction(self, _context: AssembledContext) -> str:
        return _CYPRESS_SYSTEM_INSTRUCTION

    def _build_sections(self, context: AssembledContext) -> list[PromptSection]:
        """Build prompt sections for Cypress test generation."""
        sections = [
            PromptSection(
                label="Framework Instructions",
                content=_CYPRESS_INSTRUCTIONS,
            ),
            PromptSection(
                label="Cypress Example",
                content=f"```javascript\n{_CYPRESS_EXAMPLE}\n```",
            ),
        ]

        # Add source file information
        sections.append(format_source_section(context))

        # Add route information if available
        route_info = getattr(context, "route_info", None)
        if route_info:
            sections.append(_format_route_section(context))

        # Add auth information if available
        auth_config = getattr(context, "auth_config", None)
        if auth_config:
            sections.append(_format_auth_section(context))

        # Add dependencies
        sections.append(format_dependencies_section(context))

        # Add generation requirements
        sections.append(
            PromptSection(
                label="Requirements",
                content=_build_requirements(context),
            )
        )

        return sections


def _format_route_section(context: AssembledContext) -> PromptSection:
    """Format route information section."""
    route_info = getattr(context, "route_info", None)
    if not route_info:
        return PromptSection(label="Route Information", content="No route info available")

    content_parts = [
        f"Route path: {route_info.path}",
        f"HTTP methods: {', '.join(m.value for m in route_info.methods)}",
        f"Route type: {route_info.route_type.value}",
    ]

    if route_info.params:
        content_parts.append(f"Dynamic parameters: {', '.join(route_info.params)}")

    if route_info.auth_required:
        content_parts.append("Authentication required for this route")

    if route_info.middleware:
        content_parts.append(f"Middleware: {', '.join(route_info.middleware)}")

    return PromptSection(
        label="Route Information",
        content="\n".join(content_parts),
    )


def _format_auth_section(context: AssembledContext) -> PromptSection:
    """Format authentication configuration section."""
    auth_config = getattr(context, "auth_config", None)
    if not auth_config:
        return PromptSection(label="Authentication", content="No auth config available")

    strategy_info = {
        "form": "Form-based (username/password)",
        "token": "Token-based (Bearer token or API key)",
        "cookie": "Cookie-based session",
        "oauth": "OAuth (pre-authenticated token)",
        "custom": "Custom authentication script",
    }

    content_parts = [
        f"Strategy: {strategy_info.get(auth_config.strategy, auth_config.strategy)}",
    ]

    if auth_config.strategy == "form" and auth_config.login_url:
        content_parts.append(f"Login URL: {auth_config.login_url}")
        content_parts.append(
            "Note: Use environment variables for credentials in the generated test"
        )

    return PromptSection(
        label="Authentication",
        content="\n".join(content_parts),
    )


def _build_requirements(context: AssembledContext) -> str:
    """Build test generation requirements section."""
    requirements = [
        "Generate a complete Cypress E2E test file for the provided route/component.",
        "Include test cases for:",
        "  - Happy path (successful user flow)",
        "  - Error cases (invalid input, network errors)",
        "  - Edge cases (boundary conditions, empty states)",
        "Use stable selectors (data-cy or data-testid preferred).",
        "Use cy.intercept() for API stubbing when needed.",
        "Never use cy.wait(ms) — use assertions or intercept aliases instead.",
    ]

    route_info = getattr(context, "route_info", None)
    if route_info:
        if route_info.auth_required:
            requirements.append("Include authentication setup in beforeEach hook.")
        if route_info.params:
            requirements.append(
                f"Test with various parameter values: {', '.join(route_info.params)}"
            )

    return "\n".join(requirements)
