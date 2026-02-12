# GitHub Integration

nit integrates deeply with GitHub for automated PR creation, issue tracking, and PR comments.

## Pull Requests

nit can automatically create PRs with generated tests and bug fixes.

**Enable via CLI:**

```bash
nit pick --pr
```

**Enable via config:**

```yaml
git:
  auto_pr: true
  branch_prefix: "nit/"
  base_branch: main
```

**What the PR includes:**

- Generated test files
- Bug fix patches (when `--fix` is enabled)
- A summary comment with coverage deltas, bugs found, and test results

**Branch naming:**

PRs are created on branches prefixed with the configured `branch_prefix` (default: `nit/`). For example: `nit/add-tests-auth-module`.

---

## Issues

nit can create GitHub issues for detected bugs.

**Enable via CLI:**

```bash
nit pick --create-issues
```

**Enable via config:**

```yaml
git:
  create_issues: true
```

**Issue content includes:**

- Bug description and severity
- File and line number
- Root cause analysis
- Suggested fix approach

---

## Fix PRs

Create separate PRs for each bug fix:

```bash
nit pick --fix --create-fix-prs
```

```yaml
git:
  create_fix_prs: true
```

Each fix gets its own branch and PR, making code review easier.

---

## PR Comments

When running in CI on a pull request, nit can post comments with analysis results directly on the PR.

**Requires:** `GITHUB_TOKEN` environment variable (automatically available in GitHub Actions).

---

## Git configuration

```yaml
git:
  auto_commit: false              # Auto-commit generated files
  auto_pr: false                  # Auto-create PRs
  create_issues: false            # Create issues for bugs
  create_fix_prs: false           # Create PRs for fixes
  branch_prefix: "nit/"           # Branch name prefix
  commit_message_template: ""     # Custom commit message (empty = default)
  base_branch: ""                 # Base branch (empty = auto-detect)
```

## CI setup

For GitHub Actions, see the [GitHub Action](../ci/github-action.md) documentation.

The action requires these permissions:

```yaml
permissions:
  contents: write       # For creating branches and commits
  pull-requests: write  # For creating PRs and comments
  issues: write         # For creating issues
```
