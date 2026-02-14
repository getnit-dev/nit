"""Tests for the database migration analyzer and builder.

Covers:
- Detecting migration frameworks (Alembic, Flyway, Prisma, Django, Knex)
- Discovering migration files for each framework
- Parsing version numbers and names from file naming conventions
- Full migration analysis with rollback detection
- Generating test plans from analysis results
- Handling empty projects with no migration framework
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.agents.analyzers.database import (
    Migration,
    MigrationAnalysisResult,
    analyze_migrations,
    detect_migration_framework,
    discover_migrations,
)
from nit.agents.builders.migration import MigrationTestBuilder

# ── detect_migration_framework ───────────────────────────────────


def test_detect_alembic_via_ini(tmp_path: Path) -> None:
    """detect_migration_framework should detect Alembic via alembic.ini."""
    (tmp_path / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    assert detect_migration_framework(tmp_path) == "alembic"


def test_detect_alembic_via_directory(tmp_path: Path) -> None:
    """detect_migration_framework should detect Alembic via alembic/ directory."""
    (tmp_path / "alembic").mkdir()
    assert detect_migration_framework(tmp_path) == "alembic"


def test_detect_flyway_via_conf(tmp_path: Path) -> None:
    """detect_migration_framework should detect Flyway via flyway.conf."""
    (tmp_path / "flyway.conf").write_text("flyway.url=jdbc:h2:mem:test\n", encoding="utf-8")
    assert detect_migration_framework(tmp_path) == "flyway"


def test_detect_flyway_via_sql_files(tmp_path: Path) -> None:
    """detect_migration_framework should detect Flyway via sql/V*.sql files."""
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "V1__init.sql").write_text("CREATE TABLE t (id INT);", encoding="utf-8")
    assert detect_migration_framework(tmp_path) == "flyway"


def test_detect_prisma(tmp_path: Path) -> None:
    """detect_migration_framework should detect Prisma via prisma/migrations/."""
    (tmp_path / "prisma" / "migrations").mkdir(parents=True)
    assert detect_migration_framework(tmp_path) == "prisma"


def test_detect_django(tmp_path: Path) -> None:
    """detect_migration_framework should detect Django via app/migrations/ with __init__.py."""
    app_dir = tmp_path / "myapp" / "migrations"
    app_dir.mkdir(parents=True)
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    assert detect_migration_framework(tmp_path) == "django"


def test_detect_knex_js(tmp_path: Path) -> None:
    """detect_migration_framework should detect Knex via knexfile.js."""
    (tmp_path / "knexfile.js").write_text("module.exports = {};", encoding="utf-8")
    assert detect_migration_framework(tmp_path) == "knex"


def test_detect_returns_empty_for_no_framework(tmp_path: Path) -> None:
    """detect_migration_framework should return empty string for no framework."""
    assert detect_migration_framework(tmp_path) == ""


# ── discover_migrations ──────────────────────────────────────────


@pytest.fixture()
def alembic_project(tmp_path: Path) -> Path:
    """Create a project with Alembic migrations."""
    (tmp_path / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    versions_dir = tmp_path / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    (versions_dir / "abc123_create_users.py").write_text(
        "def upgrade():\n    pass\n\ndef downgrade():\n    pass\n",
        encoding="utf-8",
    )
    (versions_dir / "def456_add_email.py").write_text(
        "def upgrade():\n    pass\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def flyway_project(tmp_path: Path) -> Path:
    """Create a project with Flyway migrations."""
    (tmp_path / "flyway.conf").write_text("flyway.url=jdbc:h2:mem:test\n", encoding="utf-8")
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "V1__create_users.sql").write_text("CREATE TABLE users (id INT);", encoding="utf-8")
    (sql_dir / "V2__add_email.sql").write_text(
        "ALTER TABLE users ADD email VARCHAR(255);", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def prisma_project(tmp_path: Path) -> Path:
    """Create a project with Prisma migrations."""
    m1 = tmp_path / "prisma" / "migrations" / "20230101120000_init"
    m1.mkdir(parents=True)
    (m1 / "migration.sql").write_text("CREATE TABLE users (id INT);", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def django_project(tmp_path: Path) -> Path:
    """Create a project with Django migrations."""
    migrations_dir = tmp_path / "myapp" / "migrations"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "__init__.py").write_text("", encoding="utf-8")
    (migrations_dir / "0001_initial.py").write_text(
        "class Migration:\n    pass\n", encoding="utf-8"
    )
    (migrations_dir / "0002_add_email.py").write_text(
        "class Migration:\n    pass\n", encoding="utf-8"
    )
    return tmp_path


def test_discover_alembic_migrations(alembic_project: Path) -> None:
    """discover_migrations should find Alembic migration files."""
    migrations = discover_migrations(alembic_project, "alembic")
    assert len(migrations) == 2
    versions = {m.version for m in migrations}
    assert "abc123" in versions
    assert "def456" in versions


def test_discover_alembic_detects_direction(alembic_project: Path) -> None:
    """discover_migrations should detect direction from downgrade function."""
    migrations = discover_migrations(alembic_project, "alembic")
    by_version = {m.version: m for m in migrations}
    # abc123 has downgrade function
    assert by_version["abc123"].direction == "both"
    # def456 has no downgrade function
    assert by_version["def456"].direction == "up"


def test_discover_flyway_migrations(flyway_project: Path) -> None:
    """discover_migrations should find Flyway V*.sql migration files."""
    migrations = discover_migrations(flyway_project, "flyway")
    assert len(migrations) == 2
    assert migrations[0].version == "1"
    assert migrations[0].name == "create_users"
    assert migrations[1].version == "2"
    assert migrations[1].name == "add_email"


def test_discover_prisma_migrations(prisma_project: Path) -> None:
    """discover_migrations should find Prisma migration directories."""
    migrations = discover_migrations(prisma_project, "prisma")
    assert len(migrations) == 1
    assert migrations[0].version == "20230101120000"
    assert migrations[0].name == "init"


def test_discover_django_migrations(django_project: Path) -> None:
    """discover_migrations should find Django migration files."""
    migrations = discover_migrations(django_project, "django")
    assert len(migrations) == 2
    versions = {m.version for m in migrations}
    assert "0001" in versions
    assert "0002" in versions


def test_discover_returns_empty_for_no_migrations(tmp_path: Path) -> None:
    """discover_migrations should return empty list when no migrations found."""
    migrations = discover_migrations(tmp_path, "alembic")
    assert migrations == []


# ── analyze_migrations ───────────────────────────────────────────


def test_analyze_alembic_project(alembic_project: Path) -> None:
    """analyze_migrations should produce full analysis for Alembic project."""
    result = analyze_migrations(alembic_project)
    assert result.framework == "alembic"
    assert len(result.migrations) == 2
    assert result.has_rollbacks is True
    assert result.migration_dir == "alembic/versions"


def test_analyze_flyway_project(flyway_project: Path) -> None:
    """analyze_migrations should produce full analysis for Flyway project."""
    result = analyze_migrations(flyway_project)
    assert result.framework == "flyway"
    assert len(result.migrations) == 2
    assert result.migration_dir == "sql"


def test_analyze_detects_rollback_capability(tmp_path: Path) -> None:
    """analyze_migrations should detect rollback capability from undo files."""
    (tmp_path / "flyway.conf").write_text("flyway.url=jdbc:h2:mem:test\n", encoding="utf-8")
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "V1__create_users.sql").write_text("CREATE TABLE users;", encoding="utf-8")
    (sql_dir / "U1__undo_create_users.sql").write_text("DROP TABLE users;", encoding="utf-8")

    result = analyze_migrations(tmp_path)
    assert result.has_rollbacks is True


def test_analyze_empty_project(tmp_path: Path) -> None:
    """analyze_migrations should return empty result for no framework."""
    result = analyze_migrations(tmp_path)
    assert result.framework == ""
    assert result.migrations == []
    assert result.has_rollbacks is False
    assert result.pending_count == 0


# ── MigrationTestBuilder ────────────────────────────────────────


def test_builder_generates_up_migration_tests() -> None:
    """MigrationTestBuilder should generate up_migration test cases."""
    analysis = MigrationAnalysisResult(
        framework="alembic",
        migrations=[
            Migration(
                version="abc123",
                name="create_users",
                file_path="alembic/versions/abc123_create_users.py",
                direction="up",
                framework="alembic",
            )
        ],
        has_rollbacks=False,
    )

    builder = MigrationTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    up_cases = [tc for tc in test_cases if tc.test_type == "up_migration"]
    assert len(up_cases) == 1
    assert up_cases[0].migration_version == "abc123"
    assert "test_up_migration_" in up_cases[0].test_name


def test_builder_generates_rollback_tests_when_supported() -> None:
    """MigrationTestBuilder should generate rollback tests when has_rollbacks is True."""
    analysis = MigrationAnalysisResult(
        framework="alembic",
        migrations=[
            Migration(
                version="abc123",
                name="create_users",
                file_path="alembic/versions/abc123_create_users.py",
                direction="both",
                framework="alembic",
            )
        ],
        has_rollbacks=True,
    )

    builder = MigrationTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    rollback_cases = [tc for tc in test_cases if tc.test_type == "rollback"]
    assert len(rollback_cases) == 1
    assert rollback_cases[0].migration_version == "abc123"
    assert "test_rollback_" in rollback_cases[0].test_name


def test_builder_skips_rollback_tests_when_not_supported() -> None:
    """MigrationTestBuilder should skip rollback tests when has_rollbacks is False."""
    analysis = MigrationAnalysisResult(
        framework="flyway",
        migrations=[
            Migration(
                version="1",
                name="create_users",
                file_path="sql/V1__create_users.sql",
                direction="up",
                framework="flyway",
            )
        ],
        has_rollbacks=False,
    )

    builder = MigrationTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    rollback_cases = [tc for tc in test_cases if tc.test_type == "rollback"]
    assert len(rollback_cases) == 0


def test_builder_generates_idempotency_tests() -> None:
    """MigrationTestBuilder should generate idempotency test cases."""
    analysis = MigrationAnalysisResult(
        framework="flyway",
        migrations=[
            Migration(
                version="1",
                name="create_users",
                file_path="sql/V1__create_users.sql",
                direction="up",
                framework="flyway",
            )
        ],
        has_rollbacks=False,
    )

    builder = MigrationTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    idempotency_cases = [tc for tc in test_cases if tc.test_type == "idempotency"]
    assert len(idempotency_cases) == 1
    assert "idempotent" in idempotency_cases[0].description


def test_builder_handles_empty_analysis() -> None:
    """MigrationTestBuilder should return empty list for empty analysis."""
    analysis = MigrationAnalysisResult()
    builder = MigrationTestBuilder()
    test_cases = builder.generate_test_plan(analysis)
    assert test_cases == []


def test_builder_test_name_slugification() -> None:
    """MigrationTestBuilder should produce valid test names from migration names."""
    analysis = MigrationAnalysisResult(
        framework="alembic",
        migrations=[
            Migration(
                version="abc123",
                name="add user's email (special chars!)",
                file_path="alembic/versions/abc123_add_users_email.py",
                direction="up",
                framework="alembic",
            )
        ],
        has_rollbacks=False,
    )

    builder = MigrationTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    for tc in test_cases:
        # Test names should only contain valid identifier characters
        assert tc.test_name.replace("_", "").isalnum()
