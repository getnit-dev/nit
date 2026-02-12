# Security Analysis

nit includes a built-in security analyzer that scans your source code for common vulnerability patterns. It runs automatically during `nit pick` and combines fast heuristic detection with optional LLM validation for high-precision results.

## How it works

Security analysis uses a two-layer approach:

1. **Heuristic scanning** -- Pattern-based detection using regex rules tuned per language. Each pattern targets a specific vulnerability class (e.g., SQL injection via string formatting) and includes safe-guard patterns that suppress known-safe constructs (e.g., parameterized queries).

2. **LLM validation** -- Medium-confidence findings (0.5--0.8) are sent to the configured LLM for a second opinion. The LLM either confirms or dismisses each finding, reducing false positives. High-confidence findings (>0.8) skip this step.

## Supported vulnerability types

| Type | CWE | Severity | Description |
|------|-----|----------|-------------|
| SQL Injection | CWE-89 | Critical | String formatting/concatenation in SQL queries |
| Command Injection | CWE-78 | Critical | Shell commands with unsanitized user input |
| Path Traversal | CWE-22 | High | File operations with user-controlled paths |
| Cross-Site Scripting (XSS) | CWE-79 | High | Dynamic HTML injection without sanitization |
| Hardcoded Credentials | CWE-798 | High | API keys, tokens, passwords in source code |
| Insecure Deserialization | CWE-502 | High | Deserializing untrusted data (pickle, eval, etc.) |
| Server-Side Request Forgery | CWE-918 | High | HTTP requests with user-controlled URLs |
| Weak Cryptography | CWE-327 | Medium | Use of MD5/SHA1 for security purposes |

## Supported languages

| Language | File extensions |
|----------|----------------|
| Python | `.py` |
| JavaScript/TypeScript | `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs` |
| Java | `.java` |
| Go | `.go` |
| Rust | `.rs` |
| C/C++ | `.c`, `.h`, `.cpp`, `.cc`, `.hpp` |
| C# | `.cs` |

## Configuration

Add a `security` section to your `.nit.yml`:

```yaml
security:
  enabled: true              # Enable/disable security analysis (default: true)
  llm_validation: true       # Use LLM to validate findings (default: true)
  confidence_threshold: 0.7  # Minimum confidence to report (0.0-1.0)
  severity_threshold: medium # Minimum severity: critical, high, medium, low, info
  exclude_patterns:          # Glob patterns to skip
    - "tests/*"
    - "vendor/*"
```

### Options

- **`enabled`** -- Set to `false` to disable security analysis entirely.
- **`llm_validation`** -- When `true`, medium-confidence findings are validated by the LLM. Disable to save LLM tokens or for faster scans.
- **`confidence_threshold`** -- Only report findings with confidence >= this value. Raise to reduce noise, lower for broader coverage.
- **`severity_threshold`** -- Only report findings at or above this severity level.
- **`exclude_patterns`** -- File glob patterns to exclude from scanning.

## Output

Security findings appear in the terminal output after a `nit pick` run:

```
Security Analysis: 3 findings (1 critical, 2 high)
 Sev  | Type              | File            | Line | Confidence
 CRIT | sql_injection     | src/db.py       |   42 | 0.85
 HIGH | credential_leak   | src/config.py   |   15 | 0.85
 HIGH | command_injection | src/runner.py    |   78 | 0.80
```

Each finding includes:
- Vulnerability type and CWE ID
- File path and line number
- Enclosing function name (when available)
- Confidence score
- Description and remediation advice

## GitHub integration

When `--create-issues` is enabled, critical and high-severity security findings are automatically created as GitHub issues with:
- `[Security]` title prefix
- Severity and CWE labels
- Code evidence and remediation steps

## Reducing false positives

The analyzer uses several strategies to minimize noise:

- **Safe-guard patterns** suppress matches when known mitigations are nearby (e.g., parameterized queries near SQL calls, DOMPurify near innerHTML)
- **Context window** checks surrounding lines (3 lines before, 1 after) for mitigation patterns
- **Placeholder detection** skips hardcoded secret findings that look like placeholders (`your-api-key-here`, `changeme`, etc.)
- **Entropy filtering** only flags generic secret assignments when the value has high Shannon entropy
- **Test file exclusion** skips test fixtures and mock data
- **LLM validation** provides a final filter for borderline cases

## Examples

### Detected (true positive)

```python
# SQL injection via f-string
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
```

### Suppressed (safe code)

```python
# Parameterized query -- safe, not flagged
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
```

### Suppressed (safe guard)

```javascript
// DOMPurify sanitization suppresses the innerHTML finding
element.innerHTML = DOMPurify.sanitize(userContent)
```
