"""Tests for the ContextAssembler and helpers in nit.llm.context."""

from __future__ import annotations

from pathlib import Path

from nit.llm.context import (
    AssembledContext,
    ContextAssembler,
    DetectedTestPattern,
    _default_token_count,
    _detect_assertions,
    _detect_go_mocking,
    _detect_js_mocking,
    _detect_mocking,
    _detect_naming,
    _detect_python_mocking,
    _extract_sample_test,
    _extract_test_imports,
    _find_any_test_files,
    _find_test_files_for,
    _format_class_sig,
    _format_function_sig,
    _format_test_pattern,
    _is_in_skip_dir,
    _read_snippet,
    _truncate_to_tokens,
    extract_test_patterns,
)
from nit.parsing.treesitter import (
    ClassInfo,
    FunctionInfo,
    ParameterInfo,
    ParseResult,
)


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ── _default_token_count ────────────────────────────────────────


def test_default_token_count() -> None:
    assert _default_token_count("abcd") == 1
    assert _default_token_count("") == 0
    assert _default_token_count("a" * 100) == 25


# ── _truncate_to_tokens ─────────────────────────────────────────


def test_truncate_to_tokens_within_budget() -> None:
    text = "line1\nline2\n"
    result = _truncate_to_tokens(text, 100, _default_token_count)
    assert result == text


def test_truncate_to_tokens_exceeds_budget() -> None:
    text = "a" * 40 + "\n" + "b" * 40 + "\n" + "c" * 40 + "\n"
    result = _truncate_to_tokens(text, 5, _default_token_count)
    assert "truncated" in result


# ── _read_snippet ────────────────────────────────────────────────


def test_read_snippet_existing_file(tmp_path: Path) -> None:
    f = _write(tmp_path, "test.py", "line1\nline2\nline3\n")
    snippet = _read_snippet(f)
    assert "line1" in snippet
    assert "line3" in snippet


def test_read_snippet_nonexistent() -> None:
    snippet = _read_snippet(Path("/nonexistent/file.py"))
    assert snippet == ""


def test_read_snippet_max_lines(tmp_path: Path) -> None:
    content = "\n".join(f"line{i}" for i in range(100))
    f = _write(tmp_path, "big.py", content)
    snippet = _read_snippet(f, max_lines=5)
    assert snippet.count("\n") <= 5


# ── _is_in_skip_dir ─────────────────────────────────────────────


def test_is_in_skip_dir_true() -> None:
    assert _is_in_skip_dir(Path("project/node_modules/foo/bar.js"))
    assert _is_in_skip_dir(Path("project/.git/objects/abc"))
    assert _is_in_skip_dir(Path(".venv/lib/python/site.py"))


def test_is_in_skip_dir_false() -> None:
    assert not _is_in_skip_dir(Path("src/module/file.py"))
    assert not _is_in_skip_dir(Path("tests/test_thing.py"))


# ── _detect_naming ───────────────────────────────────────────────


def test_detect_naming_python_function() -> None:
    votes: dict[str, int] = {"function": 0, "class": 0, "describe": 0}
    _detect_naming("def test_something():\n    pass\n", "python", votes)
    assert votes["function"] == 1
    assert votes["class"] == 0


def test_detect_naming_python_class() -> None:
    votes: dict[str, int] = {"function": 0, "class": 0, "describe": 0}
    _detect_naming("class TestMyClass:\n    pass\n", "python", votes)
    assert votes["class"] == 1


def test_detect_naming_js_describe() -> None:
    votes: dict[str, int] = {"function": 0, "class": 0, "describe": 0}
    _detect_naming("describe('suite', () => {\n});\n", "javascript", votes)
    assert votes["describe"] == 1


def test_detect_naming_go_func() -> None:
    votes: dict[str, int] = {"function": 0, "class": 0, "describe": 0}
    _detect_naming("func TestSomething(t *testing.T) {\n}\n", "go", votes)
    assert votes["function"] == 1


# ── _detect_assertions ──────────────────────────────────────────


def test_detect_assertions_assert() -> None:
    votes: dict[str, int] = {"assert": 0, "expect": 0, "should": 0}
    _detect_assertions("assert result == 42", votes)
    assert votes["assert"] == 1


def test_detect_assertions_expect() -> None:
    votes: dict[str, int] = {"assert": 0, "expect": 0, "should": 0}
    _detect_assertions("expect(result).toBe(42)", votes)
    assert votes["expect"] == 1


def test_detect_assertions_should() -> None:
    votes: dict[str, int] = {"assert": 0, "expect": 0, "should": 0}
    _detect_assertions("result.should.equal(42)", votes)
    assert votes["should"] == 1


# ── _detect_mocking ─────────────────────────────────────────────


def test_detect_python_mocking_patterns() -> None:
    content = (
        "from unittest.mock import patch\n"
        "import unittest.mock\n"
        "@pytest.fixture\n"
        "def my_fixture(monkeypatch):\n"
        "    pass\n"
    )
    patterns = _detect_python_mocking(content)
    assert "unittest.mock" in patterns
    assert "pytest.fixture" in patterns
    assert "monkeypatch" in patterns
    assert "unittest.mock.patch" in patterns


def test_detect_js_mocking_patterns() -> None:
    content = "vi.mock('module');\nvi.fn();\n"
    patterns = _detect_js_mocking(content)
    assert "vi.mock" in patterns


def test_detect_js_mocking_jest() -> None:
    content = "jest.mock('module');\njest.fn();\n"
    patterns = _detect_js_mocking(content)
    assert "jest.mock" in patterns


def test_detect_js_mocking_sinon_nock() -> None:
    patterns = _detect_js_mocking("sinon.stub();\nnock('http://api');\n")
    assert "sinon" in patterns
    assert "nock" in patterns


def test_detect_go_mocking_testify() -> None:
    patterns = _detect_go_mocking("import testify/mock\n")
    assert "testify.mock" in patterns


def test_detect_go_mocking_gomock() -> None:
    patterns = _detect_go_mocking("import gomock\n")
    assert "gomock" in patterns


def test_detect_mocking_dispatch() -> None:
    assert _detect_mocking("assert True", "python") == []
    assert _detect_mocking("expect(x)", "javascript") == []
    assert _detect_mocking("func Test()", "go") == []
    assert _detect_mocking("content", "rust") == []


# ── _extract_test_imports ────────────────────────────────────────


def test_extract_test_imports_python() -> None:
    content = "import os\nfrom pathlib import Path\n"
    imports = _extract_test_imports(content, "python")
    assert len(imports) == 2
    assert "import os" in imports[0]


def test_extract_test_imports_js() -> None:
    content = "import { render } from '@testing-library/react';\n"
    imports = _extract_test_imports(content, "javascript")
    assert len(imports) == 1


def test_extract_test_imports_unsupported() -> None:
    assert _extract_test_imports("use testing", "go") == []


# ── _extract_sample_test ────────────────────────────────────────


def test_extract_sample_test_python() -> None:
    content = (
        "def test_add():\n"
        "    result = add(1, 2)\n"
        "    assert result == 3\n"
        "\n"
        "def test_other():\n"
        "    pass\n"
    )
    sample = _extract_sample_test(content, "python")
    assert "test_add" in sample


def test_extract_sample_test_js() -> None:
    content = "it('should add', async () => {\n  expect(1 + 2).toBe(3);\n})\n"
    sample = _extract_sample_test(content, "javascript")
    assert "should add" in sample


def test_extract_sample_test_no_match() -> None:
    assert _extract_sample_test("no tests here", "python") == ""
    assert _extract_sample_test("no tests here", "javascript") == ""


# ── extract_test_patterns ────────────────────────────────────────


def test_extract_test_patterns_from_files(tmp_path: Path) -> None:
    content = (
        "import pytest\n"
        "from unittest.mock import patch\n"
        "\n"
        "def test_foo():\n"
        "    assert 1 == 1\n"
    )
    f = _write(tmp_path, "test_example.py", content)
    patterns = extract_test_patterns([f], "python")
    assert patterns.naming_style == "function"
    assert patterns.assertion_style == "assert"
    assert len(patterns.imports) > 0


def test_extract_test_patterns_no_content(tmp_path: Path) -> None:
    """Empty test files yield 'unknown' styles."""
    f = _write(tmp_path, "test_empty.py", "")
    patterns = extract_test_patterns([f], "python")
    assert patterns.naming_style == "unknown"
    assert patterns.assertion_style == "unknown"


def test_extract_test_patterns_unreadable(tmp_path: Path) -> None:
    """Missing file in list should not crash."""
    missing = tmp_path / "nonexistent.py"
    patterns = extract_test_patterns([missing], "python")
    assert patterns.naming_style == "unknown"


# ── _find_test_files_for ─────────────────────────────────────────


def test_find_test_files_for_python(tmp_path: Path) -> None:
    src = _write(tmp_path, "src/nit/utils.py", "def x(): pass\n")
    _write(tmp_path, "tests/nit/test_utils.py", "def test_x(): pass\n")
    results = _find_test_files_for(src, tmp_path, "python")
    assert len(results) >= 1


def test_find_test_files_for_no_tests(tmp_path: Path) -> None:
    src = _write(tmp_path, "src/unique_module.py", "x = 1\n")
    results = _find_test_files_for(src, tmp_path, "python")
    assert results == []


# ── _find_any_test_files ─────────────────────────────────────────


def test_find_any_test_files(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_a.py", "def test_a(): pass\n")
    _write(tmp_path, "tests/test_b.py", "def test_b(): pass\n")
    results = _find_any_test_files(tmp_path, "python", limit=5)
    assert len(results) >= 2


def test_find_any_test_files_skips_venv(tmp_path: Path) -> None:
    _write(tmp_path, ".venv/tests/test_a.py", "def test_a(): pass\n")
    results = _find_any_test_files(tmp_path, "python", limit=5)
    assert results == []


# ── _format_function_sig ─────────────────────────────────────────


def test_format_function_sig_basic() -> None:
    f = FunctionInfo(
        name="add",
        start_line=1,
        end_line=3,
        parameters=[
            ParameterInfo(name="a", type_annotation="int"),
            ParameterInfo(name="b", type_annotation="int"),
        ],
        return_type="int",
    )
    sig = _format_function_sig(f)
    assert sig == "def add(a: int, b: int) -> int"


def test_format_function_sig_async_no_params() -> None:
    f = FunctionInfo(name="fetch", start_line=1, end_line=2, is_async=True)
    sig = _format_function_sig(f)
    assert sig == "async def fetch() -> None" or sig.startswith("async def fetch")


def test_format_function_sig_no_return() -> None:
    f = FunctionInfo(
        name="do_stuff",
        start_line=1,
        end_line=2,
        parameters=[ParameterInfo(name="x")],
    )
    sig = _format_function_sig(f)
    assert sig == "def do_stuff(x)"


# ── _format_class_sig ────────────────────────────────────────────


def test_format_class_sig_with_bases() -> None:
    c = ClassInfo(
        name="MyClass",
        start_line=1,
        end_line=10,
        bases=["Base", "Mixin"],
        methods=[
            FunctionInfo(name="run", start_line=2, end_line=5),
            FunctionInfo(name="stop", start_line=6, end_line=10),
        ],
    )
    sig = _format_class_sig(c)
    assert sig == "class MyClass(Base, Mixin): [run, stop]"


def test_format_class_sig_no_bases() -> None:
    c = ClassInfo(name="Simple", start_line=1, end_line=5, methods=[])
    sig = _format_class_sig(c)
    assert sig == "class Simple: []"


# ── _format_test_pattern ────────────────────────────────────────


def test_format_test_pattern() -> None:
    tp = DetectedTestPattern(
        naming_style="function",
        assertion_style="assert",
        mocking_patterns=["pytest.fixture"],
        sample_test="def test_x():\n    assert True",
    )
    text = _format_test_pattern(tp)
    assert "Naming: function" in text
    assert "Assertions: assert" in text
    assert "Mocking: pytest.fixture" in text
    assert "Example:" in text


def test_format_test_pattern_minimal() -> None:
    tp = DetectedTestPattern()
    text = _format_test_pattern(tp)
    assert "Naming: unknown" in text
    assert "Example:" not in text


# ── AssembledContext properties ──────────────────────────────────


def test_assembled_context_function_signatures() -> None:
    pr = ParseResult(
        language="python",
        functions=[
            FunctionInfo(
                name="greet",
                start_line=1,
                end_line=2,
                parameters=[ParameterInfo(name="name", type_annotation="str")],
                return_type="str",
            )
        ],
    )
    ctx = AssembledContext(
        source_path="test.py",
        source_code="def greet(name): ...",
        language="python",
        parse_result=pr,
    )
    assert ctx.function_signatures == ["def greet(name: str) -> str"]


def test_assembled_context_class_signatures() -> None:
    pr = ParseResult(
        language="python",
        classes=[
            ClassInfo(
                name="Foo",
                start_line=1,
                end_line=10,
                bases=["Bar"],
                methods=[FunctionInfo(name="m", start_line=2, end_line=3)],
            )
        ],
    )
    ctx = AssembledContext(
        source_path="test.py",
        source_code="class Foo: ...",
        language="python",
        parse_result=pr,
    )
    assert ctx.class_signatures == ["class Foo(Bar): [m]"]


# ── ContextAssembler._resolve ────────────────────────────────────


def test_assembler_resolve_absolute(tmp_path: Path) -> None:
    assembler = ContextAssembler(tmp_path)
    abs_path = tmp_path / "src" / "file.py"
    assert assembler._resolve(abs_path) == abs_path


def test_assembler_resolve_relative(tmp_path: Path) -> None:
    assembler = ContextAssembler(tmp_path)
    rel_path = Path("src/file.py")
    assert assembler._resolve(rel_path) == tmp_path / "src" / "file.py"
