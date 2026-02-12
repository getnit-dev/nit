# E2E Testing

nit supports end-to-end test generation using Playwright.

## Playwright adapter

**Detection signals:**

- `playwright.config.ts` or `playwright.config.js`
- `package.json` with `@playwright/test` dependency

**Test patterns:** `*.spec.ts`, `*.spec.js` in E2E test directories

## Configuration

Enable E2E testing in `.nit.yml`:

```yaml
e2e:
  enabled: true
  base_url: http://localhost:3000
```

## Authentication strategies

nit supports five authentication strategies for E2E tests that require login:

### Form-based auth

Fills out a login form and submits it.

```yaml
e2e:
  enabled: true
  base_url: http://localhost:3000
  auth:
    strategy: form
    login_url: http://localhost:3000/login
    username: ${E2E_USERNAME}
    password: ${E2E_PASSWORD}
    success_indicator: "[data-testid='dashboard']"
```

| Field | Description |
|-------|-------------|
| `login_url` | URL of the login page |
| `username` | Username or email |
| `password` | Password |
| `success_indicator` | CSS selector or URL pattern confirming successful login |

### Token-based auth

Injects a bearer token or API key into request headers.

```yaml
e2e:
  auth:
    strategy: token
    token: ${API_TOKEN}
    auth_header_name: Authorization
    auth_prefix: Bearer
```

### OAuth

Uses OAuth flow for authentication.

```yaml
e2e:
  auth:
    strategy: oauth
    login_url: https://auth.example.com/authorize
    username: ${OAUTH_USER}
    password: ${OAUTH_PASSWORD}
```

### Cookie-based auth

Sets a specific cookie for authenticated requests.

```yaml
e2e:
  auth:
    strategy: cookie
    cookie_name: session_id
    cookie_value: ${SESSION_COOKIE}
```

### Custom auth

Uses a custom script for complex authentication flows.

```yaml
e2e:
  auth:
    strategy: custom
    custom_script: ./scripts/auth-setup.js
    timeout: 60000
```

The custom script receives a Playwright `page` object and should complete the authentication flow.

## Route discovery

nit includes a [Route Discovery Agent](../agents/analyzers.md#route-discovery) that scans your source code for API endpoints and page routes. Discovered routes inform E2E test generation, ensuring coverage of all application entry points.

Supported web frameworks for route discovery:

- **Python:** FastAPI, Flask, Django
- **JavaScript/TypeScript:** Express, Next.js
- **Go:** net/http, gorilla/mux

## Per-package E2E config (monorepos)

In monorepos, configure E2E settings per package:

```yaml
packages:
  packages/web-app:
    e2e:
      enabled: true
      base_url: http://localhost:3000
      auth:
        strategy: form
        login_url: http://localhost:3000/login
        username: ${WEB_APP_USER}
        password: ${WEB_APP_PASSWORD}

  packages/admin-panel:
    e2e:
      enabled: true
      base_url: http://localhost:4000
      auth:
        strategy: token
        token: ${ADMIN_TOKEN}
```
