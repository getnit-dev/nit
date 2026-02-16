"""Tests for the Prompt Template Library (llm/prompts/)."""

from __future__ import annotations

from nit.llm.context import AssembledContext, DetectedTestPattern, RelatedFile
from nit.llm.engine import LLMMessage
from nit.llm.prompts import (
    AccessibilityTestTemplate,
    AlembicMigrationTemplate,
    Catch2Template,
    ContractTestTemplate,
    DjangoMigrationTemplate,
    GraphQLTestTemplate,
    GTestTemplate,
    JestAxeTemplate,
    JestPactTemplate,
    JestSnapshotTemplate,
    JestTemplate,
    MigrationTestTemplate,
    MochaTemplate,
    PlaywrightAxeTemplate,
    PromptSection,
    PromptTemplate,
    PytestPactTemplate,
    PytestSyrupyTemplate,
    PytestTemplate,
    RenderedPrompt,
    SnapshotTestTemplate,
    UnitTestTemplate,
    VitestPactTemplate,
    VitestTemplate,
)
from nit.llm.prompts.base import (
    _join_sections,
    format_dependencies_section,
    format_related_files_section,
    format_signatures_section,
    format_source_section,
    format_test_patterns_section,
)
from nit.llm.prompts.cargo_test_prompt import CargoTestTemplate
from nit.llm.prompts.go_test_prompt import GoTestTemplate
from nit.llm.prompts.integration_test import (
    IntegrationTestTemplate,
    JestIntegrationTemplate,
    PytestIntegrationTemplate,
    VitestIntegrationTemplate,
)
from nit.llm.prompts.junit5_prompt import JUnit5Template
from nit.llm.prompts.kotest_prompt import KotestTemplate
from nit.llm.prompts.testify_prompt import TestifyTemplate
from nit.llm.prompts.xunit_prompt import XUnitTemplate
from nit.parsing.treesitter import (
    ClassInfo,
    FunctionInfo,
    ImportInfo,
    ParameterInfo,
    ParseResult,
)

# ── Helpers ──────────────────────────────────────────────────────


_DEFAULT_FUNCTION = FunctionInfo(
    name="add",
    start_line=1,
    end_line=2,
    parameters=[
        ParameterInfo(name="a", type_annotation="int"),
        ParameterInfo(name="b", type_annotation="int"),
    ],
    return_type="int",
    decorators=[],
    is_method=False,
    is_async=False,
    body_text="return a + b",
)


def _make_parse_result(
    language: str = "python",
    imports: list[ImportInfo] | None = None,
    classes: list[ClassInfo] | None = None,
) -> ParseResult:
    return ParseResult(
        language=language,
        functions=[_DEFAULT_FUNCTION],
        classes=classes or [],
        imports=imports or [],
    )


def _make_context(
    *,
    language: str = "python",
    source_code: str = "def add(a, b):\n    return a + b\n",
    parse_result: ParseResult | None = None,
    related_files: list[RelatedFile] | None = None,
    test_patterns: DetectedTestPattern | None = None,
) -> AssembledContext:
    """Build a minimal ``AssembledContext`` for testing."""
    return AssembledContext(
        source_path=f"src/module.{_ext_for(language)}",
        source_code=source_code,
        language=language,
        parse_result=parse_result or _make_parse_result(language),
        related_files=related_files or [],
        test_patterns=test_patterns,
    )


def _ext_for(language: str) -> str:
    return {"python": "py", "typescript": "ts", "javascript": "js", "cpp": "cpp"}.get(
        language, "py"
    )


# ── RenderedPrompt ───────────────────────────────────────────────


class TestRenderedPrompt:
    def test_system_message_property(self) -> None:
        rp = RenderedPrompt(
            messages=[
                _msg("system", "sys content"),
                _msg("user", "usr content"),
            ]
        )
        assert rp.system_message == "sys content"

    def test_user_message_property(self) -> None:
        rp = RenderedPrompt(
            messages=[
                _msg("system", "sys"),
                _msg("user", "usr content"),
            ]
        )
        assert rp.user_message == "usr content"

    def test_empty_messages(self) -> None:
        rp = RenderedPrompt()
        assert rp.system_message == ""
        assert rp.user_message == ""


# ── PromptSection helpers ────────────────────────────────────────


class TestFormatHelpers:
    def test_format_source_section(self) -> None:
        ctx = _make_context()
        section = format_source_section(ctx)
        assert section.label == "Source File"
        assert "src/module.py" in section.content
        assert "def add" in section.content
        assert "```python" in section.content

    def test_format_signatures_section(self) -> None:
        ctx = _make_context()
        section = format_signatures_section(ctx)
        assert section.label == "Signatures"
        assert "add" in section.content

    def test_format_signatures_with_classes(self) -> None:
        ctx = _make_context(
            parse_result=_make_parse_result(
                classes=[
                    ClassInfo(
                        name="Calc",
                        start_line=1,
                        end_line=5,
                        methods=[
                            FunctionInfo(
                                name="add",
                                start_line=2,
                                end_line=3,
                                parameters=[],
                                return_type=None,
                                decorators=[],
                                is_method=True,
                                is_async=False,
                                body_text="",
                            ),
                        ],
                        bases=["object"],
                        body_text="",
                    ),
                ],
            ),
        )
        section = format_signatures_section(ctx)
        assert "Calc" in section.content

    def test_format_test_patterns_with_patterns(self) -> None:
        tp = DetectedTestPattern(
            naming_style="function",
            assertion_style="assert",
            mocking_patterns=["pytest.fixture", "monkeypatch"],
            imports=["import pytest"],
            sample_test="def test_add():\n    assert add(1, 2) == 3",
        )
        ctx = _make_context(test_patterns=tp)
        section = format_test_patterns_section(ctx)
        assert "function" in section.content
        assert "assert" in section.content
        assert "pytest.fixture" in section.content
        assert "test_add" in section.content

    def test_format_test_patterns_none(self) -> None:
        ctx = _make_context(test_patterns=None)
        section = format_test_patterns_section(ctx)
        assert "No existing tests found" in section.content

    def test_format_dependencies_section(self) -> None:
        ctx = _make_context(
            parse_result=_make_parse_result(
                imports=[
                    ImportInfo(module="os", names=["path"], alias=None, start_line=1),
                    ImportInfo(module="sys", names=[], alias=None, start_line=2),
                ],
            ),
        )
        section = format_dependencies_section(ctx)
        assert "os" in section.content
        assert "path" in section.content
        assert "sys" in section.content

    def test_format_dependencies_empty(self) -> None:
        ctx = _make_context(parse_result=_make_parse_result(imports=[]))
        section = format_dependencies_section(ctx)
        assert "No imports detected" in section.content

    def test_format_related_files_section(self) -> None:
        ctx = _make_context(
            related_files=[
                RelatedFile(
                    path="tests/test_math.py",
                    relationship="test",
                    content_snippet="def test_add(): ...",
                ),
            ],
        )
        section = format_related_files_section(ctx)
        assert "test_math.py" in section.content
        assert "test" in section.content

    def test_format_related_files_none(self) -> None:
        ctx = _make_context(related_files=[])
        section = format_related_files_section(ctx)
        assert section.content == "None."

    def test_join_sections(self) -> None:
        sections = [
            PromptSection(label="A", content="alpha"),
            PromptSection(label="B", content="beta"),
        ]
        result = _join_sections(sections)
        assert "## A" in result
        assert "alpha" in result
        assert "## B" in result
        assert "beta" in result
        assert "---" in result

    def test_join_sections_skips_empty(self) -> None:
        sections = [
            PromptSection(label="A", content="alpha"),
            PromptSection(label="B", content=""),
            PromptSection(label="C", content="gamma"),
        ]
        result = _join_sections(sections)
        assert "## B" not in result


# ── UnitTestTemplate ─────────────────────────────────────────────


class TestUnitTestTemplate:
    def test_is_prompt_template(self) -> None:
        assert isinstance(UnitTestTemplate(), PromptTemplate)

    def test_name(self) -> None:
        assert UnitTestTemplate().name == "unit_test"

    def test_render_produces_two_messages(self) -> None:
        ctx = _make_context()
        result = UnitTestTemplate().render(ctx)
        assert isinstance(result, RenderedPrompt)
        assert len(result.messages) == 2
        assert result.messages[0].role == "system"
        assert result.messages[1].role == "user"

    def test_system_message_contains_guidelines(self) -> None:
        ctx = _make_context()
        result = UnitTestTemplate().render(ctx)
        sys_msg = result.system_message
        assert "unit test" in sys_msg.lower()
        assert "edge case" in sys_msg.lower()

    def test_user_message_contains_source(self) -> None:
        ctx = _make_context()
        result = UnitTestTemplate().render(ctx)
        assert "def add" in result.user_message

    def test_user_message_contains_signatures(self) -> None:
        ctx = _make_context()
        result = UnitTestTemplate().render(ctx)
        assert "Signatures" in result.user_message

    def test_user_message_contains_output_instructions(self) -> None:
        ctx = _make_context()
        result = UnitTestTemplate().render(ctx)
        assert "Output Instructions" in result.user_message

    def test_user_message_contains_language(self) -> None:
        ctx = _make_context(language="python")
        result = UnitTestTemplate().render(ctx)
        assert "python" in result.user_message.lower()

    def test_includes_test_patterns_when_present(self) -> None:
        tp = DetectedTestPattern(naming_style="function", assertion_style="assert")
        ctx = _make_context(test_patterns=tp)
        result = UnitTestTemplate().render(ctx)
        assert "Existing Test Patterns" in result.user_message
        assert "function" in result.user_message

    def test_includes_related_files_when_present(self) -> None:
        ctx = _make_context(
            related_files=[
                RelatedFile(
                    path="helpers.py",
                    relationship="import",
                    content_snippet="def helper(): ...",
                ),
            ],
        )
        result = UnitTestTemplate().render(ctx)
        assert "Related Files" in result.user_message
        assert "helpers.py" in result.user_message

    def test_excludes_related_section_when_empty(self) -> None:
        ctx = _make_context(related_files=[])
        result = UnitTestTemplate().render(ctx)
        assert "Related Files" not in result.user_message


# ── VitestTemplate ───────────────────────────────────────────────


class TestVitestTemplate:
    def test_is_prompt_template(self) -> None:
        assert isinstance(VitestTemplate(), PromptTemplate)

    def test_name(self) -> None:
        assert VitestTemplate().name == "vitest"

    def test_render_produces_messages(self) -> None:
        ctx = _make_context(language="typescript")
        result = VitestTemplate().render(ctx)
        assert len(result.messages) == 2

    def test_system_includes_vitest_rules(self) -> None:
        ctx = _make_context(language="typescript")
        result = VitestTemplate().render(ctx)
        sys_msg = result.system_message
        assert "vitest" in sys_msg.lower()
        assert "describe" in sys_msg.lower()
        assert "vi.mock" in sys_msg

    def test_user_includes_vitest_example(self) -> None:
        ctx = _make_context(language="typescript")
        result = VitestTemplate().render(ctx)
        assert "Vitest Example" in result.user_message
        assert "describe(" in result.user_message
        assert "expect(" in result.user_message

    def test_output_instructions_mention_vitest(self) -> None:
        ctx = _make_context(language="typescript")
        result = VitestTemplate().render(ctx)
        assert "Vitest" in result.user_message
        assert ".test.ts" in result.user_message

    def test_inherits_base_sections(self) -> None:
        ctx = _make_context(language="typescript")
        result = VitestTemplate().render(ctx)
        assert "Source File" in result.user_message
        assert "Signatures" in result.user_message

    def test_includes_source_code(self) -> None:
        ctx = _make_context(
            language="typescript",
            source_code="export function add(a: number, b: number): number { return a + b; }",
        )
        result = VitestTemplate().render(ctx)
        assert "export function add" in result.user_message


# ── PytestTemplate ───────────────────────────────────────────────


class TestPytestTemplate:
    def test_is_prompt_template(self) -> None:
        assert isinstance(PytestTemplate(), PromptTemplate)

    def test_name(self) -> None:
        assert PytestTemplate().name == "pytest"

    def test_render_produces_messages(self) -> None:
        ctx = _make_context(language="python")
        result = PytestTemplate().render(ctx)
        assert len(result.messages) == 2

    def test_system_includes_pytest_rules(self) -> None:
        ctx = _make_context(language="python")
        result = PytestTemplate().render(ctx)
        sys_msg = result.system_message
        assert "pytest" in sys_msg.lower()
        assert "assert" in sys_msg
        assert "fixture" in sys_msg.lower()

    def test_user_includes_pytest_example(self) -> None:
        ctx = _make_context(language="python")
        result = PytestTemplate().render(ctx)
        assert "pytest Example" in result.user_message
        assert "def test_" in result.user_message
        assert "@pytest.fixture" in result.user_message
        assert "parametrize" in result.user_message

    def test_output_instructions_mention_pytest(self) -> None:
        ctx = _make_context(language="python")
        result = PytestTemplate().render(ctx)
        assert "pytest" in result.user_message
        assert "test_*.py" in result.user_message

    def test_inherits_base_sections(self) -> None:
        ctx = _make_context(language="python")
        result = PytestTemplate().render(ctx)
        assert "Source File" in result.user_message
        assert "Signatures" in result.user_message

    def test_includes_dependencies(self) -> None:
        ctx = _make_context(
            parse_result=_make_parse_result(
                imports=[
                    ImportInfo(module="pathlib", names=["Path"], alias=None, start_line=1),
                ],
            ),
        )
        result = PytestTemplate().render(ctx)
        assert "pathlib" in result.user_message


# ── GTestTemplate ────────────────────────────────────────────────


class TestGTestTemplate:
    def test_is_prompt_template(self) -> None:
        assert isinstance(GTestTemplate(), PromptTemplate)

    def test_name(self) -> None:
        assert GTestTemplate().name == "gtest"

    def test_render_produces_messages(self) -> None:
        ctx = _make_context(language="cpp", source_code="int add(int a, int b) { return a + b; }")
        result = GTestTemplate().render(ctx)
        assert len(result.messages) == 2

    def test_system_includes_gtest_rules(self) -> None:
        ctx = _make_context(language="cpp", source_code="int add(int a, int b) { return a + b; }")
        result = GTestTemplate().render(ctx)
        sys_msg = result.system_message
        assert "google test" in sys_msg.lower()
        assert "test_f" in sys_msg.lower()
        assert "expect_" in sys_msg.lower()

    def test_user_includes_gtest_example(self) -> None:
        ctx = _make_context(language="cpp", source_code="int add(int a, int b) { return a + b; }")
        result = GTestTemplate().render(ctx)
        assert "Google Test Example" in result.user_message
        assert "#include <gtest/gtest.h>" in result.user_message
        assert "TEST(" in result.user_message

    def test_output_instructions_mention_gtest(self) -> None:
        ctx = _make_context(language="cpp", source_code="int add(int a, int b) { return a + b; }")
        result = GTestTemplate().render(ctx)
        assert "Google Test" in result.user_message
        assert "*_test.cpp" in result.user_message


# ── Catch2Template ───────────────────────────────────────────────


class TestCatch2Template:
    def test_is_prompt_template(self) -> None:
        assert isinstance(Catch2Template(), PromptTemplate)

    def test_name(self) -> None:
        assert Catch2Template().name == "catch2"

    def test_render_produces_messages(self) -> None:
        ctx = _make_context(language="cpp", source_code="int add(int a, int b) { return a + b; }")
        result = Catch2Template().render(ctx)
        assert len(result.messages) == 2

    def test_system_includes_catch2_rules(self) -> None:
        ctx = _make_context(language="cpp", source_code="int add(int a, int b) { return a + b; }")
        result = Catch2Template().render(ctx)
        sys_msg = result.system_message
        assert "catch2" in sys_msg.lower()
        assert "test_case" in sys_msg.lower()
        assert "require" in sys_msg.lower()

    def test_user_includes_catch2_example(self) -> None:
        ctx = _make_context(language="cpp", source_code="int add(int a, int b) { return a + b; }")
        result = Catch2Template().render(ctx)
        assert "Catch2 Example" in result.user_message
        assert "#include <catch2/catch_test_macros.hpp>" in result.user_message
        assert "TEST_CASE(" in result.user_message

    def test_output_instructions_mention_catch2(self) -> None:
        ctx = _make_context(language="cpp", source_code="int add(int a, int b) { return a + b; }")
        result = Catch2Template().render(ctx)
        assert "Catch2" in result.user_message
        assert "*_test.cpp" in result.user_message


# ── Cross-template consistency ───────────────────────────────────


_ALL_UNIT_TEMPLATES: list[type[PromptTemplate]] = [
    UnitTestTemplate,
    VitestTemplate,
    PytestTemplate,
    GTestTemplate,
    Catch2Template,
    GoTestTemplate,
    JestTemplate,
    JUnit5Template,
    KotestTemplate,
    MochaTemplate,
    XUnitTemplate,
    TestifyTemplate,
    CargoTestTemplate,
]

_ALL_STANDALONE_TEMPLATES: list[type[PromptTemplate]] = [
    MigrationTestTemplate,
    AlembicMigrationTemplate,
    DjangoMigrationTemplate,
    SnapshotTestTemplate,
    JestSnapshotTemplate,
    PytestSyrupyTemplate,
    GraphQLTestTemplate,
    AccessibilityTestTemplate,
    PlaywrightAxeTemplate,
    JestAxeTemplate,
    ContractTestTemplate,
    PytestPactTemplate,
    JestPactTemplate,
    VitestPactTemplate,
    IntegrationTestTemplate,
    PytestIntegrationTemplate,
    VitestIntegrationTemplate,
    JestIntegrationTemplate,
]


class TestTemplateCrossConsistency:
    def test_all_templates_produce_system_and_user(self) -> None:
        ctx = _make_context()
        for template_cls in [*_ALL_UNIT_TEMPLATES, *_ALL_STANDALONE_TEMPLATES]:
            result = template_cls().render(ctx)
            assert result.system_message, f"{template_cls.__name__} has empty system message"
            assert result.user_message, f"{template_cls.__name__} has empty user message"

    def test_all_templates_include_source(self) -> None:
        ctx = _make_context(source_code="def foo(): pass\n")
        for template_cls in [*_ALL_UNIT_TEMPLATES, *_ALL_STANDALONE_TEMPLATES]:
            result = template_cls().render(ctx)
            assert "def foo" in result.user_message, f"{template_cls.__name__} missing source code"

    def test_all_unit_templates_include_output_instructions(self) -> None:
        ctx = _make_context()
        for template_cls in _ALL_UNIT_TEMPLATES:
            result = template_cls().render(ctx)
            assert (
                "Output Instructions" in result.user_message
            ), f"{template_cls.__name__} missing output instructions"

    def test_framework_templates_have_distinct_names(self) -> None:
        names = {cls().name for cls in [*_ALL_UNIT_TEMPLATES, *_ALL_STANDALONE_TEMPLATES]}
        assert len(names) == len(_ALL_UNIT_TEMPLATES) + len(_ALL_STANDALONE_TEMPLATES)

    def test_framework_templates_add_framework_content(self) -> None:
        ctx = _make_context()
        base_result = UnitTestTemplate().render(ctx)
        for template_cls in _ALL_UNIT_TEMPLATES:
            if template_cls is UnitTestTemplate:
                continue
            result = template_cls().render(ctx)
            assert len(result.system_message) > len(
                base_result.system_message
            ), f"{template_cls.__name__} should have longer system message than base"
            assert len(result.user_message) > len(
                base_result.user_message
            ), f"{template_cls.__name__} should have longer user message than base"


# ── Standalone template tests ────────────────────────────────────


class TestMigrationTemplates:
    def test_base_migration_name(self) -> None:
        assert MigrationTestTemplate().name == "migration_test"

    def test_alembic_migration_name(self) -> None:
        assert AlembicMigrationTemplate().name == "alembic_migration"

    def test_django_migration_name(self) -> None:
        assert DjangoMigrationTemplate().name == "django_migration"

    def test_alembic_includes_alembic_instructions(self) -> None:
        ctx = _make_context()
        result = AlembicMigrationTemplate().render(ctx)
        assert "alembic" in result.system_message.lower()

    def test_django_includes_django_instructions(self) -> None:
        ctx = _make_context()
        result = DjangoMigrationTemplate().render(ctx)
        assert "django" in result.system_message.lower()

    def test_migration_includes_schema_section(self) -> None:
        ctx = _make_context()
        result = MigrationTestTemplate().render(ctx)
        assert "Schema Validation" in result.user_message
        assert "Migration Testing" in result.user_message

    def test_migration_output_instructions(self) -> None:
        ctx = _make_context()
        result = MigrationTestTemplate().render(ctx)
        assert "Output Instructions" in result.user_message


class TestSnapshotTemplates:
    def test_base_snapshot_name(self) -> None:
        assert SnapshotTestTemplate().name == "snapshot_test"

    def test_jest_snapshot_name(self) -> None:
        assert JestSnapshotTemplate().name == "jest_snapshot"

    def test_pytest_syrupy_name(self) -> None:
        assert PytestSyrupyTemplate().name == "pytest_syrupy"

    def test_jest_snapshot_includes_jest_instructions(self) -> None:
        ctx = _make_context()
        result = JestSnapshotTemplate().render(ctx)
        assert "jest" in result.system_message.lower()

    def test_pytest_syrupy_includes_syrupy_instructions(self) -> None:
        ctx = _make_context()
        result = PytestSyrupyTemplate().render(ctx)
        assert "syrupy" in result.system_message.lower()

    def test_snapshot_includes_snapshot_sections(self) -> None:
        ctx = _make_context()
        result = SnapshotTestTemplate().render(ctx)
        assert "Snapshot Testing" in result.user_message
        assert "Snapshot Testing Patterns" in result.user_message

    def test_snapshot_output_instructions(self) -> None:
        ctx = _make_context()
        result = SnapshotTestTemplate().render(ctx)
        assert "Output Instructions" in result.user_message


class TestGraphQLTemplate:
    def test_name(self) -> None:
        assert GraphQLTestTemplate().name == "graphql_test"

    def test_render_includes_graphql_instructions(self) -> None:
        ctx = _make_context()
        result = GraphQLTestTemplate().render(ctx)
        assert "GraphQL" in result.user_message

    def test_render_includes_example(self) -> None:
        ctx = _make_context()
        result = GraphQLTestTemplate().render(ctx)
        assert "Example Test" in result.user_message

    def test_render_includes_requirements(self) -> None:
        ctx = _make_context()
        result = GraphQLTestTemplate().render(ctx)
        assert "Requirements" in result.user_message


# ── AccessibilityTestTemplate ────────────────────────────────────


class TestAccessibilityTemplates:
    def test_base_name(self) -> None:
        assert AccessibilityTestTemplate().name == "accessibility_test"

    def test_playwright_axe_name(self) -> None:
        assert PlaywrightAxeTemplate().name == "playwright_axe"

    def test_jest_axe_name(self) -> None:
        assert JestAxeTemplate().name == "jest_axe"

    def test_includes_a11y_sections(self) -> None:
        ctx = _make_context()
        result = AccessibilityTestTemplate().render(ctx)
        assert "Accessibility Testing" in result.user_message
        assert "Accessibility Testing Patterns" in result.user_message

    def test_output_instructions(self) -> None:
        ctx = _make_context()
        result = AccessibilityTestTemplate().render(ctx)
        assert "Output Instructions" in result.user_message

    def test_playwright_includes_framework_instructions(self) -> None:
        ctx = _make_context(language="typescript")
        result = PlaywrightAxeTemplate().render(ctx)
        assert "playwright" in result.system_message.lower()

    def test_jest_axe_includes_framework_instructions(self) -> None:
        ctx = _make_context(language="typescript")
        result = JestAxeTemplate().render(ctx)
        assert "jest-axe" in result.system_message.lower()

    def test_base_has_no_extra_framework_instructions(self) -> None:
        ctx = _make_context()
        base_result = AccessibilityTestTemplate().render(ctx)
        pw_result = PlaywrightAxeTemplate().render(ctx)
        assert len(pw_result.system_message) > len(base_result.system_message)

    def test_related_files_included_when_present(self) -> None:
        ctx = _make_context(
            related_files=[
                RelatedFile(
                    path="a11y/helpers.ts",
                    relationship="import",
                    content_snippet="export function setupAxe() {}",
                ),
            ],
        )
        result = AccessibilityTestTemplate().render(ctx)
        assert "Related Files" in result.user_message

    def test_related_files_excluded_when_empty(self) -> None:
        ctx = _make_context(related_files=[])
        result = AccessibilityTestTemplate().render(ctx)
        assert "Related Files" not in result.user_message


# ── ContractTestTemplate ─────────────────────────────────────────


class TestContractTemplates:
    def test_base_name(self) -> None:
        assert ContractTestTemplate().name == "contract_test"

    def test_pytest_pact_name(self) -> None:
        assert PytestPactTemplate().name == "pytest_pact"

    def test_jest_pact_name(self) -> None:
        assert JestPactTemplate().name == "jest_pact"

    def test_vitest_pact_name(self) -> None:
        assert VitestPactTemplate().name == "vitest_pact"

    def test_includes_contract_sections(self) -> None:
        ctx = _make_context()
        result = ContractTestTemplate().render(ctx)
        assert "Contract Testing" in result.user_message
        assert "Pact Testing Patterns" in result.user_message

    def test_output_instructions(self) -> None:
        ctx = _make_context()
        result = ContractTestTemplate().render(ctx)
        assert "Output Instructions" in result.user_message

    def test_pytest_pact_includes_framework_instructions(self) -> None:
        ctx = _make_context()
        result = PytestPactTemplate().render(ctx)
        assert "pact-python" in result.system_message.lower()

    def test_jest_pact_includes_framework_instructions(self) -> None:
        ctx = _make_context(language="typescript")
        result = JestPactTemplate().render(ctx)
        assert "jest" in result.system_message.lower()
        assert "pact" in result.system_message.lower()

    def test_vitest_pact_includes_framework_instructions(self) -> None:
        ctx = _make_context(language="typescript")
        result = VitestPactTemplate().render(ctx)
        assert "vitest" in result.system_message.lower()
        assert "pact" in result.system_message.lower()

    def test_base_has_no_extra_framework_instructions(self) -> None:
        ctx = _make_context()
        base_result = ContractTestTemplate().render(ctx)
        pact_result = PytestPactTemplate().render(ctx)
        assert len(pact_result.system_message) > len(base_result.system_message)

    def test_related_files_included_when_present(self) -> None:
        ctx = _make_context(
            related_files=[
                RelatedFile(
                    path="pacts/consumer-provider.json",
                    relationship="contract",
                    content_snippet='{"consumer": {"name": "web"}}',
                ),
            ],
        )
        result = ContractTestTemplate().render(ctx)
        assert "Related Files" in result.user_message

    def test_related_files_excluded_when_empty(self) -> None:
        ctx = _make_context(related_files=[])
        result = ContractTestTemplate().render(ctx)
        assert "Related Files" not in result.user_message


# ── IntegrationTestTemplate ──────────────────────────────────────


class TestIntegrationTemplates:
    def test_base_name(self) -> None:
        assert IntegrationTestTemplate().name == "integration_test"

    def test_pytest_integration_name(self) -> None:
        assert PytestIntegrationTemplate().name == "pytest_integration"

    def test_vitest_integration_name(self) -> None:
        assert VitestIntegrationTemplate().name == "vitest_integration"

    def test_jest_integration_name(self) -> None:
        assert JestIntegrationTemplate().name == "jest_integration"

    def test_includes_integration_sections(self) -> None:
        ctx = _make_context()
        result = IntegrationTestTemplate().render(ctx)
        assert "Integration Testing" in result.user_message
        assert "Mocking Guidance" in result.user_message

    def test_output_instructions(self) -> None:
        ctx = _make_context()
        result = IntegrationTestTemplate().render(ctx)
        assert "Output Instructions" in result.user_message

    def test_pytest_integration_includes_framework_instructions(self) -> None:
        ctx = _make_context()
        result = PytestIntegrationTemplate().render(ctx)
        assert "pytest" in result.system_message.lower()

    def test_vitest_integration_includes_framework_instructions(self) -> None:
        ctx = _make_context(language="typescript")
        result = VitestIntegrationTemplate().render(ctx)
        assert "vitest" in result.system_message.lower()

    def test_jest_integration_includes_framework_instructions(self) -> None:
        ctx = _make_context(language="typescript")
        result = JestIntegrationTemplate().render(ctx)
        assert "jest" in result.system_message.lower()

    def test_base_has_no_extra_framework_instructions(self) -> None:
        ctx = _make_context()
        base_result = IntegrationTestTemplate().render(ctx)
        pytest_result = PytestIntegrationTemplate().render(ctx)
        assert len(pytest_result.system_message) > len(base_result.system_message)

    def test_related_files_included_when_present(self) -> None:
        ctx = _make_context(
            related_files=[
                RelatedFile(
                    path="tests/conftest.py",
                    relationship="test",
                    content_snippet="@pytest.fixture\ndef db_session(): ...",
                ),
            ],
        )
        result = IntegrationTestTemplate().render(ctx)
        assert "Related Files" in result.user_message

    def test_related_files_excluded_when_empty(self) -> None:
        ctx = _make_context(related_files=[])
        result = IntegrationTestTemplate().render(ctx)
        assert "Related Files" not in result.user_message


# ── Helpers ──────────────────────────────────────────────────────


def _msg(role: str, content: str) -> LLMMessage:
    """Create an LLMMessage for tests."""
    return LLMMessage(role=role, content=content)
