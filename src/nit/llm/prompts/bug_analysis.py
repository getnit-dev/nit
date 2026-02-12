"""Bug analysis prompt template for identifying and analyzing code bugs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.llm.engine import LLMMessage
from nit.llm.prompts.base import PromptSection, PromptTemplate, RenderedPrompt

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext


@dataclass
class BugAnalysisContext:
    """Context for bug analysis prompts."""

    error_message: str
    """The error message from test execution."""

    stack_trace: str
    """Full stack trace."""

    source_code: str
    """Source code being analyzed."""

    test_code: str = ""
    """Test code that triggered the error (if available)."""

    language: str = "unknown"
    """Programming language."""

    file_path: str = ""
    """Path to the source file."""


class BugAnalysisPrompt(PromptTemplate):
    """Prompt template for analyzing bugs and determining root causes."""

    @property
    def name(self) -> str:
        """Template name."""
        return "bug_analysis"

    def _system_instruction(self, _context: AssembledContext | BugAnalysisContext) -> str:
        """System instruction for bug analysis."""
        return (
            """You are an expert software debugger specializing in identifying and """
            """analyzing code bugs.

Your task is to analyze error messages, stack traces, and source code to:
1. Determine if the error is a real code bug or a test infrastructure issue
2. Identify the type of bug (null reference, type error, logic error, etc.)
3. Locate the exact code causing the problem
4. Explain the root cause in clear, technical terms
5. Suggest what validation or checks are missing

Be precise and focus on facts from the error message and code. Avoid speculation."""
        )

    def _build_sections(
        self, context: AssembledContext | BugAnalysisContext
    ) -> list[PromptSection]:
        """Build prompt sections for bug analysis."""
        if isinstance(context, BugAnalysisContext):
            return self._build_bug_sections(context)

        # Fallback for regular AssembledContext
        return [
            PromptSection(
                label="Analysis Request",
                content="Analyze the provided code for potential bugs.",
            )
        ]

    def _build_bug_sections(self, context: BugAnalysisContext) -> list[PromptSection]:
        """Build sections specific to bug analysis context."""
        sections = []

        # Error information
        error_content = f"```\n{context.error_message}\n```"
        if context.stack_trace:
            error_content += f"\n\nStack Trace:\n```\n{context.stack_trace}\n```"

        sections.append(
            PromptSection(
                label="Error Information",
                content=error_content,
            )
        )

        # Source code
        if context.source_code:
            sections.append(
                PromptSection(
                    label=f"Source Code ({context.file_path})",
                    content=f"```{context.language}\n{context.source_code}\n```",
                )
            )

        # Test code if available
        if context.test_code:
            sections.append(
                PromptSection(
                    label="Test Code",
                    content=f"```{context.language}\n{context.test_code}\n```",
                )
            )

        return sections

    def render_bug_analysis(self, context: BugAnalysisContext) -> RenderedPrompt:
        """Render a bug analysis prompt.

        Args:
            context: Bug analysis context with error details.

        Returns:
            Rendered prompt for bug analysis.
        """
        system = self._system_instruction(context)
        sections = self._build_bug_sections(context)

        user_sections = "\n\n---\n\n".join(
            [f"## {s.label}\n\n{s.content}" for s in sections if s.content]
        )

        user_prompt = f"""{user_sections}

---

## Analysis Request

Analyze this error and provide:

1. **Bug Type**: Classify the bug (null_dereference, type_error, logic_error, etc.)
2. **Is Code Bug**: Is this a bug in the production code (true) or test infrastructure (false)?
3. **Location**: Where in the source code is the bug?
4. **Root Cause**: What is causing this error to occur?
5. **Missing Validations**: What checks or validations are missing?

Be concise and factual."""

        return RenderedPrompt(
            messages=[
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=user_prompt),
            ]
        )


class RootCauseAnalysisPrompt(PromptTemplate):
    """Prompt template for deep root cause analysis."""

    @property
    def name(self) -> str:
        """Template name."""
        return "root_cause_analysis"

    def _system_instruction(self, _context: AssembledContext | BugAnalysisContext) -> str:
        """System instruction for root cause analysis."""
        return (
            """You are an expert at debugging and root cause analysis.

Your task is to deeply analyze bugs and trace them to their root cause by:
1. Understanding the data flow that leads to the bug
2. Identifying incorrect assumptions in the code
3. Finding missing edge case handling
4. Recognizing architectural or design issues
5. Explaining why the bug happens, not just what happens

Provide a detailed, structured analysis that helps developers understand and fix """
            """the underlying problem."""
        )

    def _build_sections(
        self, context: AssembledContext | BugAnalysisContext
    ) -> list[PromptSection]:
        """Build sections for root cause analysis."""
        if isinstance(context, BugAnalysisContext):
            return self._build_bug_sections(context)
        return []

    def _build_bug_sections(self, context: BugAnalysisContext) -> list[PromptSection]:
        """Build sections for root cause context."""
        return [
            PromptSection(
                label="Error",
                content=f"```\n{context.error_message}\n```",
            ),
            PromptSection(
                label="Source Code",
                content=f"```{context.language}\n{context.source_code}\n```",
            ),
        ]


class BugReproductionPrompt(PromptTemplate):
    """Prompt template for generating minimal bug reproduction tests."""

    @property
    def name(self) -> str:
        """Template name."""
        return "bug_reproduction"

    def _system_instruction(self, _context: AssembledContext | BugAnalysisContext) -> str:
        """System instruction for reproduction test generation."""
        return """You are an expert at writing minimal reproduction test cases.

Create focused, minimal tests that:
1. Reproduce the bug reliably
2. Are as short as possible (< 20 lines)
3. Have minimal dependencies and setup
4. Focus solely on demonstrating the bug
5. Use the project's testing framework and conventions

Do not include assertions that would pass - the test should fail and demonstrate the bug."""

    def _build_sections(
        self, context: AssembledContext | BugAnalysisContext
    ) -> list[PromptSection]:
        """Build sections for reproduction test generation."""
        if isinstance(context, BugAnalysisContext):
            return [
                PromptSection(
                    label="Bug to Reproduce",
                    content=context.error_message,
                ),
                PromptSection(
                    label="Source Code",
                    content=f"```{context.language}\n{context.source_code[:500]}\n```",
                ),
            ]
        return []
