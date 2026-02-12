# GitHub Action

nit provides a GitHub Action for seamless CI integration. Add AI-powered testing to any repository with a few lines of YAML.

## Basic usage

```yaml
name: nit
on: [push, pull_request]

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: getnit-dev/nit@v1
        with:
          llm_provider: openai
          llm_api_key: ${{ secrets.OPENAI_API_KEY }}
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `mode` | No | `pick` | Operation mode: `pick`, `run`, `drift`, `docs` |
| `llm_provider` | **Yes** | — | LLM provider: `openai`, `anthropic`, `ollama`, etc. |
| `llm_model` | No | — | Model name (uses provider default if empty) |
| `llm_api_key` | No | — | API key for the LLM provider |
| `path` | No | `.` | Path to analyze (monorepo support) |
| `test_type` | No | `all` | Test type filter: `unit`, `integration`, `e2e`, `all` |
| `coverage_target` | No | `80` | Target coverage percentage (1-100) |
| `fix` | No | `false` | Enable automatic bug fixing (pick mode) |
| `create_pr` | No | `false` | Create a GitHub PR with results |
| `create_issues` | No | `false` | Create GitHub issues for bugs |
| `create_fix_prs` | No | `false` | Create PRs for bug fixes |
| `upload_report` | No | `false` | Upload results to nit platform |
| `platform_url` | No | `https://platform.getnit.dev` | Platform API URL |
| `platform_api_key` | No | — | Platform API key |
| `python_version` | No | `3.12` | Python version to use |
| `shard_index` | No | — | Shard index for parallel execution |
| `shard_count` | No | — | Total number of shards |
| `sentry_enabled` | No | `false` | Enable Sentry error tracking |
| `sentry_dsn` | No | — | Sentry DSN |
| `sentry_traces_sample_rate` | No | `0.0` | Sentry tracing rate |
| `sentry_profiles_sample_rate` | No | `0.0` | Sentry profiling rate |
| `sentry_enable_logs` | No | `false` | Send logs to Sentry |
| `docs_write_to_source` | No | `false` | Write generated docstrings back to source files |
| `docs_check_mismatch` | No | `true` | Check for doc/code semantic mismatches |
| `docs_style` | No | — | Docstring style: `google`, `numpy` (auto-detect if empty) |
| `docs_framework` | No | — | Documentation framework override (auto-detect if empty) |
| `docs_output_dir` | No | — | Output directory for generated documentation files |

## Outputs

| Output | Description |
|--------|-------------|
| `tests_generated` | Number of tests generated |
| `tests_passed` | Number of tests that passed |
| `coverage_before` | Coverage % before generation |
| `coverage_after` | Coverage % after generation |
| `shard_result_path` | Path to shard result JSON (when sharding) |
| `docs_generated` | Number of documentation items generated (docs mode) |
| `docs_mismatches` | Number of doc/code mismatches found (docs mode) |

## Operation modes

### pick (default)

Runs the full pipeline: scan, analyze, generate, test, and report.

```yaml
- uses: getnit-dev/nit@v1
  with:
    mode: pick
    llm_provider: openai
    llm_api_key: ${{ secrets.OPENAI_API_KEY }}
    fix: 'true'
    create_pr: 'true'
    create_issues: 'true'
```

### run

Run existing tests only (no generation).

```yaml
- uses: getnit-dev/nit@v1
  with:
    mode: run
    llm_provider: openai
```

### drift

Check for code drift against baselines.

```yaml
- uses: getnit-dev/nit@v1
  with:
    mode: drift
    llm_provider: openai
    llm_api_key: ${{ secrets.OPENAI_API_KEY }}
```

### docs

Generate documentation. Supports mismatch detection, write-back to source files, style preferences, and output directory configuration.

```yaml
- uses: getnit-dev/nit@v1
  with:
    mode: docs
    llm_provider: openai
    llm_api_key: ${{ secrets.OPENAI_API_KEY }}
```

Generate docs with write-back and mismatch detection:

```yaml
- uses: getnit-dev/nit@v1
  with:
    mode: docs
    llm_provider: anthropic
    llm_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
    docs_write_to_source: 'true'
    docs_check_mismatch: 'true'
    docs_style: google
    docs_output_dir: docs/api
```

## Advanced examples

### PR-only workflow

Run nit only on pull requests and create a comment with results:

```yaml
name: nit PR check
on: pull_request

permissions:
  contents: write
  pull-requests: write

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: getnit-dev/nit@v1
        with:
          llm_provider: anthropic
          llm_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          llm_model: claude-sonnet-4-5-20250514
          create_pr: 'true'
          coverage_target: '85'
```

### With platform integration

```yaml
- uses: getnit-dev/nit@v1
  with:
    llm_provider: openai
    llm_api_key: ${{ secrets.OPENAI_API_KEY }}
    upload_report: 'true'
    platform_api_key: ${{ secrets.NIT_PLATFORM_API_KEY }}
```

### Required secrets

Add these secrets to your repository settings:

| Secret | Required for |
|--------|-------------|
| `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` | LLM provider authentication |
| `NIT_PLATFORM_API_KEY` | Platform report uploads |
| `SENTRY_DSN` | Sentry error tracking |
