"""Base classes and data models for mutation testing adapters.

Mutation testing introduces small changes (mutants) to source code and checks
whether the existing test suite catches them.  Surviving mutants indicate
gaps in test effectiveness.  Each concrete adapter wraps a specific mutation
testing tool (Stryker, mutmut, PIT, etc.) and produces a unified
``MutationTestReport``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class SurvivingMutant:
    """A mutant that the test suite failed to detect (kill)."""

    file_path: str
    """Path to the source file containing the mutant."""

    line_number: int
    """Line number where the mutation was applied."""

    original_code: str
    """Original source code at the mutation site."""

    mutated_code: str
    """Mutated source code that survived."""

    mutation_operator: str
    """Name of the mutation operator (e.g. 'ConditionalBoundary')."""

    description: str
    """Human-readable description of what the mutation did."""


@dataclass
class MutationTestReport:
    """Unified report produced by any mutation testing adapter."""

    tool: str
    """Name of the mutation testing tool (e.g. 'stryker', 'mutmut', 'pitest')."""

    total_mutants: int = 0
    """Total number of mutants generated."""

    killed: int = 0
    """Number of mutants detected (killed) by the test suite."""

    survived: int = 0
    """Number of mutants that the test suite failed to detect."""

    timed_out: int = 0
    """Number of mutants whose test runs timed out."""

    mutation_score: float = 0.0
    """Mutation score as a percentage (0.0-100.0)."""

    surviving_mutants: list[SurvivingMutant] = field(default_factory=list)
    """Details of each surviving mutant."""


class MutationTestingAdapter(ABC):
    """Abstract base class for mutation testing tool adapters.

    Each concrete adapter knows how to run a mutation testing tool and parse
    its output into the unified ``MutationTestReport`` format.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Mutation tool identifier (e.g. 'stryker', 'mutmut', 'pitest')."""

    @property
    @abstractmethod
    def language(self) -> str:
        """Primary language (e.g. 'javascript', 'python', 'java')."""

    @abstractmethod
    def detect(self, project_root: Path) -> bool:
        """Return True if this mutation tool is configured in *project_root*."""

    @abstractmethod
    async def run_mutation_tests(
        self,
        project_root: Path,
        *,
        source_files: list[str] | None = None,
        timeout: float = 300.0,
    ) -> MutationTestReport:
        """Run mutation tests and return a unified report.

        Args:
            project_root: Root of the project to test.
            source_files: Optional list of source files to limit mutation to.
            timeout: Maximum seconds to wait for the mutation run.

        Returns:
            A ``MutationTestReport`` with results.
        """
