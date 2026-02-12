# Memory

nit maintains a memory system that learns from each test generation run, improving quality over time.

## How memory works

Memory is stored in `.nit/memory/` as JSON files. nit tracks:

### Known patterns

Patterns that have worked well (generated tests that pass). Each pattern has a success count — frequently successful patterns are prioritized in future generation.

### Failed patterns

Patterns that produced failing tests. Each failed pattern includes a failure reason, helping nit avoid repeating the same mistakes.

### Conventions

Project-wide conventions detected from existing code:

- **Naming style** — `test_method_name`, `testMethodName`, `should_do_something`
- **Assertion style** — `assert`, `expect`, `should`
- **Import patterns** — relative vs absolute imports, common test utilities
- **Setup/teardown patterns** — fixtures, beforeEach, setUp

### Generation stats

Aggregate statistics on test generation:

- Success rate by file type
- Average tokens per generation
- Common failure categories

## Memory in prompts

Memory data is injected into LLM prompts to guide generation. For example:

```
Project conventions:
- Uses pytest fixtures (conftest.py pattern)
- Prefers assert statements over assertEqual
- Groups tests in classes named Test<ClassName>

Known successful patterns:
- Mock external APIs with unittest.mock.patch
- Use parametrize for boundary value testing

Known failed patterns:
- Avoid importing from internal._private modules (causes ImportError)
```

## CLI commands

```bash
# View project memory
nit memory show

# View memory for a specific package
nit memory show --package packages/web-app

# Export as JSON
nit memory export --format json --output memory-dump.json

# Reset all memory
nit memory reset --confirm

# Reset memory for one package
nit memory reset --package packages/web-app --confirm
```

## Storage location

```
.nit/
  memory/
    global_memory.json              # Project-wide patterns
    packages/
      <package-name>/
        memory.json                 # Package-specific patterns
    analytics/
      events.json                   # Analytics event log
      history.json                  # Historical trends
    drift_baselines.json            # Drift detection baselines
```

## Analytics

nit collects anonymous, local-only analytics about its own operations:

- Test generation success/failure rates
- Time spent per operation
- Token usage per generation
- Error frequency by category

This data stays in `.nit/memory/analytics/` and is never sent anywhere unless you explicitly configure platform uploads.

### Querying analytics

```bash
# View analytics summary
nit memory show --format json | jq '.stats'
```

Analytics data powers the [Dashboard](../integrations/dashboard.md) trend charts.
