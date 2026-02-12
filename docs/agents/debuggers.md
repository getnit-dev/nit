# Debuggers

Debugger agents find root causes, generate fixes, and verify that fixes work.

## Root Cause Analyzer

Analyzes test failures and bug reports to identify the underlying cause.

**Process:**

1. Receives a bug report or test failure
2. Gathers context: source code, stack trace, related tests, git history
3. Sends context to the LLM for root cause analysis
4. Returns a structured diagnosis with location, cause, and suggested fix

**Output includes:**

- File and line number of the root cause
- Explanation of why the bug occurs
- Suggested fix approach
- Confidence level

---

## Fix Generator

Generates code patches to fix detected bugs.

**Process:**

1. Receives the root cause analysis
2. Reads the affected source file and surrounding context
3. Generates a minimal diff/patch using the LLM
4. Outputs the fix as a code change

**Configuration:**

```yaml
pipeline:
  max_fix_loops: 1  # How many fix attempts per bug
```

---

## Fix Verifier

Verifies that generated fixes actually resolve the problem without introducing regressions.

**Process:**

1. Applies the generated fix
2. Runs the relevant test suite
3. Checks that the original bug is resolved
4. Checks that no existing tests are broken
5. Reports verification result (pass/fail/regression)

---

## Bug Verifier

Verifies that a detected bug is real and reproducible.

**Process:**

1. Receives a bug report from the Bug Analyzer
2. Attempts to reproduce the bug
3. Confirms or refutes the finding
4. Assigns a confidence score

---

## Debug workflow

The `nit debug` command orchestrates these agents:

```bash
# Analyze and fix bugs in a file
nit debug --file src/myapp/auth.py --fix
```

Pipeline:

```
Bug Analyzer → Root Cause → Fix Generator → Fix Verifier
```

In the `pick` pipeline with `--fix`, this same workflow runs automatically for all detected bugs.
