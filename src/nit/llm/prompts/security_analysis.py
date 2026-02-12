"""Security analysis prompt template for validating heuristic findings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nit.llm.engine import LLMMessage
from nit.llm.prompts.base import PromptSection, PromptTemplate, RenderedPrompt

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext


@dataclass
class SecurityAnalysisContext:
    """Context for security analysis LLM validation."""

    vulnerability_type: str
    """Vulnerability type identifier (e.g., 'sql_injection')."""

    code_snippet: str
    """Code snippet showing the potential vulnerability."""

    file_path: str
    """Path to the source file."""

    language: str
    """Programming language."""

    heuristic_description: str
    """Description from the heuristic detector."""

    data_flow: list[str] = field(default_factory=list)
    """Optional taint flow trace."""


class SecurityAnalysisPrompt(PromptTemplate):
    """Prompt for LLM validation of heuristic security findings."""

    @property
    def name(self) -> str:
        return "security_analysis"

    def _system_instruction(self, _context: AssembledContext | SecurityAnalysisContext) -> str:
        return (
            "You are a security expert validating potential vulnerabilities "
            "flagged by static analysis.\n\n"
            "Focus on:\n"
            "1. Is this a real, exploitable vulnerability or a false positive?\n"
            "2. Does the surrounding code mitigate the issue?\n"
            "3. Could an attacker actually reach and exploit this in practice?\n\n"
            "Be conservative. Only confirm high-confidence, exploitable findings. "
            "It is better to dismiss a borderline case than to flood developers "
            "with false positives."
        )

    def _build_sections(
        self, context: AssembledContext | SecurityAnalysisContext
    ) -> list[PromptSection]:
        if isinstance(context, SecurityAnalysisContext):
            return self._build_validation_sections(context)
        return [
            PromptSection(
                label="Analysis Request",
                content="Validate the provided security finding.",
            )
        ]

    def _build_validation_sections(self, context: SecurityAnalysisContext) -> list[PromptSection]:
        sections = [
            PromptSection(
                label="Finding",
                content=(
                    f"**Type**: {context.vulnerability_type}\n"
                    f"**File**: {context.file_path}\n"
                    f"**Language**: {context.language}\n\n"
                    f"**Heuristic analysis**:\n{context.heuristic_description}"
                ),
            ),
            PromptSection(
                label="Code",
                content=f"```{context.language}\n{context.code_snippet}\n```",
            ),
        ]

        if context.data_flow:
            sections.append(
                PromptSection(
                    label="Data Flow",
                    content=" -> ".join(context.data_flow),
                )
            )

        return sections

    def render_validation(self, context: SecurityAnalysisContext) -> RenderedPrompt:
        """Render a validation prompt for a security finding.

        Args:
            context: Security analysis context.

        Returns:
            Rendered prompt with system and user messages.
        """
        system = self._system_instruction(context)
        sections = self._build_validation_sections(context)

        user_sections = "\n\n---\n\n".join(
            f"## {s.label}\n\n{s.content}" for s in sections if s.content
        )

        user_prompt = f"""{user_sections}

---

## Validation Request

Is this a real, exploitable vulnerability?

Provide exactly:
1. **IS_VALID**: true or false
2. **CONFIDENCE**: 0.0-1.0
3. **REASONING**: One or two sentences explaining why.

Be concise."""

        return RenderedPrompt(
            messages=[
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=user_prompt),
            ]
        )
