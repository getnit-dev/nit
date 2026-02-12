# Config Commands

The `config` command group manages your `.nit.yml` configuration file.

## config set

Set a configuration value using dotted key notation.

```bash
nit config set <key> <value>
```

**Examples:**

```bash
# Set LLM model
nit config set llm.model gpt-4o

# Set coverage threshold
nit config set coverage.line_threshold 90

# Set Slack webhook
nit config set report.slack_webhook https://hooks.slack.com/services/...

# Set nested E2E auth
nit config set e2e.auth.strategy form
nit config set e2e.auth.login_url http://localhost:3000/login
```

Dotted keys map directly to the YAML structure. For example, `llm.model` sets the `model` field under the `llm` section.

---

## config show

Display the current configuration with sensitive values masked.

```bash
nit config show
```

Sensitive fields (`api_key`, `password`, `token`, `slack_webhook`, `dsn`, etc.) are automatically masked in the output. For example:

```
llm:
  provider: openai
  model: gpt-4o
  api_key: sk-p...Bx4q
```

---

## config validate

Validate the `.nit.yml` configuration against the expected schema.

```bash
nit config validate
```

Checks include:

- Required fields are present
- Values are within valid ranges (e.g., `temperature` between 0 and 2.0)
- Mode-specific requirements (e.g., `cli_command` required when `mode: cli`)
- Platform configuration consistency
- Coverage thresholds between 0 and 100
- Sentry configuration validity
- Auth configuration completeness per strategy

A zero exit code means the configuration is valid. Non-zero exit code with error messages indicates problems.
