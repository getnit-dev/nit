"""Database migration analyzer -- detects migration frameworks and parses migration files.

This analyzer:
1. Detects which database migration framework a project uses
2. Discovers migration files and parses version/name metadata
3. Checks for rollback support
4. Produces a MigrationAnalysisResult summarizing all discovered migrations
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── Data models ──────────────────────────────────────────────────


@dataclass
class Migration:
    """A single discovered database migration."""

    version: str
    """Version identifier for this migration."""

    name: str
    """Human-readable migration name."""

    file_path: str
    """Path to the migration file."""

    direction: str
    """Direction: 'up', 'down', or 'both'."""

    framework: str = ""
    """Migration framework that owns this migration."""


@dataclass
class MigrationAnalysisResult:
    """Aggregated result of migration analysis."""

    framework: str = ""
    """Detected migration framework name."""

    migrations: list[Migration] = field(default_factory=list)
    """All discovered migration files."""

    pending_count: int = 0
    """Number of pending (unapplied) migrations."""

    has_rollbacks: bool = False
    """Whether the project has rollback/downgrade support."""

    migration_dir: str = ""
    """Primary directory containing migration files."""


# ── Detection ────────────────────────────────────────────────────

_FRAMEWORK_CHECKERS: list[tuple[str, str]] = []


def _check_alembic(project_root: Path) -> str:
    """Check for Alembic migration framework indicators."""
    if (project_root / "alembic.ini").is_file() or (project_root / "alembic").is_dir():
        return "alembic"
    return ""


def _check_flyway(project_root: Path) -> str:
    """Check for Flyway migration framework indicators."""
    if (project_root / "flyway.conf").is_file():
        return "flyway"
    sql_dir = project_root / "sql"
    if sql_dir.is_dir() and list(sql_dir.glob("V*.sql")):
        return "flyway"
    return ""


def _check_prisma(project_root: Path) -> str:
    """Check for Prisma migration framework indicators."""
    if (project_root / "prisma" / "migrations").is_dir():
        return "prisma"
    return ""


def _check_django(project_root: Path) -> str:
    """Check for Django migration framework indicators."""
    for child in project_root.iterdir():
        if not child.is_dir():
            continue
        migrations_dir = child / "migrations"
        if migrations_dir.is_dir() and (migrations_dir / "__init__.py").is_file():
            return "django"
    return ""


def _check_knex(project_root: Path) -> str:
    """Check for Knex migration framework indicators."""
    if (project_root / "knexfile.js").is_file() or (project_root / "knexfile.ts").is_file():
        return "knex"
    return ""


def _check_sequelize(project_root: Path) -> str:
    """Check for Sequelize migration framework indicators."""
    if (project_root / ".sequelizerc").is_file():
        return "sequelize"
    config_json = project_root / "config" / "config.json"
    if config_json.is_file():
        try:
            content = config_json.read_text(encoding="utf-8")
            if "sequelize" in content.lower() or "dialect" in content.lower():
                return "sequelize"
        except OSError as exc:
            logger.debug("Could not read config/config.json: %s", exc)
    return ""


_FRAMEWORK_CHECKS = [
    _check_alembic,
    _check_flyway,
    _check_prisma,
    _check_django,
    _check_knex,
    _check_sequelize,
]


def detect_migration_framework(project_root: Path) -> str:
    """Detect which database migration framework is in use.

    Checks for framework-specific configuration files and directory
    structures in the following order: Alembic, Flyway, Prisma,
    Django, Knex, Sequelize.

    Args:
        project_root: Root directory of the project.

    Returns:
        Framework name string, or empty string if none detected.
    """
    for checker in _FRAMEWORK_CHECKS:
        result = checker(project_root)
        if result:
            logger.info("Detected %s migration framework", result)
            return result
    return ""


# ── Discovery ────────────────────────────────────────────────────


def _discover_alembic(project_root: Path) -> list[Migration]:
    """Discover Alembic migration files in alembic/versions/*.py.

    Args:
        project_root: Root directory of the project.

    Returns:
        List of discovered Migration objects.
    """
    versions_dir = project_root / "alembic" / "versions"
    if not versions_dir.is_dir():
        return []

    migrations: list[Migration] = []
    for py_file in sorted(versions_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        # Alembic files are named like: abc123_description.py
        stem = py_file.stem
        parts = stem.split("_", maxsplit=1)
        version = parts[0]
        name = parts[1] if len(parts) > 1 else stem

        # Check for downgrade function to determine direction
        try:
            content = py_file.read_text(encoding="utf-8")
            has_downgrade = "def downgrade" in content
        except OSError:
            has_downgrade = False

        direction = "both" if has_downgrade else "up"
        migrations.append(
            Migration(
                version=version,
                name=name,
                file_path=str(py_file.relative_to(project_root)),
                direction=direction,
                framework="alembic",
            )
        )

    return migrations


def _discover_flyway(project_root: Path) -> list[Migration]:
    """Discover Flyway migration files (V{version}__{name}.sql).

    Searches both ``sql/`` and ``db/migration/`` directories.

    Args:
        project_root: Root directory of the project.

    Returns:
        List of discovered Migration objects.
    """
    search_dirs = [
        project_root / "sql",
        project_root / "db" / "migration",
    ]
    pattern = re.compile(r"^V(\d+(?:\.\d+)*)__(.+)\.sql$")

    migrations: list[Migration] = []
    for search_dir in search_dirs:
        if not search_dir.is_dir():
            continue
        for sql_file in sorted(search_dir.glob("V*.sql")):
            match = pattern.match(sql_file.name)
            if match:
                version = match.group(1)
                name = match.group(2)
            else:
                version = sql_file.stem.lstrip("V")
                name = sql_file.stem

            migrations.append(
                Migration(
                    version=version,
                    name=name,
                    file_path=str(sql_file.relative_to(project_root)),
                    direction="up",
                    framework="flyway",
                )
            )

    return migrations


def _discover_prisma(project_root: Path) -> list[Migration]:
    """Discover Prisma migration files in prisma/migrations/*/migration.sql.

    Args:
        project_root: Root directory of the project.

    Returns:
        List of discovered Migration objects.
    """
    migrations_dir = project_root / "prisma" / "migrations"
    if not migrations_dir.is_dir():
        return []

    migrations: list[Migration] = []
    for subdir in sorted(migrations_dir.iterdir()):
        if not subdir.is_dir():
            continue
        migration_sql = subdir / "migration.sql"
        if not migration_sql.is_file():
            continue

        # Prisma directories are named like: 20230101120000_description
        dir_name = subdir.name
        parts = dir_name.split("_", maxsplit=1)
        version = parts[0]
        name = parts[1] if len(parts) > 1 else dir_name

        migrations.append(
            Migration(
                version=version,
                name=name,
                file_path=str(migration_sql.relative_to(project_root)),
                direction="up",
                framework="prisma",
            )
        )

    return migrations


def _discover_django(project_root: Path) -> list[Migration]:
    """Discover Django migration files in */migrations/0*.py.

    Args:
        project_root: Root directory of the project.

    Returns:
        List of discovered Migration objects.
    """
    pattern = re.compile(r"^(\d{4})_(.+)\.py$")

    migrations: list[Migration] = []
    for child in sorted(project_root.iterdir()):
        if not child.is_dir():
            continue
        migrations_dir = child / "migrations"
        if not migrations_dir.is_dir():
            continue
        if not (migrations_dir / "__init__.py").is_file():
            continue

        for py_file in sorted(migrations_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            match = pattern.match(py_file.name)
            if match:
                version = match.group(1)
                name = match.group(2)
                migrations.append(
                    Migration(
                        version=version,
                        name=name,
                        file_path=str(py_file.relative_to(project_root)),
                        direction="both",
                        framework="django",
                    )
                )

    return migrations


def _discover_knex(project_root: Path) -> list[Migration]:
    """Discover Knex migration files in migrations/*.js or migrations/*.ts.

    Args:
        project_root: Root directory of the project.

    Returns:
        List of discovered Migration objects.
    """
    migrations_dir = project_root / "migrations"
    if not migrations_dir.is_dir():
        return []

    migrations: list[Migration] = []
    for ext in ("*.js", "*.ts"):
        for migration_file in sorted(migrations_dir.glob(ext)):
            stem = migration_file.stem
            # Knex files are often named like: 20230101120000_create_users
            parts = stem.split("_", maxsplit=1)
            version = parts[0]
            name = parts[1] if len(parts) > 1 else stem

            migrations.append(
                Migration(
                    version=version,
                    name=name,
                    file_path=str(migration_file.relative_to(project_root)),
                    direction="both",
                    framework="knex",
                )
            )

    return migrations


def discover_migrations(project_root: Path, framework: str) -> list[Migration]:
    """Discover migration files for the detected framework.

    Delegates to the appropriate framework-specific discovery function
    based on the framework name.

    Args:
        project_root: Root directory of the project.
        framework: Migration framework name (from detect_migration_framework).

    Returns:
        List of discovered Migration objects.
    """
    discoverers = {
        "alembic": _discover_alembic,
        "flyway": _discover_flyway,
        "prisma": _discover_prisma,
        "django": _discover_django,
        "knex": _discover_knex,
    }

    discoverer = discoverers.get(framework)
    if discoverer is None:
        logger.debug("No migration discoverer for framework: %s", framework)
        return []

    migrations = discoverer(project_root)
    logger.info("Discovered %d migrations for %s", len(migrations), framework)
    return migrations


# ── Analysis ─────────────────────────────────────────────────────


def _check_rollback_support(
    project_root: Path, framework: str, migrations: list[Migration]
) -> bool:
    """Check whether the project has rollback/downgrade support.

    Args:
        project_root: Root directory of the project.
        framework: Detected migration framework.
        migrations: Discovered migrations.

    Returns:
        True if rollback support is detected.
    """
    if framework == "flyway":
        # Flyway: look for U*.sql undo migrations
        for search_dir in (project_root / "sql", project_root / "db" / "migration"):
            if search_dir.is_dir() and list(search_dir.glob("U*.sql")):
                return True
        return False

    if framework == "alembic":
        # Alembic: check if any migration has a downgrade function
        return any(m.direction in ("both", "down") for m in migrations)

    return framework in ("django", "knex")


def _get_migration_dir(project_root: Path, framework: str) -> str:
    """Determine the primary migration directory for the framework.

    Args:
        project_root: Root directory of the project.
        framework: Detected migration framework.

    Returns:
        Relative path to the migration directory, or empty string.
    """
    dirs: dict[str, list[str]] = {
        "alembic": ["alembic/versions"],
        "flyway": ["sql", "db/migration"],
        "prisma": ["prisma/migrations"],
        "django": [],
        "knex": ["migrations"],
    }

    candidates = dirs.get(framework, [])
    for candidate in candidates:
        if (project_root / candidate).is_dir():
            return candidate

    # Django: find the first app with migrations
    if framework == "django":
        for child in sorted(project_root.iterdir()):
            if not child.is_dir():
                continue
            migrations_dir = child / "migrations"
            if migrations_dir.is_dir() and (migrations_dir / "__init__.py").is_file():
                return str(migrations_dir.relative_to(project_root))

    return ""


def analyze_migrations(project_root: Path) -> MigrationAnalysisResult:
    """Analyze database migrations in the project.

    Main entry point: detects the migration framework, discovers all
    migration files, checks rollback support, and produces an aggregated
    analysis result.

    Args:
        project_root: Root directory of the project.

    Returns:
        MigrationAnalysisResult summarizing all discovered migrations.
    """
    framework = detect_migration_framework(project_root)
    if not framework:
        logger.info("No migration framework detected in %s", project_root)
        return MigrationAnalysisResult()

    migrations = discover_migrations(project_root, framework)
    has_rollbacks = _check_rollback_support(project_root, framework, migrations)
    migration_dir = _get_migration_dir(project_root, framework)

    logger.info(
        "Migration analysis: framework=%s, %d migrations, rollbacks=%s, dir=%s",
        framework,
        len(migrations),
        has_rollbacks,
        migration_dir,
    )

    return MigrationAnalysisResult(
        framework=framework,
        migrations=migrations,
        pending_count=0,
        has_rollbacks=has_rollbacks,
        migration_dir=migration_dir,
    )
