"""Tests for the Context Assembly Engine (llm/context.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from nit.llm.context import (
    AssembledContext,
    ContextAssembler,
    ContextSection,
    _default_token_count,
    _find_any_test_files,
    _find_test_files_for,
    _truncate_to_tokens,
    extract_test_patterns,
)
from nit.parsing.treesitter import ParseResult

if TYPE_CHECKING:
    from pathlib import Path

# ── Fixtures ─────────────────────────────────────────────────────


def _create_python_project(root: Path) -> Path:
    """Set up a minimal Python project structure and return the source file path."""
    src = root / "src" / "mypackage"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")

    source = src / "calculator.py"
    source.write_text(
        '"""A simple calculator module."""\n'
        "\n"
        "\n"
        "def add(a: int, b: int) -> int:\n"
        '    """Add two numbers."""\n'
        "    return a + b\n"
        "\n"
        "\n"
        "def subtract(a: int, b: int) -> int:\n"
        '    """Subtract b from a."""\n'
        "    return a - b\n"
        "\n"
        "\n"
        "class Calculator:\n"
        '    """Stateful calculator."""\n'
        "\n"
        "    def __init__(self) -> None:\n"
        "        self.result = 0\n"
        "\n"
        "    def add(self, n: int) -> None:\n"
        "        self.result += n\n",
        encoding="utf-8",
    )
    return source


def _create_test_file(root: Path, name: str, content: str) -> Path:
    """Create a test file in the tests/ directory."""
    tests = root / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "__init__.py").touch()
    tf = tests / name
    tf.write_text(content, encoding="utf-8")
    return tf


def _sample_pytest_test() -> str:
    return (
        "import pytest\n"
        "from unittest.mock import patch\n"
        "from mypackage.calculator import add\n"
        "\n"
        "\n"
        "def test_add_positive() -> None:\n"
        "    assert add(1, 2) == 3\n"
        "\n"
        "\n"
        "def test_add_negative() -> None:\n"
        "    assert add(-1, -2) == -3\n"
        "\n"
        "\n"
        "@pytest.fixture\n"
        "def calc():\n"
        "    from mypackage.calculator import Calculator\n"
        "    return Calculator()\n"
    )


def _sample_class_test() -> str:
    return (
        "from mypackage.calculator import add, subtract\n"
        "\n"
        "\n"
        "class TestCalculator:\n"
        "    def test_add(self) -> None:\n"
        "        assert add(1, 2) == 3\n"
        "\n"
        "    def test_subtract(self) -> None:\n"
        "        assert subtract(5, 3) == 2\n"
    )


# ── TestPattern detection ────────────────────────────────────────


class TestExtractTestPatterns:
    def test_python_function_naming(self, tmp_path: Path) -> None:
        tf = _create_test_file(tmp_path, "test_calc.py", _sample_pytest_test())
        pattern = extract_test_patterns([tf], "python")
        assert pattern.naming_style == "function"

    def test_python_class_naming(self, tmp_path: Path) -> None:
        tf = _create_test_file(tmp_path, "test_calc.py", _sample_class_test())
        pattern = extract_test_patterns([tf], "python")
        assert pattern.naming_style in {"class", "function"}

    def test_python_assert_style(self, tmp_path: Path) -> None:
        tf = _create_test_file(tmp_path, "test_calc.py", _sample_pytest_test())
        pattern = extract_test_patterns([tf], "python")
        assert pattern.assertion_style == "assert"

    def test_python_mocking_detection(self, tmp_path: Path) -> None:
        content = (
            "from unittest.mock import patch, MagicMock\n"
            "import pytest\n"
            "\n"
            "@pytest.fixture\n"
            "def mock_db():\n"
            "    return MagicMock()\n"
            "\n"
            "def test_with_mock(monkeypatch):\n"
            "    assert True\n"
        )
        tf = _create_test_file(tmp_path, "test_mock.py", content)
        pattern = extract_test_patterns([tf], "python")
        assert "unittest.mock" in pattern.mocking_patterns
        assert "pytest.fixture" in pattern.mocking_patterns
        assert "monkeypatch" in pattern.mocking_patterns

    def test_python_imports_extracted(self, tmp_path: Path) -> None:
        tf = _create_test_file(tmp_path, "test_calc.py", _sample_pytest_test())
        pattern = extract_test_patterns([tf], "python")
        assert any("pytest" in imp for imp in pattern.imports)

    def test_python_sample_test_extracted(self, tmp_path: Path) -> None:
        tf = _create_test_file(tmp_path, "test_calc.py", _sample_pytest_test())
        pattern = extract_test_patterns([tf], "python")
        assert "test_add_positive" in pattern.sample_test

    def test_js_describe_naming(self, tmp_path: Path) -> None:
        content = (
            "import { describe, it, expect } from 'vitest';\n"
            "\n"
            "describe('Calculator', () => {\n"
            "  it('should add two numbers', () => {\n"
            "    expect(1 + 2).toBe(3);\n"
            "  });\n"
            "});\n"
        )
        tf = _create_test_file(tmp_path, "calc.test.ts", content)
        pattern = extract_test_patterns([tf], "typescript")
        assert pattern.naming_style == "describe"

    def test_js_expect_assertions(self, tmp_path: Path) -> None:
        content = (
            "import { describe, it, expect } from 'vitest';\n"
            "describe('test', () => {\n"
            "  it('works', () => { expect(true).toBe(true); });\n"
            "});\n"
        )
        tf = _create_test_file(tmp_path, "calc.test.ts", content)
        pattern = extract_test_patterns([tf], "typescript")
        assert pattern.assertion_style == "expect"

    def test_js_mocking_detection(self, tmp_path: Path) -> None:
        content = "import { vi } from 'vitest';\nvi.mock('./db');\nconst fn = vi.fn();\n"
        tf = _create_test_file(tmp_path, "util.test.ts", content)
        pattern = extract_test_patterns([tf], "typescript")
        assert "vi.mock" in pattern.mocking_patterns

    def test_empty_test_files(self) -> None:
        pattern = extract_test_patterns([], "python")
        assert pattern.naming_style == "unknown"
        assert pattern.assertion_style == "unknown"

    def test_unreadable_file(self, tmp_path: Path) -> None:
        fake = tmp_path / "tests" / "test_gone.py"
        # File doesn't exist — should not crash
        pattern = extract_test_patterns([fake], "python")
        assert pattern.naming_style == "unknown"


# ── File discovery ───────────────────────────────────────────────


class TestFindTestFiles:
    def test_finds_sibling_test(self, tmp_path: Path) -> None:
        src = tmp_path / "mypackage"
        src.mkdir()
        source = src / "calc.py"
        source.write_text("def add(): pass\n", encoding="utf-8")
        test = src / "test_calc.py"
        test.write_text("def test_add(): pass\n", encoding="utf-8")

        found = _find_test_files_for(source, tmp_path, "python")
        assert any(f.name == "test_calc.py" for f in found)

    def test_finds_test_in_tests_dir(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "pkg"
        src.mkdir(parents=True)
        source = src / "calc.py"
        source.write_text("def add(): pass\n", encoding="utf-8")

        tests = src / "tests"
        tests.mkdir()
        test = tests / "test_calc.py"
        test.write_text("def test_add(): pass\n", encoding="utf-8")

        found = _find_test_files_for(source, tmp_path, "python")
        assert any(f.name == "test_calc.py" for f in found)

    def test_finds_root_tests_dir_mirror(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "pkg"
        src.mkdir(parents=True)
        source = src / "calc.py"
        source.write_text("def add(): pass\n", encoding="utf-8")

        tests = tmp_path / "tests" / "pkg"
        tests.mkdir(parents=True)
        test = tests / "test_calc.py"
        test.write_text("def test_add(): pass\n", encoding="utf-8")

        found = _find_test_files_for(source, tmp_path, "python")
        assert any(f.name == "test_calc.py" for f in found)

    def test_js_test_patterns(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        source = src / "utils.ts"
        source.write_text("export function foo() {}\n", encoding="utf-8")
        test = src / "utils.test.ts"
        test.write_text("import {foo} from './utils';\n", encoding="utf-8")

        found = _find_test_files_for(source, tmp_path, "typescript")
        assert any(f.name == "utils.test.ts" for f in found)

    def test_no_duplicates(self, tmp_path: Path) -> None:
        src = tmp_path / "mypackage"
        src.mkdir()
        source = src / "calc.py"
        source.write_text("def add(): pass\n", encoding="utf-8")
        test = src / "test_calc.py"
        test.write_text("def test_add(): pass\n", encoding="utf-8")

        found = _find_test_files_for(source, tmp_path, "python")
        paths = [str(f) for f in found]
        assert len(paths) == len(set(paths))

    def test_find_any_test_files(self, tmp_path: Path) -> None:
        tests = tmp_path / "tests"
        tests.mkdir()
        for i in range(3):
            (tests / f"test_mod{i}.py").write_text(f"def test_{i}(): pass\n", encoding="utf-8")

        found = _find_any_test_files(tmp_path, "python", limit=5)
        assert len(found) == 3

    def test_find_any_skips_venv(self, tmp_path: Path) -> None:
        venv_tests = tmp_path / ".venv" / "lib" / "tests"
        venv_tests.mkdir(parents=True)
        (venv_tests / "test_internal.py").write_text("def test_x(): pass\n", encoding="utf-8")

        # Real test
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_real.py").write_text("def test_y(): pass\n", encoding="utf-8")

        found = _find_any_test_files(tmp_path, "python")
        assert all(".venv" not in str(f) for f in found)


# ── Context windowing / truncation ───────────────────────────────


class TestWindowing:
    def test_default_token_count(self) -> None:
        assert _default_token_count("hello world") == 2  # 11 // 4

    def test_truncate_within_budget(self) -> None:
        text = "line 1\nline 2\nline 3\n"
        result = _truncate_to_tokens(text, 1000, _default_token_count)
        assert result == text

    def test_truncate_over_budget(self) -> None:
        lines = [f"This is line number {i}\n" for i in range(100)]
        text = "".join(lines)
        result = _truncate_to_tokens(text, 10, _default_token_count)
        assert len(result) < len(text)
        assert result.endswith("# ... (truncated)\n")

    def test_truncate_preserves_complete_lines(self) -> None:
        text = "short\n" * 50
        result = _truncate_to_tokens(text, 5, _default_token_count)
        # Each "short\n" is 6 chars = 1 token. Budget of 5 tokens = 5 lines
        lines = result.strip().splitlines()
        # The last line is the truncation marker
        assert lines[-1] == "# ... (truncated)"

    def test_context_section_priority_ordering(self) -> None:
        sections = [
            ContextSection("low", "c", 10, 10),
            ContextSection("high", "a", 10, 100),
            ContextSection("mid", "b", 10, 50),
        ]
        sections.sort(key=lambda s: -s.priority)
        assert [s.name for s in sections] == ["high", "mid", "low"]


# ── ContextAssembler ─────────────────────────────────────────────


class TestContextAssembler:
    def test_assemble_python_file(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)
        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(source)

        assert isinstance(ctx, AssembledContext)
        assert ctx.language == "python"
        assert "def add" in ctx.source_code
        assert len(ctx.parse_result.functions) >= 2

    def test_assemble_extracts_functions(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)
        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(source)

        func_names = [f.name for f in ctx.parse_result.functions]
        assert "add" in func_names
        assert "subtract" in func_names

    def test_assemble_extracts_classes(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)
        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(source)

        class_names = [c.name for c in ctx.parse_result.classes]
        assert "Calculator" in class_names

    def test_assemble_finds_test_files(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)
        tests = tmp_path / "tests" / "mypackage"
        tests.mkdir(parents=True)
        test_file = tests / "test_calculator.py"
        test_file.write_text(_sample_pytest_test(), encoding="utf-8")

        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(source)

        test_related = [r for r in ctx.related_files if r.relationship == "test"]
        assert len(test_related) >= 1

    def test_assemble_extracts_test_patterns(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)
        _create_test_file(tmp_path, "test_calculator.py", _sample_pytest_test())

        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(source)

        assert ctx.test_patterns is not None
        assert ctx.test_patterns.naming_style == "function"
        assert ctx.test_patterns.assertion_style == "assert"

    def test_assemble_relative_path(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)
        rel = source.relative_to(tmp_path)

        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(rel)

        assert ctx.language == "python"
        assert "def add" in ctx.source_code

    def test_assemble_unsupported_language(self, tmp_path: Path) -> None:
        txt = tmp_path / "readme.txt"
        txt.write_text("Hello world", encoding="utf-8")

        assembler = ContextAssembler(tmp_path)
        with pytest.raises(ValueError, match="Unsupported language"):
            assembler.assemble(txt)

    def test_function_signatures_property(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)
        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(source)

        sigs = ctx.function_signatures
        assert any("add" in s for s in sigs)
        assert any("subtract" in s for s in sigs)

    def test_class_signatures_property(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)
        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(source)

        sigs = ctx.class_signatures
        assert any("Calculator" in s for s in sigs)

    def test_windowing_limits_tokens(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)
        # Use a very small token budget
        assembler = ContextAssembler(tmp_path, max_context_tokens=50)
        ctx = assembler.assemble(source)

        assert ctx.total_tokens <= 50

    def test_windowing_strips_low_priority(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)
        _create_test_file(tmp_path, "test_calculator.py", _sample_pytest_test())

        # Very small budget: should keep source but drop related/patterns
        assembler = ContextAssembler(tmp_path, max_context_tokens=30)
        ctx = assembler.assemble(source)

        # Source should be present (possibly truncated)
        assert len(ctx.source_code) > 0

    def test_custom_token_counter(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)

        call_count = 0

        def counting_counter(text: str) -> int:
            nonlocal call_count
            call_count += 1
            return len(text) // 4

        assembler = ContextAssembler(
            tmp_path,
            token_counter=counting_counter,
        )
        assembler.assemble(source)

        assert call_count > 0

    def test_assemble_handles_no_tests(self, tmp_path: Path) -> None:
        source = _create_python_project(tmp_path)
        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(source)

        # No test files exist, so patterns may be None
        # (or detected from any project tests) — just shouldn't crash
        assert isinstance(ctx, AssembledContext)


# ── Import resolution ────────────────────────────────────────────


class TestImportResolution:
    def test_python_import_resolved(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "pkg"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("", encoding="utf-8")

        helper = src / "helper.py"
        helper.write_text("def help_func(): pass\n", encoding="utf-8")

        source = src / "main.py"
        source.write_text(
            "from pkg.helper import help_func\n\ndef main():\n    return help_func()\n",
            encoding="utf-8",
        )

        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(source)

        import_related = [r for r in ctx.related_files if r.relationship == "import"]
        import_paths = [r.path for r in import_related]
        assert any("helper.py" in p for p in import_paths)

    def test_js_relative_import_resolved(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()

        helper = src / "utils.ts"
        helper.write_text("export function foo() {}\n", encoding="utf-8")

        source = src / "main.ts"
        source.write_text(
            "import { foo } from './utils';\n\nexport function bar() { return foo(); }\n",
            encoding="utf-8",
        )

        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(source)

        import_related = [r for r in ctx.related_files if r.relationship == "import"]
        import_paths = [r.path for r in import_related]
        assert any("utils.ts" in p for p in import_paths)

    def test_js_node_modules_import_not_resolved(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        source = src / "main.ts"
        source.write_text(
            "import express from 'express';\n\nconst app = express();\n",
            encoding="utf-8",
        )

        assembler = ContextAssembler(tmp_path)
        ctx = assembler.assemble(source)

        import_related = [r for r in ctx.related_files if r.relationship == "import"]
        assert not any("express" in r.path for r in import_related)


# ── AssembledContext properties ───────────────────────────────────


class TestAssembledContextProperties:
    def test_function_signatures_formatting(self) -> None:
        ctx = AssembledContext(
            source_path="test.py",
            source_code="",
            language="python",
            parse_result=ParseResult(language="python"),
        )
        assert ctx.function_signatures == []

    def test_class_signatures_formatting(self) -> None:
        ctx = AssembledContext(
            source_path="test.py",
            source_code="",
            language="python",
            parse_result=ParseResult(language="python"),
        )
        assert ctx.class_signatures == []
