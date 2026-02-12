"""Authentication strategies for E2E tests."""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from pathlib import Path

    from nit.config import AuthConfig


@dataclass
class AuthContext:
    """Context passed to authentication strategies."""

    config: AuthConfig
    """Authentication configuration."""

    base_url: str
    """Base URL for the application."""

    project_root: Path
    """Project root directory."""


class AuthStrategy(ABC):
    """Base class for authentication strategies."""

    @abstractmethod
    async def setup(self, context: AuthContext) -> dict[str, Any]:
        """Set up authentication and return Playwright context options.

        Returns:
            Dictionary of Playwright browser context options (cookies, storage state, etc.)
        """
        ...

    @abstractmethod
    def get_playwright_script(self, context: AuthContext) -> str:
        """Generate Playwright test setup code for this auth strategy.

        Returns:
            JavaScript/TypeScript code to be inserted into test files
        """
        ...


class FormAuthStrategy(AuthStrategy):
    """Form-based authentication (username + password)."""

    async def setup(self, _context: AuthContext) -> dict[str, Any]:
        """Navigate to login page, fill form, and wait for success."""
        # Return empty dict - actual setup happens in the test via the script
        # This allows the test to have full control over the browser instance
        return {}

    def get_playwright_script(self, context: AuthContext) -> str:
        """Generate Playwright login setup code."""
        config = context.config

        indicator = json.dumps(config.success_indicator)
        success_check = (
            f"await page.waitForURL({indicator});"
            if config.success_indicator.startswith(("http://", "https://", "/"))
            else (
                f"await page.waitForSelector({indicator});"
                if config.success_indicator
                else "await page.waitForNavigation();"
            )
        )

        username_selector = 'input[name="username"], input[name="email"], input[type="email"]'
        credential_selector = 'input[name="password"], input[type="password"]'
        submit_selector = (
            'button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")'
        )

        login_url = json.dumps(config.login_url)
        username = json.dumps(config.username)
        password = json.dumps(config.password)

        return f"""
  // Form-based authentication
  await page.goto({login_url});
  await page.fill('{username_selector}', {username});
  await page.fill('{credential_selector}', {password});
  await page.click('{submit_selector}');
  {success_check}
"""


class TokenAuthStrategy(AuthStrategy):
    """Token-based authentication (Bearer token, API key)."""

    async def setup(self, context: AuthContext) -> dict[str, Any]:
        """Inject token into browser context via extraHTTPHeaders."""
        config = context.config

        token_value = f"{config.auth_prefix} {config.token}" if config.auth_prefix else config.token

        return {
            "extra_http_headers": {
                config.auth_header_name: token_value,
            }
        }

    def get_playwright_script(self, context: AuthContext) -> str:
        """Generate Playwright token injection code."""
        config = context.config

        base_url = json.dumps(context.base_url)
        token = json.dumps(config.token)

        return f"""
  // Token-based authentication (injected via extraHTTPHeaders in context setup)
  // Alternatively, inject into localStorage if your app expects it there:
  await page.goto({base_url});
  await page.evaluate((t) => {{
    localStorage.setItem('token', t);
    localStorage.setItem('authToken', t);
  }}, {token});
  await page.reload();
"""


class CookieAuthStrategy(AuthStrategy):
    """Cookie-based authentication."""

    async def setup(self, context: AuthContext) -> dict[str, Any]:
        """Inject authentication cookie into browser context."""
        config = context.config

        return {
            "cookies": [
                {
                    "name": config.cookie_name,
                    "value": config.cookie_value,
                    "domain": self._extract_domain(context.base_url),
                    "path": "/",
                }
            ]
        }

    def get_playwright_script(self, context: AuthContext) -> str:
        """Generate Playwright cookie injection code."""
        config = context.config

        cookie_name = json.dumps(config.cookie_name)
        cookie_value = json.dumps(config.cookie_value)
        base_url = json.dumps(context.base_url)

        return f"""
  // Cookie-based authentication (injected via cookies in context setup)
  await context.addCookies([
    {{
      name: {cookie_name},
      value: {cookie_value},
      domain: new URL({base_url}).hostname,
      path: '/',
    }}
  ]);
  await page.goto({base_url});
"""

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.hostname or "localhost"


class OAuthAuthStrategy(AuthStrategy):
    """OAuth authentication (placeholder for pre-authenticated tokens)."""

    async def setup(self, context: AuthContext) -> dict[str, Any]:
        """Set up OAuth authentication using a pre-authenticated token.

        For OAuth, we assume the token is already obtained and stored in the config.
        """
        config = context.config

        # Treat OAuth like token auth - inject the pre-authenticated token
        if config.token:
            token_value = (
                f"{config.auth_prefix} {config.token}" if config.auth_prefix else config.token
            )
            return {
                "extra_http_headers": {
                    config.auth_header_name: token_value,
                }
            }

        # If no token, assume session cookie approach
        if config.cookie_name and config.cookie_value:
            return {
                "cookies": [
                    {
                        "name": config.cookie_name,
                        "value": config.cookie_value,
                        "domain": CookieAuthStrategy()._extract_domain(context.base_url),
                        "path": "/",
                    }
                ]
            }

        return {}

    def get_playwright_script(self, context: AuthContext) -> str:
        """Generate Playwright OAuth setup code."""
        config = context.config

        if config.token:
            return TokenAuthStrategy().get_playwright_script(context)

        if config.cookie_name and config.cookie_value:
            return CookieAuthStrategy().get_playwright_script(context)

        base_url = json.dumps(context.base_url)
        return f"""
  // OAuth authentication (expects pre-authenticated session)
  // Please configure either token or cookie in .nit.yml
  await page.goto({base_url});
"""


class CustomAuthStrategy(AuthStrategy):
    """Custom authentication via external script."""

    async def setup(self, context: AuthContext) -> dict[str, Any]:
        """Run custom authentication script and return context options."""
        config = context.config

        if not config.custom_script:
            return {}

        script_path = (context.project_root / config.custom_script).resolve()
        try:
            script_path.relative_to(context.project_root.resolve())
        except ValueError:
            msg = f"Custom auth script must be inside project root: {config.custom_script}"
            raise ValueError(msg) from None

        if not script_path.exists():
            msg = f"Custom auth script not found: {script_path}"
            raise FileNotFoundError(msg)

        # Execute custom script - it should output JSON with context options
        try:
            result = subprocess.run(
                [str(script_path)],
                capture_output=True,
                text=True,
                check=True,
                cwd=context.project_root,
                timeout=30,
            )

            # Parse output as JSON
            output = json.loads(result.stdout)
            if not isinstance(output, dict):
                msg = "Custom auth script must return a JSON object"
                raise ValueError(msg)
            return output
        except subprocess.CalledProcessError as e:
            msg = f"Custom auth script failed: {e.stderr}"
            raise RuntimeError(msg) from e
        except json.JSONDecodeError as e:
            msg = f"Custom auth script output is not valid JSON: {e}"
            raise ValueError(msg) from e

    def get_playwright_script(self, context: AuthContext) -> str:
        """Generate Playwright custom auth setup code."""
        config = context.config
        base_url = json.dumps(context.base_url)

        return f"""
  // Custom authentication (handled by external script)
  // Script: {config.custom_script}
  await page.goto({base_url});
"""


def get_auth_strategy(config: AuthConfig) -> AuthStrategy:
    """Get the appropriate authentication strategy based on config.

    Args:
        config: Authentication configuration

    Returns:
        An AuthStrategy instance

    Raises:
        ValueError: If strategy is invalid or not configured
    """
    if not config.strategy:
        msg = "No authentication strategy configured"
        raise ValueError(msg)

    strategies: dict[str, type[AuthStrategy]] = {
        "form": FormAuthStrategy,
        "token": TokenAuthStrategy,
        "cookie": CookieAuthStrategy,
        "oauth": OAuthAuthStrategy,
        "custom": CustomAuthStrategy,
    }

    strategy_class = strategies.get(config.strategy.lower())
    if not strategy_class:
        valid = ", ".join(strategies.keys())
        msg = f"Invalid auth strategy: {config.strategy}. Must be one of: {valid}"
        raise ValueError(msg)

    return strategy_class()
