# Drift Detection

Drift detection identifies behavioral changes in your code between runs, helping catch regressions that tests alone might miss.

## What drift detection tracks

| Signal | Description |
|--------|-------------|
| **Removed tests** | Tests that existed in the baseline but are now missing |
| **Changed signatures** | Function signatures that have changed |
| **Modified return types** | Functions whose return types have changed |
| **Behavioral divergence** | Code that behaves differently from its documented or tested behavior |
| **New untested code** | Code added since the baseline with no test coverage |

## Usage

```bash
# Run drift detection
nit drift

# Output as JSON
nit drift --format json
```

## How baselines work

1. **First run:** nit creates a baseline snapshot stored in `.nit/memory/drift_baselines.json`
2. **Subsequent runs:** nit compares the current code against the latest baseline
3. **Drift report:** differences are flagged with severity levels

## Baseline storage

Baselines are stored locally in `.nit/memory/drift_baselines.json` and include:

- Function signatures and their locations
- Test file mappings
- Coverage snapshots
- Code structure hashes

## Drift alerts

When drift is detected, nit can:

- **Terminal output:** display drift report in the terminal
- **Slack notification:** send an alert via webhook (see [Slack Integration](../integrations/slack.md))
- **GitHub comment:** post drift findings on a PR
- **Platform upload:** send drift data to the nit platform dashboard

## CI integration

Add drift checks to your CI pipeline:

```yaml
name: Drift check
on:
  push:
    branches: [main]

jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: getnit-dev/nit@v1
        with:
          mode: drift
          llm_provider: openai
          llm_api_key: ${{ secrets.OPENAI_API_KEY }}
```

## Drift comparator

The drift comparator analyzes differences between baseline and current state:

- **Structural changes** — added/removed/renamed functions
- **Semantic changes** — behavior changes detected via LLM analysis
- **Coverage changes** — coverage increases or decreases

Each change is classified by risk level (low, medium, high) based on the nature and scope of the change.
