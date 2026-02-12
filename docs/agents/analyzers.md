# Analyzers

Analyzers examine your code, coverage, changes, and patterns to inform test generation and bug detection.

## Code Analyzer

Analyzes source code structure using tree-sitter AST parsing.

**Capabilities:**

- Extracts functions, classes, methods, and their signatures
- Builds code dependency maps
- Identifies code complexity metrics
- Maps imports and call graphs

**Used by:** Builders (for context assembly), Bug Analyzer

---

## Coverage Analyzer

Runs coverage tools via framework adapters and identifies testing gaps.

**Capabilities:**

- Identifies **untested files** — files with no coverage at all
- Identifies **undertested functions** — functions below the `undertested_threshold` (default: 50%)
- Identifies **dead zones** — high-complexity functions with zero coverage
- Generates a prioritized gap report sorted by risk and impact

**Configuration:**

```yaml
coverage:
  line_threshold: 80.0
  branch_threshold: 75.0
  function_threshold: 85.0
  complexity_threshold: 10
  undertested_threshold: 50.0
```

**Used by:** Pick pipeline, Generate command

---

## Diff Analyzer

Uses git diff to identify changed files and map them to their test files.

**Capabilities:**

- Parses git diff between refs (e.g., `HEAD~1..HEAD` or PR base..head)
- Maps changed source files to corresponding test files
- Creates delta-focused work lists for CI/PR mode
- Filters changes by file type and relevance

**CLI usage:**

```bash
nit scan --diff --base-ref main
```

**Used by:** Pick pipeline (PR mode), CI workflows

---

## Risk Analyzer

Assesses the risk of code changes to prioritize testing efforts.

**Capabilities:**

- Evaluates change size and complexity
- Identifies high-risk modifications (security-sensitive code, public APIs)
- Weights risk by file importance and change frequency

**Used by:** Pick pipeline

---

## Route Discovery

Discovers API routes and endpoints in web applications.

**Supported frameworks:**

| Framework | Language | Detection method |
|-----------|----------|-----------------|
| FastAPI | Python | Decorator parsing (`@app.get`, `@router.post`) |
| Flask | Python | Route decorators |
| Django | Python | URL patterns |
| Express | JavaScript | Route method calls |
| Next.js | JavaScript/TypeScript | File-based routing (`pages/`, `app/`) |
| net/http | Go | Handler registration |

**Used by:** E2E Builder (to generate tests covering all endpoints)

---

## Bug Analyzer

Detects potential bugs in source code using LLM-powered analysis.

**Capabilities:**

- Null/undefined dereferences
- Off-by-one errors
- Resource leaks
- Unhandled error paths
- Type confusion
- Race conditions (basic detection)

Each detected bug is classified by severity (critical, high, medium, low).

**Used by:** Pick pipeline, Debug command

---

## Semantic Gap Detector

Identifies semantic gaps — places where the code's behavior doesn't match what a reasonable developer would expect.

**Capabilities:**

- Missing error handling for common failure modes
- Inconsistent return types
- Unvalidated inputs at public boundaries
- Silent failures (swallowed exceptions)

**Used by:** Pick pipeline (when enabled)
