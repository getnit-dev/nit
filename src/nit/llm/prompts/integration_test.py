"""Integration test generation prompt template.

Produces a structured prompt for generating integration tests that cover
interactions with external services (databases, HTTP APIs, filesystems, message queues).
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
You are an expert software engineer specializing in writing high-quality \
integration tests.  Your task is to generate comprehensive integration tests \
for code that interacts with external services like databases, HTTP APIs, \
file systems, and message queues.

Follow these guidelines:
- Test the integration points between your code and external services.
- Use appropriate mocking strategies to isolate external dependencies.
- Create realistic test data and fixtures based on actual schemas/types.
- Test both success paths and error scenarios (network failures, timeouts, etc.).
- Verify that data flows correctly through the integration boundary.
- Use descriptive test names that explain what integration is being verified.
- Keep tests focused on the integration logic, not business logic.
- Match the existing project test conventions when available.
- Include proper setup and teardown for integration resources.
- Output valid, runnable code with no placeholders or TODOs.\
"""


class IntegrationTestTemplate(PromptTemplate):
    """Language-agnostic integration test generation template.

    Renders a prompt with structured sections for source, dependencies,
    integration points, mocking strategies, and fixture recommendations.
    Subclasses can override ``_framework_instructions`` to inject
    framework-specific guidance.
    """

    @property
    def name(self) -> str:
        return "integration_test"

    def _system_instruction(self, context: AssembledContext) -> str:
        extra = self._framework_instructions(context)
        if extra:
            return f"{_SYSTEM_INSTRUCTION}\n\n{extra}"
        return _SYSTEM_INSTRUCTION

    def _build_sections(self, context: AssembledContext) -> list[PromptSection]:
        sections = [
            format_source_section(context),
            format_signatures_section(context),
            self._integration_points_section(context),
            self._mocking_strategy_section(context),
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

    # ── Integration-specific sections ────────────────────────────────

    def _integration_points_section(self, _context: AssembledContext) -> PromptSection:
        """Build section describing integration testing focus.

        Note: Integration dependency information is added separately by the
        IntegrationBuilder agent as an additional message.
        """
        return PromptSection(
            label="Integration Testing",
            content=(
                "Generate integration tests that verify interactions with external services. "
                "Use appropriate mocking strategies for each dependency type."
            ),
        )

    def _mocking_strategy_section(self, _context: AssembledContext) -> PromptSection:
        """Build section with general mocking guidance.

        Note: Specific mocking strategies are provided by the IntegrationBuilder agent.
        """
        return PromptSection(
            label="Mocking Guidance",
            content=(
                "Use framework-appropriate mocking for external dependencies:\n"
                "- Database: Mock connections and queries\n"
                "- HTTP: Mock API responses and network calls\n"
                "- Filesystem: Use temporary directories or mock file operations\n"
                "- Message queues: Mock producers/consumers"
            ),
        )

    # ── Extension points for framework subclasses ─────────────────

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
                "Generate a complete integration test file for the source code above.\n"
                f"Write the tests in {context.language}.\n"
                "Include all necessary imports, setup/teardown, mocks, and test data.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )


# ── Framework-specific integration test templates ────────────────


class PytestIntegrationTemplate(IntegrationTestTemplate):
    """pytest-specific integration test template."""

    @property
    def name(self) -> str:
        return "pytest_integration"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use pytest conventions:
- Use function-based tests (`def test_...`).
- Use pytest fixtures for setup/teardown (`@pytest.fixture`).
- Use `unittest.mock` or `pytest-mock` for mocking dependencies.
- Use `responses` library for HTTP mocking.
- Use `tmp_path` fixture for filesystem tests.
- Use `assert` statements for assertions.
- Group related tests with descriptive function names."""


class VitestIntegrationTemplate(IntegrationTestTemplate):
    """Vitest-specific integration test template."""

    @property
    def name(self) -> str:
        return "vitest_integration"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use Vitest conventions:
- Use `describe()` and `it()` blocks.
- Use `vi.mock()` for module mocking.
- Use MSW (Mock Service Worker) for HTTP API mocking.
- Use `beforeEach()` / `afterEach()` for setup/teardown.
- Use `expect()` assertions from Vitest.
- Import from 'vitest' and '@testing-library' where appropriate."""


class JestIntegrationTemplate(IntegrationTestTemplate):
    """Jest-specific integration test template."""

    @property
    def name(self) -> str:
        return "jest_integration"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use Jest conventions:
- Use `describe()` and `it()` or `test()` blocks.
- Use `jest.mock()` for module mocking.
- Use `nock` or MSW for HTTP API mocking.
- Use `beforeEach()` / `afterEach()` for setup/teardown.
- Use `expect()` assertions from Jest.
- Use `jest.fn()` for mock functions."""
