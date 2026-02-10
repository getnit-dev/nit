"""Base prompt template system with variable substitution and framework overrides."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nit.llm.engine import LLMMessage

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext


@dataclass
class PromptSection:
    """A labelled block of content within a rendered prompt."""

    label: str
    content: str


@dataclass
class RenderedPrompt:
    """The final output of a prompt template — a list of LLM messages."""

    messages: list[LLMMessage] = field(default_factory=list)

    @property
    def system_message(self) -> str:
        """Return the first system message content, or empty string."""
        for msg in self.messages:
            if msg.role == "system":
                return msg.content
        return ""

    @property
    def user_message(self) -> str:
        """Return the first user message content, or empty string."""
        for msg in self.messages:
            if msg.role == "user":
                return msg.content
        return ""


class PromptTemplate(ABC):
    """Abstract base class for prompt templates.

    Subclasses implement ``_system_instruction`` and ``_build_sections``
    to define the prompt structure.  The base class handles variable
    substitution and rendering into ``RenderedPrompt``.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable template identifier (e.g. 'unit_test', 'vitest')."""

    @abstractmethod
    def _system_instruction(self, context: AssembledContext) -> str:
        """Return the system-level instruction text."""

    @abstractmethod
    def _build_sections(self, context: AssembledContext) -> list[PromptSection]:
        """Return ordered sections that form the user message body."""

    def render(self, context: AssembledContext) -> RenderedPrompt:
        """Render the template into a list of LLM messages.

        Args:
            context: Assembled context for the source file under test.

        Returns:
            A ``RenderedPrompt`` containing system and user messages.
        """
        system = self._system_instruction(context)
        sections = self._build_sections(context)
        user_body = _join_sections(sections)

        return RenderedPrompt(
            messages=[
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=user_body),
            ]
        )


# ── Helpers ───────────────────────────────────────────────────────


def format_source_section(context: AssembledContext) -> PromptSection:
    """Build the source-code section from assembled context."""
    return PromptSection(
        label="Source File",
        content=(
            f"File: {context.source_path}\n"
            f"Language: {context.language}\n\n"
            f"```{context.language}\n{context.source_code}\n```"
        ),
    )


def format_signatures_section(context: AssembledContext) -> PromptSection:
    """Build the function/class signatures section."""
    lines = [f"- {sig}" for sig in context.function_signatures]
    lines.extend(f"- {sig}" for sig in context.class_signatures)
    return PromptSection(label="Signatures", content="\n".join(lines))


def format_test_patterns_section(context: AssembledContext) -> PromptSection:
    """Build the existing test-patterns section."""
    tp = context.test_patterns
    if tp is None:
        return PromptSection(label="Existing Test Patterns", content="No existing tests found.")

    lines = [
        f"Naming convention: {tp.naming_style}",
        f"Assertion style: {tp.assertion_style}",
    ]
    if tp.mocking_patterns:
        lines.append(f"Mocking: {', '.join(tp.mocking_patterns)}")
    if tp.imports:
        lines.append(f"Common imports: {', '.join(tp.imports[:10])}")
    if tp.sample_test:
        lines.append(f"\nExample test from the project:\n```\n{tp.sample_test}\n```")
    return PromptSection(label="Existing Test Patterns", content="\n".join(lines))


def format_dependencies_section(context: AssembledContext) -> PromptSection:
    """Build the imports/dependencies section."""
    imports = context.parse_result.imports
    if not imports:
        return PromptSection(label="Dependencies", content="No imports detected.")

    lines: list[str] = []
    for imp in imports:
        names = f" ({', '.join(imp.names)})" if imp.names else ""
        lines.append(f"- {imp.module}{names}")
    return PromptSection(label="Dependencies", content="\n".join(lines))


def format_related_files_section(context: AssembledContext) -> PromptSection:
    """Build the related-files section."""
    if not context.related_files:
        return PromptSection(label="Related Files", content="None.")

    parts: list[str] = []
    for rf in context.related_files:
        header = f"{rf.path} ({rf.relationship})"
        if rf.content_snippet:
            parts.append(f"{header}:\n```\n{rf.content_snippet}\n```")
        else:
            parts.append(header)
    return PromptSection(label="Related Files", content="\n\n".join(parts))


def _join_sections(sections: list[PromptSection]) -> str:
    """Join prompt sections into a single user-message string."""
    blocks = [f"## {s.label}\n\n{s.content}" for s in sections if s.content]
    return "\n\n---\n\n".join(blocks)
