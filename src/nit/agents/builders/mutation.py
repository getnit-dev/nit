"""MutationTestBuilder — generates test cases to kill surviving mutants.

Given a ``MutationAnalysisResult``, this builder produces a list of
``MutationTestCase`` entries describing what test to write for each
surviving mutant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nit.adapters.mutation.base import SurvivingMutant
    from nit.agents.analyzers.mutation import MutationAnalysisResult

logger = logging.getLogger(__name__)


@dataclass
class MutationTestCase:
    """A test case designed to kill a surviving mutant."""

    mutant: SurvivingMutant
    """The surviving mutant this test targets."""

    test_name: str
    """Suggested name for the test function."""

    test_strategy: str
    """Strategy description for how to kill this mutant."""

    description: str
    """Human-readable explanation of the test."""


# Mapping of mutation operators to testing strategies
_STRATEGY_MAP: dict[str, str] = {
    "ConditionalBoundary": (
        "Test boundary values — supply inputs that sit exactly on the conditional "
        "boundary (e.g. n == threshold) so that flipping < to <= or > to >= "
        "produces a different result."
    ),
    "NegateConditional": (
        "Assert the exact boolean outcome of the condition for both true and "
        "false branches.  If the condition is negated the wrong branch will "
        "execute and the assertion will fail."
    ),
    "RemoveConditional": (
        "Ensure both branches of the conditional are exercised and produce "
        "observably different results.  With the conditional removed only one "
        "branch runs, which should break the assertion."
    ),
    "ReturnValues": (
        "Assert the precise return value of the function.  Mutating the "
        "return expression (e.g. returning 0 instead of the computed value) "
        "will fail the equality check."
    ),
    "VoidMethodCall": (
        "Verify the observable side-effect of the void method call.  "
        "Removing the call should leave state unchanged, which the test "
        "can detect via assertions on that state."
    ),
    "MathMutator": (
        "Test with inputs where swapping the math operator (e.g. + to -) "
        "gives a numerically different result.  Assert the exact expected "
        "output."
    ),
    "IncrementsMutator": (
        "Use inputs where incrementing vs decrementing produces a detectably "
        "different value.  Assert the exact expected output."
    ),
    "InvertNegsMutator": (
        "Test with a value whose sign matters.  Negating the value should "
        "produce a wrong result that the assertion catches."
    ),
}

_DEFAULT_STRATEGY = (
    "Write a test that exercises the mutated code path and asserts the "
    "correct behaviour.  The surviving mutant indicates the current tests "
    "do not distinguish the original code from the mutation."
)


class MutationTestBuilder:
    """Generates test-case plans for surviving mutants.

    Given a ``MutationAnalysisResult``, this builder creates a
    ``MutationTestCase`` for each surviving mutant describing what test
    to write and what strategy to use.
    """

    def generate_test_plan(
        self,
        analysis: MutationAnalysisResult,
        *,
        high_priority_only: bool = False,
    ) -> list[MutationTestCase]:
        """Generate a test case for each surviving mutant.

        Args:
            analysis: Result from ``MutationTestAnalyzer.analyze()``.
            high_priority_only: If ``True``, only generate test cases for
                high-priority surviving mutants.

        Returns:
            List of ``MutationTestCase`` entries.
        """
        mutants = (
            analysis.high_priority_mutants
            if high_priority_only
            else analysis.report.surviving_mutants
        )

        cases = [self._build_test_case(mutant, idx) for idx, mutant in enumerate(mutants)]

        logger.info(
            "Generated %d mutation test cases from %s analysis",
            len(cases),
            analysis.adapter_name,
        )

        return cases

    @staticmethod
    def _build_test_case(mutant: SurvivingMutant, index: int) -> MutationTestCase:
        """Build a single test case for a surviving mutant.

        Args:
            mutant: The surviving mutant to target.
            index: Index for generating unique test names.

        Returns:
            A ``MutationTestCase``.
        """
        # Sanitise file path for use in a test-function name
        safe_file = (
            mutant.file_path.replace("/", "_")
            .replace("\\", "_")
            .replace(".", "_")
            .replace("-", "_")
        )

        test_name = f"test_kill_mutant_{safe_file}_line{mutant.line_number}_{index}"

        strategy = _STRATEGY_MAP.get(mutant.mutation_operator, _DEFAULT_STRATEGY)

        description = (
            f"Kill surviving mutant in {mutant.file_path} at line "
            f"{mutant.line_number}: {mutant.description}"
        )

        return MutationTestCase(
            mutant=mutant,
            test_name=test_name,
            test_strategy=strategy,
            description=description,
        )
