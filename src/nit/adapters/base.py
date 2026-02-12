"""Abstract base classes for test and doc framework adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from nit.adapters.coverage.base import CoverageReport
    from nit.llm.prompts.base import PromptTemplate


class CaseStatus(Enum):
    """Outcome of a single test case."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class CaseResult:
    """Result of a single test case execution."""

    name: str
    status: CaseStatus
    duration_ms: float = 0.0
    failure_message: str = ""
    file_path: str = ""


@dataclass
class RunResult:
    """Aggregated result of a test run."""

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: float = 0.0
    test_cases: list[CaseResult] = field(default_factory=list)
    raw_output: str = ""
    success: bool = False
    coverage: CoverageReport | None = None

    @property
    def total(self) -> int:
        """Total number of test cases."""
        return self.passed + self.failed + self.skipped + self.errors


@dataclass
class ValidationResult:
    """Result of validating generated test code."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class TestFrameworkAdapter(ABC):
    """Abstract base class for test framework adapters.

    Each concrete adapter knows how to detect, generate prompts for,
    run, and validate tests for a specific framework (e.g. Vitest, pytest).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Framework identifier (e.g. ``'vitest'``, ``'pytest'``)."""

    @property
    @abstractmethod
    def language(self) -> str:
        """Primary language (e.g. ``'typescript'``, ``'python'``)."""

    @abstractmethod
    def detect(self, project_path: Path) -> bool:
        """Return ``True`` if this framework is present in *project_path*."""

    @abstractmethod
    def get_test_pattern(self) -> list[str]:
        """Return glob patterns for test files (e.g. ``['**/*.test.ts']``)."""

    @abstractmethod
    def get_prompt_template(self) -> PromptTemplate:
        """Return the prompt template for generating tests with this framework."""

    @abstractmethod
    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = 120.0,
    ) -> RunResult:
        """Execute tests and return structured results.

        Args:
            project_path: Root of the project containing the tests.
            test_files: Specific test files to run.  ``None`` runs all.
            timeout: Maximum seconds to wait for test execution.

        Returns:
            A ``RunResult`` with pass/fail counts and per-case details.
        """

    @abstractmethod
    def validate_test(self, test_code: str) -> ValidationResult:
        """Validate that *test_code* is syntactically correct.

        Uses tree-sitter (or equivalent) to parse the code without executing it.
        """

    def get_required_packages(self) -> list[str]:
        """Return list of required packages for this adapter.

        Override this method to specify packages that must be installed
        for the test framework to work (e.g., ``["pytest", "pytest-json-report"]``
        for pytest).

        Returns:
            List of package names. Empty list means no packages required.
        """
        return []

    def get_required_commands(self) -> list[str]:
        """Return list of required commands for this adapter.

        Override this method to specify commands that must be available
        in PATH or the local environment (e.g., ``["node"]`` for Vitest).

        Returns:
            List of command names. Empty list means no commands required.
        """
        return []


class DocFrameworkAdapter(ABC):
    """Abstract base class for documentation framework adapters.

    Each concrete adapter knows how to detect, generate prompts for,
    build, and validate documentation for a specific framework
    (e.g. TypeDoc, Sphinx, Doxygen).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Framework identifier (e.g. ``'typedoc'``, ``'sphinx'``, ``'doxygen'``)."""

    @property
    @abstractmethod
    def language(self) -> str:
        """Primary language (e.g. ``'typescript'``, ``'python'``, ``'cpp'``)."""

    @abstractmethod
    def detect(self, project_path: Path) -> bool:
        """Return ``True`` if this framework is present in *project_path*."""

    @abstractmethod
    def get_doc_pattern(self) -> list[str]:
        """Return glob patterns for doc source files (e.g. ``['docs/**/*.rst']``)."""

    @abstractmethod
    def get_prompt_template(self) -> PromptTemplate:
        """Return the prompt template for generating docs with this framework."""

    @abstractmethod
    async def build_docs(
        self,
        project_path: Path,
        *,
        timeout: float = 120.0,
    ) -> bool:
        """Build documentation and return ``True`` if successful.

        Args:
            project_path: Root of the project containing the documentation.
            timeout: Maximum seconds to wait for doc build.

        Returns:
            ``True`` if the documentation built successfully, ``False`` otherwise.
        """

    @abstractmethod
    def validate_doc(self, doc_code: str) -> ValidationResult:
        """Validate that *doc_code* is syntactically correct.

        Uses language-specific parsers to check docstring/comment syntax
        without building the full documentation.
        """
