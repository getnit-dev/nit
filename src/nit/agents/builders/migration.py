"""MigrationTestBuilder -- generates test plans for database migration testing.

This builder:
1. Receives a MigrationAnalysisResult from the database analyzer
2. Generates test cases for each migration (up, rollback, idempotency, schema)
3. Produces MigrationTestCase entries ready for code generation
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nit.agents.analyzers.database import MigrationAnalysisResult
    from nit.llm.prompts.base import PromptTemplate

logger = logging.getLogger(__name__)


@dataclass
class MigrationTestCase:
    """A single migration test case to be generated."""

    migration_version: str
    """Version of the migration under test."""

    migration_name: str
    """Human-readable name of the migration."""

    test_name: str
    """Generated test function/method name."""

    test_type: str
    """Type of test: 'up_migration', 'rollback', 'idempotency', or 'schema_validation'."""

    description: str
    """Human-readable description of what this test verifies."""

    framework: str = ""
    """Migration framework used by the project."""


def _slugify(text: str) -> str:
    """Convert an arbitrary string into a valid test-name slug.

    Args:
        text: Arbitrary description string.

    Returns:
        Lowercased, underscore-separated slug suitable for a test name.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug or "unnamed"


class MigrationTestBuilder:
    """Generates test plans from migration analysis results.

    For each migration, the builder creates test cases covering:
    - Up migration (apply)
    - Rollback (if supported)
    - Idempotency (applying twice)
    - Schema validation (post-migration schema check)
    """

    def get_prompt_template(self, framework: str = "alembic") -> PromptTemplate:
        """Return the prompt template for migration test generation.

        Args:
            framework: The migration framework (``"alembic"`` or ``"django"``).

        Returns:
            A framework-specific migration test prompt template.
        """
        from nit.llm.prompts.migration_test_prompt import (
            AlembicMigrationTemplate,
            DjangoMigrationTemplate,
        )

        if framework == "django":
            return DjangoMigrationTemplate()
        return AlembicMigrationTemplate()

    def generate_test_plan(self, analysis: MigrationAnalysisResult) -> list[MigrationTestCase]:
        """Generate a list of migration test cases from the analysis result.

        For each migration, up to four test cases are produced:
        1. ``up_migration`` -- verifies the migration applies successfully
        2. ``rollback`` -- verifies rollback works (only if has_rollbacks)
        3. ``idempotency`` -- verifies running migration twice doesn't error
        4. ``schema_validation`` -- verifies expected schema after migration

        Args:
            analysis: The result from :func:`analyze_migrations`.

        Returns:
            List of MigrationTestCase entries ready for code generation.
        """
        test_cases: list[MigrationTestCase] = []

        for migration in analysis.migrations:
            slug = _slugify(migration.name)

            # Up migration test
            test_cases.append(
                MigrationTestCase(
                    migration_version=migration.version,
                    migration_name=migration.name,
                    test_name=f"test_up_migration_{slug}",
                    test_type="up_migration",
                    description=(
                        f"Verify migration {migration.version} ({migration.name}) "
                        f"applies successfully"
                    ),
                    framework=analysis.framework,
                )
            )

            # Rollback test (only if rollbacks are supported)
            if analysis.has_rollbacks:
                test_cases.append(
                    MigrationTestCase(
                        migration_version=migration.version,
                        migration_name=migration.name,
                        test_name=f"test_rollback_{slug}",
                        test_type="rollback",
                        description=(
                            f"Verify migration {migration.version} ({migration.name}) "
                            f"can be rolled back"
                        ),
                        framework=analysis.framework,
                    )
                )

            # Idempotency test
            test_cases.append(
                MigrationTestCase(
                    migration_version=migration.version,
                    migration_name=migration.name,
                    test_name=f"test_idempotency_{slug}",
                    test_type="idempotency",
                    description=(
                        f"Verify migration {migration.version} ({migration.name}) "
                        f"is idempotent when applied twice"
                    ),
                    framework=analysis.framework,
                )
            )

            # Schema validation test
            test_cases.append(
                MigrationTestCase(
                    migration_version=migration.version,
                    migration_name=migration.name,
                    test_name=f"test_schema_validation_{slug}",
                    test_type="schema_validation",
                    description=(
                        f"Verify expected schema after migration "
                        f"{migration.version} ({migration.name})"
                    ),
                    framework=analysis.framework,
                )
            )

        logger.info(
            "Generated %d migration test cases from %d migrations",
            len(test_cases),
            len(analysis.migrations),
        )

        return test_cases
