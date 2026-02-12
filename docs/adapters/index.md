# Adapters Overview

Adapters are the bridge between nit and your project's testing, coverage, and documentation tools. Each adapter knows how to detect its framework, generate appropriate tests, run them, and parse results.

## How adapters work

1. **Detection** — each adapter checks for framework-specific signals (config files, dependencies, import patterns)
2. **Selection** — the adapter registry picks the right adapter(s) based on your project profile
3. **Prompt generation** — adapters provide framework-specific LLM prompts for test generation
4. **Test execution** — adapters know how to invoke the test runner and parse results
5. **Validation** — generated tests are syntax-checked via tree-sitter before being written

## Adapter categories

| Category | Count | Description |
|----------|-------|-------------|
| [Unit Testing](unit-testing.md) | 11 | pytest, Vitest, Jest, Go test, GTest, Catch2, JUnit5, Kotest, Cargo test, xUnit, Testify |
| [Coverage](coverage.md) | 8 | coverage.py, Istanbul, go cover, Coverlet, JaCoCo, gcov, tarpaulin |
| [E2E Testing](e2e.md) | 1 | Playwright (with auth strategies) |
| [Documentation](documentation.md) | 8 | Sphinx, Doxygen, godoc, JSDoc, TypeDoc, rustdoc, MkDocs |

## Auto-detection

nit auto-detects your frameworks during `nit scan`. You can override detection by explicitly setting frameworks in `.nit.yml`:

```yaml
testing:
  unit_framework: pytest
  e2e_framework: playwright
```

## Adapter registry

The adapter registry (`nit.adapters.registry`) discovers adapters at runtime by:

1. Scanning the `nit.adapters.unit`, `nit.adapters.e2e`, and `nit.adapters.docs` packages
2. Loading external adapters registered via Python entry points

See [Custom Adapters](../advanced/custom-adapters.md) for how to create your own.
