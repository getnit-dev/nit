# Token Budgets & Rate Limits

nit provides controls for managing LLM costs and API usage.

## Token budget

Set a total token budget for the session. When the budget is exhausted, nit stops making LLM calls.

```yaml
llm:
  token_budget: 100000  # Total tokens for this run (0 = unlimited)
```

**Default:** `0` (unlimited)

This is useful for CI runs where you want to cap spending per workflow execution.

## Rate limiting

Control how many requests nit makes per minute:

```yaml
llm:
  requests_per_minute: 60
```

**Default:** `60`

This prevents hitting provider rate limits, especially during large test generation runs.

## Retries

Configure automatic retries for transient failures (rate limits, timeouts, server errors):

```yaml
llm:
  max_retries: 3
```

**Default:** `3`

Retries use exponential backoff.

## Temperature

Control the randomness of generated output:

```yaml
llm:
  temperature: 0.2
```

**Default:** `0.2`

| Value | Behavior |
|-------|----------|
| `0.0` | Most deterministic — same input produces similar output |
| `0.2` | Slightly creative (recommended for test generation) |
| `0.5` | Moderate creativity |
| `1.0+` | High creativity (not recommended for tests) |

## Max tokens

Set the maximum number of tokens the LLM can generate per request:

```yaml
llm:
  max_tokens: 4096
```

**Default:** `4096`

Increase for complex test files that may be longer. Decrease to reduce costs.

## Usage tracking

nit tracks LLM usage per session. After a run, you can see:

- Total tokens consumed (input + output)
- Number of API calls made
- Cost estimate (when using billed providers)

In platform mode, usage data is also uploaded for dashboard visualization. See [Platform Integration](../integrations/platform.md).

## Cost optimization tips

1. **Use `gpt-4o-mini` or `ollama` for development** — save premium models for CI
2. **Set `token_budget`** — prevent runaway costs in CI
3. **Use `--file` flag** — target specific files instead of scanning the entire codebase
4. **Enable sharding** — parallelize work across CI jobs to reduce per-job token usage
5. **Use diff mode** — `nit scan --diff` only analyzes changed files
