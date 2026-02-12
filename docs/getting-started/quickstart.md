# Quickstart

This guide walks you through generating your first AI-powered tests with nit.

## 1. Initialize your project

Navigate to your project root and run:

```bash
nit init
```

This creates a `.nit.yml` configuration file with sensible defaults based on your project structure.

## 2. Configure your LLM

Edit `.nit.yml` to add your LLM provider:

=== "OpenAI"

    ```yaml
    llm:
      provider: openai
      model: gpt-4o
      api_key: ${OPENAI_API_KEY}
    ```

=== "Anthropic"

    ```yaml
    llm:
      provider: anthropic
      model: claude-sonnet-4-5-20250514
      api_key: ${ANTHROPIC_API_KEY}
    ```

=== "Ollama (local)"

    ```yaml
    llm:
      mode: ollama
      model: llama3
      base_url: http://localhost:11434
    ```

!!! tip
    Use `${ENV_VAR}` syntax to reference environment variables instead of hardcoding API keys.

## 3. Scan your project

```bash
nit scan
```

nit auto-detects your languages, frameworks, workspace structure, and existing test patterns. The results are cached in `.nit/profile.json` for subsequent runs.

## 4. Generate tests

```bash
nit generate --path src/
```

nit analyzes your source code, identifies coverage gaps, and generates tests using your configured LLM. Generated test files are placed alongside your existing test structure.

## 5. Run tests

```bash
nit run
```

Executes all tests (including newly generated ones) using your project's test runner.

## 6. Full pipeline (recommended)

For the full experience, use `pick` — it combines scanning, analysis, generation, testing, and reporting into a single command:

```bash
nit pick
```

The pick pipeline:

1. Detects your frameworks and languages
2. Analyzes code for bugs and coverage gaps
3. Assesses risk of recent changes
4. Generates tests for uncovered code
5. Runs all tests and collects results
6. Optionally creates PRs, issues, and reports

## What's next

- [Configuration reference](configuration.md) — customize every aspect of nit
- [CLI commands](../cli/commands.md) — explore all available commands
- [GitHub Action](../ci/github-action.md) — add nit to your CI pipeline
