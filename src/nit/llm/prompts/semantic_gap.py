"""Semantic gap analysis prompt template for identifying missing test scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nit.llm.engine import LLMMessage
from nit.llm.prompts.base import PromptSection, PromptTemplate, RenderedPrompt

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext


@dataclass
class SemanticGapContext:
    """Context for semantic gap analysis prompts."""

    source_code: str
    """Source code to analyze for test gaps."""

    language: str
    """Programming language."""

    file_path: str
    """Path to the source file."""

    function_name: str
    """Name of the function being analyzed."""

    complexity: int
    """Cyclomatic complexity of the function."""

    coverage_percentage: float
    """Current code coverage percentage for this function."""

    existing_test_patterns: list[str] = field(default_factory=list)
    """List of test scenarios already covered."""

    related_tests: str = ""
    """Related test code (if available)."""

    ast_structure: str = ""
    """Control flow summary from AST analysis."""


class SemanticGapPrompt(PromptTemplate):
    """Prompt template for semantic test gap analysis."""

    @property
    def name(self) -> str:
        """Template name."""
        return "semantic_gap"

    def _system_instruction(self, _context: AssembledContext | SemanticGapContext) -> str:
        """System instruction for semantic gap analysis."""
        return """You are an expert test coverage analyst specializing in identifying \
semantic gaps in test suites.

Your task is to analyze source code and identify missing test scenarios that go beyond \
simple code coverage metrics. Focus on:

1. **Edge Cases**: Boundary conditions, empty inputs, maximum values, negative numbers
2. **Error Paths**: Exception handling, error conditions, validation failures
3. **Integration**: Dependencies, external systems, database interactions
4. **Behavioral**: Business logic branches, state transitions, workflow scenarios
5. **Concurrency**: Race conditions, thread safety, async operations (if applicable)
6. **Security**: Input validation, injection attacks, authorization checks

Provide specific, actionable test cases that would improve test quality beyond just \
increasing coverage percentages. Be concise and focus on high-value scenarios."""

    def _build_sections(
        self, context: AssembledContext | SemanticGapContext
    ) -> list[PromptSection]:
        """Build prompt sections for semantic gap analysis."""
        if isinstance(context, SemanticGapContext):
            return self._build_gap_sections(context)

        # Fallback for regular AssembledContext
        return [
            PromptSection(
                label="Analysis Request",
                content="Analyze the provided code for semantic test gaps.",
            )
        ]

    def _build_gap_sections(self, context: SemanticGapContext) -> list[PromptSection]:
        """Build sections specific to semantic gap analysis context."""
        sections = []

        # Function metadata
        metadata_content = f"""File: {context.file_path}
Function: {context.function_name}
Language: {context.language}
Complexity: {context.complexity}
Current Coverage: {context.coverage_percentage:.1f}%"""

        sections.append(
            PromptSection(
                label="Function Metadata",
                content=metadata_content,
            )
        )

        # Source code
        sections.append(
            PromptSection(
                label="Source Code",
                content=f"```{context.language}\n{context.source_code}\n```",
            )
        )

        # Control flow structure
        if context.ast_structure:
            sections.append(
                PromptSection(
                    label="Control Flow Summary",
                    content=context.ast_structure,
                )
            )

        # Existing test patterns
        if context.existing_test_patterns:
            patterns_content = "\n".join(f"- {p}" for p in context.existing_test_patterns)
            sections.append(
                PromptSection(
                    label="Already Tested Scenarios",
                    content=patterns_content,
                )
            )

        # Related test code
        if context.related_tests:
            sections.append(
                PromptSection(
                    label="Related Test Code",
                    content=f"```{context.language}\n{context.related_tests}\n```",
                )
            )

        return sections

    def render_gap_analysis(self, context: SemanticGapContext) -> RenderedPrompt:
        """Render a semantic gap analysis prompt.

        Args:
            context: Semantic gap context with function details.

        Returns:
            Rendered prompt for gap analysis.
        """
        system = self._system_instruction(context)
        sections = self._build_gap_sections(context)

        user_sections = "\n\n---\n\n".join(
            [f"## {s.label}\n\n{s.content}" for s in sections if s.content]
        )

        user_prompt = f"""{user_sections}

---

## Analysis Request

Identify semantic test gaps for this function. For each gap, provide:

**CATEGORY**: edge_case | error_path | integration | behavioral | concurrency | security

**SEVERITY**: high | medium | low

**DESCRIPTION**: Brief description of what's missing

**TEST_CASES**:
- Specific test scenario 1
- Specific test scenario 2
- ...

**CONFIDENCE**: 0.0-1.0 (how confident you are this is a real gap)

**REASONING**: Why this gap exists and why it matters

---

Separate multiple gaps with "---" delimiter. Focus on high-value gaps that would catch \
real bugs, not just increase coverage numbers."""

        return RenderedPrompt(
            messages=[
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=user_prompt),
            ]
        )
