# nit GitHub Action

This GitHub Action makes it easy to integrate nit into your CI/CD pipeline.

## Usage

### Basic Example

```yaml
name: Test with nit

on: [pull_request]

jobs:
  nit-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run nit
        uses: getnit-dev/nit@v1
        with:
          mode: pick
          llm_provider: anthropic
          llm_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Advanced Example with Multiple Modes

```yaml
name: nit QA Suite

on:
  pull_request:
    types: [opened, synchronize, reopened]
  push:
    branches: [main]
  schedule:
    - cron: '0 2 * * *'  # Nightly at 2 AM UTC

jobs:
  # Generate tests for PR changes
  pr-analysis:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: getnit-dev/nit@v1
        with:
          mode: pick
          llm_provider: anthropic
          llm_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          test_type: all
          coverage_target: 80

  # Run existing tests on main
  main-validation:
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: getnit-dev/nit@v1
        with:
          mode: run
          llm_provider: openai
          llm_model: gpt-4o
          llm_api_key: ${{ secrets.OPENAI_API_KEY }}

  # Nightly drift check
  drift-monitoring:
    if: github.event_name == 'schedule'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: getnit-dev/nit@v1
        with:
          mode: drift
          llm_provider: anthropic
          llm_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

### Monorepo Example

```yaml
- uses: getnit-dev/nit@v1
  with:
    mode: pick
    path: packages/backend
    llm_provider: anthropic
    llm_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `mode` | Operation mode: `pick`, `run`, `drift`, `docs` | No | `pick` |
| `llm_provider` | LLM provider (openai, anthropic, ollama, etc.) | Yes | - |
| `llm_model` | Model name (e.g., gpt-4o, claude-3-5-sonnet) | No | - |
| `llm_api_key` | API key for the LLM provider | No | - |
| `path` | Path to analyze (for monorepos) | No | `.` |
| `test_type` | Test type: `unit`, `integration`, `e2e`, `all` | No | `all` |
| `coverage_target` | Target coverage percentage (1-100) | No | `80` |
| `python_version` | Python version to use | No | `3.14` |

## Outputs

| Output | Description |
|--------|-------------|
| `tests_generated` | Number of tests generated |
| `tests_passed` | Number of tests that passed |
| `coverage_before` | Coverage percentage before generation |
| `coverage_after` | Coverage percentage after generation |

## Required Secrets

Set up these secrets in your repository settings:

- `ANTHROPIC_API_KEY` - For Claude models
- `OPENAI_API_KEY` - For GPT models

## Modes

### `pick` (Default)
Full pipeline: scan → analyze → generate → test
- Detects your stack
- Analyzes code for untested areas
- Generates new tests
- Runs and validates tests

### `run`
Run existing tests only
- Executes your current test suite
- Reports coverage and results
- No test generation

### `drift`
Monitor LLM endpoint drift
- Checks if LLM responses have changed
- Useful for AI-powered features
- Catches breaking changes in model behavior

### `docs`
Generate/update documentation
- Creates API documentation
- Updates README files
- Generates test reports

## Support

- **Documentation**: https://getnit.dev
- **Issues**: https://github.com/getnit-dev/nit/issues
- **PyPI**: https://pypi.org/project/getnit/
