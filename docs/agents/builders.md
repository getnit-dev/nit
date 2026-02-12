# Builders

Builders are the agents responsible for generating tests and documentation.

## Unit Builder

The primary test generation agent. Generates unit tests using framework-specific adapters and LLM prompts.

**Process:**

1. Loads the project profile and selects the appropriate adapter
2. Assembles context: source code, AST, existing tests, coverage data, memory patterns
3. Sends context to the LLM with framework-specific prompts
4. Receives generated test code
5. Validates syntax via tree-sitter
6. Runs the test to verify it passes
7. If it fails, classifies the failure and optionally retries (self-healing)

**Failure classification:**

| Type | Description | Action |
|------|-------------|--------|
| Test bug | Generated test has a bug | Retry with error context |
| Code bug | Test exposes a real bug | Report as bug finding |
| Missing dep | Test needs an unavailable dependency | Skip and note |
| Timeout | Test execution timed out | Skip and note |

**Configuration:**

```yaml
llm:
  temperature: 0.2    # Lower = more deterministic tests
  max_tokens: 4096    # Max output for generated test
pipeline:
  max_fix_loops: 1    # Retry count for failing tests
```

---

## E2E Builder

Generates end-to-end tests using Playwright.

**Process:**

1. Discovers application routes (via Route Discovery Agent)
2. Loads E2E configuration (base URL, auth strategy)
3. Generates Playwright test scripts covering discovered routes
4. Handles authentication setup based on configured strategy

**Requires:** E2E configuration in `.nit.yml`. See [E2E Testing](../adapters/e2e.md).

---

## Integration Builder

Generates integration tests that verify interactions between components.

**Focus areas:**

- API endpoint tests
- Database interaction tests
- Service-to-service communication tests

---

## Infrastructure Builder

Generates infrastructure and deployment validation tests.

**Focus areas:**

- Configuration validation
- Environment variable checks
- Health check endpoints
- Dependency availability tests

---

## Doc Builder

Generates and maintains documentation using language-specific doc adapters and LLM-powered content generation.

**Process:**

1. Parses source files using Tree-sitter to extract functions, classes, and signatures
2. Compares current state against saved doc state (`.nit/memory/doc_state.json`) to detect changes
3. Identifies functions that are new, modified, or have stale documentation
4. Sends changes to the LLM with framework-specific prompts (Sphinx, JSDoc, Doxygen, etc.)
5. Parses generated documentation blocks from the LLM response
6. Updates the saved doc state for future change detection
7. Optionally writes docstrings back to source files or to an output directory
8. Optionally runs semantic mismatch detection on existing documentation

**Capabilities:**

- Function/class docstrings across 7 frameworks (Sphinx, JSDoc, TypeDoc, Doxygen, godoc, rustdoc, MkDocs)
- Semantic mismatch detection — compares existing docs against code to find inaccuracies
- Write-back to source files — inserts generated docstrings directly into your code
- Output directory support — writes documentation as Markdown files
- Style preferences — Google or NumPy style for Python docstrings
- Exclude patterns — skip files matching glob patterns
- Memory-based diffing — only regenerates docs for changed functions

**Configuration:**

```yaml
docs:
  enabled: true
  style: google              # google, numpy, or auto-detect
  framework: ""              # Override framework detection
  write_to_source: false     # Write docs back to source files
  check_mismatch: true       # Detect doc/code mismatches
  output_dir: ""             # Output directory for Markdown files
  exclude_patterns: []       # Glob patterns to exclude
  max_tokens: 4096           # Token budget per file
```

**Usage:**

```bash
# Generate docstrings
nit docs --type docstrings

# Write back to source files
nit docs --type docstrings --write-to-source

# Generate to output directory
nit docs --type docstrings --output-dir docs/api

# Override style
nit docs --type docstrings --style numpy

# Check for mismatches only
nit docs --type docstrings --check-mismatch
```

See [Documentation Adapters](../adapters/documentation.md) for supported formats and CLI flags.

---

## README Updater

Updates the project's README.md with current information.

```bash
nit docs --type readme
```

Analyzes the project structure and generates/updates sections like:

- Project description
- Installation instructions
- Usage examples
- API overview
