"""GraphQL schema analyzer — discovers and parses GraphQL schemas.

This analyzer:
1. Detects GraphQL schema files in the project (*.graphql, *.gql)
2. Parses schema definitions using regex-based SDL parsing (no external deps)
3. Extracts Query, Mutation, and Subscription operations
4. Extracts custom type definitions (Object, Input, Enum, Interface, Union)
5. Checks package.json for graphql dependency presence
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── Data models ──────────────────────────────────────────────────


@dataclass
class GraphQLField:
    """Represents a single field within a GraphQL type or operation."""

    name: str
    """Name of the field."""

    type_name: str
    """Type of the field (e.g., 'String', 'Int!', '[User!]!')."""

    args: list[str] = field(default_factory=list)
    """Argument names for this field, if any."""


@dataclass
class GraphQLOperation:
    """Represents a single query, mutation, or subscription operation."""

    operation_type: str
    """One of 'query', 'mutation', or 'subscription'."""

    name: str
    """Name of the operation field."""

    fields: list[GraphQLField] = field(default_factory=list)
    """Nested fields within this operation, if parsed."""

    description: str = ""
    """Optional description extracted from comments."""


@dataclass
class GraphQLTypeInfo:
    """Represents a custom type definition in the schema."""

    name: str
    """Name of the type (e.g., 'User', 'CreateUserInput')."""

    kind: str
    """Kind of type: 'type', 'input', 'enum', 'interface', 'union', 'scalar'."""

    fields: list[GraphQLField] = field(default_factory=list)
    """Fields belonging to this type (empty for enums/scalars/unions)."""


@dataclass
class GraphQLSchemaAnalysis:
    """Complete analysis of a GraphQL schema file."""

    queries: list[GraphQLOperation] = field(default_factory=list)
    """All query operations found in the schema."""

    mutations: list[GraphQLOperation] = field(default_factory=list)
    """All mutation operations found in the schema."""

    subscriptions: list[GraphQLOperation] = field(default_factory=list)
    """All subscription operations found in the schema."""

    types: list[GraphQLTypeInfo] = field(default_factory=list)
    """All custom type definitions found in the schema."""

    @property
    def total_operations(self) -> int:
        """Return total number of operations (queries + mutations + subscriptions)."""
        return len(self.queries) + len(self.mutations) + len(self.subscriptions)


# ── Regex patterns for SDL parsing ───────────────────────────────

# Matches top-level type blocks: type Foo { ... }
_TYPE_BLOCK_RE = re.compile(
    r"""
    (?:^|\n)                       # start of string or newline
    \s*                            # optional leading whitespace
    (type|input|interface|enum)    # keyword
    \s+                            # whitespace
    (\w+)                          # type name
    (?:\s+implements\s+[\w\s&,]+)? # optional implements clause
    \s*\{                          # opening brace
    ([^}]*)                        # body (everything up to closing brace)
    \}                             # closing brace
    """,
    re.VERBOSE,
)

# Matches a field line: fieldName(arg1: Type, arg2: Type): ReturnType
_FIELD_RE = re.compile(
    r"""
    ^\s*                        # leading whitespace
    (?:"[^"]*"\s*)?             # optional description string
    (\w+)                       # field name
    (?:\(([^)]*)\))?            # optional arguments in parens
    \s*:\s*                     # colon separator
    (.+?)                       # return type (non-greedy)
    \s*$                        # end of line
    """,
    re.VERBOSE | re.MULTILINE,
)

# Matches union definitions: union SearchResult = User | Post
_UNION_RE = re.compile(
    r"(?:^|\n)\s*union\s+(\w+)\s*=\s*([^\n]+)",
)

# Matches scalar definitions: scalar DateTime
_SCALAR_RE = re.compile(
    r"(?:^|\n)\s*scalar\s+(\w+)",
)

# Matches argument entries: argName: ArgType
_ARG_RE = re.compile(r"(\w+)\s*:")

# Root operation type names
_ROOT_TYPES = {"Query", "Mutation", "Subscription"}


# ── Parsing functions ────────────────────────────────────────────


def _parse_fields(body: str) -> list[GraphQLField]:
    """Parse field definitions from a type body.

    Args:
        body: The text between braces of a type definition.

    Returns:
        List of parsed GraphQLField instances.
    """
    fields: list[GraphQLField] = []
    for match in _FIELD_RE.finditer(body):
        name = match.group(1)
        raw_args = match.group(2) or ""
        type_name = match.group(3).strip()

        args = [m.group(1) for m in _ARG_RE.finditer(raw_args)]

        fields.append(GraphQLField(name=name, type_name=type_name, args=args))
    return fields


def _classify_operation(type_name: str, fields: list[GraphQLField]) -> list[GraphQLOperation]:
    """Convert root type fields into GraphQLOperation instances.

    Args:
        type_name: The root type name (Query, Mutation, Subscription).
        fields: Parsed fields from the root type body.

    Returns:
        List of GraphQLOperation instances.
    """
    op_type_map = {
        "Query": "query",
        "Mutation": "mutation",
        "Subscription": "subscription",
    }
    op_type = op_type_map[type_name]

    return [
        GraphQLOperation(
            operation_type=op_type,
            name=f.name,
            fields=[],
            description="",
        )
        for f in fields
    ]


def analyze_graphql_schema(schema_path: Path) -> GraphQLSchemaAnalysis:
    """Analyze a GraphQL schema file and extract operations and types.

    Reads the file at *schema_path* and uses regex-based parsing to
    extract Query, Mutation, Subscription operations as well as custom
    type definitions (type, input, interface, enum, union, scalar).

    Args:
        schema_path: Path to a ``.graphql`` or ``.gql`` file.

    Returns:
        A populated ``GraphQLSchemaAnalysis`` instance.
    """
    analysis = GraphQLSchemaAnalysis()

    try:
        content = schema_path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, PermissionError) as exc:
        logger.warning("Could not read schema file %s: %s", schema_path, exc)
        return analysis

    # Strip single-line comments (but not descriptions in quotes)
    stripped = re.sub(r"#[^\n]*", "", content)

    # Parse type/input/interface/enum blocks
    for match in _TYPE_BLOCK_RE.finditer(stripped):
        keyword = match.group(1)
        type_name = match.group(2)
        body = match.group(3)

        fields = _parse_fields(body)

        if type_name in _ROOT_TYPES:
            operations = _classify_operation(type_name, fields)
            if type_name == "Query":
                analysis.queries.extend(operations)
            elif type_name == "Mutation":
                analysis.mutations.extend(operations)
            elif type_name == "Subscription":
                analysis.subscriptions.extend(operations)
        else:
            kind = keyword  # 'type', 'input', 'interface', 'enum'
            analysis.types.append(GraphQLTypeInfo(name=type_name, kind=kind, fields=fields))

    # Parse union definitions
    for match in _UNION_RE.finditer(stripped):
        union_name = match.group(1)
        analysis.types.append(GraphQLTypeInfo(name=union_name, kind="union", fields=[]))

    # Parse scalar definitions
    for match in _SCALAR_RE.finditer(stripped):
        scalar_name = match.group(1)
        analysis.types.append(GraphQLTypeInfo(name=scalar_name, kind="scalar", fields=[]))

    logger.info(
        "Parsed schema %s: %d queries, %d mutations, %d subscriptions, %d types",
        schema_path.name,
        len(analysis.queries),
        len(analysis.mutations),
        len(analysis.subscriptions),
        len(analysis.types),
    )

    return analysis


# ── Detection ────────────────────────────────────────────────────

# Directories commonly containing GraphQL schemas
_SEARCH_DIRS = (".", "src", "graphql", "api", "schema", "app")

# Well-known schema file names
_SCHEMA_NAMES = {"schema.graphql", "schema.gql"}


def _has_graphql_dependency(project_root: Path) -> bool:
    """Check package.json for a graphql dependency.

    Args:
        project_root: Project root directory.

    Returns:
        True if ``graphql`` appears in dependencies or devDependencies.
    """
    package_json = project_root / "package.json"
    if not package_json.exists():
        return False

    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
        deps = {
            **data.get("dependencies", {}),
            **data.get("devDependencies", {}),
        }
        return "graphql" in deps
    except (json.JSONDecodeError, UnicodeDecodeError, PermissionError):
        return False


def detect_graphql_schemas(project_root: Path) -> list[Path]:
    """Find GraphQL schema files in a project.

    Searches for ``*.graphql`` and ``*.gql`` files in the project root
    and common subdirectories (``src/``, ``graphql/``, ``api/``,
    ``schema/``, ``app/``).  Also checks ``package.json`` for a
    ``graphql`` dependency as a signal that schemas may exist.

    Args:
        project_root: Root directory of the project to scan.

    Returns:
        Sorted list of unique paths to discovered schema files.
    """
    found = _scan_search_dirs(project_root)

    # If we found nothing but package.json has graphql, do a deeper search
    if not found and _has_graphql_dependency(project_root):
        logger.debug("graphql dependency found in package.json, doing deeper search")
        found = _deep_search(project_root)

    result = sorted(found)
    logger.info("Detected %d GraphQL schema file(s) in %s", len(result), project_root)
    return result


def _scan_search_dirs(project_root: Path) -> set[Path]:
    """Scan common directories for GraphQL schema files.

    Args:
        project_root: Root directory of the project.

    Returns:
        Set of resolved paths to discovered schema files.
    """
    found: set[Path] = set()

    for search_dir_name in _SEARCH_DIRS:
        search_dir = project_root if search_dir_name == "." else project_root / search_dir_name

        if not search_dir.is_dir():
            continue

        # Look for well-known schema file names directly in this dir
        for name in _SCHEMA_NAMES:
            candidate = search_dir / name
            if candidate.is_file():
                found.add(candidate.resolve())

        # Glob for all .graphql and .gql files (non-recursive in each dir)
        for pattern in ("*.graphql", "*.gql"):
            for path in search_dir.glob(pattern):
                if path.is_file():
                    found.add(path.resolve())

    return found


def _deep_search(project_root: Path) -> set[Path]:
    """Recursively search entire project tree for GraphQL schema files.

    Args:
        project_root: Root directory of the project.

    Returns:
        Set of resolved paths to discovered schema files.
    """
    found: set[Path] = set()
    for pattern in ("**/*.graphql", "**/*.gql"):
        for path in project_root.glob(pattern):
            if path.is_file() and "node_modules" not in path.parts:
                found.add(path.resolve())
    return found
