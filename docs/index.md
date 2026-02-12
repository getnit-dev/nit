# nit

**Open-source AI testing, documentation & quality agent.**

nit auto-detects your stack, generates comprehensive tests, finds bugs, monitors drift, and produces documentation — all powered by your choice of LLM provider.

## What nit does

- **Auto-detects** your project's languages, frameworks, and workspace structure
- **Generates** unit, integration, and E2E tests using AI
- **Analyzes** coverage gaps, code risks, and semantic gaps
- **Finds bugs** via static analysis and LLM-powered inspection
- **Fixes bugs** automatically with generated patches
- **Monitors drift** in code behavior over time
- **Generates documentation** (docstrings, changelogs, READMEs)
- **Reports** to GitHub PRs/issues, Slack, HTML dashboards, and terminal

## What nit does not do

- nit does **not** run your production code or modify your deployment pipeline
- nit does **not** send any telemetry unless you explicitly opt in via Sentry configuration
- nit does **not** store your code — LLM calls go directly to your chosen provider
- nit does **not** require a paid account — it is fully open source and self-hosted

## Supported languages & frameworks

| Language | Unit Testing | Coverage | Documentation |
|----------|-------------|----------|---------------|
| Python | pytest | coverage.py | Sphinx |
| JavaScript/TypeScript | Vitest, Jest | Istanbul | JSDoc, TypeDoc |
| Go | go test, testify | go cover | godoc |
| Rust | cargo test | tarpaulin | rustdoc |
| C/C++ | Google Test, Catch2 | gcov | Doxygen |
| Java | JUnit 5 | JaCoCo | — |
| Kotlin | Kotest | JaCoCo | — |
| C#/.NET | xUnit | Coverlet | — |
| Any | — | — | MkDocs |

## Quick links

- [Installation](getting-started/installation.md) — get nit running in 2 minutes
- [Quickstart](getting-started/quickstart.md) — your first test generation
- [Configuration](getting-started/configuration.md) — full `.nit.yml` reference
- [GitHub Action](ci/github-action.md) — add nit to your CI pipeline
- [LLM Setup](llm/index.md) — configure your AI provider
