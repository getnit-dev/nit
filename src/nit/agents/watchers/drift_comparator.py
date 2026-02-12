"""Drift comparison strategies (tasks 3.11.4, 3.11.5).

Implements multiple comparison strategies for drift detection:
- semantic: embedding-based cosine similarity using sentence-transformers
- exact: exact string match
- regex: regex pattern match
- schema: JSON schema validation
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from jsonschema import ValidationError, validate
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class ComparisonType(Enum):
    """Type of drift comparison."""

    SEMANTIC = "semantic"
    EXACT = "exact"
    REGEX = "regex"
    SCHEMA = "schema"


@dataclass
class DriftComparisonResult:
    """Result of a drift comparison."""

    passed: bool
    similarity_score: float | None = None
    error: str | None = None
    details: dict[str, Any] | None = None


@dataclass
class CompareConfig:
    """Configuration for a drift comparison operation."""

    comparison_type: ComparisonType
    """Type of comparison to perform."""

    baseline: str
    """Baseline output text."""

    current: str
    """Current output text."""

    baseline_embedding: list[float] | None = None
    """Pre-computed baseline embedding (for semantic)."""

    threshold: float = 0.8
    """Similarity threshold (for semantic)."""

    pattern: str | None = None
    """Regex pattern (for regex)."""

    schema: dict[str, Any] | None = field(default=None)
    """JSON schema (for schema)."""


class DriftComparator:
    """Compare outputs for drift detection using various strategies."""

    def __init__(self) -> None:
        """Initialize the drift comparator.

        Lazy-loads sentence-transformers model only when semantic comparison is used.
        """
        self._model: Any = None  # sentence_transformers.SentenceTransformer

    def _load_model(self) -> Any:
        """Load the sentence-transformers model lazily.

        Returns:
            The loaded model.
        """
        if self._model is None:
            # Use a small, fast model that runs locally
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Loaded sentence-transformers model: all-MiniLM-L6-v2")
        return self._model

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for text using sentence-transformers (task 3.11.4).

        Args:
            text: Text to embed.

        Returns:
            Embedding vector.
        """
        model = self._load_model()
        embedding = model.encode(text, convert_to_numpy=True)
        return list(embedding.tolist())

    def semantic_compare(
        self,
        baseline_text: str,
        current_text: str,
        *,
        baseline_embedding: list[float] | None = None,
        threshold: float = 0.8,
    ) -> DriftComparisonResult:
        """Compare texts using semantic similarity (task 3.11.4).

        Uses sentence-transformers to generate embeddings and compute cosine similarity.

        Args:
            baseline_text: Baseline output text.
            current_text: Current output text.
            baseline_embedding: Pre-computed baseline embedding (optional).
            threshold: Minimum similarity score to pass (0.0 to 1.0).

        Returns:
            Comparison result with similarity score.
        """
        try:
            # Get or compute baseline embedding
            if baseline_embedding is None:
                baseline_embedding = self.embed_text(baseline_text)

            # Compute current embedding
            current_embedding = self.embed_text(current_text)

            # Compute cosine similarity
            similarity = self._cosine_similarity(baseline_embedding, current_embedding)

            passed = similarity >= threshold

            return DriftComparisonResult(
                passed=passed,
                similarity_score=similarity,
                details={
                    "threshold": threshold,
                    "baseline_length": len(baseline_text),
                    "current_length": len(current_text),
                },
            )

        except Exception as e:
            logger.error("Semantic comparison failed: %s", e)
            return DriftComparisonResult(
                passed=False,
                similarity_score=None,
                error=str(e),
            )

    def exact_compare(self, baseline_text: str, current_text: str) -> DriftComparisonResult:
        """Compare texts for exact match (task 3.11.5).

        Args:
            baseline_text: Baseline output text.
            current_text: Current output text.

        Returns:
            Comparison result.
        """
        passed = baseline_text == current_text

        return DriftComparisonResult(
            passed=passed,
            similarity_score=1.0 if passed else 0.0,
            details={
                "baseline_length": len(baseline_text),
                "current_length": len(current_text),
            },
        )

    def regex_compare(self, pattern: str, current_text: str) -> DriftComparisonResult:
        """Compare text against regex pattern (task 3.11.5).

        Args:
            pattern: Regex pattern to match.
            current_text: Current output text.

        Returns:
            Comparison result.
        """
        try:
            match = re.search(pattern, current_text, re.DOTALL)
            passed = match is not None

            return DriftComparisonResult(
                passed=passed,
                similarity_score=1.0 if passed else 0.0,
                details={
                    "pattern": pattern,
                    "matched": passed,
                    "match_groups": match.groups() if match else None,
                },
            )

        except re.error as e:
            logger.error("Invalid regex pattern: %s", e)
            return DriftComparisonResult(
                passed=False,
                similarity_score=None,
                error=f"Invalid regex pattern: {e}",
            )

    def schema_compare(self, schema: dict[str, Any], current_text: str) -> DriftComparisonResult:
        """Validate JSON output against schema (task 3.11.5).

        Args:
            schema: JSON schema to validate against.
            current_text: Current output text (should be JSON).

        Returns:
            Comparison result.
        """
        try:
            # Try to parse as JSON
            try:
                current_data = json.loads(current_text)
            except json.JSONDecodeError as e:
                return DriftComparisonResult(
                    passed=False,
                    similarity_score=0.0,
                    error=f"Output is not valid JSON: {e}",
                )

            # Validate against schema using jsonschema
            try:
                validate(instance=current_data, schema=schema)

                return DriftComparisonResult(
                    passed=True,
                    similarity_score=1.0,
                    details={
                        "schema_type": schema.get("type"),
                        "validated": True,
                    },
                )

            except ValidationError as e:
                return DriftComparisonResult(
                    passed=False,
                    similarity_score=0.0,
                    error=f"Schema validation failed: {e.message}",
                    details={
                        "validation_path": list(e.path),
                        "schema_path": list(e.schema_path),
                    },
                )

        except Exception as e:
            logger.error("Schema comparison failed: %s", e)
            return DriftComparisonResult(
                passed=False,
                similarity_score=None,
                error=str(e),
            )

    def compare(self, config: CompareConfig) -> DriftComparisonResult:
        """Compare baseline and current outputs using specified strategy.

        Args:
            config: Comparison configuration with all necessary parameters.

        Returns:
            Comparison result.
        """
        dispatch = {
            ComparisonType.SEMANTIC: self._dispatch_semantic,
            ComparisonType.EXACT: self._dispatch_exact,
            ComparisonType.REGEX: self._dispatch_regex,
            ComparisonType.SCHEMA: self._dispatch_schema,
        }

        handler = dispatch.get(config.comparison_type)
        if handler is None:
            return DriftComparisonResult(
                passed=False,
                error=f"Unknown comparison type: {config.comparison_type}",
            )

        return handler(config)

    def _dispatch_semantic(self, config: CompareConfig) -> DriftComparisonResult:
        """Dispatch semantic comparison."""
        return self.semantic_compare(
            config.baseline,
            config.current,
            baseline_embedding=config.baseline_embedding,
            threshold=config.threshold,
        )

    def _dispatch_exact(self, config: CompareConfig) -> DriftComparisonResult:
        """Dispatch exact comparison."""
        return self.exact_compare(config.baseline, config.current)

    def _dispatch_regex(self, config: CompareConfig) -> DriftComparisonResult:
        """Dispatch regex comparison."""
        if config.pattern is None:
            return DriftComparisonResult(
                passed=False,
                error="Regex comparison requires a pattern",
            )
        return self.regex_compare(config.pattern, config.current)

    def _dispatch_schema(self, config: CompareConfig) -> DriftComparisonResult:
        """Dispatch schema comparison."""
        if config.schema is None:
            return DriftComparisonResult(
                passed=False,
                error="Schema comparison requires a schema",
            )
        return self.schema_compare(config.schema, config.current)

    @staticmethod
    def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            vec1: First vector.
            vec2: Second vector.

        Returns:
            Cosine similarity score (0.0 to 1.0).
        """
        if len(vec1) != len(vec2):
            msg = f"Vectors must have same length, got {len(vec1)} and {len(vec2)}"
            raise ValueError(msg)

        # Compute dot product
        dot_product = float(sum(a * b for a, b in zip(vec1, vec2, strict=True)))

        # Compute magnitudes
        mag1 = float(sum(a * a for a in vec1) ** 0.5)
        mag2 = float(sum(b * b for b in vec2) ** 0.5)

        # Avoid division by zero
        if mag1 == 0.0 or mag2 == 0.0:
            return 0.0

        # Return cosine similarity
        return float(dot_product / (mag1 * mag2))
