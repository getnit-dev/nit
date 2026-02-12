# Agents Overview

nit uses a multi-agent architecture where specialized agents handle different aspects of testing, analysis, and reporting. Agents communicate through structured `TaskInput` and `TaskOutput` dataclasses.

## Agent categories

| Category | Purpose | Agents |
|----------|---------|--------|
| [Analyzers](analyzers.md) | Examine code, coverage, diffs, risk, routes, bugs | 7 agents |
| [Builders](builders.md) | Generate tests and documentation | 5 agents |
| [Debuggers](debuggers.md) | Find root causes and generate fixes | 4 agents |
| [Watchers](watchers.md) | Monitor trends and trigger actions | 3 agents |
| [Pipelines](pipelines.md) | Orchestrate multi-step workflows | 1 pipeline |

## Architecture

```
┌─────────────┐
│  CLI / CI   │
└──────┬──────┘
       │
┌──────▼──────┐     ┌────────────┐
│  Detectors  │────▶│  Profile   │
└──────┬──────┘     └────────────┘
       │
┌──────▼──────┐     ┌────────────┐
│  Analyzers  │────▶│  Gaps /    │
│             │     │  Risks     │
└──────┬──────┘     └────────────┘
       │
┌──────▼──────┐     ┌────────────┐
│  Builders   │────▶│  Tests /   │
│             │     │  Docs      │
└──────┬──────┘     └────────────┘
       │
┌──────▼──────┐     ┌────────────┐
│  Reporters  │────▶│  GitHub /  │
│             │     │  Slack /   │
└─────────────┘     │  Dashboard │
                    └────────────┘
```

## Detectors

Detectors run before agents to build a project profile:

- **FrameworkDetector** — identifies test frameworks (pytest, Vitest, Go test, etc.)
- **LanguageDetector** — detects programming languages in the project
- **WorkspaceDetector** — identifies monorepo structure and package boundaries

## Task lifecycle

Each agent follows a standard lifecycle:

1. **PENDING** — task is queued
2. **RUNNING** — agent is processing
3. **COMPLETED** — task finished successfully
4. **FAILED** — task encountered an error

Agents can be composed into pipelines (see [Pipelines](pipelines.md)) for multi-step workflows.
