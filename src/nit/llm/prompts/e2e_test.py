"""E2E test prompt template for Playwright.

Generates end-to-end tests using Playwright with best practices:
- Page object pattern for reusability
- Proper await/waitFor usage for stability
- data-testid selectors for reliability
- Authentication setup when needed
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

_E2E_SYSTEM_INSTRUCTION = """\
You are an expert E2E test engineer specializing in Playwright for TypeScript/JavaScript.

Your task is to generate robust, maintainable end-to-end tests that verify \
user workflows and critical paths through the application.

Key principles:
1. **Stability**: Use proper wait strategies (waitForSelector, waitForURL, waitForLoadState) \
to handle async operations reliably.
2. **Maintainability**: Use data-testid attributes for selectors when available; \
fall back to accessible selectors (getByRole, getByLabel, getByText).
3. **Readability**: Write clear test descriptions that explain what user action is being tested.
4. **Isolation**: Each test should be independent and not rely on state from other tests.
5. **Coverage**: Test happy paths, error cases, and edge cases.

Output only the test code in a single TypeScript file. \
Do NOT include explanations or markdown formatting.
"""

_E2E_INSTRUCTIONS = """\
Framework: Playwright (TypeScript / JavaScript)

Playwright-specific rules:
- Use `import { test, expect } from '@playwright/test';` at the top.
- Structure tests with `test()` blocks. Use `test.describe()` for grouping related tests.
- Use `test.beforeEach()` for setup that applies to multiple tests.
- For navigation: `await page.goto('https://...')` or `await page.goto('/relative-path')`
- For waiting: `await page.waitForSelector('[data-testid="..."]')`, \
`await page.waitForURL('**/dashboard')`
- For finding elements: Prefer `page.getByRole()`, `page.getByLabel()`, `page.getByTestId()` \
over plain selectors when possible.
- For assertions: Use `expect(page).toHaveURL()`, `expect(page.locator('...')).toBeVisible()`, \
`expect(page.locator('...')).toHaveText('...')`
- For interactions: `await page.click()`, `await page.fill()`, `await page.selectOption()`, etc.
- Always use `await` for async operations.
- Use `page.locator()` for complex queries: `page.locator('[data-testid="submit-btn"]')`
- For multiple matching elements: `page.locator('...').nth(0)` or `page.locator('...').first()`

Authentication best practices:
- If the route requires authentication, include login/auth setup in `test.beforeEach()`.
- Use `page.context().storageState()` to save authentication state for reuse.
- Store credentials in environment variables or config, never hardcode.

Page object pattern (optional but recommended for complex flows):
- Extract common page interactions into helper functions or classes.
- Example: `async function loginAs(page, username, password) { ... }`
"""

_E2E_EXAMPLE = """\
import { test, expect } from '@playwright/test';

test.describe('User Authentication', () => {
  test('should login successfully with valid credentials', async ({ page }) => {
    await page.goto('/login');

    // Fill login form
    await page.fill('[data-testid="username"]', 'testuser@example.com');
    await page.fill('[data-testid="password"]', 'password123');

    // Submit form
    await page.click('[data-testid="login-button"]');

    // Wait for navigation and verify success
    await page.waitForURL('**/dashboard');
    await expect(page.locator('[data-testid="user-menu"]')).toBeVisible();
    await expect(page.locator('[data-testid="welcome-message"]')).toContainText('Welcome');
  });

  test('should show error message with invalid credentials', async ({ page }) => {
    await page.goto('/login');

    await page.fill('[data-testid="username"]', 'invalid@example.com');
    await page.fill('[data-testid="password"]', 'wrongpassword');
    await page.click('[data-testid="login-button"]');

    // Verify error message appears
    await expect(page.locator('[data-testid="error-message"]')).toBeVisible();
    const errorMsg = page.locator('[data-testid="error-message"]');
    await expect(errorMsg).toContainText('Invalid credentials');

    // Verify we're still on login page
    await expect(page).toHaveURL(/.*login/);
  });
});

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    // Login before each test in this group
    await page.goto('/login');
    await page.fill('[data-testid="username"]', 'testuser@example.com');
    await page.fill('[data-testid="password"]', 'password123');
    await page.click('[data-testid="login-button"]');
    await page.waitForURL('**/dashboard');
  });

  test('should display user statistics', async ({ page }) => {
    // Verify dashboard elements are visible
    await expect(page.locator('[data-testid="stats-widget"]')).toBeVisible();
    await expect(page.locator('[data-testid="total-users"]')).toBeVisible();

    // Verify stats have numeric values
    const totalUsers = await page.locator('[data-testid="total-users"]').textContent();
    expect(totalUsers).toMatch(/\\d+/);
  });

  test('should navigate to settings page', async ({ page }) => {
    await page.click('[data-testid="settings-link"]');
    await page.waitForURL('**/settings');

    await expect(page.locator('h1')).toContainText('Settings');
  });
});
"""


class E2ETestTemplate(PromptTemplate):
    """E2E test generation prompt template for Playwright."""

    @property
    def name(self) -> str:
        return "e2e_test"

    def _system_instruction(self, context: AssembledContext) -> str:  # noqa: ARG002
        """Return the system-level instruction for E2E test generation."""
        return _E2E_SYSTEM_INSTRUCTION

    def _build_sections(self, context: AssembledContext) -> list[PromptSection]:
        """Build prompt sections for E2E test generation.

        Includes:
        - Framework instructions
        - Example test
        - Source file information (route handler, component, etc.)
        - Route information (if available)
        - Authentication requirements
        - Dependencies
        """
        sections = [
            PromptSection(
                label="Framework Instructions",
                content=_E2E_INSTRUCTIONS,
            ),
            PromptSection(
                label="Example Test",
                content=f"```typescript\n{_E2E_EXAMPLE}\n```",
            ),
        ]

        # Add source file information
        sections.append(format_source_section(context))

        # Add route information if available
        if hasattr(context, "route_info") and context.route_info:
            sections.append(_format_route_section(context))

        # Add authentication information if available
        if hasattr(context, "auth_config") and context.auth_config:
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
        content_parts.append("⚠️  Authentication required for this route")

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
        "Generate a complete Playwright E2E test file for the provided route/component.",
        "Include test cases for:",
        "  - Happy path (successful user flow)",
        "  - Error cases (invalid input, network errors)",
        "  - Edge cases (boundary conditions, empty states)",
        "Use stable selectors (data-testid preferred, then accessible selectors).",
        "Include proper wait strategies to handle async operations.",
        "Add comments explaining complex interactions or business logic.",
    ]

    # Add route-specific requirements
    route_info = getattr(context, "route_info", None)
    if route_info:
        if route_info.auth_required:
            requirements.append("Include authentication setup in beforeEach hook.")
        if route_info.params:
            requirements.append(
                f"Test with various parameter values: {', '.join(route_info.params)}"
            )

    return "\n".join(requirements)
