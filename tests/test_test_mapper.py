"""Tests for the TestMapper (agents/analyzers/test_mapper.py).

Covers:
- Naming-convention mapping for Python, JS/TS, Go
- Import-based mapping for Python and JS/TS
- Confidence scoring
- map_all_tests batch operation
- Edge cases (unmappable files, missing directories)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.agents.analyzers.test_mapper import (
    CONFIDENCE_IMPORT,
    CONFIDENCE_NAMING,
    TestMapper,
    TestMapping,
)

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Create a minimal project tree for test mapping."""
    # src/foo.py
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.py").write_text("def hello(): pass\n")
    (src / "foo_bar.py").write_text("def world(): pass\n")

    # src/utils.py (for import resolution)
    (src / "utils.py").write_text("def util_fn(): pass\n")

    # root-level bar.py
    (tmp_path / "bar.py").write_text("def bar(): pass\n")

    # src/component.ts
    (src / "component.ts").write_text("export function render() {}\n")

    # src/widget.js
    (src / "widget.js").write_text("module.exports = { widget: true };\n")

    # Go files in a pkg directory
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "handler.go").write_text("package pkg\nfunc Handle() {}\n")

    # tests directory
    tests = tmp_path / "tests"
    tests.mkdir()

    return tmp_path


# ── Naming convention tests ───────────────────────────────────────


def test_map_python_test_to_source_in_src(project_root: Path) -> None:
    """test_foo.py should map to src/foo.py."""
    mapper = TestMapper(project_root)
    test_file = project_root / "tests" / "test_foo.py"
    test_file.write_text("import foo\n")

    result = mapper.map_test_to_sources(test_file)

    assert "src/foo.py" in result.source_files
    assert result.confidence == CONFIDENCE_NAMING


def test_map_python_test_to_source_in_root(project_root: Path) -> None:
    """test_bar.py should map to bar.py at the project root."""
    mapper = TestMapper(project_root)
    test_file = project_root / "tests" / "test_bar.py"
    test_file.write_text("")

    result = mapper.map_test_to_sources(test_file)

    assert "bar.py" in result.source_files
    assert result.confidence == CONFIDENCE_NAMING


def test_map_python_test_with_underscores(project_root: Path) -> None:
    """test_foo_bar.py should map to src/foo_bar.py."""
    mapper = TestMapper(project_root)
    test_file = project_root / "tests" / "test_foo_bar.py"
    test_file.write_text("")

    result = mapper.map_test_to_sources(test_file)

    assert "src/foo_bar.py" in result.source_files


def test_map_ts_test_to_source(project_root: Path) -> None:
    """component.test.ts should map to src/component.ts."""
    mapper = TestMapper(project_root)
    test_file = project_root / "tests" / "component.test.ts"
    test_file.write_text("")

    result = mapper.map_test_to_sources(test_file)

    assert "src/component.ts" in result.source_files
    assert result.confidence == CONFIDENCE_NAMING


def test_map_js_spec_to_source(project_root: Path) -> None:
    """widget.spec.js should map to src/widget.js."""
    mapper = TestMapper(project_root)
    test_file = project_root / "tests" / "widget.spec.js"
    test_file.write_text("")

    result = mapper.map_test_to_sources(test_file)

    assert "src/widget.js" in result.source_files
    assert result.confidence == CONFIDENCE_NAMING


def test_map_go_test_to_source(project_root: Path) -> None:
    """handler_test.go should map to handler.go in the same directory."""
    mapper = TestMapper(project_root)
    test_file = project_root / "pkg" / "handler_test.go"
    test_file.write_text("package pkg\n")

    result = mapper.map_test_to_sources(test_file)

    assert "pkg/handler.go" in result.source_files
    assert result.confidence == CONFIDENCE_NAMING


def test_unmappable_test_returns_empty_sources(project_root: Path) -> None:
    """A test file with no matching source should return empty sources."""
    mapper = TestMapper(project_root)
    test_file = project_root / "tests" / "test_nonexistent.py"
    test_file.write_text("")

    result = mapper.map_test_to_sources(test_file)

    assert result.source_files == []
    assert result.confidence == 0.0


# ── Import analysis tests ────────────────────────────────────────


def test_python_import_finds_source(project_root: Path) -> None:
    """Python `from src.utils import ...` should resolve to src/utils.py."""
    mapper = TestMapper(project_root)
    # Create the nit-style package so that the module resolves via src/
    test_file = project_root / "tests" / "test_imports.py"
    test_file.write_text("from utils import util_fn\n")

    result = mapper.map_test_to_sources(test_file)

    # The import resolver should find src/utils.py
    matching = [s for s in result.source_files if "utils.py" in s]
    assert matching


def test_js_import_finds_source(project_root: Path) -> None:
    """JS `import ... from '../src/component'` should resolve."""
    mapper = TestMapper(project_root)
    test_file = project_root / "tests" / "component.test.ts"
    test_file.write_text("import { render } from '../src/component';\n")

    result = mapper.map_test_to_sources(test_file)

    matching = [s for s in result.source_files if "component" in s]
    assert matching


def test_js_require_finds_source(project_root: Path) -> None:
    """JS `require('../src/widget')` should resolve."""
    mapper = TestMapper(project_root)
    test_file = project_root / "tests" / "widget.spec.js"
    test_file.write_text("const w = require('../src/widget');\n")

    result = mapper.map_test_to_sources(test_file)

    matching = [s for s in result.source_files if "widget" in s]
    assert matching


# ── Confidence tests ──────────────────────────────────────────────


def test_naming_confidence_higher_than_import(project_root: Path) -> None:
    """When both naming and import match, confidence should be CONFIDENCE_NAMING."""
    mapper = TestMapper(project_root)
    test_file = project_root / "tests" / "test_foo.py"
    test_file.write_text("from foo import hello\n")

    result = mapper.map_test_to_sources(test_file)

    assert result.confidence == CONFIDENCE_NAMING


def test_import_only_confidence(project_root: Path) -> None:
    """When only imports match, confidence should be CONFIDENCE_IMPORT."""
    mapper = TestMapper(project_root)
    test_file = project_root / "tests" / "test_imports_only.py"
    # No naming match (test_imports_only.py -> imports_only.py doesn't exist)
    # but it imports utils which does exist
    test_file.write_text("from utils import util_fn\n")

    result = mapper.map_test_to_sources(test_file)

    matching = [s for s in result.source_files if "utils.py" in s]
    assert matching
    assert result.confidence == CONFIDENCE_IMPORT


# ── Batch mapping test ────────────────────────────────────────────


def test_map_all_tests(project_root: Path) -> None:
    """map_all_tests should process multiple test files."""
    mapper = TestMapper(project_root)

    test1 = project_root / "tests" / "test_foo.py"
    test1.write_text("")
    test2 = project_root / "tests" / "test_bar.py"
    test2.write_text("")
    test3 = project_root / "tests" / "test_nonexistent.py"
    test3.write_text("")

    results = mapper.map_all_tests([test1, test2, test3])

    assert len(results) == 3
    assert all(isinstance(r, TestMapping) for r in results)
    # test_foo.py and test_bar.py should have source mappings
    assert results[0].source_files  # test_foo -> src/foo.py
    assert results[1].source_files  # test_bar -> bar.py
    assert not results[2].source_files  # test_nonexistent -> nothing
