"""Accessibility test generation prompt template.

Produces a structured prompt for generating accessibility tests
using tools like axe-core, jest-axe, and Playwright.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import (
    PromptSection,
    PromptTemplate,
    format_dependencies_section,
    format_related_files_section,
    format_signatures_section,
    format_source_section,
    format_test_patterns_section,
)

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext


_SYSTEM_INSTRUCTION = """\
You are an expert software engineer specializing in web accessibility \
testing and WCAG compliance.  Your task is to generate comprehensive \
accessibility tests that verify pages and components meet WCAG 2.1 AA \
standards.

Follow these guidelines:
- Use axe-core for automated accessibility scanning where possible.
- Test keyboard navigation for all interactive elements.
- Verify ARIA attributes (roles, labels, states) are correct.
- Check focus management and tab order.
- Test color contrast ratios meet WCAG AA requirements.
- Verify form labels and error messages are accessible.
- Test screen reader compatibility using semantic HTML checks.
- Use descriptive test names that reference the accessibility criteria.
- Match the existing project test conventions when available.
- Output valid, runnable code with no placeholders or TODOs.\
"""


class AccessibilityTestTemplate(PromptTemplate):
    """Language-agnostic accessibility test generation template.

    Renders a prompt with structured sections for source code,
    accessibility testing patterns, WCAG criteria, and output format.
    Subclasses can override ``_framework_instructions`` to inject
    framework-specific guidance.
    """

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "accessibility_test"

    def _system_instruction(self, context: AssembledContext) -> str:
        """Return the system-level instruction text."""
        extra = self._framework_instructions(context)
        if extra:
            return f"{_SYSTEM_INSTRUCTION}\n\n{extra}"
        return _SYSTEM_INSTRUCTION

    def _build_sections(self, context: AssembledContext) -> list[PromptSection]:
        """Return ordered sections that form the user message body."""
        sections = [
            format_source_section(context),
            format_signatures_section(context),
            self._accessibility_testing_section(context),
            self._a11y_patterns_section(context),
            format_test_patterns_section(context),
            format_dependencies_section(context),
        ]
        related = format_related_files_section(context)
        if related.content != "None.":
            sections.append(related)

        extra = self._extra_sections(context)
        sections.extend(extra)

        sections.append(self._output_instructions(context))
        return sections

    # ── Accessibility-specific sections ──────────────────────────

    def _accessibility_testing_section(self, _context: AssembledContext) -> PromptSection:
        """Build section describing accessibility testing focus."""
        return PromptSection(
            label="Accessibility Testing",
            content=(
                "Generate accessibility tests that verify WCAG 2.1 AA compliance. "
                "Each test should check specific accessibility criteria including "
                "keyboard navigation, ARIA attributes, focus management, and color "
                "contrast. Use axe-core for automated scanning where applicable."
            ),
        )

    def _a11y_patterns_section(self, _context: AssembledContext) -> PromptSection:
        """Build section with accessibility testing patterns."""
        return PromptSection(
            label="Accessibility Testing Patterns",
            content=(
                "Use these accessibility testing patterns:\n"
                "- Automated axe-core scans: Run axe.run() on rendered pages/components "
                "and assert zero violations\n"
                "- Keyboard navigation: Tab through interactive elements, verify focus "
                "is visible and in logical order\n"
                "- ARIA labels: Check that all interactive elements have accessible names "
                "via aria-label, aria-labelledby, or associated <label>\n"
                "- Focus management: Verify focus moves correctly after route changes, "
                "modal opens/closes, and dynamic content updates\n"
                "- Color contrast: Use axe-core color-contrast rule or manual checks "
                "for text against backgrounds"
            ),
        )

    # ── Extension points for framework subclasses ────────────────

    def _framework_instructions(self, _context: AssembledContext) -> str:
        """Return additional system-level instructions for a specific framework.

        Override in subclasses to add framework-specific guidance.
        The default implementation returns an empty string.
        """
        return ""

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        """Return additional user-message sections for a specific framework.

        Override in subclasses to add framework-specific examples or rules.
        The default implementation returns an empty list.
        """
        return []

    def _output_instructions(self, context: AssembledContext) -> PromptSection:
        """Return instructions describing the expected output format."""
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete accessibility test file for the source code above.\n"
                f"Write the tests in {context.language}.\n"
                "Include all necessary imports, page setup, and assertions.\n"
                "Return ONLY the test code -- no explanations, no markdown fences."
            ),
        )


# ── Framework-specific accessibility test templates ──────────────


class PlaywrightAxeTemplate(AccessibilityTestTemplate):
    """Playwright + @axe-core/playwright accessibility test template."""

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "playwright_axe"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use Playwright with @axe-core/playwright conventions:
- Import `AxeBuilder` from `@axe-core/playwright`.
- Use `test` and `expect` from `@playwright/test`.
- Create an AxeBuilder instance with `new AxeBuilder({ page })`.
- Call `.analyze()` to run the accessibility scan.
- Assert `accessibilityScanResults.violations` is empty or filter by impact.
- Use `page.keyboard.press('Tab')` for keyboard navigation tests.
- Use `page.locator('[role="..."]')` for ARIA role checks.
- Use `page.evaluate()` to inspect focus state when needed."""


class JestAxeTemplate(AccessibilityTestTemplate):
    """jest-axe accessibility test template."""

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "jest_axe"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use jest-axe conventions for component-level accessibility testing:
- Import `axe` and `toHaveNoViolations` from `jest-axe`.
- Call `expect.extend(toHaveNoViolations)` in setup.
- Render components using React Testing Library or similar.
- Run `const results = await axe(container)` on the rendered container.
- Assert `expect(results).toHaveNoViolations()`.
- Use `screen.getByRole()` to verify ARIA roles are correct.
- Use `screen.getByLabelText()` to verify form labels.
- Test keyboard interactions with `fireEvent.keyDown()`."""
