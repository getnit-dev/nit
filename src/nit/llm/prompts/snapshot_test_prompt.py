"""Snapshot/approval test generation prompt template.

Produces a structured prompt for generating snapshot and approval tests
that verify output stability across code changes.
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
You are an expert software engineer specializing in snapshot and approval \
testing.  Your task is to generate comprehensive snapshot tests that verify \
output stability and detect unintended changes.

Follow these guidelines:
- Write snapshot tests that capture the full output of functions or components.
- Use inline snapshots where the output is small and stable.
- Use file-based snapshots for large or complex outputs.
- Test both default and edge-case inputs to maximize snapshot coverage.
- Group related snapshots in descriptive test blocks.
- Ensure snapshot names are unique and descriptive.
- Include tests that verify serialization and rendering logic.
- Match the existing project test conventions when available.
- Output valid, runnable code with no placeholders or TODOs.\
"""


class SnapshotTestTemplate(PromptTemplate):
    """Language-agnostic snapshot test generation template.

    Renders a prompt with structured sections for source code, snapshot
    testing patterns, and output format.  Subclasses can override
    ``_framework_instructions`` to inject framework-specific guidance.
    """

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "snapshot_test"

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
            self._snapshot_testing_section(context),
            self._snapshot_patterns_section(context),
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

    # ── Snapshot-specific sections ────────────────────────────────

    def _snapshot_testing_section(self, _context: AssembledContext) -> PromptSection:
        """Build section describing snapshot testing focus."""
        return PromptSection(
            label="Snapshot Testing",
            content=(
                "Generate snapshot tests that capture and verify the output of "
                "functions, components, or serialization logic. Each test should "
                "produce a deterministic snapshot that detects unintended changes."
            ),
        )

    def _snapshot_patterns_section(self, _context: AssembledContext) -> PromptSection:
        """Build section with snapshot-specific testing patterns."""
        return PromptSection(
            label="Snapshot Testing Patterns",
            content=(
                "Use these snapshot testing patterns:\n"
                "- Capture full output for complex objects or rendered components\n"
                "- Use inline snapshots for small, stable outputs\n"
                "- Test multiple input variations to cover edge cases\n"
                "- Ensure deterministic outputs (mock dates, random values, etc.)\n"
                "- Group related snapshots with descriptive test names\n"
                "- Avoid snapshotting volatile data (timestamps, random IDs)"
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
                "Generate a complete snapshot test file for the source code above.\n"
                f"Write the tests in {context.language}.\n"
                "Include all necessary imports, snapshot configuration, and assertions.\n"
                "Return ONLY the test code -- no explanations, no markdown fences."
            ),
        )


# ── Framework-specific snapshot test templates ───────────────────


class JestSnapshotTemplate(SnapshotTestTemplate):
    """Jest snapshot test template."""

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "jest_snapshot"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use Jest snapshot testing conventions:
- Use `expect(value).toMatchSnapshot()` for file-based snapshots.
- Use `expect(value).toMatchInlineSnapshot()` for inline snapshots.
- Use `describe()` and `it()` blocks for test organization.
- Use `beforeEach()` for test setup and mock configuration.
- Mock non-deterministic values (Date.now, Math.random) before snapshotting.
- Use `expect.addSnapshotSerializer()` for custom serialization.
- Use `jest.spyOn()` to control side effects during snapshot capture."""


class PytestSyrupyTemplate(SnapshotTestTemplate):
    """pytest + syrupy snapshot test template."""

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "pytest_syrupy"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use pytest with syrupy conventions:
- Use function-based tests (`def test_...`).
- Accept the `snapshot` fixture as a parameter.
- Use `assert result == snapshot` for snapshot assertions.
- Use `@pytest.mark.parametrize` for testing multiple inputs.
- Use `snapshot.use_extension(...)` for custom serializers.
- Organize tests with descriptive function names.
- Use pytest fixtures for setup and teardown."""
