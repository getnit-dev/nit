"""Prompt analysis and optimization module (task 3.12.1, 3.12.2).

Analyzes LLM prompts for token count, redundancy, clarity, and suggests optimizations.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import tiktoken

if TYPE_CHECKING:
    from nit.llm.prompts.base import RenderedPrompt

# Prompt analysis thresholds
_MIN_AMBIGUOUS_PATTERNS = 2
_MAX_SENTENCE_WORD_COUNT = 40
_MAX_LONG_SENTENCES = 3
_MAX_VAGUE_TERMS = 3
_LARGE_PROMPT_THRESHOLD = 2000
_REDUNDANCY_THRESHOLD = 0.1
_LOW_CLARITY_THRESHOLD = 0.7


@dataclass
class PromptAnalysis:
    """Analysis result for a prompt."""

    total_tokens: int
    """Total token count across all messages."""

    message_tokens: dict[str, int] = field(default_factory=dict)
    """Token count per message role (system, user, etc.)."""

    redundancy_score: float = 0.0
    """Redundancy score (0-1, higher = more redundant)."""

    clarity_score: float = 0.0
    """Clarity score (0-1, higher = clearer)."""

    redundant_phrases: list[str] = field(default_factory=list)
    """Detected redundant phrases."""

    clarity_issues: list[str] = field(default_factory=list)
    """Detected clarity issues."""


@dataclass
class PromptOptimization:
    """Optimization suggestions for a prompt."""

    current_tokens: int
    """Current total token count."""

    potential_savings: int
    """Estimated tokens that can be saved."""

    suggestions: list[str] = field(default_factory=list)
    """List of actionable optimization suggestions."""

    temperature_recommendation: float | None = None
    """Recommended temperature for this prompt type."""

    max_tokens_recommendation: int | None = None
    """Recommended max_tokens for this prompt type."""


class PromptAnalyzer:
    """Analyzer for LLM prompts (task 3.12.1)."""

    def __init__(self, model: str = "gpt-4") -> None:
        """Initialize the analyzer.

        Args:
            model: Model name for tokenization (default: gpt-4).
        """
        try:
            self._encoder = tiktoken.encoding_for_model(model)
        except KeyError:
            # Fallback to cl100k_base (GPT-4, GPT-3.5-turbo)
            self._encoder = tiktoken.get_encoding("cl100k_base")

    def analyze(self, prompt: RenderedPrompt) -> PromptAnalysis:
        """Analyze a rendered prompt (task 3.12.1).

        Args:
            prompt: The rendered prompt to analyze.

        Returns:
            Analysis results.
        """
        # Token counting
        total_tokens = 0
        message_tokens: dict[str, int] = {}

        for message in prompt.messages:
            tokens = len(self._encoder.encode(message.content))
            total_tokens += tokens
            message_tokens[message.role] = message_tokens.get(message.role, 0) + tokens

        # Redundancy detection
        combined_text = " ".join(msg.content for msg in prompt.messages)
        redundancy_score, redundant_phrases = self._detect_redundancy(combined_text)

        # Clarity scoring
        clarity_score, clarity_issues = self._score_clarity(combined_text)

        return PromptAnalysis(
            total_tokens=total_tokens,
            message_tokens=message_tokens,
            redundancy_score=redundancy_score,
            clarity_score=clarity_score,
            redundant_phrases=redundant_phrases,
            clarity_issues=clarity_issues,
        )

    def _detect_redundancy(self, text: str) -> tuple[float, list[str]]:
        """Detect redundant phrases in text.

        Args:
            text: Text to analyze.

        Returns:
            Tuple of (redundancy_score, redundant_phrases).
        """
        # Normalize text: lowercase, remove extra whitespace
        normalized = " ".join(text.lower().split())

        # Extract n-grams (3-5 words)
        redundant_phrases = []
        for n in range(3, 6):
            ngrams = self._extract_ngrams(normalized, n)
            # Find phrases that appear more than once
            phrase_counts = Counter(ngrams)
            for phrase, count in phrase_counts.items():
                if count > 1:
                    redundant_phrases.append(phrase)

        # Calculate redundancy score based on repeated content
        if not redundant_phrases:
            return 0.0, []

        # Score: ratio of redundant tokens to total tokens
        # Count actual occurrences of each phrase
        redundant_token_count = 0
        for phrase in set(redundant_phrases):  # Use set to avoid double-counting
            # Count occurrences by searching for the phrase in normalized text
            count = 0
            pos = 0
            while True:
                pos = normalized.find(phrase, pos)
                if pos == -1:
                    break
                count += 1
                pos += len(phrase)

            if count > 1:
                redundant_token_count += len(phrase.split()) * (count - 1)

        total_words = len(normalized.split())
        redundancy_score = min(redundant_token_count / max(total_words, 1), 1.0)

        # Return top 5 most repeated phrases
        def phrase_count(phrase: str) -> int:
            return normalized.count(phrase)

        top_phrases = sorted(redundant_phrases, key=phrase_count, reverse=True)[:5]

        return redundancy_score, top_phrases

    def _extract_ngrams(self, text: str, n: int) -> list[str]:
        """Extract n-grams from text.

        Args:
            text: Text to process.
            n: N-gram size.

        Returns:
            List of n-grams.
        """
        words = text.split()
        return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]

    def _score_clarity(self, text: str) -> tuple[float, list[str]]:
        """Score prompt clarity (task 3.12.1).

        Args:
            text: Text to analyze.

        Returns:
            Tuple of (clarity_score, clarity_issues).
        """
        issues = []
        score = 1.0  # Start at perfect clarity

        # Check for clear output format specification
        has_output_format = bool(
            re.search(
                r"(output|return).*?(json|yaml|markdown|code|format|structure|template|"
                r"function|class|test)",
                text.lower(),
            )
            or re.search(
                r"format:.*?(json|yaml|code|markdown)",
                text.lower(),
            )
        )
        if not has_output_format:
            issues.append("No clear output format specification")
            score -= 0.2

        # Check for ambiguous instructions (multiple contradictory instructions)
        ambiguous_patterns = [
            r"but also",
            r"however",
            r"unless",
            r"except when",
            r"may or may not",
        ]
        ambiguous_count = sum(
            1 for pattern in ambiguous_patterns if re.search(pattern, text.lower())
        )
        if ambiguous_count > _MIN_AMBIGUOUS_PATTERNS:
            issues.append("Multiple conditional/ambiguous instructions detected")
            score -= 0.2

        # Check for overly complex sentences
        sentences = re.split(r"[.!?]+", text)
        long_sentences = [s for s in sentences if len(s.split()) > _MAX_SENTENCE_WORD_COUNT]
        if len(long_sentences) > _MAX_LONG_SENTENCES:
            issues.append(
                f"Contains {len(long_sentences)} overly complex sentences "
                f"(>{_MAX_SENTENCE_WORD_COUNT} words)"
            )
            score -= 0.15

        # Check for vague language
        vague_terms = ["maybe", "perhaps", "possibly", "probably", "might", "could"]
        vague_count = sum(text.lower().count(term) for term in vague_terms)
        if vague_count > _MAX_VAGUE_TERMS:
            issues.append(f"Contains {vague_count} vague/uncertain terms")
            score -= 0.15

        # Check for examples/few-shot demonstrations
        has_examples = bool(re.search(r"(example|for instance|such as|e\.g\.|```)", text.lower()))
        if not has_examples:
            issues.append("No examples or demonstrations provided")
            score -= 0.1

        # Check for clear task description
        has_task = bool(re.search(r"(task|goal|objective|purpose|must|should):", text.lower()))
        if not has_task:
            issues.append("No clear task/objective statement")
            score -= 0.2

        return max(score, 0.0), issues


class PromptOptimizer:
    """Generates optimization suggestions for prompts (task 3.12.2)."""

    def __init__(self) -> None:
        """Initialize the optimizer."""
        self._analyzer = PromptAnalyzer()

    def suggest_optimizations(
        self, prompt: RenderedPrompt, analysis: PromptAnalysis | None = None
    ) -> PromptOptimization:
        """Generate optimization suggestions (task 3.12.2).

        Args:
            prompt: The rendered prompt to optimize.
            analysis: Pre-computed analysis (optional, will compute if not provided).

        Returns:
            Optimization suggestions.
        """
        if analysis is None:
            analysis = self._analyzer.analyze(prompt)

        suggestions = []
        potential_savings = 0

        # Token reduction suggestions
        if analysis.total_tokens > _LARGE_PROMPT_THRESHOLD:
            suggestions.append(
                f"Prompt is large ({analysis.total_tokens} tokens). "
                "Consider removing non-essential context or examples."
            )
            potential_savings += int(analysis.total_tokens * 0.1)

        # Redundancy suggestions
        if analysis.redundancy_score > _REDUNDANCY_THRESHOLD:
            savings = int(analysis.total_tokens * analysis.redundancy_score)
            suggestions.append(
                f"Redundancy detected (score: {analysis.redundancy_score:.2f}). "
                f"Remove or consolidate repeated phrases to save ~{savings} tokens."
            )
            potential_savings += savings

        if analysis.redundant_phrases:
            top_three = ", ".join(repr(p) for p in analysis.redundant_phrases[:3])
            suggestions.append(f"Top redundant phrases: {top_three}")

        # Clarity suggestions
        if analysis.clarity_score < _LOW_CLARITY_THRESHOLD:
            suggestions.append(
                f"Clarity score is low ({analysis.clarity_score:.2f}). "
                "Consider addressing the following issues:"
            )
            suggestions.extend(f"  - {issue}" for issue in analysis.clarity_issues)

        # Output format suggestions
        if "No clear output format specification" in analysis.clarity_issues:
            suggestions.append(
                "Add explicit output format specification (e.g., 'Return ONLY valid JSON' "
                "or 'Output a Python function')."
            )

        # Few-shot suggestions
        if "No examples or demonstrations provided" in analysis.clarity_issues:
            suggestions.append(
                "Add 1-2 few-shot examples to improve output quality and consistency."
            )

        # Temperature recommendations
        temperature_recommendation = self._recommend_temperature(prompt)

        # Max tokens recommendations
        max_tokens_recommendation = self._recommend_max_tokens(prompt, analysis)

        return PromptOptimization(
            current_tokens=analysis.total_tokens,
            potential_savings=potential_savings,
            suggestions=suggestions,
            temperature_recommendation=temperature_recommendation,
            max_tokens_recommendation=max_tokens_recommendation,
        )

    def _recommend_temperature(self, prompt: RenderedPrompt) -> float:
        """Recommend temperature based on prompt type.

        Args:
            prompt: The rendered prompt.

        Returns:
            Recommended temperature (0.0-1.0).
        """
        combined_text = " ".join(msg.content.lower() for msg in prompt.messages)

        # Creative/analysis tasks: moderate temperature (check first, more specific)
        if any(
            keyword in combined_text
            for keyword in [
                "creative",
                "creatively",
                "brainstorm",
                "ideate",
                "imaginative",
                "original",
            ]
        ):
            return 0.7

        if any(
            keyword in combined_text
            for keyword in ["analyze", "explain", "describe", "suggest", "discuss"]
        ):
            return 0.5

        # Code generation: low temperature (deterministic)
        if any(
            keyword in combined_text
            for keyword in ["test", "function", "class", "generate code", "implement"]
        ):
            return 0.2

        # Default: low temperature for consistency
        return 0.3

    def _recommend_max_tokens(self, prompt: RenderedPrompt, analysis: PromptAnalysis) -> int:
        """Recommend max_tokens based on prompt type and size.

        Args:
            prompt: The rendered prompt.
            analysis: Prompt analysis.

        Returns:
            Recommended max_tokens.
        """
        combined_text = " ".join(msg.content.lower() for msg in prompt.messages)

        # Code generation: moderate output size
        if "test" in combined_text or "code" in combined_text:
            return 2048

        # Documentation: larger output
        if "documentation" in combined_text or "docstring" in combined_text:
            return 1024

        # Analysis/explanation: moderate output
        if "analyze" in combined_text or "explain" in combined_text:
            return 1024

        # Default: scale with input size (but cap at 4096)
        return min(analysis.total_tokens + 1024, 4096)
