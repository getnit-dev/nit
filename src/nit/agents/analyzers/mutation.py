"""MutationTestAnalyzer — runs mutation testing and identifies high-priority gaps.

This analyzer:
1. Auto-detects which mutation testing tool to use via adapter detection
2. Runs the mutation tests
3. Identifies high-priority surviving mutants (in critical code paths)
4. Produces a ``MutationAnalysisResult`` for downstream builders
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nit.adapters.mutation.base import MutationTestReport, SurvivingMutant
from nit.adapters.mutation.mutmut_adapter import MutmutAdapter
from nit.adapters.mutation.pitest_adapter import PitestAdapter
from nit.adapters.mutation.stryker_adapter import StrykerAdapter

if TYPE_CHECKING:
    from pathlib import Path

    from nit.adapters.mutation.base import MutationTestingAdapter

logger = logging.getLogger(__name__)

# Mutation operators that indicate high-risk surviving mutants
_HIGH_PRIORITY_OPERATORS = frozenset(
    {
        "ConditionalBoundary",
        "NegateConditional",
        "RemoveConditional",
        "ReturnValues",
        "VoidMethodCall",
        "MathMutator",
        "IncrementsMutator",
        "InvertNegsMutator",
    }
)


@dataclass
class MutationAnalysisResult:
    """Result of mutation testing analysis."""

    adapter_name: str
    """Name of the mutation testing adapter that was used."""

    report: MutationTestReport
    """Full mutation testing report."""

    high_priority_mutants: list[SurvivingMutant] = field(default_factory=list)
    """Surviving mutants considered high-priority based on operator or location."""


class MutationTestAnalyzer:
    """Analyzes a project using mutation testing to identify test-suite gaps.

    Auto-detects the appropriate mutation testing tool, runs the analysis,
    and classifies surviving mutants by priority.
    """

    def __init__(
        self,
        *,
        adapters: list[MutationTestingAdapter] | None = None,
        high_priority_operators: frozenset[str] | None = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            adapters: Mutation testing adapters to consider.  If ``None``,
                the built-in adapters (Stryker, mutmut, PIT) are used.
            high_priority_operators: Mutation operator names that make a
                surviving mutant high-priority.  If ``None``, the built-in
                set is used.
        """
        self._adapters: list[MutationTestingAdapter] = adapters or [
            StrykerAdapter(),
            MutmutAdapter(),
            PitestAdapter(),
        ]
        self._high_priority_ops = high_priority_operators or _HIGH_PRIORITY_OPERATORS

    async def analyze(
        self,
        project_root: Path,
        *,
        source_files: list[str] | None = None,
        timeout: float = 300.0,
    ) -> MutationAnalysisResult:
        """Run mutation testing and return analysis results.

        Detects the appropriate adapter, runs mutation tests, and classifies
        surviving mutants.

        Args:
            project_root: Root directory of the project.
            source_files: Optional list of source files to limit mutation to.
            timeout: Maximum seconds to wait for the mutation run.

        Returns:
            ``MutationAnalysisResult`` with report and high-priority mutants.
        """
        adapter = self._detect_adapter(project_root)
        if adapter is None:
            logger.warning("No mutation testing tool detected in %s", project_root)
            return MutationAnalysisResult(
                adapter_name="none",
                report=MutationTestReport(tool="none"),
            )

        logger.info("Using mutation testing adapter: %s", adapter.name)

        report = await adapter.run_mutation_tests(
            project_root,
            source_files=source_files,
            timeout=timeout,
        )

        logger.info(
            "Mutation testing complete: %d total, %d killed, %d survived (%.1f%% score)",
            report.total_mutants,
            report.killed,
            report.survived,
            report.mutation_score,
        )

        high_priority = self._identify_high_priority(report.surviving_mutants)

        logger.info(
            "Identified %d high-priority surviving mutants out of %d",
            len(high_priority),
            len(report.surviving_mutants),
        )

        return MutationAnalysisResult(
            adapter_name=adapter.name,
            report=report,
            high_priority_mutants=high_priority,
        )

    def _detect_adapter(self, project_root: Path) -> MutationTestingAdapter | None:
        """Auto-detect which mutation testing adapter to use.

        Args:
            project_root: Root directory of the project.

        Returns:
            The first adapter that detects its tool, or ``None``.
        """
        for adapter in self._adapters:
            if adapter.detect(project_root):
                return adapter
        return None

    def _identify_high_priority(
        self,
        surviving: list[SurvivingMutant],
    ) -> list[SurvivingMutant]:
        """Classify surviving mutants as high-priority.

        A mutant is high-priority if its mutation operator is in the
        known-critical set.

        Args:
            surviving: All surviving mutants.

        Returns:
            Subset of surviving mutants considered high-priority.
        """
        return [m for m in surviving if m.mutation_operator in self._high_priority_ops]
