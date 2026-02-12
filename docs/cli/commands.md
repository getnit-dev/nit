# Commands

## init

Initialize a `.nit.yml` configuration file for your project.

```bash
nit init
```

Scans the project to detect languages, frameworks, and workspace structure, then writes a starter configuration file with auto-detected values.

---

## scan

Scan the project to detect languages, frameworks, coverage, and workspace structure.

```bash
nit scan [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Path to scan (default: current directory) |
| `--force` | Force re-scan even if cached profile exists |
| `--json` | Output results as JSON |
| `--diff` | Only scan files changed since last commit |
| `--base-ref REF` | Base git ref for diff mode (default: `HEAD~1`) |
| `--compare-ref REF` | Compare git ref for diff mode |

The scan results are cached in `.nit/profile.json`. Subsequent commands use this profile to select the correct adapters and prompts.

---

## generate

Generate tests for source files using AI.

```bash
nit generate [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Path to generate tests for |
| `--model MODEL` | Override LLM model |
| `--type TYPE` | Test type: `unit`, `integration`, `e2e`, `all` |
| `--file FILE` | Generate tests for a specific file |
| `--coverage-target N` | Target coverage percentage (1-100) |
| `--format FORMAT` | Output format: `terminal`, `json` |

The generate command:

1. Loads the project profile (runs scan if needed)
2. Identifies untested or undertested source files
3. Assembles context (source code, AST, existing tests, patterns)
4. Sends context to the LLM with framework-specific prompts
5. Validates generated tests (syntax check via tree-sitter)
6. Writes passing tests to disk

---

## run

Run tests using your project's test runner.

```bash
nit run [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Path to test |
| `--type TYPE` | Test type filter |
| `--format FORMAT` | Output format |

---

## pick

The flagship command. Runs the full nit pipeline: detect, analyze, generate, test, and report.

```bash
nit pick [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Path to analyze |
| `--model MODEL` | Override LLM model |
| `--type TYPE` | Test type: `unit`, `integration`, `e2e`, `all` |
| `--file FILE` | Target a specific file |
| `--coverage-target N` | Target coverage percentage |
| `--fix` | Enable automatic bug fixing |
| `--pr` | Create a GitHub PR with generated tests/fixes |
| `--create-issues` | Create GitHub issues for detected bugs |
| `--create-fix-prs` | Create separate PRs for each bug fix |
| `--report` | Upload results to nit platform |
| `--format FORMAT` | Output format: `terminal`, `json` |
| `--shard-index N` | Shard index for parallel execution |
| `--shard-count N` | Total number of shards |
| `--shard-output PATH` | Path to write shard result JSON |

The pick pipeline executes these stages:

1. **Framework detection** — identify languages and test frameworks
2. **Bug analysis** — scan code for potential bugs
3. **Risk assessment** — evaluate risk of recent changes
4. **Coverage analysis** — find untested code paths
5. **Root cause analysis** — analyze detected bugs
6. **Fix generation** — generate patches for bugs (when `--fix` is enabled)
7. **Fix verification** — run tests on fixes
8. **Report generation** — output results
9. **GitHub integration** — create PRs/issues (when enabled)

---

## analyze

Analyze code quality, coverage gaps, and risks.

```bash
nit analyze [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Path to analyze |
| `--type TYPE` | Analysis type: `coverage`, `risk`, `code`, `all` |
| `--format FORMAT` | Output format |

---

## debug

Debug specific bugs in your source code.

```bash
nit debug [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Path to debug |
| `--file FILE` | Target file |
| `--fix` | Generate and apply fixes |

---

## report

Generate reports from previous nit runs.

```bash
nit report [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Project path |
| `--pr` | Create a GitHub PR |
| `--create-issues` | Create GitHub issues |
| `--create-fix-prs` | Create fix PRs |
| `--upload-platform` | Upload to nit platform |
| `--no-commit` | Skip git commits |
| `--html` | Generate HTML dashboard |
| `--serve` | Serve HTML report locally |
| `--port PORT` | Port for HTML server (default: 8080) |
| `--days N` | Number of days for trend data |

---

## drift

Detect code drift and behavioral changes.

```bash
nit drift [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Path to monitor |
| `--format FORMAT` | Output format |

Drift detection compares the current state of your code against saved baselines to identify behavioral changes, removed tests, or divergent patterns.

---

## watch

Monitor coverage trends and auto-generate tests when coverage drops.

```bash
nit watch [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Path to watch |
| `--interval N` | Check interval in seconds |

---

## docs

Generate documentation: changelogs, READMEs, and docstrings. Supports semantic mismatch detection, writing docstrings back to source files, style preferences, and output directory configuration.

```bash
nit docs [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Path to document |
| `--type TYPE` | Doc type: `changelog`, `readme`, `docstrings`, `all` |
| `--format FORMAT` | Output format |
| `--file FILE` | Target a specific file |
| `--all` | Process all source files (not just changed) |
| `--write-to-source` | Write generated docstrings back into source files |
| `--output-dir PATH` | Output directory for generated documentation files |
| `--style STYLE` | Docstring style override: `google`, `numpy` |
| `--framework FRAMEWORK` | Documentation framework override (e.g., `sphinx`, `jsdoc`) |
| `--check-mismatch` / `--no-check-mismatch` | Enable/disable doc/code semantic mismatch detection |

See [Documentation Adapters](../adapters/documentation.md) for supported frameworks and configuration.

---

## combine

Combine sharded test results from parallel CI runs.

```bash
nit combine [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Directory containing shard result JSON files |
| `--output PATH` | Output path for combined results |

Used after parallel sharded runs to merge results into a single report. See [Sharding](../ci/sharding.md) for details.
