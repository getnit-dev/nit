"""Generic unit test generation prompt template.

Produces a structured prompt with source code, existing test patterns,
framework conventions, and dependency information.  Framework-specific
subclasses (Vitest, pytest, …) extend this with tailored instructions.
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
unit tests.  Your task is to generate comprehensive unit tests for the \
provided source code.

Follow these guidelines:
- Test each public function and method individually.
- Cover normal cases, edge cases, and error paths.
- Use descriptive test names that explain the scenario being verified.
- Keep each test focused on a single behaviour.
- Do NOT test private/internal helpers unless they contain complex logic.
- Match the existing project test conventions when available.
- Include only the test code — do not repeat the source implementation.
- Output valid, runnable code with no placeholders or TODOs.\
"""


class UnitTestTemplate(PromptTemplate):
    """Language-agnostic unit test generation template.

    Renders a prompt with structured sections for source, signatures,
    existing patterns, dependencies, and related files.  Subclasses can
    override ``_framework_instructions`` to inject framework-specific
    guidance.
    """

    @property
    def name(self) -> str:
        return "unit_test"

    def _system_instruction(self, context: AssembledContext) -> str:
        extra = self._framework_instructions(context)
        if extra:
            return f"{_SYSTEM_INSTRUCTION}\n\n{extra}"
        return _SYSTEM_INSTRUCTION

    def _build_sections(self, context: AssembledContext) -> list[PromptSection]:
        sections = [
            format_source_section(context),
            format_signatures_section(context),
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
                "Generate a complete test file for the source code above.\n"
                f"Write the tests in {context.language}.\n"
                "Return ONLY the test code — no explanations, no markdown fences."
            ),
        )
