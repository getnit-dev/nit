"""Fix generation prompt template for generating code fixes for bugs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.llm.engine import LLMMessage
from nit.llm.prompts.base import PromptSection, PromptTemplate, RenderedPrompt

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext


@dataclass
class FixGenerationContext:
    """Context for fix generation prompts."""

    bug_type: str
    """Type of bug being fixed."""

    bug_description: str
    """Description of the bug."""

    root_cause: str
    """Root cause analysis."""

    source_code: str
    """Original source code with the bug."""

    missing_checks: list[str]
    """List of missing validation checks."""

    incorrect_assumptions: list[str]
    """List of incorrect assumptions."""

    language: str = "unknown"
    """Programming language."""

    file_path: str = ""
    """Path to the source file."""


class FixGenerationPrompt(PromptTemplate):
    """Prompt template for generating code fixes."""

    @property
    def name(self) -> str:
        """Template name."""
        return "fix_generation"

    def _system_instruction(self, _context: AssembledContext | FixGenerationContext) -> str:
        """System instruction for fix generation."""
        return (
            """You are an expert software engineer specializing in writing correct, """
            """minimal bug fixes.

Your task is to generate a code fix that:
1. Addresses the root cause, not just the symptoms
2. Follows the existing code style and conventions
3. Adds necessary validation and error handling
4. Is minimal - only changes what's necessary
5. Does not introduce new bugs or break existing functionality
6. Handles edge cases properly

Provide the COMPLETE fixed source code, maintaining all existing functionality """
            """while fixing the bug."""
        )

    def _build_sections(
        self, context: AssembledContext | FixGenerationContext
    ) -> list[PromptSection]:
        """Build prompt sections for fix generation."""
        if isinstance(context, FixGenerationContext):
            return self._build_fix_sections(context)

        return [
            PromptSection(
                label="Fix Request",
                content="Generate a fix for the provided code.",
            )
        ]

    def _build_fix_sections(self, context: FixGenerationContext) -> list[PromptSection]:
        """Build sections specific to fix generation context."""
        sections = []

        # Bug information
        bug_info = [
            f"**Type**: {context.bug_type}",
            f"**Description**: {context.bug_description}",
        ]

        sections.append(
            PromptSection(
                label="Bug Information",
                content="\n".join(bug_info),
            )
        )

        # Root cause
        sections.append(
            PromptSection(
                label="Root Cause Analysis",
                content=context.root_cause,
            )
        )

        # Missing checks
        if context.missing_checks:
            checks_content = "\n".join(f"- {check}" for check in context.missing_checks)
            sections.append(
                PromptSection(
                    label="Missing Validation Checks",
                    content=checks_content,
                )
            )

        # Incorrect assumptions
        if context.incorrect_assumptions:
            assumptions_content = "\n".join(
                f"- {assumption}" for assumption in context.incorrect_assumptions
            )
            sections.append(
                PromptSection(
                    label="Incorrect Assumptions to Address",
                    content=assumptions_content,
                )
            )

        # Source code
        sections.append(
            PromptSection(
                label="Original Source Code",
                content=f"```{context.language}\n{context.source_code}\n```",
            )
        )

        return sections

    def render_fix_generation(self, context: FixGenerationContext) -> RenderedPrompt:
        """Render a fix generation prompt.

        Args:
            context: Fix generation context with bug details.

        Returns:
            Rendered prompt for fix generation.
        """
        system = self._system_instruction(context)
        sections = self._build_fix_sections(context)

        user_sections = "\n\n---\n\n".join(
            [f"## {s.label}\n\n{s.content}" for s in sections if s.content]
        )

        user_prompt = f"""{user_sections}

---

## Fix Instructions

Generate the COMPLETE fixed source code with all necessary changes.
Ensure you:
1. Add all missing validation checks
2. Address incorrect assumptions
3. Handle edge cases
4. Maintain existing code style
5. Keep changes minimal and focused

After the code, provide a brief explanation of what you changed and why.

Format your response as:
```{context.language}
<complete fixed code>
```

**Explanation**: <what you changed and why>"""

        return RenderedPrompt(
            messages=[
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=user_prompt),
            ]
        )


class MinimalFixPrompt(PromptTemplate):
    """Prompt template for generating minimal, focused fixes."""

    @property
    def name(self) -> str:
        """Template name."""
        return "minimal_fix"

    def _system_instruction(self, _context: AssembledContext | FixGenerationContext) -> str:
        """System instruction for minimal fix generation."""
        return """You are an expert at writing minimal, surgical code fixes.

Generate the SMALLEST possible fix that:
1. Addresses the specific bug
2. Changes as few lines as possible
3. Does not refactor or improve unrelated code
4. Preserves all existing behavior except the bug

Be extremely conservative - only fix what's broken."""

    def _build_sections(
        self, context: AssembledContext | FixGenerationContext
    ) -> list[PromptSection]:
        """Build sections for minimal fix."""
        if isinstance(context, FixGenerationContext):
            return [
                PromptSection(
                    label="Bug",
                    content=f"{context.bug_type}: {context.bug_description}",
                ),
                PromptSection(
                    label="Code",
                    content=f"```{context.language}\n{context.source_code}\n```",
                ),
            ]
        return []


class SafeFixPrompt(PromptTemplate):
    """Prompt template for generating safe, well-tested fixes with error handling."""

    @property
    def name(self) -> str:
        """Template name."""
        return "safe_fix"

    def _system_instruction(self, _context: AssembledContext | FixGenerationContext) -> str:
        """System instruction for safe fix generation."""
        return """You are an expert at writing robust, production-ready bug fixes.

Generate a fix that:
1. Addresses the root cause completely
2. Includes comprehensive error handling
3. Validates all inputs and assumptions
4. Handles edge cases gracefully
5. Includes logging for debugging
6. Documents why the fix is necessary

Prioritize safety and correctness over brevity."""

    def _build_sections(
        self, context: AssembledContext | FixGenerationContext
    ) -> list[PromptSection]:
        """Build sections for safe fix."""
        if isinstance(context, FixGenerationContext):
            sections = [
                PromptSection(
                    label="Bug Analysis",
                    content=f"**Type**: {context.bug_type}\n**Root Cause**: {context.root_cause}",
                ),
                PromptSection(
                    label="Source Code",
                    content=f"```{context.language}\n{context.source_code}\n```",
                ),
            ]

            if context.missing_checks:
                sections.append(
                    PromptSection(
                        label="Required Validations",
                        content="\n".join(f"- {check}" for check in context.missing_checks),
                    )
                )

            return sections
        return []
