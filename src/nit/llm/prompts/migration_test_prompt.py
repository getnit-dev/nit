"""Database migration test generation prompt template.

Produces a structured prompt for generating tests that verify database
migrations apply correctly, can be rolled back, and produce the expected
schema changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import (
    PromptSection,
    PromptTemplate,
    format_dependencies_section,
    format_related_files_section,
    format_signatures_section,
    format_source_section,
    format_test_patterns_section,
)

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext


_SYSTEM_INSTRUCTION = """\
You are an expert software engineer specializing in database migration \
testing.  Your task is to generate comprehensive tests that verify \
database migrations apply correctly, can be rolled back, and produce \
the expected schema changes.

Follow these guidelines:
- Write tests that verify each migration applies without errors.
- Write rollback tests that confirm migrations can be safely reversed.
- Write idempotency tests to ensure applying a migration twice does not \
  cause errors.
- Write schema validation tests that check tables, columns, indexes, \
  and constraints after migration.
- Test both success and error scenarios for each migration step.
- Use descriptive test names that reference the migration version and name.
- Set up test databases or use transaction rollback for isolation.
- Match the existing project test conventions when available.
- Output valid, runnable code with no placeholders or TODOs.\
"""


class MigrationTestTemplate(PromptTemplate):
    """Language-agnostic database migration test generation template.

    Renders a prompt with structured sections for source code, migration
    testing patterns, schema validation, and output format.  Subclasses
    can override ``_framework_instructions`` to inject framework-specific
    guidance.
    """

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "migration_test"

    def _system_instruction(self, context: AssembledContext) -> str:
        """Return the system-level instruction text."""
        extra = self._framework_instructions(context)
        if extra:
            return f"{_SYSTEM_INSTRUCTION}\n\n{extra}"
        return _SYSTEM_INSTRUCTION

    def _build_sections(self, context: AssembledContext) -> list[PromptSection]:
        """Return ordered sections that form the user message body."""
        sections = [
            format_source_section(context),
            format_signatures_section(context),
            self._migration_testing_section(context),
            self._schema_validation_section(context),
            format_test_patterns_section(context),
            format_dependencies_section(context),
        ]
        related = format_related_files_section(context)
        if related.content != "None.":
            sections.append(related)

        extra = self._extra_sections(context)
        sections.extend(extra)

        sections.append(self._output_instructions(context))
        return sections

    # ── Migration-specific sections ──────────────────────────────

    def _migration_testing_section(self, _context: AssembledContext) -> PromptSection:
        """Build section describing migration testing focus."""
        return PromptSection(
            label="Migration Testing",
            content=(
                "Generate tests that verify database migrations. "
                "Each test should set up a test database, apply the migration, "
                "verify the schema changes, and clean up after itself."
            ),
        )

    def _schema_validation_section(self, _context: AssembledContext) -> PromptSection:
        """Build section with schema validation testing patterns."""
        return PromptSection(
            label="Schema Validation Patterns",
            content=(
                "Use these schema validation patterns:\n"
                "- Verify tables exist after migration\n"
                "- Verify columns have correct types and constraints\n"
                "- Verify indexes are created properly\n"
                "- Verify foreign key relationships\n"
                "- Verify default values and nullable settings\n"
                "- Test rollback restores the previous schema"
            ),
        )

    # ── Extension points for framework subclasses ────────────────

    def _framework_instructions(self, _context: AssembledContext) -> str:
        """Return additional system-level instructions for a specific framework.

        Override in subclasses to add framework-specific guidance.
        The default implementation returns an empty string.
        """
        return ""

    def _extra_sections(self, _context: AssembledContext) -> list[PromptSection]:
        """Return additional user-message sections for a specific framework.

        Override in subclasses to add framework-specific examples or rules.
        The default implementation returns an empty list.
        """
        return []

    def _output_instructions(self, context: AssembledContext) -> PromptSection:
        """Return instructions describing the expected output format."""
        return PromptSection(
            label="Output Instructions",
            content=(
                "Generate a complete migration test file for the source code above.\n"
                f"Write the tests in {context.language}.\n"
                "Include all necessary imports, database setup, and assertions.\n"
                "Return ONLY the test code -- no explanations, no markdown fences."
            ),
        )


# ── Framework-specific migration test templates ──────────────────


class AlembicMigrationTemplate(MigrationTestTemplate):
    """Alembic migration test template."""

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "alembic_migration"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use pytest with Alembic testing conventions:
- Use function-based tests (`def test_...`).
- Use pytest fixtures for database setup (`@pytest.fixture`).
- Use `alembic.command.upgrade` and `alembic.command.downgrade` to apply migrations.
- Verify schema changes using SQLAlchemy `inspect` or raw SQL queries.
- Use `alembic.config.Config` to configure the migration environment.
- Test both upgrade and downgrade paths for each revision.
- Use `assert` statements for schema assertions."""


class DjangoMigrationTemplate(MigrationTestTemplate):
    """Django migration test template."""

    @property
    def name(self) -> str:
        """Human-readable template identifier."""
        return "django_migration"

    def _framework_instructions(self, _context: AssembledContext) -> str:
        return """\
Use Django's test framework for migration testing:
- Use `django.test.TestCase` or `TransactionTestCase` as the base class.
- Use `django.core.management.call_command('migrate', ...)` to apply migrations.
- Use `MigrationExecutor` from `django.db.migrations.executor` for targeted migrations.
- Verify schema using `connection.introspection.get_table_list()`.
- Test forward and backward migration paths.
- Use `@override_settings(MIGRATION_MODULES=...)` for isolated testing.
- Verify data migrations transform data correctly."""
