"""Tests for the GraphQL analyzer and test builder.

Covers:
- Detecting GraphQL schema files in a project
- Parsing Query operations from SDL
- Parsing Mutation operations
- Parsing Subscription operations
- Extracting custom types (type, input, enum, interface, union, scalar)
- GraphQLTestBuilder.generate_test_plan
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nit.agents.analyzers.graphql import (
    GraphQLOperation,
    GraphQLSchemaAnalysis,
    analyze_graphql_schema,
    detect_graphql_schemas,
)
from nit.agents.builders.graphql import GraphQLTestBuilder

# ── Sample schemas ───────────────────────────────────────────────

_MINIMAL_SCHEMA = """\
type Query {
  hello: String
}
"""

_FULL_SCHEMA = """\
# A full-featured schema for testing

scalar DateTime

type User {
  id: ID!
  name: String!
  email: String!
  createdAt: DateTime
  posts: [Post!]!
}

input CreateUserInput {
  name: String!
  email: String!
}

input UpdateUserInput {
  name: String
  email: String
}

enum Role {
  ADMIN
  USER
  GUEST
}

interface Node {
  id: ID!
}

union SearchResult = User | Post

type Post {
  id: ID!
  title: String!
  body: String!
  author: User!
}

type Query {
  user(id: ID!): User
  users(limit: Int, offset: Int): [User!]!
  post(id: ID!): Post
  search(term: String!): [SearchResult!]!
}

type Mutation {
  createUser(input: CreateUserInput!): User!
  updateUser(id: ID!, input: UpdateUserInput!): User
  deleteUser(id: ID!): Boolean!
  createPost(title: String!, body: String!, authorId: ID!): Post!
}

type Subscription {
  userCreated: User!
  postPublished(authorId: ID): Post!
}
"""

_SCHEMA_WITH_COMMENTS = """\
# This schema uses inline comments
type Query {
  # Returns a greeting
  greeting(name: String!): String!
  # Returns the current time
  currentTime: DateTime
}

# Custom scalar
scalar DateTime
"""


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def project_with_schema(tmp_path: Path) -> Path:
    """Create a project directory with GraphQL schema files."""
    # Root schema
    (tmp_path / "schema.graphql").write_text(_FULL_SCHEMA)

    # Nested schema in src/
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "extra.gql").write_text(_MINIMAL_SCHEMA)

    return tmp_path


@pytest.fixture
def project_with_package_json(tmp_path: Path) -> Path:
    """Create a project with graphql in package.json but no root schemas."""
    nested = tmp_path / "lib" / "graphql"
    nested.mkdir(parents=True)
    (nested / "api.graphql").write_text(_MINIMAL_SCHEMA)

    package = {"dependencies": {"graphql": "^16.0.0", "express": "^4.18.0"}}
    (tmp_path / "package.json").write_text(json.dumps(package))

    return tmp_path


@pytest.fixture
def empty_project(tmp_path: Path) -> Path:
    """Create an empty project directory with no schema files."""
    (tmp_path / "src").mkdir()
    return tmp_path


# ── Detection tests ──────────────────────────────────────────────


def test_detect_schemas_finds_root_and_src(project_with_schema: Path) -> None:
    """detect_graphql_schemas should find schema files in root and src/."""
    schemas = detect_graphql_schemas(project_with_schema)

    assert len(schemas) == 2
    names = {p.name for p in schemas}
    assert "schema.graphql" in names
    assert "extra.gql" in names


def test_detect_schemas_empty_project(empty_project: Path) -> None:
    """detect_graphql_schemas returns empty list when no schemas exist."""
    schemas = detect_graphql_schemas(empty_project)
    assert schemas == []


def test_detect_schemas_via_package_json(project_with_package_json: Path) -> None:
    """detect_graphql_schemas does a deep search when package.json has graphql."""
    schemas = detect_graphql_schemas(project_with_package_json)

    assert len(schemas) == 1
    assert schemas[0].name == "api.graphql"


def test_detect_schemas_graphql_dir(tmp_path: Path) -> None:
    """detect_graphql_schemas finds schemas in a graphql/ directory."""
    gql_dir = tmp_path / "graphql"
    gql_dir.mkdir()
    (gql_dir / "types.graphql").write_text(_MINIMAL_SCHEMA)

    schemas = detect_graphql_schemas(tmp_path)

    assert len(schemas) == 1
    assert schemas[0].name == "types.graphql"


# ── Schema analysis: Query ───────────────────────────────────────


def test_analyze_minimal_schema(tmp_path: Path) -> None:
    """analyze_graphql_schema parses a minimal Query type."""
    schema_file = tmp_path / "schema.graphql"
    schema_file.write_text(_MINIMAL_SCHEMA)

    analysis = analyze_graphql_schema(schema_file)

    assert len(analysis.queries) == 1
    assert analysis.queries[0].name == "hello"
    assert analysis.queries[0].operation_type == "query"
    assert analysis.mutations == []
    assert analysis.subscriptions == []
    assert analysis.total_operations == 1


def test_analyze_full_schema_queries(tmp_path: Path) -> None:
    """analyze_graphql_schema extracts all queries from the full schema."""
    schema_file = tmp_path / "schema.graphql"
    schema_file.write_text(_FULL_SCHEMA)

    analysis = analyze_graphql_schema(schema_file)

    query_names = {q.name for q in analysis.queries}
    assert query_names == {"user", "users", "post", "search"}
    assert all(q.operation_type == "query" for q in analysis.queries)


# ── Schema analysis: Mutation ────────────────────────────────────


def test_analyze_mutations(tmp_path: Path) -> None:
    """analyze_graphql_schema extracts mutation operations."""
    schema_file = tmp_path / "schema.graphql"
    schema_file.write_text(_FULL_SCHEMA)

    analysis = analyze_graphql_schema(schema_file)

    mutation_names = {m.name for m in analysis.mutations}
    assert mutation_names == {"createUser", "updateUser", "deleteUser", "createPost"}
    assert all(m.operation_type == "mutation" for m in analysis.mutations)


# ── Schema analysis: Subscription ────────────────────────────────


def test_analyze_subscriptions(tmp_path: Path) -> None:
    """analyze_graphql_schema extracts subscription operations."""
    schema_file = tmp_path / "schema.graphql"
    schema_file.write_text(_FULL_SCHEMA)

    analysis = analyze_graphql_schema(schema_file)

    sub_names = {s.name for s in analysis.subscriptions}
    assert sub_names == {"userCreated", "postPublished"}
    assert all(s.operation_type == "subscription" for s in analysis.subscriptions)


# ── Schema analysis: custom types ────────────────────────────────


def test_analyze_custom_types(tmp_path: Path) -> None:
    """analyze_graphql_schema extracts custom type definitions."""
    schema_file = tmp_path / "schema.graphql"
    schema_file.write_text(_FULL_SCHEMA)

    analysis = analyze_graphql_schema(schema_file)

    type_names = {t.name for t in analysis.types}
    assert "User" in type_names
    assert "Post" in type_names
    assert "CreateUserInput" in type_names
    assert "UpdateUserInput" in type_names
    assert "Role" in type_names
    assert "Node" in type_names
    assert "SearchResult" in type_names
    assert "DateTime" in type_names


def test_type_kinds(tmp_path: Path) -> None:
    """Custom types should have the correct kind value."""
    schema_file = tmp_path / "schema.graphql"
    schema_file.write_text(_FULL_SCHEMA)

    analysis = analyze_graphql_schema(schema_file)

    kind_map = {t.name: t.kind for t in analysis.types}
    assert kind_map["User"] == "type"
    assert kind_map["CreateUserInput"] == "input"
    assert kind_map["Role"] == "enum"
    assert kind_map["Node"] == "interface"
    assert kind_map["SearchResult"] == "union"
    assert kind_map["DateTime"] == "scalar"


def test_type_fields(tmp_path: Path) -> None:
    """Object types should have their fields extracted."""
    schema_file = tmp_path / "schema.graphql"
    schema_file.write_text(_FULL_SCHEMA)

    analysis = analyze_graphql_schema(schema_file)

    user_type = next(t for t in analysis.types if t.name == "User")
    field_names = {f.name for f in user_type.fields}
    assert "id" in field_names
    assert "name" in field_names
    assert "email" in field_names
    assert "posts" in field_names


# ── Schema analysis: total_operations property ───────────────────


def test_total_operations(tmp_path: Path) -> None:
    """total_operations should equal queries + mutations + subscriptions."""
    schema_file = tmp_path / "schema.graphql"
    schema_file.write_text(_FULL_SCHEMA)

    analysis = analyze_graphql_schema(schema_file)

    expected = len(analysis.queries) + len(analysis.mutations) + len(analysis.subscriptions)
    assert analysis.total_operations == expected
    # Full schema: 4 queries + 4 mutations + 2 subscriptions = 10
    assert analysis.total_operations == 10


# ── Schema analysis: comments ────────────────────────────────────


def test_analyze_schema_with_comments(tmp_path: Path) -> None:
    """Comments should be stripped without affecting parsing."""
    schema_file = tmp_path / "schema.graphql"
    schema_file.write_text(_SCHEMA_WITH_COMMENTS)

    analysis = analyze_graphql_schema(schema_file)

    assert len(analysis.queries) == 2
    query_names = {q.name for q in analysis.queries}
    assert query_names == {"greeting", "currentTime"}


# ── Schema analysis: nonexistent file ────────────────────────────


def test_analyze_nonexistent_file(tmp_path: Path) -> None:
    """analyze_graphql_schema returns empty analysis for missing files."""
    result = analyze_graphql_schema(tmp_path / "missing.graphql")

    assert result.queries == []
    assert result.mutations == []
    assert result.subscriptions == []
    assert result.types == []
    assert result.total_operations == 0


# ── Schema analysis: empty schema ────────────────────────────────


def test_analyze_empty_schema(tmp_path: Path) -> None:
    """analyze_graphql_schema handles an empty schema file gracefully."""
    schema_file = tmp_path / "schema.graphql"
    schema_file.write_text("")

    result = analyze_graphql_schema(schema_file)
    assert result.total_operations == 0


# ── GraphQLTestBuilder ───────────────────────────────────────────


def test_builder_generates_query_tests() -> None:
    """GraphQLTestBuilder creates test cases for each query."""
    analysis = GraphQLSchemaAnalysis()
    analysis.queries = [
        _make_operation("query", "getUser"),
        _make_operation("query", "listUsers"),
    ]

    builder = GraphQLTestBuilder()
    cases = builder.generate_test_plan(analysis)

    # 4 test types per query * 2 queries = 8
    query_cases = [c for c in cases if c.operation_type == "query"]
    assert len(query_cases) == 8

    # Verify test types
    test_types = {c.test_type for c in query_cases}
    assert test_types == {"execution", "validation", "auth", "error_handling"}


def test_builder_generates_mutation_tests() -> None:
    """GraphQLTestBuilder creates test cases for each mutation."""
    analysis = GraphQLSchemaAnalysis()
    analysis.mutations = [_make_operation("mutation", "createUser")]

    builder = GraphQLTestBuilder()
    cases = builder.generate_test_plan(analysis)

    mutation_cases = [c for c in cases if c.operation_type == "mutation"]
    assert len(mutation_cases) == 4

    test_types = {c.test_type for c in mutation_cases}
    assert test_types == {"execution", "validation", "auth", "error_handling"}


def test_builder_generates_subscription_tests() -> None:
    """GraphQLTestBuilder creates test cases for each subscription."""
    analysis = GraphQLSchemaAnalysis()
    analysis.subscriptions = [_make_operation("subscription", "onMessage")]

    builder = GraphQLTestBuilder()
    cases = builder.generate_test_plan(analysis)

    sub_cases = [c for c in cases if c.operation_type == "subscription"]
    # Subscriptions get 2 tests (execution + error_handling)
    assert len(sub_cases) == 2

    test_types = {c.test_type for c in sub_cases}
    assert test_types == {"execution", "error_handling"}


def test_builder_mixed_operations() -> None:
    """GraphQLTestBuilder handles a mix of queries, mutations, and subscriptions."""
    analysis = GraphQLSchemaAnalysis()
    analysis.queries = [_make_operation("query", "getItem")]
    analysis.mutations = [_make_operation("mutation", "addItem")]
    analysis.subscriptions = [_make_operation("subscription", "itemAdded")]

    builder = GraphQLTestBuilder()
    cases = builder.generate_test_plan(analysis)

    # 4 (query) + 4 (mutation) + 2 (subscription) = 10
    assert len(cases) == 10


def test_builder_empty_analysis() -> None:
    """GraphQLTestBuilder returns empty list for empty analysis."""
    builder = GraphQLTestBuilder()
    cases = builder.generate_test_plan(GraphQLSchemaAnalysis())
    assert cases == []


def test_builder_test_case_fields() -> None:
    """Each GraphQLTestCase should have all required fields populated."""
    analysis = GraphQLSchemaAnalysis()
    analysis.queries = [_make_operation("query", "getUser")]

    builder = GraphQLTestBuilder()
    cases = builder.generate_test_plan(analysis)

    for case in cases:
        assert case.operation_name == "getUser"
        assert case.operation_type == "query"
        assert case.test_name
        assert case.test_type in ("execution", "validation", "auth", "error_handling")
        assert case.description


# ── Helpers ──────────────────────────────────────────────────────


def _make_operation(operation_type: str, name: str) -> GraphQLOperation:
    """Create a minimal GraphQLOperation for testing.

    Args:
        operation_type: One of 'query', 'mutation', or 'subscription'.
        name: Name of the operation field.

    Returns:
        A ``GraphQLOperation`` instance with empty fields and description.
    """
    return GraphQLOperation(
        operation_type=operation_type,
        name=name,
        fields=[],
        description="",
    )
