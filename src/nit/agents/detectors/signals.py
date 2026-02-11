"""Detection signal types for framework identification.

Each signal type represents a different kind of evidence that a particular
framework is in use.  Signals carry a *weight* that the ``FrameworkDetector``
uses when computing a composite confidence score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FrameworkCategory(Enum):
    """The purpose/category of a detected framework."""

    UNIT_TEST = "unit_test"
    E2E_TEST = "e2e_test"
    INTEGRATION_TEST = "integration_test"
    DOC = "doc"
    LINT = "lint"
    BUILD = "build"


# ── Signal dataclasses ──────────────────────────────────────────────


@dataclass(frozen=True)
class ConfigFile:
    """A known configuration file that indicates a framework.

    Example: ``vitest.config.ts`` → Vitest, ``jest.config.js`` → Jest.
    """

    pattern: str
    weight: float = 0.9


@dataclass(frozen=True)
class Dependency:
    """A dependency entry in a manifest file.

    Example: ``vitest`` in ``package.json`` devDependencies → Vitest.
    """

    name: str
    dev_only: bool = False
    weight: float = 0.8


@dataclass(frozen=True)
class ImportPattern:
    """A source-level import/require pattern.

    Example: ``from pytest import ...`` or ``import { describe } from 'vitest'``.
    """

    pattern: str
    weight: float = 0.7


@dataclass(frozen=True)
class FilePattern:
    """A file-naming convention that implies a framework.

    Example: ``**/*.test.ts`` → Vitest/Jest, ``test_*.py`` → pytest.
    """

    glob: str
    weight: float = 0.5


@dataclass(frozen=True)
class CMakePattern:
    """A CMake-specific pattern (``find_package``, ``gtest_discover_tests``, …)."""

    pattern: str
    weight: float = 0.8


@dataclass(frozen=True)
class PackageJsonField:
    """A field inside ``package.json`` (e.g. ``scripts.test`` containing ``vitest``).

    ``field_path`` is dot-separated: ``"scripts.test"``.
    ``value_pattern`` is a substring or regex to match against the field value.
    """

    field_path: str
    value_pattern: str
    weight: float = 0.7


@dataclass(frozen=True)
class CsprojDependency:
    """A NuGet package reference in a ``.csproj`` file.

    Example: ``PackageReference Include="xunit"`` → xUnit.
    """

    name: str
    weight: float = 0.8


# Union of all supported signal types.
Signal = (
    ConfigFile
    | CsprojDependency
    | Dependency
    | ImportPattern
    | FilePattern
    | CMakePattern
    | PackageJsonField
)


# ── Framework rule ──────────────────────────────────────────────────


@dataclass
class FrameworkRule:
    """Declarative rule describing how to detect a single framework.

    The ``FrameworkDetector`` evaluates each rule's signals against the
    project and computes a confidence score from the matching signals.
    """

    name: str
    language: str
    category: FrameworkCategory
    signals: list[Signal] = field(default_factory=list)


# ── Detection result ────────────────────────────────────────────────


@dataclass
class DetectedFramework:
    """A framework that was positively identified in the project."""

    name: str
    language: str
    category: FrameworkCategory
    confidence: float
    matched_signals: list[Signal] = field(default_factory=list)


@dataclass
class FrameworkProfile:
    """Full framework detection result for a project."""

    frameworks: list[DetectedFramework] = field(default_factory=list)
    root: str = ""

    def by_category(self, category: FrameworkCategory) -> list[DetectedFramework]:
        """Return frameworks matching *category*, sorted by confidence descending."""
        return sorted(
            [f for f in self.frameworks if f.category == category],
            key=lambda f: -f.confidence,
        )

    def by_language(self, language: str) -> list[DetectedFramework]:
        """Return frameworks for *language*, sorted by confidence descending."""
        return sorted(
            [f for f in self.frameworks if f.language == language],
            key=lambda f: -f.confidence,
        )
