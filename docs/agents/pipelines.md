# Pipelines

Pipelines orchestrate multiple agents into end-to-end workflows.

## Pick Pipeline

The `pick` command runs nit's flagship pipeline — a multi-step workflow that handles the full testing lifecycle.

### Stages

```
1. Framework Detection
       │
2. Bug Analysis
       │
3. Risk Assessment
       │
4. Coverage Analysis
       │
5. Root Cause Analysis (for detected bugs)
       │
6. Fix Generation (when --fix is enabled)
       │
7. Fix Verification
       │
8. Test Generation
       │
9. Test Execution
       │
10. Report Generation
       │
11. GitHub Integration (PRs, issues)
```

### Usage

```bash
# Basic pick — detect, analyze, generate, test
nit pick

# Full pipeline with fixes and GitHub integration
nit pick --fix --pr --create-issues

# Target a specific file
nit pick --file src/myapp/auth.py

# Target a specific test type
nit pick --type unit

# Set coverage target
nit pick --coverage-target 90
```

### Configuration

```yaml
pipeline:
  max_fix_loops: 1    # Max fix-rerun iterations per bug

git:
  auto_commit: false   # Auto-commit generated tests
  auto_pr: false       # Auto-create PRs
  create_issues: false # Auto-create GitHub issues
  create_fix_prs: false # Create PRs for fixes
```

### Output

The pick pipeline produces a `PickPipelineResult` containing:

| Field | Description |
|-------|-------------|
| `success` | Whether the pipeline completed successfully |
| `tests_run` | Total tests executed |
| `tests_passed` | Tests that passed |
| `tests_failed` | Tests that failed |
| `tests_errors` | Tests with errors |
| `bugs_found` | List of detected bugs |
| `fixes_applied` | List of applied fixes |
| `errors` | List of pipeline errors |

### CI mode

In CI mode (`--ci` flag), the pick pipeline:

- Outputs JSON for machine parsing
- Uses non-interactive prompts
- Sets appropriate exit codes
- Supports sharding for parallel execution

```bash
nit --ci pick --format json
```

### Sharded execution

For large projects, split the pick pipeline across parallel CI jobs:

```bash
# Job 1 of 4
nit pick --shard-index 0 --shard-count 4 --shard-output .nit/shard-0.json

# Job 2 of 4
nit pick --shard-index 1 --shard-count 4 --shard-output .nit/shard-1.json

# ... then combine
nit combine --path .nit/ --output .nit/combined.json
```

See [Sharding](../ci/sharding.md) for full CI examples.
