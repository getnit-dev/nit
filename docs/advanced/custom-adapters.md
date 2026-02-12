# Custom Adapters

nit's adapter system is extensible. You can create custom adapters for frameworks not yet supported and register them via Python entry points.

## Adapter types

| Type | Base class | Package |
|------|-----------|---------|
| Unit test | `TestFrameworkAdapter` | `nit.adapters.unit` |
| E2E test | `TestFrameworkAdapter` | `nit.adapters.e2e` |
| Documentation | `DocFrameworkAdapter` | `nit.adapters.docs` |

## Creating a custom test adapter

Create a new Python package with an adapter class:

```python
# my_adapter/adapter.py
from pathlib import Path
from nit.adapters.base import TestFrameworkAdapter, RunResult

class MyFrameworkAdapter(TestFrameworkAdapter):
    @property
    def name(self) -> str:
        return "myframework"

    @property
    def language(self) -> str:
        return "python"

    def detect(self, project_root: Path) -> bool:
        """Return True if this framework is used in the project."""
        return (project_root / "myframework.config.json").exists()

    @property
    def test_patterns(self) -> list[str]:
        """Glob patterns for test files."""
        return ["*_spec.py", "spec_*.py"]

    def build_prompt(self, source_code: str, context: dict) -> str:
        """Build the LLM prompt for test generation."""
        return f"""Generate tests for the following code using MyFramework:

{source_code}

Use the `describe`/`it` syntax. Include edge cases."""

    def run_tests(self, project_root: Path, test_files: list[Path]) -> RunResult:
        """Run tests and return results."""
        # Implementation here
        ...

    def validate_syntax(self, test_code: str) -> bool:
        """Validate generated test syntax."""
        # Implementation here
        ...
```

## Registering via entry points

In your package's `pyproject.toml`:

```toml
[project.entry-points."nit.adapters.unit"]
myframework = "my_adapter.adapter:MyFrameworkAdapter"
```

After installing the package, nit automatically discovers and loads your adapter.

## Creating a documentation adapter

```python
from pathlib import Path
from nit.adapters.base import DocFrameworkAdapter

class MyDocAdapter(DocFrameworkAdapter):
    @property
    def name(self) -> str:
        return "mydocs"

    @property
    def language(self) -> str:
        return "python"

    def detect(self, project_root: Path) -> bool:
        return (project_root / "mydocs.yml").exists()

    def build_prompt(self, source_code: str, context: dict) -> str:
        return f"Generate documentation for:\n{source_code}"
```

Register it under `nit.adapters.docs`:

```toml
[project.entry-points."nit.adapters.docs"]
mydocs = "my_adapter.docs:MyDocAdapter"
```

## Entry point groups

| Group | Adapter type |
|-------|-------------|
| `nit.adapters.unit` | Unit/integration test adapters |
| `nit.adapters.e2e` | E2E test adapters |
| `nit.adapters.docs` | Documentation adapters |

## Template adapters

nit includes template adapters that demonstrate common patterns:

- `src/nit/adapters/unit/template_adapter.py` — test adapter template
- `src/nit/adapters/docs/template_adapter.py` — doc adapter template

These are not used in production but serve as reference implementations for adapter developers.

## Adapter discovery order

1. Built-in adapters (scanned from `nit.adapters.*` packages)
2. Entry point adapters (from installed packages)

Built-in adapters take priority — if a built-in and entry point adapter share the same name, the entry point adapter is skipped.
