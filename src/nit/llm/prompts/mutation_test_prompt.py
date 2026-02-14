"""Prompt template for mutation-test generation.

Produces LLM messages that ask the model to generate tests targeting
surviving mutants discovered during mutation testing analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nit.llm.engine import LLMMessage

if TYPE_CHECKING:
    from nit.adapters.mutation.base import SurvivingMutant
    from nit.agents.builders.mutation import MutationTestCase


@dataclass
class MutationTestPromptContext:
    """Context passed to the mutation-test prompt builder."""

    language: str
    """Programming language of the source under test."""

    test_framework: str
    """Test framework to generate tests for (e.g. 'pytest', 'vitest')."""

    source_path: str
    """Path to the source file being tested."""

    source_code: str
    """Full source code of the file under test."""

    test_cases: list[MutationTestCase] = field(default_factory=list)
    """Test cases to generate, one per surviving mutant."""


def build_mutation_test_messages(
    context: MutationTestPromptContext,
) -> list[LLMMessage]:
    """Build LLM messages for generating mutation-killing tests.

    Args:
        context: Mutation test prompt context with mutants and source info.

    Returns:
        List of LLM messages (system + user).
    """
    system_msg = _build_system_instruction(context)
    user_msg = _build_user_message(context)

    return [
        LLMMessage(role="system", content=system_msg),
        LLMMessage(role="user", content=user_msg),
    ]


def _build_system_instruction(context: MutationTestPromptContext) -> str:
    """Build the system-level instruction for mutation test generation.

    Args:
        context: Mutation test prompt context.

    Returns:
        System instruction string.
    """
    return (
        "You are an expert test engineer specialising in mutation testing.\n"
        f"You write tests using the **{context.test_framework}** framework for "
        f"**{context.language}** code.\n\n"
        "Your task is to write tests that **kill surviving mutants**.  A "
        "surviving mutant means the current test suite cannot distinguish "
        "between the original code and a small syntactic change (mutation).\n\n"
        "RULES:\n"
        "1. Output ONLY valid test code — no prose, no markdown fences.\n"
        "2. Each test must fail if the described mutation is applied.\n"
        "3. Use precise assertions that detect the mutation.\n"
        "4. Keep tests focused: one logical assertion per test function.\n"
        "5. Do NOT duplicate existing test coverage — target the gap.\n"
        "6. Use descriptive test names that reference the mutant."
    )


def _format_mutant_section(tc: MutationTestCase) -> str:
    """Format a single mutant into a prompt section.

    Args:
        tc: Mutation test case with mutant details.

    Returns:
        Formatted section string.
    """
    mutant: SurvivingMutant = tc.mutant
    lines = [
        f"### Mutant: {tc.test_name}",
        "",
        f"- **File:** {mutant.file_path}",
        f"- **Line:** {mutant.line_number}",
        f"- **Operator:** {mutant.mutation_operator}",
        f"- **Description:** {mutant.description}",
    ]

    if mutant.original_code:
        lines.extend(
            [
                "",
                "**Original code:**",
                f"```\n{mutant.original_code}\n```",
            ]
        )

    if mutant.mutated_code:
        lines.extend(
            [
                "",
                "**Mutated code (surviving):**",
                f"```\n{mutant.mutated_code}\n```",
            ]
        )

    lines.extend(
        [
            "",
            f"**Suggested strategy:** {tc.test_strategy}",
        ]
    )

    return "\n".join(lines)


def _build_user_message(context: MutationTestPromptContext) -> str:
    """Build the user message listing mutants and source code.

    Args:
        context: Mutation test prompt context.

    Returns:
        User message string.
    """
    sections: list[str] = [
        "## Source Code Under Test",
        "",
        f"File: `{context.source_path}`",
        f"Language: {context.language}",
        "",
        f"```{context.language}",
        context.source_code,
        "```",
        "",
        "## Surviving Mutants",
        "",
        "Generate a test for each of the following surviving mutants:",
        "",
    ]

    sections.extend(_format_mutant_section(tc) for tc in context.test_cases)

    sections.extend(
        [
            "",
            "## Task",
            "",
            f"Write {context.test_framework} tests that kill every mutant listed above.  "
            "Output only the test code.",
        ]
    )

    return "\n".join(sections)
