"""Integration tests for the detection pipeline.

Tests StackDetector + FrameworkDetector + AdapterRegistry working together
to detect languages, frameworks, and select adapters for real project layouts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.adapters.registry import AdapterRegistry
from nit.agents.detectors.framework import detect_frameworks
from nit.agents.detectors.signals import FrameworkCategory
from nit.agents.detectors.stack import detect_languages
from tests.integration.conftest import write_file, write_json

# ── Helpers ──────────────────────────────────────────────────────


def _framework_names(root: Path) -> list[str]:
    """Detect frameworks and return their names sorted."""
    profile = detect_frameworks(root)
    return sorted(fw.name for fw in profile.frameworks)


def _unit_framework_names(root: Path) -> list[str]:
    """Detect unit test frameworks and return their names sorted."""
    profile = detect_frameworks(root)
    return sorted(
        fw.name for fw in profile.frameworks if fw.category == FrameworkCategory.UNIT_TEST
    )


# ── Vitest detection pipeline ────────────────────────────────────


@pytest.mark.integration
class TestVitestDetectionPipeline:
    """Full pipeline: stack detect -> framework detect -> adapter select for Vitest."""

    def test_detects_javascript_language(self, vitest_project: Path) -> None:
        lang_profile = detect_languages(vitest_project)
        assert lang_profile.primary_language == "typescript"

    def test_detects_vitest_framework(self, vitest_project: Path) -> None:
        fw_profile = detect_frameworks(vitest_project)
        unit_names = [
            fw.name for fw in fw_profile.frameworks if fw.category == FrameworkCategory.UNIT_TEST
        ]
        assert "vitest" in unit_names

    def test_vitest_framework_confidence_high(self, vitest_project: Path) -> None:
        fw_profile = detect_frameworks(vitest_project)
        vitest_fws = [fw for fw in fw_profile.frameworks if fw.name == "vitest"]
        assert len(vitest_fws) == 1
        # Config file (0.9) + dependency (0.8) + import + file patterns => high confidence
        assert vitest_fws[0].confidence >= 0.8

    def test_registry_selects_vitest_adapter(self, vitest_project: Path) -> None:
        registry = AdapterRegistry()
        adapter = registry.get_test_adapter("vitest")
        assert adapter is not None
        assert adapter.name == "vitest"
        assert adapter.detect(vitest_project)


# ── Pytest detection pipeline ────────────────────────────────────


@pytest.mark.integration
class TestPytestDetectionPipeline:
    """Full pipeline for pytest projects."""

    def test_detects_python_language(self, py_test_project: Path) -> None:
        lang_profile = detect_languages(py_test_project)
        assert lang_profile.primary_language == "python"

    def test_detects_pytest_framework(self, py_test_project: Path) -> None:
        names = _unit_framework_names(py_test_project)
        assert "pytest" in names

    def test_registry_selects_pytest_adapter(self, py_test_project: Path) -> None:
        registry = AdapterRegistry()
        adapter = registry.get_test_adapter("pytest")
        assert adapter is not None
        assert adapter.detect(py_test_project)


# ── Cargo test detection pipeline ────────────────────────────────


@pytest.mark.integration
class TestCargoTestDetectionPipeline:
    """Full pipeline for Rust cargo test projects."""

    def test_detects_rust_language(self, cargo_project: Path) -> None:
        lang_profile = detect_languages(cargo_project)
        assert lang_profile.primary_language == "rust"

    def test_detects_cargo_test_framework(self, cargo_project: Path) -> None:
        names = _unit_framework_names(cargo_project)
        assert "cargo_test" in names

    def test_registry_selects_cargo_test_adapter(self, cargo_project: Path) -> None:
        registry = AdapterRegistry()
        adapter = registry.get_test_adapter("cargo_test")
        assert adapter is not None
        assert adapter.detect(cargo_project)


# ── Go test detection pipeline ───────────────────────────────────


@pytest.mark.integration
class TestGoTestDetectionPipeline:
    """Full pipeline for Go test projects."""

    def test_detects_go_language(self, go_project: Path) -> None:
        lang_profile = detect_languages(go_project)
        assert lang_profile.primary_language == "go"

    def test_detects_gotest_framework(self, go_project: Path) -> None:
        names = _unit_framework_names(go_project)
        assert "gotest" in names

    def test_registry_selects_gotest_adapter(self, go_project: Path) -> None:
        registry = AdapterRegistry()
        adapter = registry.get_test_adapter("gotest")
        assert adapter is not None
        assert adapter.detect(go_project)


# ── GTest detection pipeline ─────────────────────────────────────


@pytest.mark.integration
class TestGTestDetectionPipeline:
    """Full pipeline for Google Test (C++) projects."""

    def test_detects_gtest_framework(self, gtest_project: Path) -> None:
        names = _unit_framework_names(gtest_project)
        assert "gtest" in names

    def test_registry_selects_gtest_adapter(self, gtest_project: Path) -> None:
        registry = AdapterRegistry()
        adapter = registry.get_test_adapter("gtest")
        assert adapter is not None
        assert adapter.detect(gtest_project)


# ── Catch2 detection pipeline ────────────────────────────────────


@pytest.mark.integration
class TestCatch2DetectionPipeline:
    """Full pipeline for Catch2 (C++) projects."""

    def test_detects_catch2_framework(self, catch2_project: Path) -> None:
        names = _unit_framework_names(catch2_project)
        assert "catch2" in names

    def test_registry_selects_catch2_adapter(self, catch2_project: Path) -> None:
        registry = AdapterRegistry()
        adapter = registry.get_test_adapter("catch2")
        assert adapter is not None
        assert adapter.detect(catch2_project)


# ── JUnit 5 detection pipeline ───────────────────────────────────


@pytest.mark.integration
class TestJUnit5DetectionPipeline:
    """Full pipeline for JUnit 5 (Java) projects."""

    def test_detects_java_language(self, junit5_project: Path) -> None:
        lang_profile = detect_languages(junit5_project)
        assert lang_profile.primary_language == "java"

    def test_detects_junit5_framework(self, junit5_project: Path) -> None:
        names = _unit_framework_names(junit5_project)
        assert "junit5" in names

    def test_registry_selects_junit5_adapter(self, junit5_project: Path) -> None:
        registry = AdapterRegistry()
        adapter = registry.get_test_adapter("junit5")
        assert adapter is not None
        assert adapter.detect(junit5_project)


# ── xUnit detection pipeline ─────────────────────────────────────


@pytest.mark.integration
class TestXUnitDetectionPipeline:
    """Full pipeline for xUnit (C#/.NET) projects."""

    def test_detects_csharp_language(self, xunit_project: Path) -> None:
        lang_profile = detect_languages(xunit_project)
        assert lang_profile.primary_language == "csharp"

    def test_detects_xunit_framework(self, xunit_project: Path) -> None:
        names = _unit_framework_names(xunit_project)
        assert "xunit" in names

    def test_registry_selects_xunit_adapter(self, xunit_project: Path) -> None:
        registry = AdapterRegistry()
        adapter = registry.get_test_adapter("xunit")
        assert adapter is not None
        assert adapter.detect(xunit_project)


# ── Monorepo detection pipeline ──────────────────────────────────


@pytest.mark.integration
class TestMonorepoDetection:
    """Test detection across a monorepo with nested packages."""

    def test_monorepo_detects_multiple_languages(self, tmp_path: Path) -> None:
        """A monorepo with JS and Python packages detects both languages."""
        # JS package
        write_json(
            tmp_path,
            "packages/web/package.json",
            {"name": "web", "devDependencies": {"vitest": "^1.0.0"}},
        )
        write_file(
            tmp_path,
            "packages/web/src/app.test.ts",
            'import { describe } from "vitest";\n',
        )

        # Python package
        write_file(
            tmp_path,
            "packages/api/pyproject.toml",
            '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
            '[project.optional-dependencies]\ndev = ["pytest"]\n',
        )
        write_file(
            tmp_path,
            "packages/api/tests/test_main.py",
            "import pytest\n\ndef test_hello():\n    assert True\n",
        )

        lang_profile = detect_languages(tmp_path)
        detected_langs = {li.language for li in lang_profile.languages}
        assert "typescript" in detected_langs
        assert "python" in detected_langs

    def test_monorepo_detects_nested_frameworks(self, tmp_path: Path) -> None:
        """Framework detection at sub-package roots finds the correct framework."""
        # JS/Vitest sub-package
        js_root = tmp_path / "packages" / "web"
        write_json(
            tmp_path,
            "packages/web/package.json",
            {"name": "web", "devDependencies": {"vitest": "^1.0.0"}},
        )
        write_file(js_root, "src/app.test.ts", 'import { it } from "vitest";\n')

        # Python/pytest sub-package
        py_root = tmp_path / "packages" / "api"
        write_file(
            tmp_path,
            "packages/api/pyproject.toml",
            '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
            '[project.optional-dependencies]\ndev = ["pytest"]\n',
        )
        write_file(py_root, "tests/test_main.py", "def test_ok(): pass\n")

        # Detect at each sub-package level
        js_fw = detect_frameworks(js_root)
        py_fw = detect_frameworks(py_root)

        js_names = sorted(fw.name for fw in js_fw.frameworks)
        py_names = sorted(fw.name for fw in py_fw.frameworks)

        assert "vitest" in js_names
        assert "pytest" in py_names

    def test_monorepo_adapter_selection_per_package(self, tmp_path: Path) -> None:
        """AdapterRegistry correctly selects different adapters per sub-package."""
        registry = AdapterRegistry()

        # Go sub-package
        go_root = tmp_path / "services" / "auth"
        write_file(
            tmp_path,
            "services/auth/go.mod",
            "module example.com/auth\n\ngo 1.21\n",
        )
        write_file(
            tmp_path,
            "services/auth/handler_test.go",
            'package auth\n\nimport "testing"\n\nfunc TestHandler(t *testing.T) {}\n',
        )

        # Rust sub-package
        rust_root = tmp_path / "services" / "core"
        write_file(
            tmp_path,
            "services/core/Cargo.toml",
            '[package]\nname = "core"\nversion = "0.1.0"\nedition = "2021"\n',
        )
        write_file(
            tmp_path,
            "services/core/src/lib.rs",
            "#[cfg(test)]\nmod tests {\n    #[test]\n    fn it_works() {}\n}\n",
        )

        go_adapter = registry.get_test_adapter("gotest")
        rust_adapter = registry.get_test_adapter("cargo_test")

        assert go_adapter is not None
        assert rust_adapter is not None
        assert go_adapter.detect(go_root)
        assert rust_adapter.detect(rust_root)

        # Verify cross-detection doesn't happen
        assert not go_adapter.detect(rust_root)
        assert not rust_adapter.detect(go_root)


# ── Registry completeness ────────────────────────────────────────


@pytest.mark.integration
class TestRegistryCompleteness:
    """Verify the adapter registry discovers all expected adapters."""

    def test_all_unit_adapters_registered(self) -> None:
        registry = AdapterRegistry()
        adapters = registry.list_test_adapters()
        expected = {
            "pytest",
            "vitest",
            "gtest",
            "catch2",
            "cargo_test",
            "gotest",
            "junit5",
            "xunit",
        }
        assert expected.issubset(set(adapters)), f"Missing adapters: {expected - set(adapters)}"

    def test_get_and_detect_roundtrip(self, tmp_path: Path) -> None:
        """Each adapter retrieved by name returns a valid instance."""
        registry = AdapterRegistry()
        for name in registry.list_test_adapters():
            adapter = registry.get_test_adapter(name)
            assert adapter is not None, f"Failed to get adapter: {name}"
            assert adapter.name == name
            # detect on empty dir should return False (no matching files)
            assert not adapter.detect(tmp_path)
