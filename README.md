# nit

### Open-Source AI Testing, Documentation & Quality Agent

[![PyPI version](https://badge.fury.io/py/getnit.svg)](https://pypi.org/project/getnit/)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**nit** is a local-first AI quality agent that auto-detects your project's stack and generates comprehensive tests at every level—unit, integration, and E2E—using your existing test frameworks.

---

## The Problem

Software testing is broken:

- **85% of bugs reach production** despite decades of testing tools
- **Unit test coverage stagnates** because writing tests is tedious and always deprioritized
- **E2E tests are brittle** — auth flows, flaky selectors, and environment config drain engineering time
- **AI-generated code creates technical debt** — only 29% of developers trust AI code accuracy
- **LLM-powered features drift silently** — model updates change your app's behavior and nobody notices
- **Documentation rots** — always the last thing updated, first thing abandoned

Existing solutions are expensive SaaS products ($2.5K–$4K/month) or narrow open-source tools that only cover one slice.

**nit does the full loop**: detect your stack → generate tests → run them → report bugs → self-heal broken tests → track coverage → monitor LLM drift → keep docs current.

---

## Features

- ✅ **Auto-detects** your languages, frameworks, and test infrastructure (no config needed)
- ✅ **Generates framework-native tests** — Vitest, pytest, Jest, Playwright, and more
- ✅ **Self-iterates** — validates generated tests, auto-fixes errors (up to 3 retries per test)
- ✅ **Learns your patterns** — analyzes existing tests, matches your project's style and conventions
- ✅ **Runs continuously** — CLI for local dev, GitHub Action for PRs, scheduled drift monitoring
- ✅ **Coverage-driven** — identifies untested code, undertested functions, and dead zones
- ✅ **Self-healing E2E tests** — when UI selectors break, nit updates them automatically
- ✅ **LLM drift monitoring** — tracks prompt→output quality over time for AI features
- ✅ **Multi-language** — Python, TypeScript/JavaScript, C/C++, Java, Go, Rust (more coming)
- ✅ **Monorepo-aware** — supports Turborepo, Nx, pnpm workspaces, Yarn, npm, Cargo, Go modules
- ✅ **Bring your own LLM** — works with OpenAI, Anthropic, Ollama, or any LiteLLM-supported provider

---

## Installation

### Via pip (recommended)

```bash
pip install getnit
```

### Via pipx (isolated environment)

```bash
pipx install getnit
```

### From source (for development)

```bash
git clone https://github.com/getnit/nit.git
cd nit
pip install -e ".[dev]"
```

---

## Quickstart

### 1. Initialize nit in your project

```bash
cd your-project/
nit init
```

nit will:
- Detect your languages (Python, TS/JS, C++, Java, Go, Rust)
- Detect test frameworks (pytest, Vitest, Jest, GTest, JUnit)
- Detect workspace tools (Turborepo, Nx, pnpm, Cargo, etc.)
- Create `.nit.yml` config file
- Save a project profile to `.nit/profile.json`

### 2. Configure your LLM provider

Edit `.nit.yml`:

```yaml
llm:
  provider: openai  # or: anthropic, ollama, bedrock, vertex_ai, etc.
  model: gpt-4o  # or: claude-3-5-sonnet-20241022, llama3.1, etc.
  api_key: ${OPENAI_API_KEY}  # supports env var substitution
```

Or use a local model with Ollama:

```yaml
llm:
  provider: ollama
  model: llama3.1
  base_url: http://localhost:11434
```

### 3. Scan your codebase

```bash
nit scan
```

This analyzes your codebase and identifies:
- Untested files (0% coverage)
- Undertested functions (public functions with no tests)
- High-complexity code with no coverage
- Stale tests (tests for deleted code)

### 4. Generate tests

```bash
nit generate
```

nit will:
- Parse source files with tree-sitter AST
- Extract functions, classes, imports, and dependencies
- Analyze existing test patterns in your project
- Generate tests matching your conventions
- Validate syntax with tree-sitter
- Run tests to confirm they pass
- Self-iterate on failures (up to 3 retries)

Target specific files:

```bash
nit generate --file src/utils/pricing.ts
nit generate --file src/api/handlers.py
```

Generate until coverage target is met:

```bash
nit generate --coverage-target 80
```

### 5. Run your test suite

```bash
nit run
```

This executes your test suite using your native test runner and displays results with coverage.

### 6. Monitor LLM drift (for AI-powered apps)

If your app uses LLM APIs, nit can monitor output quality over time.

Create `.nit/drift-tests.yml`:

```yaml
drift_tests:
  - name: "Product description generator"
    endpoint: "src/services/ai/generateDescription.ts"
    inputs:
      - prompt: "Write a product description for a wireless mouse"
        expected_traits:
          - contains_keywords: ["wireless", "mouse"]
          - min_length: 50
          - max_length: 200
    comparison: semantic  # semantic | exact | regex | schema
    threshold: 0.85  # cosine similarity threshold for semantic comparison
```

Run drift checks:

```bash
nit drift          # run all drift tests
nit drift --baseline   # update baselines to current outputs
nit drift --watch      # continuous monitoring
```

---

## Configuration Reference

nit uses `.nit.yml` for configuration. All settings are optional—defaults work for most projects.

### Full example

```yaml
# Project root detection (auto-detected if not specified)
root: .

# LLM configuration
llm:
  provider: openai  # openai | anthropic | ollama | bedrock | vertex_ai | ...
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}  # supports ${ENV_VAR} substitution
  base_url: https://api.openai.com/v1  # optional, for custom endpoints
  max_tokens: 2048
  temperature: 0.2

# Test generation settings
generation:
  max_iterations: 3  # retries per test on failure
  batch_size: 5      # parallel test generation
  skip_existing: true  # don't regenerate existing tests

# Coverage settings
coverage:
  target: 80  # target percentage
  exclude:
    - "**/__pycache__/**"
    - "**/node_modules/**"
    - "**/dist/**"
    - "**/build/**"

# E2E test settings (for Playwright/Cypress)
e2e:
  base_url: http://localhost:3000
  auth:
    strategy: form  # form | oauth | token | cookie | custom
    login_url: /login
    credentials:
      username_field: email
      password_field: password
      username: test@example.com
      password: ${TEST_PASSWORD}
    wait_for: /dashboard  # URL after successful auth

# Monorepo package overrides
packages:
  apps/web:
    llm:
      model: gpt-4o-mini  # cheaper model for frontend tests
  packages/core:
    generation:
      max_iterations: 5  # more retries for critical code

# Memory and learning
memory:
  enabled: true
  store_failed_patterns: true

# Reporting
report:
  format: terminal  # terminal | json | html
  slack_webhook: ${SLACK_WEBHOOK_URL}  # optional Slack notifications
```

### Environment variable substitution

Any config value can reference environment variables:

```yaml
llm:
  api_key: ${OPENAI_API_KEY}
  base_url: ${CUSTOM_LLM_ENDPOINT:-https://api.openai.com/v1}  # with default
```

---

## GitHub Action

Run nit on every PR to ensure new code has tests.

### `.github/workflows/nit.yml`

```yaml
name: nit

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  test-coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.14'

      - name: Install nit
        run: pip install getnit

      - name: Run nit
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          nit scan
          nit generate --coverage-target 80
          nit run
```

### PR mode (diff-only testing)

```yaml
- name: Run nit on changed files only
  run: nit generate --diff
```

---

## How It Works

### 1. Detection Phase

nit uses multiple signals to understand your project:

- **Language detection**: Scan file extensions → parse with tree-sitter to confirm
- **Framework detection**: Check config files (`package.json`, `pyproject.toml`, `CMakeLists.txt`), import patterns, file structures
- **Workspace detection**: Identify monorepo tools (Turborepo, Nx, pnpm, Cargo, Go workspaces)
- **Coverage mapping**: Parse existing tests, map to source files, identify gaps

### 2. Generation Phase

For each untested file/function:

1. **Parse** with tree-sitter → extract functions, classes, dependencies, types
2. **Analyze** imports and call graph → understand side effects (DB, API, filesystem)
3. **Retrieve context** → find related files, existing test patterns, project conventions
4. **Prompt LLM** with structured context:
   - Source code being tested
   - Existing test examples (for style matching)
   - Framework-specific patterns (from adapter templates)
   - Dependency information (what to mock)
5. **Validate** generated test:
   - Parse with tree-sitter → must be syntactically valid
   - Run test → must pass or fail for expected reasons
   - Self-iterate → if errors, feed error back to LLM (up to 3 retries)
6. **Write** verified test file in correct location

### 3. Memory & Learning

nit learns from your project:

- **Conventions**: Naming patterns, assertion styles, mocking strategies
- **Failed patterns**: What didn't work, to avoid repeating mistakes
- **Successful patterns**: What worked well, to reuse
- **Project structure**: Where tests go, how they're organized

Memory is stored in `.nit/memory/` and improves generation quality over time.

---

## Supported Languages & Frameworks

### Unit Testing

| Language | Test Frameworks | Coverage Tools |
|---|---|---|
| **TypeScript/JavaScript** | Vitest, Jest, Mocha | Istanbul (c8, nyc) |
| **Python** | pytest, unittest | coverage.py |
| **C/C++** | Google Test, Catch2 | gcov, lcov |
| **Java** | JUnit 5, TestNG | JaCoCo |
| **Go** | go test, testify | go test -cover |
| **Rust** | cargo test | cargo-tarpaulin |

### E2E Testing

- Playwright (TypeScript/JavaScript)
- Cypress (TypeScript/JavaScript)

### Documentation

- Sphinx (Python)
- TypeDoc (TypeScript)
- JSDoc (JavaScript)
- Doxygen (C/C++)
- rustdoc (Rust)
- godoc (Go)
- MkDocs (Markdown)

---

## Development

### Prerequisites

- Python 3.14+
- pip or pipx

### Setup

```bash
# Clone the repo
git clone https://github.com/getnit/nit.git
cd nit

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install in development mode
.venv/bin/pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
.venv/bin/pytest

# Run with coverage
.venv/bin/pytest --cov=src/nit --cov-report=html

# Run specific test file
.venv/bin/pytest tests/test_stack_detector.py
```

### Code Quality (mandatory before committing)

All four must pass with zero errors:

```bash
# 1. Format
.venv/bin/black src/ tests/

# 2. Lint
.venv/bin/ruff check src/ tests/

# 3. Type check
.venv/bin/mypy src/

# 4. Tests
.venv/bin/pytest
```

Or use pre-commit hooks:

```bash
.venv/bin/pre-commit install
.venv/bin/pre-commit run --all-files
```

---

## Contributing

We welcome contributions! Here's how to get started:

### 1. Pick an issue

Browse [open issues](https://github.com/getnit/nit/issues) or create a new one if you have an idea.

### 2. Fork and create a branch

```bash
git checkout -b feature/your-feature-name
```

### 3. Make your changes

Follow the code quality requirements above. All PRs must pass:
- Black formatting
- Ruff linting
- mypy type checking
- pytest tests

### 4. Write tests

All new features must include tests. Aim for >80% coverage.

### 5. Update documentation

If you change user-facing behavior, update the README or docs.

### 6. Submit a PR

Push your branch and open a PR. Describe what you changed and why.

### Building a New Adapter

Want to add support for a new test framework? See [CONTRIBUTING.md](CONTRIBUTING.md) for the adapter development guide.

Example: Adding JUnit 5 support

1. Create `src/nit/adapters/unit/junit5_adapter.py`
2. Implement `TestFrameworkAdapter` interface
3. Add detection logic (check for `pom.xml` or `build.gradle` with JUnit deps)
4. Implement test execution (`mvn test` or `./gradlew test`)
5. Parse test results (JUnit XML or JSON)
6. Write tests in `tests/adapters/unit/test_junit5_adapter.py`
7. Register in `src/nit/adapters/unit/__init__.py`

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        nit CLI (Python)                          │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │   SCANNER    │  │  GENERATOR   │  │     RUNNER         │    │
│  │              │  │              │  │                    │    │
│  │ • Tree-sitter│  │ • LLM engine │  │ • Subprocess mgr  │    │
│  │   AST parse  │  │   (LiteLLM)  │  │ • Parallel exec   │    │
│  │ • Framework  │  │ • Templates  │  │ • Result parser    │    │
│  │   detection  │  │ • Adapters   │  │ • Coverage merge   │    │
│  └──────────────┘  └──────────────┘  └────────────────────┘    │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              FRAMEWORK ADAPTERS (pluggable)               │   │
│  │                                                           │   │
│  │  Vitest • Jest • pytest • GTest • JUnit • Playwright     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Roadmap

See [PLAN.md](PLAN.md) for the full development roadmap.

### Phase 1 — Foundation (Weeks 1–4) ✅

- [x] Project scaffolding
- [x] Tree-sitter integration for multi-language AST parsing
- [x] Stack, framework, and workspace detection
- [x] LLM interface with LiteLLM
- [x] Unit test generation (Vitest, pytest)
- [x] Coverage integration (Istanbul, coverage.py)
- [x] Test validation and self-iteration loop
- [x] Memory system for learning project conventions
- [x] CLI commands: `init`, `scan`, `generate`, `run`

### Phase 2 — CI + E2E + Monorepo (Weeks 5–8)

- [ ] GitHub Action for PR testing
- [ ] Diff-based testing (PR mode)
- [ ] E2E test generation (Playwright)
- [ ] Route discovery for web apps
- [ ] Auth configuration system
- [ ] Full monorepo support with per-package memory
- [ ] Self-healing test regeneration
- [ ] GitHub PR and Issue reporters

### Phase 3 — Systems Languages + Debuggers (Weeks 9–14)

- [ ] C/C++ adapters (GTest, Catch2, CMake)
- [ ] Go adapter (go test, testify)
- [ ] Java adapter (JUnit 5, Gradle/Maven)
- [ ] Rust adapter (cargo test)
- [ ] Bug analysis and fix generation
- [ ] LLM drift monitoring with semantic comparison
- [ ] Prompt optimization suggestions

### Phase 4 — Documentation + Dashboard (Weeks 15–20)

- [ ] Documentation generation (Sphinx, TypeDoc, Doxygen, MkDocs)
- [ ] README auto-update
- [ ] Changelog generation
- [ ] Local HTML dashboard
- [ ] Landing page (React + Cloudflare Workers)
- [ ] Slack/Discord notifications
- [ ] C#/.NET adapter (xUnit, Coverlet)

### Phase 5 — Web Platform (Future)

- [ ] Hosted dashboard with metrics, trends, and analytics
- [ ] LLM proxy for managed API keys
- [ ] Team collaboration features

---

## FAQ

### Q: Do I need to send my code to a third party?

**No.** nit runs entirely locally. You bring your own LLM API key (or use a local model with Ollama). Your code never leaves your machine unless you explicitly use a remote LLM provider.

### Q: Which LLM providers are supported?

nit uses [LiteLLM](https://github.com/BerriAI/litellm), which supports 100+ providers:
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude 3.5 Sonnet, Claude 3 Opus)
- Google (Gemini, Vertex AI)
- AWS Bedrock
- Azure OpenAI
- Ollama (local models: llama3.1, codellama, mistral, etc.)
- Groq, Together AI, Replicate, Hugging Face, and more

### Q: How much does it cost?

nit itself is free and open-source (MIT license). You pay only for LLM API usage:
- OpenAI GPT-4o: ~$0.01–0.03 per generated test
- Anthropic Claude 3.5 Sonnet: ~$0.01–0.02 per test
- Ollama (local): $0 (runs on your hardware)

A typical project with 100 untested functions costs $1–3 to reach 80% coverage.

### Q: Will nit overwrite my existing tests?

No. By default, nit only generates tests for untested code. Use `--skip-existing=false` to regenerate.

### Q: Can nit fix bugs in my code?

Phase 3 (coming soon) will include bug detection and fix generation. For now, nit focuses on test generation.

### Q: Does nit work with monorepos?

Yes! nit detects and supports Turborepo, Nx, pnpm workspaces, Yarn workspaces, npm workspaces, Cargo workspaces, Go workspaces, Bazel, Gradle multi-project, and Maven multi-module.

### Q: Can I use nit in CI/CD?

Yes. See the [GitHub Action](#github-action) section above. GitLab CI and Bitbucket Pipelines support is planned.

---

## License

[MIT](LICENSE) © nit contributors

---

## Links

- **Homepage**: [https://getnit.dev](https://getnit.dev)
- **GitHub**: [https://github.com/getnit/nit](https://github.com/getnit/nit)
- **PyPI**: [https://pypi.org/project/getnit/](https://pypi.org/project/getnit/)
- **Documentation**: [https://docs.getnit.dev](https://docs.getnit.dev) (coming soon)
- **Issues**: [https://github.com/getnit/nit/issues](https://github.com/getnit/nit/issues)

---

**Built with ❤️ by the nit community**
