"""GraphQL test generation prompt template.

Generates tests for GraphQL operations (queries, mutations, subscriptions)
with best practices:
- Query execution and response shape validation
- Variable and input validation
- Authentication and authorization checks
- Error handling for nullable and non-existent resources
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nit.llm.prompts.base import (
    PromptSection,
    PromptTemplate,
    format_dependencies_section,
    format_source_section,
)

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext

_GRAPHQL_SYSTEM_INSTRUCTION = """\
You are an expert test engineer specializing in GraphQL API testing.

Your task is to generate robust, maintainable tests that verify GraphQL \
operations including queries, mutations, and subscriptions.

Key principles:
1. **Correctness**: Verify response shapes match the schema and return expected data.
2. **Validation**: Test that invalid variables and inputs produce proper GraphQL errors.
3. **Auth**: Verify that protected operations reject unauthenticated or unauthorized requests.
4. **Error Handling**: Test nullable fields, not-found cases, and server error responses.
5. **Isolation**: Each test should be independent; use setup/teardown for shared state.

Output only the test code in a single file. \
Do NOT include explanations or markdown formatting.
"""

_GRAPHQL_INSTRUCTIONS = """\
GraphQL testing rules:
- Send operations via HTTP POST to the GraphQL endpoint with JSON body:
  { "query": "...", "variables": { ... } }
- Verify the response has a top-level `data` key for successful operations.
- Verify the response has a top-level `errors` array for failed operations.
- Check that returned fields match the schema types (String, Int, Boolean, ID, etc.).
- For mutations, verify side effects (created/updated/deleted resources).
- For subscriptions, verify that events are emitted after triggering mutations.
- Use descriptive test names that explain the scenario being tested.

Variable validation patterns:
- Omit required variables and assert an error is returned.
- Send variables with wrong types and assert a validation error.
- Send null for non-nullable arguments and assert a validation error.

Authentication patterns:
- Send a request without an auth header and assert a 401/403 or auth error in `errors`.
- Send a request with an expired or invalid token and assert an auth error.

Error handling patterns:
- Query for a resource that does not exist and assert null or an error.
- Attempt a mutation that violates a unique constraint and assert a conflict error.
- Trigger a server-side failure and verify the response includes a meaningful error message.
"""

_GRAPHQL_EXAMPLE = """\
import { describe, it, expect, beforeAll } from 'vitest';

const GRAPHQL_ENDPOINT = 'http://localhost:4000/graphql';

async function gqlRequest(
  query: string,
  variables?: Record<string, unknown>,
  token?: string,
) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(GRAPHQL_ENDPOINT, {
    method: 'POST',
    headers,
    body: JSON.stringify({ query, variables }),
  });
  return res.json();
}

describe('User queries', () => {
  it('should return user by ID', async () => {
    const query = `query GetUser($id: ID!) { user(id: $id) { id name email } }`;
    const result = await gqlRequest(query, { id: '1' }, 'valid-token');
    expect(result.data.user).toBeDefined();
    expect(result.data.user.id).toBe('1');
    expect(result.data.user.name).toEqual(expect.any(String));
  });

  it('should return error for missing user', async () => {
    const query = `query GetUser($id: ID!) { user(id: $id) { id name } }`;
    const result = await gqlRequest(query, { id: 'nonexistent' }, 'valid-token');
    expect(result.data.user).toBeNull();
  });

  it('should reject unauthenticated request', async () => {
    const query = `query GetUser($id: ID!) { user(id: $id) { id } }`;
    const result = await gqlRequest(query, { id: '1' });
    expect(result.errors).toBeDefined();
    expect(result.errors[0].message).toMatch(/auth/i);
  });
});

describe('CreateUser mutation', () => {
  it('should create a user with valid input', async () => {
    const mutation = `
      mutation CreateUser($input: CreateUserInput!) {
        createUser(input: $input) { id name email }
      }
    `;
    const result = await gqlRequest(
      mutation,
      { input: { name: 'Alice', email: 'alice@example.com' } },
      'valid-token',
    );
    expect(result.data.createUser.name).toBe('Alice');
  });

  it('should reject invalid email', async () => {
    const mutation = `
      mutation CreateUser($input: CreateUserInput!) {
        createUser(input: $input) { id }
      }
    `;
    const result = await gqlRequest(
      mutation,
      { input: { name: 'Bob', email: 'not-an-email' } },
      'valid-token',
    );
    expect(result.errors).toBeDefined();
  });
});
"""


class GraphQLTestTemplate(PromptTemplate):
    """Prompt template for GraphQL test generation."""

    @property
    def name(self) -> str:
        """Template name identifier."""
        return "graphql_test"

    def _system_instruction(self, _context: AssembledContext) -> str:
        """Return the system-level instruction for GraphQL test generation."""
        return _GRAPHQL_SYSTEM_INSTRUCTION

    def _build_sections(self, context: AssembledContext) -> list[PromptSection]:
        """Build prompt sections for GraphQL test generation.

        Includes:
        - Framework instructions
        - Example test
        - Source file information (schema or resolver)
        - Dependencies

        Args:
            context: Assembled context for the source file under test.

        Returns:
            Ordered list of prompt sections.
        """
        sections = [
            PromptSection(
                label="GraphQL Testing Instructions",
                content=_GRAPHQL_INSTRUCTIONS,
            ),
            PromptSection(
                label="Example Test",
                content=f"```typescript\n{_GRAPHQL_EXAMPLE}\n```",
            ),
        ]

        # Add source file information
        sections.append(format_source_section(context))

        # Add dependencies
        sections.append(format_dependencies_section(context))

        # Add generation requirements
        sections.append(
            PromptSection(
                label="Requirements",
                content=_build_requirements(),
            )
        )

        return sections


def _build_requirements() -> str:
    """Build the test generation requirements section.

    Returns:
        Formatted requirements string.
    """
    return "\n".join(
        [
            "Generate a complete test file for the provided GraphQL schema/resolvers.",
            "Include test cases for:",
            "  - Successful query execution with valid variables",
            "  - Mutation execution verifying side effects",
            "  - Variable validation (missing, wrong type, null for non-nullable)",
            "  - Authentication and authorization checks",
            "  - Error handling (not found, conflict, server error)",
            "Use a helper function for GraphQL HTTP requests to reduce boilerplate.",
            "Add comments explaining complex test scenarios or business rules.",
        ]
    )
