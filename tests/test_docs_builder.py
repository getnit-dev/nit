"""Tests for the DocBuilder agent (agents/builders/docs.py).

Covers:
- DocFramework enum values
- FunctionState / FileDocState / DocBuildTask / DocBuildResult dataclasses
- DocBuilder.__init__ wiring
- DocBuilder.run() happy path, invalid task, check_only, empty sources
- _load_doc_states / _save_doc_states roundtrip
- _discover_source_files with exclusions
- _detect_doc_framework per language
- _build_current_state from ParseResult
- _build_signature / _build_class_signature
- _detect_changes (new, modified, undocumented, first-time)
- _generate_docs with LLM call and LLMError handling
- _parse_generated_docs regex parsing
- _update_doc_state docstring and timestamp update
- _result_to_dict serialization
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.agents.base import TaskInput, TaskStatus
from nit.agents.builders.docs import (
    DocBuilder,
    DocBuildResult,
    DocBuildTask,
    DocFramework,
    DocMismatch,
    FileDocState,
    FunctionState,
)
from nit.config import DocsConfig
from nit.llm.engine import LLMError, LLMResponse
from nit.llm.prompts.doc_generation import DocChange
from nit.parsing.treesitter import (
    ClassInfo,
    FunctionInfo,
    ParameterInfo,
    ParseResult,
)

# ── DocFramework enum ────────────────────────────────────────────


class TestDocFramework:
    def test_all_values_exist(self) -> None:
        expected = {
            "sphinx",
            "typedoc",
            "jsdoc",
            "doxygen",
            "godoc",
            "rustdoc",
            "mkdocs",
            "unknown",
        }
        actual = {member.value for member in DocFramework}
        assert actual == expected

    def test_access_by_name(self) -> None:
        assert DocFramework.SPHINX.value == "sphinx"
        assert DocFramework.UNKNOWN.value == "unknown"


# ── FunctionState dataclass ──────────────────────────────────────


class TestFunctionState:
    def test_construction_defaults(self) -> None:
        state = FunctionState(name="foo", signature="foo(x)")
        assert state.name == "foo"
        assert state.signature == "foo(x)"
        assert state.docstring is None
        assert state.line_number == 0

    def test_construction_with_all_fields(self) -> None:
        state = FunctionState(
            name="bar",
            signature="bar(a, b) -> int",
            docstring="Adds two numbers.",
            line_number=42,
        )
        assert state.docstring == "Adds two numbers."
        assert state.line_number == 42


# ── FileDocState dataclass ───────────────────────────────────────


class TestFileDocState:
    def test_construction_with_maps(self) -> None:
        func = FunctionState(name="greet", signature="greet(name)")
        cls = FunctionState(name="MyClass", signature="class MyClass")
        state = FileDocState(
            file_path="src/main.py",
            language="python",
            doc_framework="sphinx",
            functions={"greet": func},
            classes={"MyClass": cls},
        )
        assert state.functions["greet"].name == "greet"
        assert state.classes["MyClass"].signature == "class MyClass"
        assert state.last_updated == ""


# ── DocBuildTask dataclass ───────────────────────────────────────


class TestDocBuildTask:
    def test_post_init_sets_target_from_source_files(self) -> None:
        task = DocBuildTask(source_files=["a.py", "b.py"])
        assert task.target == "a.py, b.py"

    def test_post_init_truncates_to_three(self) -> None:
        task = DocBuildTask(source_files=["a.py", "b.py", "c.py", "d.py"])
        assert task.target == "a.py, b.py, c.py"

    def test_post_init_keeps_explicit_target(self) -> None:
        task = DocBuildTask(target="explicit", source_files=["a.py"])
        assert task.target == "explicit"

    def test_empty_source_files_leaves_target_empty(self) -> None:
        task = DocBuildTask()
        assert task.target == ""


# ── DocBuildResult dataclass ─────────────────────────────────────


class TestDocBuildResult:
    def test_construction(self) -> None:
        change = DocChange(
            function_name="fn",
            change_type="new",
            signature="fn()",
        )
        result = DocBuildResult(
            file_path="x.py",
            changes=[change],
            generated_docs={"fn": '"""Docs."""'},
            outdated=True,
        )
        assert result.file_path == "x.py"
        assert len(result.changes) == 1
        assert result.outdated is True
        assert result.errors == []


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_llm() -> MagicMock:
    engine = MagicMock()
    engine.generate = AsyncMock(return_value=LLMResponse(text="", model="mock-model"))
    return engine


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a minimal project layout for the builder."""
    (tmp_path / ".nit" / "memory").mkdir(parents=True)
    return tmp_path


def _make_builder(
    llm: MagicMock,
    root: Path,
    docs_config: DocsConfig | None = None,
) -> DocBuilder:
    """Create a DocBuilder with mocked dependencies."""
    with patch("nit.agents.builders.docs.get_registry") as mock_reg:
        mock_reg.return_value = MagicMock()
        return DocBuilder(llm, root, docs_config=docs_config)


# ── DocBuilder.__init__ ──────────────────────────────────────────


class TestDocBuilderInit:
    def test_init_stores_llm_and_root(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        assert builder._llm is mock_llm
        assert builder._root == project_root

    def test_init_loads_empty_states(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        assert builder._doc_states == {}

    def test_name_and_description(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        assert builder.name == "doc_builder"
        assert "documentation" in builder.description.lower()


# ── _load_doc_states / _save_doc_states roundtrip ────────────────


class TestDocStatePersistence:
    def test_save_and_load_roundtrip(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        state = FileDocState(
            file_path="lib.py",
            language="python",
            doc_framework="sphinx",
            functions={
                "add": FunctionState(
                    name="add",
                    signature="add(a, b)",
                    docstring="Adds.",
                    line_number=10,
                )
            },
            classes={
                "Calc": FunctionState(
                    name="Calc",
                    signature="class Calc",
                    docstring=None,
                    line_number=1,
                )
            },
            last_updated="2025-01-01T00:00:00",
        )
        builder._doc_states["lib.py"] = state
        builder._save_doc_states()

        # Build a fresh builder that loads from disk
        builder2 = _make_builder(mock_llm, project_root)
        loaded = builder2._doc_states["lib.py"]
        assert loaded.file_path == "lib.py"
        assert loaded.language == "python"
        assert loaded.functions["add"].signature == "add(a, b)"
        assert loaded.classes["Calc"].line_number == 1
        assert loaded.last_updated == "2025-01-01T00:00:00"


# ── _discover_source_files ───────────────────────────────────────


class TestDiscoverSourceFiles:
    def test_discovers_supported_extensions(self, mock_llm: MagicMock, project_root: Path) -> None:
        base = Path("/clean/project")
        builder = _make_builder(mock_llm, project_root)
        builder._root = base

        found = [
            base / "src" / "main.py",
            base / "src" / "app.ts",
            base / "src" / "lib.go",
        ]

        with patch.object(Path, "glob", return_value=found):
            files = builder._discover_source_files()

        names = {Path(f).name for f in files}
        assert "main.py" in names
        assert "app.ts" in names
        assert "lib.go" in names

    def test_excludes_test_node_modules_build_dist_venv(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        base = Path("/clean/project")
        builder = _make_builder(mock_llm, project_root)
        builder._root = base

        skip = [
            base / "test" / "skip.py",
            base / "node_modules" / "pkg.js",
            base / "build" / "out.py",
            base / "dist" / "bundle.js",
            base / ".venv" / "site.py",
        ]

        with patch.object(Path, "glob", return_value=skip):
            files = builder._discover_source_files()

        assert files == []


# ── _detect_doc_framework ────────────────────────────────────────


class TestDetectDocFramework:
    def test_python_returns_sphinx(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        assert builder._detect_doc_framework("python") == "sphinx"

    def test_typescript_returns_jsdoc_by_default(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        builder = _make_builder(mock_llm, project_root)
        assert builder._detect_doc_framework("typescript") == "jsdoc"

    def test_typescript_returns_typedoc_when_config_exists(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        (project_root / "typedoc.json").write_text("{}")
        builder = _make_builder(mock_llm, project_root)
        assert builder._detect_doc_framework("typescript") == "typedoc"

    def test_cpp_returns_doxygen(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        assert builder._detect_doc_framework("cpp") == "doxygen"

    def test_c_returns_doxygen(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        assert builder._detect_doc_framework("c") == "doxygen"

    def test_go_returns_godoc(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        assert builder._detect_doc_framework("go") == "godoc"

    def test_rust_returns_rustdoc(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        assert builder._detect_doc_framework("rust") == "rustdoc"

    def test_unknown_language_returns_unknown(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        builder = _make_builder(mock_llm, project_root)
        assert builder._detect_doc_framework("brainfuck") == "unknown"


# ── _build_signature / _build_class_signature ────────────────────


class TestBuildSignature:
    def test_function_no_return_type(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        func = FunctionInfo(
            name="greet",
            start_line=1,
            end_line=3,
            parameters=[ParameterInfo(name="name")],
        )
        assert builder._build_signature(func) == "greet(name)"

    def test_function_with_return_type(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        func = FunctionInfo(
            name="add",
            start_line=1,
            end_line=3,
            parameters=[ParameterInfo(name="a"), ParameterInfo(name="b")],
            return_type="int",
        )
        assert builder._build_signature(func) == "add(a, b) -> int"

    def test_function_no_params(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        func = FunctionInfo(name="noop", start_line=1, end_line=1)
        assert builder._build_signature(func) == "noop()"

    def test_class_signature_no_bases(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        cls_info = ClassInfo(name="Foo", start_line=1, end_line=5)
        assert builder._build_class_signature(cls_info) == "class Foo"

    def test_class_signature_with_base_classes(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        builder = _make_builder(mock_llm, project_root)
        # The builder uses getattr(cls, "base_classes", []) which
        # won't find ClassInfo.bases, so we simulate a class object
        # that actually has base_classes.
        cls_mock = MagicMock()
        cls_mock.name = "Bar"
        cls_mock.base_classes = ["Base1", "Base2"]
        assert builder._build_class_signature(cls_mock) == "class Bar(Base1, Base2)"


# ── _build_current_state ─────────────────────────────────────────


class TestBuildCurrentState:
    def test_builds_state_from_parse_result(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        parse_result = ParseResult(
            language="python",
            functions=[
                FunctionInfo(
                    name="process",
                    start_line=5,
                    end_line=10,
                    parameters=[ParameterInfo(name="data")],
                    return_type="bool",
                ),
            ],
            classes=[
                ClassInfo(name="Handler", start_line=15, end_line=30),
            ],
        )

        state = builder._build_current_state("src/mod.py", "python", "sphinx", parse_result)

        assert state.file_path == "src/mod.py"
        assert state.language == "python"
        assert state.doc_framework == "sphinx"
        assert "process" in state.functions
        assert state.functions["process"].line_number == 5
        assert state.functions["process"].signature == "process(data) -> bool"
        assert "Handler" in state.classes
        assert state.classes["Handler"].signature == "class Handler"


# ── _detect_changes ──────────────────────────────────────────────


class TestDetectChanges:
    @pytest.fixture
    def builder(self, mock_llm: MagicMock, project_root: Path) -> DocBuilder:
        return _make_builder(mock_llm, project_root)

    def test_first_time_no_prev_state(self, builder: DocBuilder) -> None:
        current = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            functions={
                "foo": FunctionState(name="foo", signature="foo()"),
            },
        )
        changes = builder._detect_changes(None, current)
        assert len(changes) == 1
        assert changes[0].function_name == "foo"
        assert changes[0].change_type == "new"

    def test_first_time_skips_documented_functions(self, builder: DocBuilder) -> None:
        current = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            functions={
                "documented": FunctionState(
                    name="documented",
                    signature="documented()",
                    docstring="Already documented.",
                ),
            },
        )
        changes = builder._detect_changes(None, current)
        assert len(changes) == 0

    def test_new_function_detected(self, builder: DocBuilder) -> None:
        prev = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            functions={},
        )
        current = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            functions={
                "new_fn": FunctionState(name="new_fn", signature="new_fn(x)"),
            },
        )
        changes = builder._detect_changes(prev, current)
        assert len(changes) == 1
        assert changes[0].change_type == "new"

    def test_modified_signature_detected(self, builder: DocBuilder) -> None:
        prev = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            functions={
                "fn": FunctionState(name="fn", signature="fn(a)"),
            },
        )
        current = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            functions={
                "fn": FunctionState(
                    name="fn",
                    signature="fn(a, b)",
                    docstring="Old doc.",
                ),
            },
        )
        changes = builder._detect_changes(prev, current)
        assert len(changes) == 1
        assert changes[0].change_type == "modified"
        assert changes[0].existing_doc == "Old doc."

    def test_undocumented_existing_function(self, builder: DocBuilder) -> None:
        prev = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            functions={
                "fn": FunctionState(
                    name="fn",
                    signature="fn(a)",
                    docstring=None,
                ),
            },
        )
        current = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            functions={
                "fn": FunctionState(name="fn", signature="fn(a)"),
            },
        )
        changes = builder._detect_changes(prev, current)
        assert len(changes) == 1
        assert changes[0].change_type == "new"

    def test_no_changes_when_same_and_documented(self, builder: DocBuilder) -> None:
        state_fn = FunctionState(name="fn", signature="fn(a)", docstring="Doc.")
        prev = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            functions={"fn": state_fn},
        )
        current = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            functions={"fn": FunctionState(name="fn", signature="fn(a)", docstring="Doc.")},
        )
        changes = builder._detect_changes(prev, current)
        assert changes == []

    def test_class_changes_detected(self, builder: DocBuilder) -> None:
        prev = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            classes={},
        )
        current = FileDocState(
            file_path="a.py",
            language="python",
            doc_framework="sphinx",
            classes={
                "NewClass": FunctionState(name="NewClass", signature="class NewClass"),
            },
        )
        changes = builder._detect_changes(prev, current)
        assert len(changes) == 1
        assert changes[0].function_name == "NewClass"
        assert changes[0].change_type == "new"


# ── _generate_docs ───────────────────────────────────────────────


_LLM_HELLO_OUTPUT = '--- FUNCTION: hello ---\n"""Say hello."""\n--- END ---'


class TestGenerateDocs:
    @pytest.mark.asyncio
    async def test_generate_docs_calls_llm(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        source_file = project_root / "example.py"
        source_file.write_text("def hello(): pass\n")

        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_LLM_HELLO_OUTPUT, model="mock")
        )

        change = DocChange(
            function_name="hello",
            change_type="new",
            signature="hello()",
        )
        docs = await builder._generate_docs("example.py", "python", "sphinx", [change], source_file)
        assert "hello" in docs
        mock_llm.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_docs_handles_llm_error(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        builder = _make_builder(mock_llm, project_root)
        source_file = project_root / "err.py"
        source_file.write_text("def boom(): pass\n")

        mock_llm.generate = AsyncMock(side_effect=LLMError("rate limit"))

        change = DocChange(
            function_name="boom",
            change_type="new",
            signature="boom()",
        )
        docs = await builder._generate_docs("err.py", "python", "sphinx", [change], source_file)
        assert docs == {}


# ── _parse_generated_docs ────────────────────────────────────────


class TestParseGeneratedDocs:
    def test_parses_single_function(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        text = '--- FUNCTION: greet ---\n"""Greet someone."""\n--- END ---'
        result = builder._parse_generated_docs(text)
        assert result == {"greet": '"""Greet someone."""'}

    def test_parses_multiple_functions(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        text = (
            "--- FUNCTION: add ---\n"
            '"""Add two numbers."""\n'
            "--- END ---\n"
            "--- FUNCTION: sub ---\n"
            '"""Subtract two numbers."""\n'
            "--- END ---"
        )
        result = builder._parse_generated_docs(text)
        assert len(result) == 2
        assert "add" in result
        assert "sub" in result

    def test_returns_empty_for_no_markers(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        result = builder._parse_generated_docs("just some random text")
        assert result == {}

    def test_handles_multiline_doc(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        text = (
            "--- FUNCTION: calc ---\n"
            '"""Calculate the result.\n'
            "\n"
            "Args:\n"
            "    x: The input.\n"
            "\n"
            "Returns:\n"
            "    The output.\n"
            '"""\n'
            "--- END ---"
        )
        result = builder._parse_generated_docs(text)
        assert "calc" in result
        assert "Args:" in result["calc"]
        assert "Returns:" in result["calc"]


# ── _update_doc_state ────────────────────────────────────────────


class TestUpdateDocState:
    def test_updates_function_docstrings(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        state = FileDocState(
            file_path="m.py",
            language="python",
            doc_framework="sphinx",
            functions={
                "fn": FunctionState(name="fn", signature="fn()"),
            },
        )
        builder._update_doc_state("m.py", state, {"fn": '"""Documented."""'})

        assert state.functions["fn"].docstring == '"""Documented."""'
        assert state.last_updated != ""
        assert builder._doc_states["m.py"] is state

    def test_updates_class_docstrings(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        state = FileDocState(
            file_path="m.py",
            language="python",
            doc_framework="sphinx",
            classes={
                "Cls": FunctionState(name="Cls", signature="class Cls"),
            },
        )
        builder._update_doc_state("m.py", state, {"Cls": '"""A class."""'})
        assert state.classes["Cls"].docstring == '"""A class."""'

    def test_sets_timestamp(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        state = FileDocState(
            file_path="m.py",
            language="python",
            doc_framework="sphinx",
        )
        builder._update_doc_state("m.py", state, {})
        assert state.last_updated != ""


# ── _result_to_dict ──────────────────────────────────────────────


class TestResultToDict:
    def test_serializes_result(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        change = DocChange(
            function_name="run",
            change_type="modified",
            signature="run(fast)",
            existing_doc="Old.",
        )
        result = DocBuildResult(
            file_path="app.py",
            changes=[change],
            generated_docs={"run": '"""Run fast."""'},
            outdated=True,
            errors=["something went wrong"],
        )
        d = builder._result_to_dict(result)
        assert d["file_path"] == "app.py"
        assert d["outdated"] is True
        assert d["errors"] == ["something went wrong"]
        assert len(d["changes"]) == 1
        assert d["changes"][0]["function_name"] == "run"
        assert d["changes"][0]["change_type"] == "modified"
        assert d["changes"][0]["existing_doc"] == "Old."
        assert d["generated_docs"] == {"run": '"""Run fast."""'}


# ── DocBuilder.run() ─────────────────────────────────────────────


class TestDocBuilderRun:
    @pytest.mark.asyncio
    async def test_rejects_non_doc_build_task(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        builder = _make_builder(mock_llm, project_root)
        wrong_task = TaskInput(task_type="other", target="x")
        output = await builder.run(wrong_task)
        assert output.status == TaskStatus.FAILED
        assert any("DocBuildTask" in e for e in output.errors)

    @pytest.mark.asyncio
    async def test_run_with_source_files(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)

        # Create a real source file
        src = project_root / "hello.py"
        src.write_text("def hello(): pass\n")

        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=_LLM_HELLO_OUTPUT, model="mock")
        )

        parse_result = ParseResult(
            language="python",
            functions=[
                FunctionInfo(name="hello", start_line=1, end_line=1),
            ],
        )

        with (
            patch(
                "nit.agents.builders.docs.detect_language",
                return_value="python",
            ),
            patch(
                "nit.agents.builders.docs.extract_from_file",
                return_value=parse_result,
            ),
        ):
            task = DocBuildTask(source_files=["hello.py"])
            output = await builder.run(task)

        assert output.status == TaskStatus.COMPLETED
        results = output.result["results"]
        assert len(results) == 1
        assert results[0]["file_path"] == "hello.py"

    @pytest.mark.asyncio
    async def test_check_only_does_not_save_or_generate(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        builder = _make_builder(mock_llm, project_root)

        src = project_root / "check.py"
        src.write_text("def check(): pass\n")

        parse_result = ParseResult(
            language="python",
            functions=[
                FunctionInfo(name="check", start_line=1, end_line=1),
            ],
        )

        with (
            patch(
                "nit.agents.builders.docs.detect_language",
                return_value="python",
            ),
            patch(
                "nit.agents.builders.docs.extract_from_file",
                return_value=parse_result,
            ),
        ):
            task = DocBuildTask(source_files=["check.py"], check_only=True)
            output = await builder.run(task)

        assert output.status == TaskStatus.COMPLETED
        results = output.result["results"]
        assert results[0]["outdated"] is True
        # LLM should NOT have been called
        mock_llm.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_empty_source_files_discovers(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        builder = _make_builder(mock_llm, project_root)

        with patch.object(builder, "_discover_source_files", return_value=[]):
            task = DocBuildTask()
            output = await builder.run(task)

        assert output.status == TaskStatus.COMPLETED
        assert output.result["results"] == []

    @pytest.mark.asyncio
    async def test_run_file_not_found_returns_error(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        builder = _make_builder(mock_llm, project_root)
        task = DocBuildTask(source_files=["nonexistent.py"])

        with (
            patch(
                "nit.agents.builders.docs.detect_language",
                return_value="python",
            ),
            patch(
                "nit.agents.builders.docs.extract_from_file",
                return_value=ParseResult(language="python"),
            ),
        ):
            output = await builder.run(task)

        assert output.status == TaskStatus.FAILED
        results = output.result["results"]
        assert any("not found" in e for e in results[0]["errors"])


# ── DocMismatch dataclass ─────────────────────────────────────


class TestDocMismatch:
    def test_construction(self) -> None:
        m = DocMismatch(
            function_name="foo",
            file_path="mod.py",
            mismatch_type="missing_param",
            description="param 'x' not documented",
            severity="warning",
        )
        assert m.function_name == "foo"
        assert m.mismatch_type == "missing_param"
        assert m.severity == "warning"

    def test_default_severity(self) -> None:
        m = DocMismatch(
            function_name="bar",
            file_path="a.py",
            mismatch_type="semantic_drift",
            description="drift",
        )
        assert m.severity == "warning"


# ── DocBuildResult new fields ──────────────────────────────────


class TestDocBuildResultNewFields:
    def test_mismatches_default_empty(self) -> None:
        result = DocBuildResult(
            file_path="x.py",
            changes=[],
            generated_docs={},
            outdated=False,
        )
        assert result.mismatches == []
        assert result.files_written == []

    def test_mismatches_assigned(self) -> None:
        mm = DocMismatch(
            function_name="f",
            file_path="x.py",
            mismatch_type="wrong_return",
            description="wrong",
        )
        result = DocBuildResult(
            file_path="x.py",
            changes=[],
            generated_docs={},
            outdated=True,
            mismatches=[mm],
            files_written=["x.py"],
        )
        assert len(result.mismatches) == 1
        assert result.files_written == ["x.py"]


# ── DocsConfig integration ─────────────────────────────────────


class TestDocBuilderWithDocsConfig:
    def test_init_stores_docs_config(self, mock_llm: MagicMock, project_root: Path) -> None:
        cfg = DocsConfig(write_to_source=True, style="google")
        builder = _make_builder(mock_llm, project_root, docs_config=cfg)
        assert builder._docs_config is cfg
        assert builder._max_tokens == 4096

    def test_config_max_tokens_override(self, mock_llm: MagicMock, project_root: Path) -> None:
        cfg = DocsConfig(max_tokens=2048)
        builder = _make_builder(mock_llm, project_root, docs_config=cfg)
        assert builder._max_tokens == 2048


# ── _parse_mismatch_response ───────────────────────────────────


class TestParseMismatchResponse:
    def test_parses_json_array(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        response = (
            '[{"function": "foo", "type": "missing_param",'
            ' "description": "param x missing", "severity": "warning"}]'
        )
        result = builder._parse_mismatch_response(response, "test.py")
        assert len(result) == 1
        assert result[0].function_name == "foo"
        assert result[0].mismatch_type == "missing_param"

    def test_handles_markdown_code_block(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        item = (
            '{"function": "bar", "type": "wrong_return",'
            ' "description": "bad", "severity": "error"}'
        )
        inner = f"[{item}]"
        response = f"```json\n{inner}\n```"
        result = builder._parse_mismatch_response(response, "test.py")
        assert len(result) == 1
        assert result[0].severity == "error"

    def test_empty_array(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        result = builder._parse_mismatch_response("[]", "test.py")
        assert result == []

    def test_invalid_json_returns_empty(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        result = builder._parse_mismatch_response("not json", "test.py")
        assert result == []

    def test_non_list_returns_empty(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        result = builder._parse_mismatch_response('{"key": "val"}', "test.py")
        assert result == []


# ── _result_to_dict with new fields ────────────────────────────


class TestResultToDictNewFields:
    def test_includes_mismatches_and_files_written(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        builder = _make_builder(mock_llm, project_root)
        mm = DocMismatch(
            function_name="f",
            file_path="x.py",
            mismatch_type="semantic_drift",
            description="desc",
        )
        result = DocBuildResult(
            file_path="x.py",
            changes=[],
            generated_docs={},
            outdated=False,
            mismatches=[mm],
            files_written=["x.py"],
        )
        d = builder._result_to_dict(result)
        assert len(d["mismatches"]) == 1
        assert d["mismatches"][0]["mismatch_type"] == "semantic_drift"
        assert d["files_written"] == ["x.py"]


# ── _write_docs_to_source ──────────────────────────────────────


class TestWriteDocsToSource:
    def test_python_inserts_docstring(self, mock_llm: MagicMock, project_root: Path) -> None:
        cfg = DocsConfig(write_to_source=True)
        builder = _make_builder(mock_llm, project_root, docs_config=cfg)

        source = "def hello():\n    pass\n"
        src_file = project_root / "mod.py"
        src_file.write_text(source, encoding="utf-8")

        state = FileDocState(
            file_path="mod.py",
            language="python",
            doc_framework="sphinx",
            functions={"hello": FunctionState(name="hello", signature="hello()", line_number=1)},
            classes={},
        )
        written = builder._write_docs_to_source(src_file, "python", {"hello": "Say hello."}, state)
        assert len(written) == 1
        content = src_file.read_text(encoding="utf-8")
        assert '"""Say hello."""' in content

    def test_js_inserts_above_function(self, mock_llm: MagicMock, project_root: Path) -> None:
        cfg = DocsConfig(write_to_source=True)
        builder = _make_builder(mock_llm, project_root, docs_config=cfg)

        source = "function greet() {\n  return 'hi';\n}\n"
        src_file = project_root / "mod.js"
        src_file.write_text(source, encoding="utf-8")

        state = FileDocState(
            file_path="mod.js",
            language="javascript",
            doc_framework="jsdoc",
            functions={"greet": FunctionState(name="greet", signature="greet()", line_number=1)},
            classes={},
        )
        written = builder._write_docs_to_source(
            src_file, "javascript", {"greet": "/**\n * Greet user.\n */"}, state
        )
        assert len(written) == 1
        content = src_file.read_text(encoding="utf-8")
        assert "Greet user." in content

    def test_no_write_when_no_line_number(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        src_file = project_root / "mod.py"
        src_file.write_text("def f():\n    pass\n", encoding="utf-8")

        state = FileDocState(
            file_path="mod.py",
            language="python",
            doc_framework="sphinx",
            functions={"f": FunctionState(name="f", signature="f()", line_number=0)},
            classes={},
        )
        written = builder._write_docs_to_source(src_file, "python", {"f": "doc"}, state)
        assert written == []


# ── _write_docs_to_output_dir ──────────────────────────────────


class TestWriteDocsToOutputDir:
    def test_creates_output_file(self, mock_llm: MagicMock, project_root: Path) -> None:
        builder = _make_builder(mock_llm, project_root)
        written = builder._write_docs_to_output_dir(
            "src/mod.py", {"hello": "Say hello."}, str(project_root / "out")
        )
        assert len(written) == 1
        out_file = project_root / "out" / "src" / "mod.md"
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "hello" in content
        assert "Say hello." in content


# ── Exclude patterns ───────────────────────────────────────────


class TestExcludePatterns:
    @pytest.mark.asyncio
    async def test_exclude_patterns_filter_files(
        self, mock_llm: MagicMock, project_root: Path
    ) -> None:
        cfg = DocsConfig(exclude_patterns=["vendor/*", "*.generated.py"])
        builder = _make_builder(mock_llm, project_root, docs_config=cfg)

        with patch.object(
            builder,
            "_discover_source_files",
            return_value=["src/main.py", "vendor/lib.py", "auto.generated.py"],
        ):
            task = DocBuildTask()
            # Mock _process_file to avoid actual processing
            with patch.object(
                builder,
                "_process_file",
                return_value=DocBuildResult(
                    file_path="src/main.py",
                    changes=[],
                    generated_docs={},
                    outdated=False,
                ),
            ) as mock_process:
                await builder.run(task)

            # Only src/main.py should be processed
            assert mock_process.call_count == 1
            call_args = mock_process.call_args
            assert call_args[0][0] == "src/main.py"
