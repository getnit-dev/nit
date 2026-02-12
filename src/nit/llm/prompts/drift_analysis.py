"""Drift analysis prompt template for analyzing LLM output drift (task 3.12.3).

Used when drift is detected to help understand causes and suggest improvements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.llm.engine import LLMMessage
from nit.llm.prompts.base import PromptSection, PromptTemplate, RenderedPrompt

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext


@dataclass
class DriftAnalysisContext:
    """Context for drift analysis prompts."""

    test_id: str
    """Identifier of the drift test."""

    test_name: str
    """Human-readable test name."""

    baseline_output: str
    """The baseline/expected output."""

    current_output: str
    """The current output that drifted."""

    similarity_score: float | None = None
    """Similarity score (0-1) between baseline and current."""

    comparison_type: str = "semantic"
    """Type of comparison used (exact, semantic, regex, schema)."""

    prompt_used: str = ""
    """The prompt that was sent to the LLM (if available)."""

    model: str = ""
    """Model used for generation."""


class DriftAnalysisPrompt(PromptTemplate):
    """Prompt template for analyzing detected drift (task 3.12.3)."""

    @property
    def name(self) -> str:
        """Template name."""
        return "drift_analysis"

    def _system_instruction(self, _context: AssembledContext | DriftAnalysisContext) -> str:
        """System instruction for drift analysis."""
        return """You are an expert at analyzing LLM behavior and prompt engineering.

Your task is to analyze drift in LLM outputs - when the model's responses deviate
from expected baselines over time. Focus on:

1. Identifying what changed between baseline and current output
2. Determining if drift is semantic (meaning changed) or stylistic (format changed)
3. Assessing whether drift is problematic or acceptable
4. Root causes: prompt ambiguity, model updates, temperature settings, etc.
5. Concrete suggestions to reduce drift or update the baseline

Be specific and actionable. Focus on observable differences."""

    def _build_sections(
        self, context: AssembledContext | DriftAnalysisContext
    ) -> list[PromptSection]:
        """Build prompt sections for drift analysis."""
        if isinstance(context, DriftAnalysisContext):
            return self._build_drift_sections(context)

        # Fallback for regular AssembledContext
        return [
            PromptSection(
                label="Analysis Request",
                content="Analyze the provided drift results.",
            )
        ]

    def _build_drift_sections(self, context: DriftAnalysisContext) -> list[PromptSection]:
        """Build sections specific to drift analysis context."""
        sections = []

        # Test information
        test_info = f"""Test: {context.test_name}
ID: {context.test_id}
Comparison Type: {context.comparison_type}"""

        if context.similarity_score is not None:
            test_info += f"\nSimilarity Score: {context.similarity_score:.3f}"

        if context.model:
            test_info += f"\nModel: {context.model}"

        sections.append(
            PromptSection(
                label="Test Information",
                content=test_info,
            )
        )

        # Outputs comparison
        outputs_content = f"""**Baseline Output:**
```
{context.baseline_output}
```

**Current Output (Drifted):**
```
{context.current_output}
```"""

        sections.append(
            PromptSection(
                label="Output Comparison",
                content=outputs_content,
            )
        )

        # Prompt used (if available)
        if context.prompt_used:
            sections.append(
                PromptSection(
                    label="Prompt Used",
                    content=f"```\n{context.prompt_used}\n```",
                )
            )

        return sections

    def render_drift_analysis(self, context: DriftAnalysisContext) -> RenderedPrompt:
        """Render a drift analysis prompt (task 3.12.3).

        Args:
            context: Drift analysis context with outputs.

        Returns:
            Rendered prompt for drift analysis.
        """
        system = self._system_instruction(context)
        sections = self._build_drift_sections(context)

        user_sections = "\n\n---\n\n".join(
            [f"## {s.label}\n\n{s.content}" for s in sections if s.content]
        )

        user_prompt = f"""{user_sections}

---

## Analysis Request

Analyze this drift and provide:

1. **Key Differences**: What specific differences exist between baseline and current output?
   - Semantic changes (meaning/content changed)
   - Stylistic changes (format/structure changed)
   - Factual changes (different facts or data)

2. **Drift Severity**: How problematic is this drift?
   - Critical: Meaning or correctness changed
   - Moderate: Format or style changed significantly
   - Minor: Trivial wording or whitespace differences

3. **Root Cause**: Why might this drift have occurred?
   - Prompt ambiguity or unclear instructions
   - Missing output format constraints
   - Model version changes
   - Temperature/sampling settings
   - Missing few-shot examples

4. **Recommendations**: How to address this drift?
   - Prompt improvements (make more specific, add constraints)
   - Parameter adjustments (temperature, max_tokens)
   - Add few-shot examples
   - Update baseline if drift is acceptable
   - Add schema validation for structured outputs

Be concise and specific."""

        return RenderedPrompt(
            messages=[
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=user_prompt),
            ]
        )


class PromptImprovementSuggestion(PromptTemplate):
    """Prompt template for suggesting prompt improvements based on drift patterns."""

    @property
    def name(self) -> str:
        """Template name."""
        return "prompt_improvement"

    def _system_instruction(self, _context: AssembledContext | DriftAnalysisContext) -> str:
        """System instruction for prompt improvement."""
        return """You are a prompt engineering expert specializing in stability and consistency.

Your task is to improve prompts that are experiencing drift by:
1. Adding clearer output format specifications
2. Providing few-shot examples demonstrating expected output
3. Adding constraints to reduce variance
4. Making instructions more explicit and unambiguous
5. Suggesting appropriate temperature and parameter settings

Generate concrete, actionable improvements."""

    def _build_sections(
        self, context: AssembledContext | DriftAnalysisContext
    ) -> list[PromptSection]:
        """Build sections for prompt improvement."""
        if isinstance(context, DriftAnalysisContext) and context.prompt_used:
            similarity = context.similarity_score if context.similarity_score is not None else "N/A"
            return [
                PromptSection(
                    label="Current Prompt",
                    content=f"```\n{context.prompt_used}\n```",
                ),
                PromptSection(
                    label="Observed Drift",
                    content=f"Baseline vs Current differ (similarity: {similarity})",
                ),
            ]
        return []
