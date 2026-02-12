"""Tests for prompt analysis and optimization module (task 3.12.5)."""

from __future__ import annotations

import pytest

from nit.llm.engine import LLMMessage
from nit.llm.prompt_analysis import PromptAnalyzer, PromptOptimizer
from nit.llm.prompts.base import RenderedPrompt


@pytest.fixture
def simple_prompt() -> RenderedPrompt:
    """A simple, well-formed prompt."""
    return RenderedPrompt(
        messages=[
            LLMMessage(
                role="system",
                content="You are a helpful assistant that generates unit tests.",
            ),
            LLMMessage(
                role="user",
                content="""Task: Generate a test for this function.

Source code:
```python
def add(a: int, b: int) -> int:
    return a + b
```

Output format: Return ONLY the test code as valid Python.

Example:
```python
def test_add():
    assert add(1, 2) == 3
```

Generate the test now.""",
            ),
        ]
    )


@pytest.fixture
def redundant_prompt() -> RenderedPrompt:
    """A prompt with redundant content."""
    return RenderedPrompt(
        messages=[
            LLMMessage(
                role="system",
                content="""You are a test generator. You generate tests.
Your job is to generate tests for code. Generate tests that are good tests.
Make sure the tests you generate are comprehensive tests.""",
            ),
            LLMMessage(
                role="user",
                content="""Generate a test. Make sure to generate a test that tests the function.
The test should test the function properly. Generate a good test.
Write a test that tests this function. Make sure the test is a good test.""",
            ),
        ]
    )


@pytest.fixture
def unclear_prompt() -> RenderedPrompt:
    """A prompt with clarity issues."""
    return RenderedPrompt(
        messages=[
            LLMMessage(
                role="system",
                content="You might want to perhaps generate something, maybe.",
            ),
            LLMMessage(
                role="user",
                content="""Here's some code. Do something with it. Not sure what exactly.
Could be tests, could be documentation. Whatever seems right. Unless you think
something else is better. But also consider the other approach. However, if you
feel like it, maybe try a different method.""",
            ),
        ]
    )


@pytest.fixture
def large_prompt() -> RenderedPrompt:
    """A large prompt with many tokens."""
    # Create a prompt with lots of repetitive content
    large_content = "\n\n".join(
        [f"This is section {i}. " + "Here is some context. " * 50 for i in range(20)]
    )
    return RenderedPrompt(
        messages=[
            LLMMessage(role="system", content="System instruction."),
            LLMMessage(role="user", content=large_content),
        ]
    )


class TestPromptAnalyzer:
    """Tests for PromptAnalyzer (task 3.12.1)."""

    def test_token_counting(self, simple_prompt: RenderedPrompt) -> None:
        """Test basic token counting."""
        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(simple_prompt)

        assert analysis.total_tokens > 0
        assert "system" in analysis.message_tokens
        assert "user" in analysis.message_tokens
        assert analysis.message_tokens["system"] > 0
        assert analysis.message_tokens["user"] > 0
        assert (
            analysis.total_tokens
            == analysis.message_tokens["system"] + analysis.message_tokens["user"]
        )

    def test_redundancy_detection(self, redundant_prompt: RenderedPrompt) -> None:
        """Test redundancy detection with redundant content."""
        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(redundant_prompt)

        assert analysis.redundancy_score > 0.1
        assert len(analysis.redundant_phrases) > 0

    def test_no_redundancy_in_clean_prompt(self, simple_prompt: RenderedPrompt) -> None:
        """Test that clean prompts have low redundancy."""
        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(simple_prompt)

        assert analysis.redundancy_score < 0.3

    def test_clarity_scoring_good_prompt(self, simple_prompt: RenderedPrompt) -> None:
        """Test clarity scoring on a well-formed prompt."""
        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(simple_prompt)

        # Good prompt should have high clarity
        assert analysis.clarity_score > 0.5
        # May have some minor issues, but should be mostly clear
        assert len(analysis.clarity_issues) < 3

    def test_clarity_scoring_unclear_prompt(self, unclear_prompt: RenderedPrompt) -> None:
        """Test clarity scoring on an unclear prompt."""
        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(unclear_prompt)

        # Unclear prompt should have low clarity
        assert analysis.clarity_score < 0.5
        assert len(analysis.clarity_issues) > 0

    def test_detect_missing_output_format(self) -> None:
        """Test detection of missing output format specification."""
        prompt = RenderedPrompt(
            messages=[
                LLMMessage(
                    role="user",
                    content="Generate something for this code. Here is the code: def foo(): pass",
                )
            ]
        )

        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(prompt)

        assert "No clear output format specification" in analysis.clarity_issues

    def test_detect_vague_language(self) -> None:
        """Test detection of vague/uncertain language."""
        prompt = RenderedPrompt(
            messages=[
                LLMMessage(
                    role="user",
                    content="""Maybe generate a test. Perhaps add some assertions.
Possibly include setup. Might want to consider edge cases. Could be useful.""",
                )
            ]
        )

        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(prompt)

        assert any(
            "vague" in issue.lower() or "uncertain" in issue.lower()
            for issue in analysis.clarity_issues
        )

    def test_detect_missing_examples(self) -> None:
        """Test detection of missing examples."""
        prompt = RenderedPrompt(
            messages=[
                LLMMessage(
                    role="user",
                    content="Generate a test. Return the code.",
                )
            ]
        )

        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(prompt)

        assert "No examples" in " ".join(analysis.clarity_issues)

    def test_large_prompt_token_count(self, large_prompt: RenderedPrompt) -> None:
        """Test token counting on large prompts."""
        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(large_prompt)

        assert analysis.total_tokens > 1000


class TestPromptOptimizer:
    """Tests for PromptOptimizer (task 3.12.2)."""

    def test_suggest_token_reduction_for_large_prompt(self, large_prompt: RenderedPrompt) -> None:
        """Test token reduction suggestions for large prompts."""
        optimizer = PromptOptimizer()
        optimization = optimizer.suggest_optimizations(large_prompt)

        assert optimization.current_tokens > 1000
        assert any("large" in s.lower() or "token" in s.lower() for s in optimization.suggestions)

    def test_suggest_redundancy_removal(self, redundant_prompt: RenderedPrompt) -> None:
        """Test suggestions for removing redundancy."""
        optimizer = PromptOptimizer()
        optimization = optimizer.suggest_optimizations(redundant_prompt)

        assert any("redundan" in s.lower() for s in optimization.suggestions)
        assert optimization.potential_savings > 0

    def test_suggest_clarity_improvements(self, unclear_prompt: RenderedPrompt) -> None:
        """Test suggestions for improving clarity."""
        optimizer = PromptOptimizer()
        optimization = optimizer.suggest_optimizations(unclear_prompt)

        assert any("clarity" in s.lower() for s in optimization.suggestions)

    def test_suggest_output_format_specification(self) -> None:
        """Test suggestion to add output format specification."""
        prompt = RenderedPrompt(
            messages=[LLMMessage(role="user", content="Generate a test for this code.")]
        )

        optimizer = PromptOptimizer()
        optimization = optimizer.suggest_optimizations(prompt)

        assert any("output format" in s.lower() for s in optimization.suggestions)

    def test_suggest_few_shot_examples(self) -> None:
        """Test suggestion to add few-shot examples."""
        prompt = RenderedPrompt(
            messages=[
                LLMMessage(
                    role="user",
                    content="Generate code. Return JSON format.",
                )
            ]
        )

        optimizer = PromptOptimizer()
        optimization = optimizer.suggest_optimizations(prompt)

        assert any(
            "example" in s.lower() or "few-shot" in s.lower() for s in optimization.suggestions
        )

    def test_temperature_recommendation_for_code_generation(self) -> None:
        """Test temperature recommendation for code generation tasks."""
        prompt = RenderedPrompt(
            messages=[
                LLMMessage(
                    role="user",
                    content="Generate a unit test function for this code.",
                )
            ]
        )

        optimizer = PromptOptimizer()
        optimization = optimizer.suggest_optimizations(prompt)

        # Code generation should recommend low temperature
        assert optimization.temperature_recommendation is not None
        assert optimization.temperature_recommendation <= 0.3

    def test_temperature_recommendation_for_creative_tasks(self) -> None:
        """Test temperature recommendation for creative/analysis tasks."""
        prompt = RenderedPrompt(
            messages=[
                LLMMessage(
                    role="user",
                    content="Analyze this code and explain what it does creatively.",
                )
            ]
        )

        optimizer = PromptOptimizer()
        optimization = optimizer.suggest_optimizations(prompt)

        # Creative tasks should recommend moderate temperature
        assert optimization.temperature_recommendation is not None
        assert optimization.temperature_recommendation >= 0.3

    def test_max_tokens_recommendation(self, simple_prompt: RenderedPrompt) -> None:
        """Test max_tokens recommendation."""
        optimizer = PromptOptimizer()
        optimization = optimizer.suggest_optimizations(simple_prompt)

        assert optimization.max_tokens_recommendation is not None
        assert optimization.max_tokens_recommendation > 0

    def test_no_suggestions_for_perfect_prompt(self) -> None:
        """Test that a well-optimized prompt gets minimal suggestions."""
        prompt = RenderedPrompt(
            messages=[
                LLMMessage(
                    role="system",
                    content="You are a Python test generator.",
                ),
                LLMMessage(
                    role="user",
                    content="""Task: Generate a pytest test for the function below.

Source code:
```python
def multiply(x: int, y: int) -> int:
    return x * y
```

Output format: Return ONLY valid Python code with no explanations.

Example:
```python
def test_multiply():
    assert multiply(2, 3) == 6
    assert multiply(0, 5) == 0
```

Generate the test.""",
                ),
            ]
        )

        optimizer = PromptOptimizer()
        optimization = optimizer.suggest_optimizations(prompt)

        # Should have minimal or no critical suggestions
        assert len(optimization.suggestions) <= 2

    def test_optimization_with_precomputed_analysis(self, simple_prompt: RenderedPrompt) -> None:
        """Test optimization with pre-computed analysis."""
        analyzer = PromptAnalyzer()
        analysis = analyzer.analyze(simple_prompt)

        optimizer = PromptOptimizer()
        optimization = optimizer.suggest_optimizations(simple_prompt, analysis=analysis)

        assert optimization.current_tokens == analysis.total_tokens
