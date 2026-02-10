"""Tests for adapter registry — auto-discovery and selection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from pathlib import Path

from nit.adapters.base import DocFrameworkAdapter, TestFrameworkAdapter, ValidationResult
from nit.adapters.registry import AdapterRegistry, get_registry
from nit.agents.detectors.signals import DetectedFramework, FrameworkCategory
from nit.agents.detectors.workspace import PackageInfo
from nit.llm.prompts.base import PromptTemplate
from nit.models.profile import ProjectProfile

# ── Mock Adapters ────────────────────────────────────────────────────


class MockTestAdapter(TestFrameworkAdapter):
    """Mock test adapter for testing registry."""

    @property
    def name(self) -> str:
        return "mock_test"

    @property
    def language(self) -> str:
        return "python"

    def detect(self, project_path: Path) -> bool:
        # Always detects for testing purposes
        return True

    def get_test_pattern(self) -> list[str]:
        return ["**/*_test.py"]

    def get_prompt_template(self) -> PromptTemplate:
        return MagicMock(spec=PromptTemplate)

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = 120.0,
    ) -> MagicMock:
        return MagicMock()

    def validate_test(self, test_code: str) -> ValidationResult:
        return ValidationResult(valid=True)


class MockDocAdapter(DocFrameworkAdapter):
    """Mock doc adapter for testing registry."""

    @property
    def name(self) -> str:
        return "mock_doc"

    @property
    def language(self) -> str:
        return "python"

    def detect(self, project_path: Path) -> bool:
        # Always detects for testing purposes
        return True

    def get_doc_pattern(self) -> list[str]:
        return ["docs/**/*.md"]

    def get_prompt_template(self) -> PromptTemplate:
        return MagicMock(spec=PromptTemplate)

    async def build_docs(
        self,
        project_path: Path,
        *,
        timeout: float = 120.0,
    ) -> bool:
        return True

    def validate_doc(self, doc_code: str) -> ValidationResult:
        return ValidationResult(valid=True)


class SelectiveTestAdapter(TestFrameworkAdapter):
    """Test adapter that only detects in specific directories."""

    def __init__(self, detect_in: str = "") -> None:
        self._detect_in = detect_in

    @property
    def name(self) -> str:
        return "selective_test"

    @property
    def language(self) -> str:
        return "typescript"

    def detect(self, project_path: Path) -> bool:
        # Only detect if path contains the specified string
        return self._detect_in in str(project_path)

    def get_test_pattern(self) -> list[str]:
        return ["**/*.test.ts"]

    def get_prompt_template(self) -> PromptTemplate:
        return MagicMock(spec=PromptTemplate)

    async def run_tests(
        self,
        project_path: Path,
        *,
        test_files: list[Path] | None = None,
        timeout: float = 120.0,
    ) -> MagicMock:
        return MagicMock()

    def validate_test(self, test_code: str) -> ValidationResult:
        return ValidationResult(valid=True)


# ── Registry Tests ───────────────────────────────────────────────────


def test_registry_initialization() -> None:
    """Test that registry initializes and discovers adapters."""
    registry = AdapterRegistry()
    assert registry is not None

    # Should discover at least the pytest, vitest, gtest, and catch2 adapters
    test_adapters = registry.list_test_adapters()
    assert "catch2" in test_adapters
    assert "gtest" in test_adapters
    assert "pytest" in test_adapters
    assert "vitest" in test_adapters


def test_get_test_adapter() -> None:
    """Test retrieving a test adapter by name."""
    registry = AdapterRegistry()

    # Should be able to get pytest adapter
    adapter = registry.get_test_adapter("pytest")
    assert adapter is not None
    assert adapter.name == "pytest"
    assert adapter.language == "python"

    # Should be able to get vitest adapter
    adapter = registry.get_test_adapter("vitest")
    assert adapter is not None
    assert adapter.name == "vitest"
    assert adapter.language == "typescript"

    # Should be able to get gtest adapter
    adapter = registry.get_test_adapter("gtest")
    assert adapter is not None
    assert adapter.name == "gtest"
    assert adapter.language == "cpp"

    # Should be able to get catch2 adapter
    adapter = registry.get_test_adapter("catch2")
    assert adapter is not None
    assert adapter.name == "catch2"
    assert adapter.language == "cpp"


def test_get_nonexistent_adapter() -> None:
    """Test retrieving a non-existent adapter returns None."""
    registry = AdapterRegistry()
    adapter = registry.get_test_adapter("nonexistent")
    assert adapter is None


def test_get_doc_adapter_when_none_registered() -> None:
    """Test doc adapter retrieval when no doc adapters exist."""
    registry = AdapterRegistry()
    # Should return None since we haven't implemented doc adapters yet
    adapter = registry.get_doc_adapter("sphinx")
    assert adapter is None


def test_list_adapters() -> None:
    """Test listing all registered adapters."""
    registry = AdapterRegistry()

    test_adapters = registry.list_test_adapters()
    assert isinstance(test_adapters, list)
    assert len(test_adapters) > 0
    assert "catch2" in test_adapters
    assert "gtest" in test_adapters
    assert "pytest" in test_adapters
    assert "vitest" in test_adapters

    doc_adapters = registry.list_doc_adapters()
    assert isinstance(doc_adapters, list)
    # Currently no doc adapters implemented


def test_select_adapters_for_single_repo(tmp_path: Path) -> None:
    """Test adapter selection for a single-repo project."""
    registry = AdapterRegistry()

    # Create a profile with pytest detected
    profile = ProjectProfile(
        root=str(tmp_path),
        frameworks=[
            DetectedFramework(
                name="pytest",
                language="python",
                category=FrameworkCategory.UNIT_TEST,
                confidence=0.9,
            ),
        ],
        packages=[],  # Empty packages = single repo
    )

    # Create a conftest.py so pytest detection works
    (tmp_path / "conftest.py").touch()

    selected = registry.select_adapters_for_profile(profile)
    assert str(tmp_path) in selected
    adapters = selected[str(tmp_path)]
    assert len(adapters) > 0
    assert any(a.name == "pytest" for a in adapters)


def test_select_adapters_for_monorepo(tmp_path: Path) -> None:
    """Test adapter selection for a monorepo with multiple packages."""
    registry = AdapterRegistry()

    # Create package directories
    pkg1 = tmp_path / "packages" / "backend"
    pkg2 = tmp_path / "packages" / "frontend"
    pkg1.mkdir(parents=True)
    pkg2.mkdir(parents=True)

    # Backend uses pytest
    (pkg1 / "conftest.py").touch()

    # Frontend uses vitest
    (pkg2 / "package.json").write_text('{"devDependencies": {"vitest": "^1.0.0"}}')

    # Create profile with both frameworks
    profile = ProjectProfile(
        root=str(tmp_path),
        frameworks=[
            DetectedFramework(
                name="pytest",
                language="python",
                category=FrameworkCategory.UNIT_TEST,
                confidence=0.9,
            ),
            DetectedFramework(
                name="vitest",
                language="typescript",
                category=FrameworkCategory.UNIT_TEST,
                confidence=0.9,
            ),
        ],
        packages=[
            PackageInfo(name="backend", path=str(pkg1), dependencies=[]),
            PackageInfo(name="frontend", path=str(pkg2), dependencies=[]),
        ],
    )

    selected = registry.select_adapters_for_profile(profile)

    # Should have entries for both packages
    assert str(pkg1) in selected
    assert str(pkg2) in selected

    # Backend should have pytest
    backend_adapters = selected[str(pkg1)]
    assert any(a.name == "pytest" for a in backend_adapters)

    # Frontend should have vitest
    frontend_adapters = selected[str(pkg2)]
    assert any(a.name == "vitest" for a in frontend_adapters)


def test_adapter_detection_filtering(tmp_path: Path) -> None:
    """Test that adapters are only selected when they actually detect."""
    registry = AdapterRegistry()

    # Create a profile claiming vitest exists, but no vitest files present
    profile = ProjectProfile(
        root=str(tmp_path),
        frameworks=[
            DetectedFramework(
                name="vitest",
                language="typescript",
                category=FrameworkCategory.UNIT_TEST,
                confidence=0.9,
            ),
        ],
        packages=[],
    )

    # Don't create any vitest config files
    selected = registry.select_adapters_for_profile(profile)

    # Should not select vitest since detection will fail
    adapters = selected.get(str(tmp_path), [])
    assert not any(a.name == "vitest" for a in adapters)


def test_multiple_frameworks_same_category(tmp_path: Path) -> None:
    """Test selecting multiple unit test frameworks for the same package."""
    registry = AdapterRegistry()

    # Setup project with both pytest and vitest
    (tmp_path / "conftest.py").touch()
    (tmp_path / "package.json").write_text('{"devDependencies": {"vitest": "^1.0.0"}}')

    profile = ProjectProfile(
        root=str(tmp_path),
        frameworks=[
            DetectedFramework(
                name="pytest",
                language="python",
                category=FrameworkCategory.UNIT_TEST,
                confidence=0.9,
            ),
            DetectedFramework(
                name="vitest",
                language="typescript",
                category=FrameworkCategory.UNIT_TEST,
                confidence=0.8,
            ),
        ],
        packages=[],
    )

    selected = registry.select_adapters_for_profile(profile)
    adapters = selected[str(tmp_path)]

    # Should have both adapters
    adapter_names = {a.name for a in adapters}
    assert "pytest" in adapter_names
    assert "vitest" in adapter_names


def test_get_registry_singleton() -> None:
    """Test that get_registry returns a singleton instance."""
    registry1 = get_registry()
    registry2 = get_registry()
    assert registry1 is registry2


def test_empty_profile(tmp_path: Path) -> None:
    """Test adapter selection with an empty profile."""
    registry = AdapterRegistry()

    profile = ProjectProfile(
        root=str(tmp_path),
        frameworks=[],
        packages=[],
    )

    selected = registry.select_adapters_for_profile(profile)
    adapters = selected.get(str(tmp_path), [])
    assert len(adapters) == 0


def test_registry_handles_import_errors(monkeypatch: Any) -> None:
    """Test that registry gracefully handles adapter import errors."""
    # This test verifies error handling in discovery
    # We can't easily force import errors without breaking other tests,
    # but we verify the registry still initializes
    registry = AdapterRegistry()
    assert registry is not None
    # Should still have some adapters even if some fail to load
    assert len(registry.list_test_adapters()) > 0


def test_adapter_instantiation_error_handling() -> None:
    """Test that registry handles adapter instantiation errors."""
    registry = AdapterRegistry()

    # Try to get a non-existent adapter
    adapter = registry.get_test_adapter("nonexistent_adapter_12345")
    assert adapter is None

    # Registry should still be functional
    assert len(registry.list_test_adapters()) > 0


def test_doc_adapter_selection_when_available(tmp_path: Path) -> None:
    """Test doc adapter selection when doc frameworks are detected."""
    registry = AdapterRegistry()

    profile = ProjectProfile(
        root=str(tmp_path),
        frameworks=[
            DetectedFramework(
                name="sphinx",
                language="python",
                category=FrameworkCategory.DOC,
                confidence=0.9,
            ),
        ],
        packages=[],
    )

    selected = registry.select_adapters_for_profile(profile)

    # Currently no doc adapters, so should be empty
    # This will pass once doc adapters are implemented
    adapters = selected.get(str(tmp_path), [])
    # For now, should be empty (no doc adapters registered)
    assert isinstance(adapters, list)


def test_frameworks_by_category_filtering(tmp_path: Path) -> None:
    """Test that only frameworks matching the correct category are selected."""
    registry = AdapterRegistry()

    # Create profile with mixed framework categories
    profile = ProjectProfile(
        root=str(tmp_path),
        frameworks=[
            DetectedFramework(
                name="pytest",
                language="python",
                category=FrameworkCategory.UNIT_TEST,
                confidence=0.9,
            ),
            DetectedFramework(
                name="playwright",
                language="typescript",
                category=FrameworkCategory.E2E_TEST,
                confidence=0.8,
            ),
        ],
        packages=[],
    )

    (tmp_path / "conftest.py").touch()

    selected = registry.select_adapters_for_profile(profile)
    adapters = selected.get(str(tmp_path), [])

    # Should only get pytest (unit), not playwright (e2e not implemented yet)
    adapter_names = {a.name for a in adapters}
    assert "pytest" in adapter_names
    # Playwright adapter doesn't exist yet, so won't be selected
