# CLAUDE.md — Development Notes

## Environment

- Python is managed via `.venv` — always use `.venv/bin/python` for running scripts
- Activate: `source .venv/bin/activate` or use `.venv/bin/python` directly
- Install dev deps: `.venv/bin/pip install -e ".[dev]"`

## Quality Gates (mandatory before finishing any task)

Run all four in this order. All must pass with zero errors.

1. **Format:** `.venv/bin/black src/ tests/`
2. **Lint:** `.venv/bin/ruff check src/ tests/`
3. **Types:** `.venv/bin/mypy src/ tests/`
4. **Tests:** `.venv/bin/pytest`

## Code Quality Rules

- Never add `# noqa`, `# type: ignore`, or any inline suppression to work around lint/type errors. Fix the underlying code instead.
- Never add `per-file-ignores` or tool overrides to silence new warnings. Fix them properly.
- Write clean, idiomatic Python that passes strict ruff and strict mypy out of the box.
- Use `TYPE_CHECKING` guards for imports only needed by type annotations (not at runtime).
- Prefer list comprehensions and `extend()` over append-in-a-loop patterns.

## Project Structure

- Source: `src/nit/`
- Tests: `tests/`
- Config: `pyproject.toml`
- Package name: `getnit` (PyPI), import as `nit`
- CLI entry point: `nit.cli:cli`

## Naming Conventions

- **Adapter files** use the `_adapter` suffix: `vitest_adapter.py`, `pytest_adapter.py`, `gtest_adapter.py`, etc. This avoids shadowing third-party packages (e.g. `pytest`, `coverage`) and keeps naming consistent across all adapters.
- **Prompt files** use a `_prompt` suffix when needed to avoid collisions: `pytest_prompt.py`.
- **Test files** mirror source names: `test_vitest_adapter.py`, `test_pytest_adapter.py`.
