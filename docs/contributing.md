# Contributing

## Development setup

```bash
git clone https://github.com/getnit-dev/nit.git
cd nit
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quality gates

All four must pass before submitting a PR:

```bash
# 1. Format
.venv/bin/black src/ tests/

# 2. Lint
.venv/bin/ruff check src/ tests/

# 3. Type check
.venv/bin/mypy src/ tests/

# 4. Tests
.venv/bin/pytest
```

## Code quality rules

- Never add `# noqa`, `# type: ignore`, or any inline suppression — fix the underlying code
- Never add `per-file-ignores` or tool overrides to silence new warnings
- Use `TYPE_CHECKING` guards for imports only needed by type annotations
- Prefer list comprehensions and `extend()` over append-in-a-loop patterns

## Project structure

```
src/nit/
  adapters/         # Framework adapters (unit, coverage, e2e, docs)
  agents/           # Agent implementations
    analyzers/      # Code, coverage, diff, risk, route analysis
    builders/       # Test and doc generation
    debuggers/      # Root cause, fix gen, verification
    reporters/      # GitHub, Slack, terminal, dashboard
    watchers/       # Coverage, drift, schedule monitoring
    detectors/      # Framework, language, workspace detection
    pipelines/      # Multi-step workflows
    healers/        # Self-healing for test failures
  llm/              # LLM engine, adapters, prompts
  memory/           # Pattern memory, analytics
  models/           # Data models
  parsing/          # Tree-sitter code parsing
  sharding/         # Parallel execution
  telemetry/        # Sentry integration
  utils/            # Git, platform client, changelog, etc.
  cli.py            # CLI entry point
  config.py         # Configuration parsing

tests/              # Test files (mirrors source structure)
docs/               # Documentation (MkDocs)
```

## Naming conventions

- **Adapter files** use the `_adapter` suffix: `vitest_adapter.py`, `pytest_adapter.py`
- **Prompt files** use the `_prompt` suffix: `pytest_prompt.py`
- **Test files** mirror source names: `test_vitest_adapter.py`, `test_pytest_adapter.py`

## Building docs

```bash
pip install -e ".[docs]"
mkdocs serve       # Local preview at http://localhost:8000
mkdocs build       # Build static site to site/
```

## Adding a new adapter

1. Create the adapter file in the appropriate package (e.g., `src/nit/adapters/unit/myframework_adapter.py`)
2. Implement the `TestFrameworkAdapter` or `DocFrameworkAdapter` base class
3. Add detection signals and test patterns
4. Create a corresponding test file (e.g., `tests/test_myframework_adapter.py`)
5. Run all quality gates

See [Custom Adapters](advanced/custom-adapters.md) for the full guide.
