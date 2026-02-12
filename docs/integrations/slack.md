# Slack Integration

nit can send notifications to Slack when critical events occur.

## Setup

1. Create a [Slack Incoming Webhook](https://api.slack.com/messaging/webhooks) for your workspace
2. Add the webhook URL to your configuration:

```yaml
report:
  slack_webhook: ${SLACK_WEBHOOK_URL}
```

!!! tip
    Use environment variable expansion (`${SLACK_WEBHOOK_URL}`) to avoid committing the webhook URL to your repository.

## Notification events

nit sends Slack notifications for:

| Event | When |
|-------|------|
| **Bug discovered** | A new bug is detected during analysis |
| **Coverage drop** | Coverage falls below configured thresholds |
| **Drift alert** | Code drift is detected between runs |

## Message format

Slack messages use [Block Kit](https://api.slack.com/block-kit) for rich formatting:

- **Bug notifications** include severity, file path, function name, and description
- **Coverage alerts** include before/after percentages and affected files
- **Drift alerts** include changed functions and behavioral differences

## Example notification

A bug discovery notification includes:

```
🔴 Bug Detected — high severity
File: src/auth/login.py:42
Function: validate_token()

Null dereference: token.claims accessed without
checking if token is None when JWT validation fails.
```

## Per-environment webhooks

You can use different webhooks for different environments by using environment variables:

```yaml
report:
  slack_webhook: ${SLACK_WEBHOOK_URL}
```

Then set `SLACK_WEBHOOK_URL` differently in CI vs local development.
