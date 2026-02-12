# CLI Overview

nit provides a rich command-line interface built on [Click](https://click.palletsprojects.com/). All commands are available via the `nit` executable.

## Global options

```
nit [OPTIONS] COMMAND [ARGS]...
```

| Option | Description |
|--------|-------------|
| `--version` | Show version and exit |
| `--ci` | Enable CI mode (non-interactive, JSON-friendly output) |
| `--help` | Show help message and exit |

## Command groups

| Command | Description |
|---------|-------------|
| [`init`](commands.md#init) | Initialize `.nit.yml` configuration |
| [`scan`](commands.md#scan) | Detect languages, frameworks, and test coverage |
| [`generate`](commands.md#generate) | Generate tests using AI |
| [`run`](commands.md#run) | Run tests with your project's test runner |
| [`pick`](commands.md#pick) | Full pipeline: scan, analyze, generate, test, report |
| [`analyze`](commands.md#analyze) | Analyze code, coverage, risks, and patterns |
| [`debug`](commands.md#debug) | Debug and fix specific bugs |
| [`report`](commands.md#report) | Generate reports (terminal, HTML, JSON, GitHub) |
| [`drift`](commands.md#drift) | Detect code drift and behavioral changes |
| [`watch`](commands.md#watch) | Monitor coverage trends, auto-generate tests |
| [`docs`](commands.md#docs) | Generate documentation (changelog, README, docstrings) |
| [`combine`](commands.md#combine) | Combine sharded test results |
| [`config`](config-commands.md) | Manage `.nit.yml` configuration |
| [`memory`](memory-commands.md) | View and manage project memory |
