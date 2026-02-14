"""Contract test (Pact) generation prompt template.

Produces a structured prompt for generating consumer-driven contract tests
using the Pact framework pattern.
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
You are an expert software engineer specializing in consumer-driven contract \
testing with Pact.  Your task is to generate comprehensive contract tests that \
verify interactions between consumer and provider services.

Follow these guidelines:
- Write consumer tests that set up expected interactions and verify the consumer \
  sends the correct requests.
- Write provider verification tests that replay recorded interactions against \
  the real provider.
- Use Pact matchers (like, eachLike, term) for flexible response matching.
- Test both success and error scenarios for each interaction.
- Include provider state setup for each interaction.
- Verify request method, path, headers, and body.
- Verify response status, headers, and body schema.
- Use descriptive test names that reference the interaction being tested.
- Match the existing project test conventions when available.
- Output valid, runnable code with no placeholders or TODOs.\
"""


class ContractTestTemplate(PromptTemplate):
    """Language-agnostic contract test generation template.

    Renders a prompt with structured sections for source code, contract
    interactions, consumer/provider testing patterns, and output format.
    Subclasses can override ``_framework_instructions`` to inject
    framework-specific guidance.
    """

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "contract_test"

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
            self._contract_testing_section(context),
            self._pact_patterns_section(context),
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

    # ── Contract-specific sections ───────────────────────────────

    def _contract_testing_section(self, _context: AssembledContext) -> PromptSection:
        """Build section describing contract testing focus."""
        return PromptSection(
            label="Contract Testing",
            content=(
                "Generate contract tests that verify consumer-provider interactions. "
                "Each test should set up expected interactions, exercise the consumer "
                "code, and verify the requests match the contract."
            ),
        )

    def _pact_patterns_section(self, _context: AssembledContext) -> PromptSection:
        """Build section with Pact-specific testing patterns."""
        return PromptSection(
            label="Pact Testing Patterns",
            content=(
                "Use these Pact contract testing patterns:\n"
                "- Consumer tests: Set up mock provider, define expected interactions, "
                "call consumer code, verify interactions\n"
                "- Provider tests: Load pact files, set up provider states, verify "
                "all interactions against the real provider\n"
                "- Use Pact matchers for flexible body matching\n"
                "- Define provider states that set up required test data\n"
                "- Test both happy paths and error scenarios"
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
                "Generate a complete contract test file for the source code above.\n"
                f"Write the tests in {context.language}.\n"
                "Include all necessary imports, provider state setup, and assertions.\n"
                "Return ONLY the test code -- no explanations, no markdown fences."
            ),
        )


# ── Framework-specific contract test templates ───────────────────


class PytestPactTemplate(ContractTestTemplate):
    """pytest + pact-python contract test template."""

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "pytest_pact"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use pytest with pact-python conventions:
- Use function-based tests (`def test_...`).
- Use pytest fixtures for Pact setup (`@pytest.fixture`).
- Set up the Pact mock service in a fixture.
- Use `pact.given(...).upon_receiving(...).with_request(...).will_respond_with(...)`.
- Verify interactions with `pact.verify()`.
- Use `assert` statements for additional assertions."""


class JestPactTemplate(ContractTestTemplate):
    """Jest + @pact-foundation/pact contract test template."""

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "jest_pact"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use Jest with @pact-foundation/pact conventions:
- Use `describe()` and `it()` blocks.
- Set up `PactV3` or `Pact` provider in `beforeAll()`.
- Use `provider.addInteraction()` to define expected interactions.
- Use `provider.executeTest()` to run the consumer code.
- Verify interactions in `afterEach()` or `afterAll()`.
- Use `expect()` assertions from Jest.
- Use Pact matchers from `@pact-foundation/pact`."""


class VitestPactTemplate(ContractTestTemplate):
    """Vitest + @pact-foundation/pact contract test template."""

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "vitest_pact"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use Vitest with @pact-foundation/pact conventions:
- Use `describe()` and `it()` blocks.
- Set up `PactV3` or `Pact` provider in `beforeAll()`.
- Use `provider.addInteraction()` to define expected interactions.
- Use `provider.executeTest()` to run the consumer code.
- Use `expect()` assertions from Vitest.
- Import Pact matchers from `@pact-foundation/pact`."""
