"""Tests for doc_generation.py — prompt construction and style preferences."""

from __future__ import annotations

from nit.llm.prompts.doc_generation import (
    DocChange,
    DocGenerationContext,
    DocGenerationTemplate,
    build_doc_generation_messages,
    build_mismatch_detection_messages,
)

# ── build_doc_generation_messages ─────────────────────────────────────


class TestBuildDocGenerationMessages:
    def test_returns_system_and_user(self) -> None:
        ctx = DocGenerationContext(
            changes=[DocChange("foo", "new", "def foo(x: int) -> str")],
            doc_framework="sphinx",
            language="python",
            source_path="src/mod.py",
            source_code="def foo(x: int) -> str:\n    return str(x)\n",
        )
        msgs = build_doc_generation_messages(ctx)
        assert len(msgs) == 2
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"

    def test_user_message_contains_file_info(self) -> None:
        ctx = DocGenerationContext(
            changes=[DocChange("bar", "modified", "def bar() -> None")],
            doc_framework="jsdoc",
            language="javascript",
            source_path="src/utils.js",
            source_code="function bar() {}",
        )
        msgs = build_doc_generation_messages(ctx)
        user = msgs[1].content
        assert "src/utils.js" in user
        assert "javascript" in user
        assert "bar" in user

    def test_system_message_contains_framework_instruction(self) -> None:
        ctx = DocGenerationContext(
            changes=[],
            doc_framework="doxygen",
            language="cpp",
            source_path="src/foo.cpp",
            source_code="",
        )
        msgs = build_doc_generation_messages(ctx)
        system = msgs[0].content
        assert "Doxygen" in system
        assert "@brief" in system

    def test_existing_doc_included_in_user_message(self) -> None:
        ctx = DocGenerationContext(
            changes=[
                DocChange(
                    "baz",
                    "modified",
                    "def baz(a, b)",
                    existing_doc='"""Old doc."""',
                )
            ],
            doc_framework="sphinx",
            language="python",
            source_path="m.py",
            source_code="",
        )
        msgs = build_doc_generation_messages(ctx)
        assert "Old doc." in msgs[1].content

    def test_no_existing_doc_says_none(self) -> None:
        ctx = DocGenerationContext(
            changes=[DocChange("fn", "new", "def fn()")],
            doc_framework="sphinx",
            language="python",
            source_path="m.py",
            source_code="",
        )
        msgs = build_doc_generation_messages(ctx)
        assert "None" in msgs[1].content


# ── Style preference ─────────────────────────────────────────────────


class TestStylePreference:
    def test_google_style_override(self) -> None:
        ctx = DocGenerationContext(
            changes=[],
            doc_framework="sphinx",
            language="python",
            source_path="m.py",
            source_code="",
            style_preference="google",
        )
        msgs = build_doc_generation_messages(ctx)
        system = msgs[0].content
        assert "Google-style" in system
        assert "Args:" in system

    def test_numpy_style_override(self) -> None:
        ctx = DocGenerationContext(
            changes=[],
            doc_framework="sphinx",
            language="python",
            source_path="m.py",
            source_code="",
            style_preference="numpy",
        )
        msgs = build_doc_generation_messages(ctx)
        system = msgs[0].content
        assert "NumPy-style" in system
        assert "Parameters" in system
        assert "----------" in system

    def test_style_ignored_for_non_sphinx(self) -> None:
        ctx = DocGenerationContext(
            changes=[],
            doc_framework="jsdoc",
            language="javascript",
            source_path="m.js",
            source_code="",
            style_preference="google",
        )
        msgs = build_doc_generation_messages(ctx)
        system = msgs[0].content
        # Should use jsdoc instruction, not google
        assert "JSDoc" in system
        assert "Google-style" not in system

    def test_empty_style_uses_default_sphinx(self) -> None:
        ctx = DocGenerationContext(
            changes=[],
            doc_framework="sphinx",
            language="python",
            source_path="m.py",
            source_code="",
            style_preference="",
        )
        msgs = build_doc_generation_messages(ctx)
        system = msgs[0].content
        # Default sphinx includes both styles
        assert "Google-style or NumPy-style" in system


# ── build_mismatch_detection_messages ─────────────────────────────────


class TestBuildMismatchDetectionMessages:
    def test_returns_system_and_user(self) -> None:
        msgs = build_mismatch_detection_messages(
            documented_items=[("foo", "def foo(x)", '"""Does stuff."""')],
            language="python",
            doc_framework="sphinx",
            source_code="def foo(x):\n    pass\n",
            source_path="mod.py",
        )
        assert len(msgs) == 2
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"

    def test_system_instructs_json_output(self) -> None:
        msgs = build_mismatch_detection_messages(
            documented_items=[],
            language="python",
            doc_framework="sphinx",
            source_code="",
            source_path="mod.py",
        )
        system = msgs[0].content
        assert "JSON array" in system
        assert "missing_param" in system
        assert "semantic_drift" in system

    def test_user_contains_documented_items(self) -> None:
        msgs = build_mismatch_detection_messages(
            documented_items=[
                ("func_a", "def func_a(x, y)", '"""Adds x and y."""'),
                ("func_b", "def func_b()", '"""Returns nothing."""'),
            ],
            language="python",
            doc_framework="sphinx",
            source_code="def func_a(x, y):\n    return x + y\n\ndef func_b():\n    pass\n",
            source_path="math_utils.py",
        )
        user = msgs[1].content
        assert "func_a" in user
        assert "func_b" in user
        assert "Adds x and y" in user
        assert "math_utils.py" in user

    def test_user_contains_source_code(self) -> None:
        source = 'fn main() { println!("hello"); }'
        msgs = build_mismatch_detection_messages(
            documented_items=[("main", "fn main()", "/// Entry point.")],
            language="rust",
            doc_framework="rustdoc",
            source_code=source,
            source_path="main.rs",
        )
        user = msgs[1].content
        assert source in user
        assert "```rust" in user

    def test_empty_documented_items(self) -> None:
        msgs = build_mismatch_detection_messages(
            documented_items=[],
            language="go",
            doc_framework="godoc",
            source_code="package main\n",
            source_path="main.go",
        )
        user = msgs[1].content
        assert "Documented Functions/Classes to Check" in user
        # Should still have the final instruction
        assert "JSON array" in user


# ── Framework instructions ────────────────────────────────────────────


class TestFrameworkInstructions:
    def _system_for(self, framework: str, language: str = "python") -> str:
        ctx = DocGenerationContext(
            changes=[],
            doc_framework=framework,
            language=language,
            source_path="f.py",
            source_code="",
        )
        return build_doc_generation_messages(ctx)[0].content

    def test_sphinx(self) -> None:
        assert "triple-quoted docstrings" in self._system_for("sphinx")

    def test_typedoc(self) -> None:
        assert "TSDoc" in self._system_for("typedoc", "typescript")

    def test_jsdoc(self) -> None:
        assert "JSDoc" in self._system_for("jsdoc", "javascript")

    def test_doxygen(self) -> None:
        assert "@brief" in self._system_for("doxygen", "cpp")

    def test_godoc(self) -> None:
        assert "Go doc comments" in self._system_for("godoc", "go")

    def test_rustdoc(self) -> None:
        assert "triple-slash" in self._system_for("rustdoc", "rust")

    def test_mkdocs(self) -> None:
        assert "MkDocs" in self._system_for("mkdocs")

    def test_unknown_framework_fallback(self) -> None:
        system = self._system_for("unknown_framework")
        assert "clear, concise documentation" in system


# ── DocGenerationTemplate ────────────────────────────────────────────


class TestDocGenerationTemplate:
    def _make_ctx(self) -> DocGenerationContext:
        return DocGenerationContext(
            changes=[DocChange("foo", "new", "def foo()")],
            doc_framework="sphinx",
            language="python",
            source_path="mod.py",
            source_code="def foo(): pass\n",
        )

    def test_name_includes_framework(self) -> None:
        ctx = self._make_ctx()
        tmpl = DocGenerationTemplate(ctx)
        assert tmpl.name == "doc_generation_sphinx"

    def test_system_instruction(self) -> None:
        ctx = self._make_ctx()
        tmpl = DocGenerationTemplate(ctx)
        # _system_instruction takes an AssembledContext but it's ignored;
        # pass None since it's duck-typed.
        instruction = tmpl._system_instruction(None)  # type: ignore[arg-type]
        assert isinstance(instruction, str)
        assert len(instruction) > 0

    def test_build_sections_returns_empty(self) -> None:
        ctx = self._make_ctx()
        tmpl = DocGenerationTemplate(ctx)
        sections = tmpl._build_sections(None)  # type: ignore[arg-type]
        assert sections == []

    def test_build_messages(self) -> None:
        ctx = self._make_ctx()
        tmpl = DocGenerationTemplate(ctx)
        msgs = tmpl.build_messages()
        assert len(msgs) == 2
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"
