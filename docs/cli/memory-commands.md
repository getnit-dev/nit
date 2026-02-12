# Memory Commands

The `memory` command group lets you inspect and manage nit's learned patterns and conventions.

nit builds up memory over time as it generates tests — tracking which patterns work well, which fail, and what conventions your project follows.

## memory show

Display the current project memory.

```bash
nit memory show [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Project path |
| `--package PKG` | Show memory for a specific package |
| `--format FORMAT` | Output format: `terminal`, `json` |

Shows:

- **Known patterns** — test patterns that have worked well, with success counts
- **Failed patterns** — patterns that failed, with failure reasons
- **Conventions** — detected naming styles, assertion preferences, import patterns
- **Generation stats** — historical success/failure rates

---

## memory reset

Clear memory for the project or a specific package.

```bash
nit memory reset [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Project path |
| `--package PKG` | Reset memory for a specific package only |
| `--confirm` | Skip confirmation prompt |

!!! warning
    This permanently deletes learned patterns. nit will need to re-learn your project's conventions from scratch.

---

## memory export

Export memory data as JSON or CSV for analysis.

```bash
nit memory export [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--path PATH` | Project path |
| `--format FORMAT` | Export format: `json`, `csv` |
| `--output PATH` | Output file path |

Useful for debugging memory behavior or migrating patterns between projects.

---

## How memory works

Memory is stored in `.nit/memory/` as JSON files:

- `global_memory.json` — project-wide patterns and conventions
- `packages/<name>/memory.json` — per-package memory (monorepos)

Memory improves test generation quality over time by:

1. **Tracking successful patterns** — when a generated test passes, the pattern is reinforced
2. **Avoiding failed patterns** — when a test fails or is rejected, the pattern is recorded to avoid repeating the same approach
3. **Learning conventions** — nit detects your project's naming conventions, assertion styles, and import patterns
4. **Informing prompts** — memory data is included in LLM prompts to generate tests that match your project's style
