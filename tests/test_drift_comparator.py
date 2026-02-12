"""Tests for drift comparator (tasks 3.11.4, 3.11.5)."""

from __future__ import annotations

import pytest

from nit.agents.watchers.drift_comparator import CompareConfig, ComparisonType, DriftComparator


@pytest.fixture
def comparator() -> DriftComparator:
    """Create a drift comparator instance."""
    return DriftComparator()


def test_exact_compare_identical(comparator: DriftComparator) -> None:
    """Test exact comparison with identical strings."""
    result = comparator.exact_compare("hello world", "hello world")

    assert result.passed
    assert result.similarity_score == 1.0
    assert result.error is None


def test_exact_compare_different(comparator: DriftComparator) -> None:
    """Test exact comparison with different strings."""
    result = comparator.exact_compare("hello world", "hello universe")

    assert not result.passed
    assert result.similarity_score == 0.0
    assert result.error is None


def test_regex_compare_match(comparator: DriftComparator) -> None:
    """Test regex comparison with matching pattern."""
    result = comparator.regex_compare(r"hello \w+", "hello world")

    assert result.passed
    assert result.similarity_score == 1.0
    assert result.error is None
    assert result.details is not None
    assert result.details["matched"]


def test_regex_compare_no_match(comparator: DriftComparator) -> None:
    """Test regex comparison with non-matching pattern."""
    result = comparator.regex_compare(r"goodbye \w+", "hello world")

    assert not result.passed
    assert result.similarity_score == 0.0
    assert result.error is None


def test_regex_compare_invalid_pattern(comparator: DriftComparator) -> None:
    """Test regex comparison with invalid pattern."""
    result = comparator.regex_compare(r"[invalid(", "hello world")

    assert not result.passed
    assert result.error is not None
    assert "Invalid regex pattern" in result.error


def test_schema_compare_valid_json(comparator: DriftComparator) -> None:
    """Test schema comparison with valid JSON."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "number"},
        },
        "required": ["name"],
    }

    json_text = '{"name": "Alice", "age": 30}'

    result = comparator.schema_compare(schema, json_text)

    assert result.passed
    assert result.similarity_score == 1.0
    assert result.error is None


def test_schema_compare_invalid_json(comparator: DriftComparator) -> None:
    """Test schema comparison with invalid JSON."""
    schema = {"type": "object"}
    invalid_json = "not json at all"

    result = comparator.schema_compare(schema, invalid_json)

    assert not result.passed
    assert result.similarity_score == 0.0
    assert result.error is not None
    assert "not valid JSON" in result.error


def test_schema_compare_schema_violation(comparator: DriftComparator) -> None:
    """Test schema comparison with schema violation."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
        },
        "required": ["name"],
    }

    # Missing required field
    json_text = '{"age": 30}'

    result = comparator.schema_compare(schema, json_text)

    assert not result.passed
    assert result.similarity_score == 0.0
    assert result.error is not None
    assert "validation failed" in result.error.lower()


def test_semantic_compare_identical(comparator: DriftComparator) -> None:
    """Test semantic comparison with identical strings."""
    text = "The quick brown fox jumps over the lazy dog"

    result = comparator.semantic_compare(text, text, threshold=0.8)

    assert result.passed
    assert result.similarity_score is not None
    assert result.similarity_score >= 0.99  # Should be very close to 1.0
    assert result.error is None


def test_semantic_compare_similar(comparator: DriftComparator) -> None:
    """Test semantic comparison with semantically similar strings."""
    baseline = "The cat sat on the mat"
    current = "A cat was sitting on the mat"

    result = comparator.semantic_compare(baseline, current, threshold=0.7)

    assert result.similarity_score is not None
    assert result.similarity_score > 0.7  # Should be semantically similar
    assert result.error is None


def test_semantic_compare_different(comparator: DriftComparator) -> None:
    """Test semantic comparison with semantically different strings."""
    baseline = "Machine learning is a subset of artificial intelligence"
    current = "Pizza is a popular Italian dish"

    result = comparator.semantic_compare(baseline, current, threshold=0.8)

    assert result.similarity_score is not None
    assert result.similarity_score < 0.5  # Should be very different
    assert not result.passed


def test_semantic_compare_with_precomputed_embedding(comparator: DriftComparator) -> None:
    """Test semantic comparison with pre-computed baseline embedding."""
    baseline = "Hello world"
    current = "Hello world"

    # Pre-compute embedding
    baseline_embedding = comparator.embed_text(baseline)

    result = comparator.semantic_compare(
        baseline,
        current,
        baseline_embedding=baseline_embedding,
        threshold=0.8,
    )

    assert result.passed
    assert result.similarity_score is not None
    assert result.similarity_score >= 0.99


def test_cosine_similarity() -> None:
    """Test cosine similarity calculation."""
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [1.0, 0.0, 0.0]

    similarity = DriftComparator._cosine_similarity(vec1, vec2)
    assert similarity == pytest.approx(1.0)

    vec3 = [1.0, 0.0, 0.0]
    vec4 = [0.0, 1.0, 0.0]

    similarity2 = DriftComparator._cosine_similarity(vec3, vec4)
    assert similarity2 == pytest.approx(0.0)


def test_cosine_similarity_length_mismatch() -> None:
    """Test cosine similarity with mismatched vector lengths."""
    vec1 = [1.0, 0.0]
    vec2 = [1.0, 0.0, 0.0]

    with pytest.raises(ValueError, match="same length"):
        DriftComparator._cosine_similarity(vec1, vec2)


def test_compare_dispatcher_semantic(comparator: DriftComparator) -> None:
    """Test the compare() dispatcher for semantic comparison."""
    result = comparator.compare(
        CompareConfig(
            comparison_type=ComparisonType.SEMANTIC,
            baseline="hello world",
            current="hello world",
            threshold=0.8,
        )
    )

    assert result.passed


def test_compare_dispatcher_exact(comparator: DriftComparator) -> None:
    """Test the compare() dispatcher for exact comparison."""
    result = comparator.compare(
        CompareConfig(
            comparison_type=ComparisonType.EXACT,
            baseline="hello world",
            current="hello world",
        )
    )

    assert result.passed


def test_compare_dispatcher_regex(comparator: DriftComparator) -> None:
    """Test the compare() dispatcher for regex comparison."""
    result = comparator.compare(
        CompareConfig(
            comparison_type=ComparisonType.REGEX,
            baseline="baseline not used",
            current="hello world",
            pattern=r"hello \w+",
        )
    )

    assert result.passed


def test_compare_dispatcher_schema(comparator: DriftComparator) -> None:
    """Test the compare() dispatcher for schema comparison."""
    schema = {"type": "object"}

    result = comparator.compare(
        CompareConfig(
            comparison_type=ComparisonType.SCHEMA,
            baseline="baseline not used",
            current='{"key": "value"}',
            schema=schema,
        )
    )

    assert result.passed


def test_compare_dispatcher_regex_missing_pattern(comparator: DriftComparator) -> None:
    """Test regex comparison without required pattern."""
    result = comparator.compare(
        CompareConfig(
            comparison_type=ComparisonType.REGEX,
            baseline="baseline",
            current="current",
        )
    )

    assert not result.passed
    assert result.error is not None
    assert "requires a pattern" in result.error


def test_compare_dispatcher_schema_missing_schema(comparator: DriftComparator) -> None:
    """Test schema comparison without required schema."""
    result = comparator.compare(
        CompareConfig(
            comparison_type=ComparisonType.SCHEMA,
            baseline="baseline",
            current="current",
        )
    )

    assert not result.passed
    assert result.error is not None
    assert "requires a schema" in result.error
