# Watchers

Watchers monitor your project over time and trigger actions when conditions are met.

## Coverage Watcher

Monitors test coverage trends and alerts when coverage drops.

**Capabilities:**

- Tracks coverage over time (per run, per commit)
- Alerts when coverage drops below thresholds
- Optionally auto-generates tests to fill new coverage gaps
- Sends notifications via Slack webhook

**Usage:**

```bash
nit watch --path src/
```

**Configuration:**

```yaml
coverage:
  line_threshold: 80.0
  branch_threshold: 75.0
  function_threshold: 85.0
report:
  slack_webhook: https://hooks.slack.com/services/...
```

---

## Drift Watcher

Detects code drift — behavioral changes between runs that might indicate regressions.

**Capabilities:**

- Saves baseline snapshots of code behavior
- Compares current state against baselines
- Identifies:
    - Removed tests
    - Changed function signatures
    - Modified return types
    - Behavioral divergence
- Generates drift reports

**Usage:**

```bash
nit drift
```

**How baselines work:**

Baselines are stored in `.nit/memory/drift_baselines.json`. The first run creates a baseline. Subsequent runs compare against the latest baseline.

See [Drift Detection](../advanced/drift-detection.md) for details.

---

## Schedule Watcher

Manages scheduled monitoring tasks.

**Capabilities:**

- Detects optimal check intervals based on project activity
- Triggers coverage checks and drift detection on schedule
- Integrates with CI cron jobs for automated monitoring
