"""Tests for E2E authentication configuration."""

# ruff: noqa: S105, S106, S108
# S105: Hardcoded passwords (test values only)
# S106: Hardcoded passwords in function arguments (test values only)
# S108: Insecure temp file usage (test paths only)

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nit.adapters.e2e.auth import (
    AuthContext,
    CookieAuthStrategy,
    CustomAuthStrategy,
    FormAuthStrategy,
    OAuthAuthStrategy,
    TokenAuthStrategy,
    get_auth_strategy,
)
from nit.config import AuthConfig, load_config, validate_auth_config


class TestAuthConfigParsing:
    """Test authentication configuration parsing from YAML."""

    def test_form_auth_config(self, tmp_path: Path) -> None:
        """Test parsing form-based auth configuration."""
        config_yaml = """  # noqa: S105
e2e:
  enabled: true
  base_url: http://localhost:3000
  auth:
    strategy: form
    login_url: /login
    username: test@example.com
    password: ${TEST_PASSWORD}
    success_indicator: /dashboard
    timeout: 15000
"""
        config_file = tmp_path / ".nit.yml"
        config_file.write_text(config_yaml)

        config = load_config(tmp_path)

        assert config.e2e.enabled is True
        assert config.e2e.base_url == "http://localhost:3000"
        assert config.e2e.auth.strategy == "form"
        assert config.e2e.auth.login_url == "/login"
        assert config.e2e.auth.username == "test@example.com"
        assert config.e2e.auth.password == ""  # Env var not set
        assert config.e2e.auth.success_indicator == "/dashboard"
        assert config.e2e.auth.timeout == 15000

    def test_token_auth_config(self, tmp_path: Path) -> None:
        """Test parsing token-based auth configuration."""
        config_yaml = """
e2e:
  auth:
    strategy: token
    token: ${AUTH_TOKEN}
    token_header: X-API-Key
    token_prefix: ""
"""
        config_file = tmp_path / ".nit.yml"
        config_file.write_text(config_yaml)

        config = load_config(tmp_path)

        assert config.e2e.auth.strategy == "token"
        assert config.e2e.auth.token == ""  # Env var not set
        assert config.e2e.auth.auth_header_name == "X-API-Key"
        assert config.e2e.auth.auth_prefix == ""

    def test_cookie_auth_config(self, tmp_path: Path) -> None:
        """Test parsing cookie-based auth configuration."""
        config_yaml = """
e2e:
  auth:
    strategy: cookie
    cookie_name: session_id
    cookie_value: ${SESSION_COOKIE}
"""
        config_file = tmp_path / ".nit.yml"
        config_file.write_text(config_yaml)

        config = load_config(tmp_path)

        assert config.e2e.auth.strategy == "cookie"
        assert config.e2e.auth.cookie_name == "session_id"
        assert config.e2e.auth.cookie_value == ""  # Env var not set

    def test_oauth_auth_config(self, tmp_path: Path) -> None:
        """Test parsing OAuth auth configuration."""
        config_yaml = """
e2e:
  auth:
    strategy: oauth
    token: ${OAUTH_TOKEN}
"""
        config_file = tmp_path / ".nit.yml"
        config_file.write_text(config_yaml)

        config = load_config(tmp_path)

        assert config.e2e.auth.strategy == "oauth"
        assert config.e2e.auth.token == ""  # Env var not set

    def test_custom_auth_config(self, tmp_path: Path) -> None:
        """Test parsing custom auth configuration."""
        config_yaml = """
e2e:
  auth:
    strategy: custom
    custom_script: scripts/auth-setup.sh
"""
        config_file = tmp_path / ".nit.yml"
        config_file.write_text(config_yaml)

        config = load_config(tmp_path)

        assert config.e2e.auth.strategy == "custom"
        assert config.e2e.auth.custom_script == "scripts/auth-setup.sh"

    def test_package_specific_auth_config(self, tmp_path: Path) -> None:
        """Test per-package auth configuration overrides."""
        config_yaml = """
e2e:
  enabled: false
  auth:
    strategy: token

packages:
  apps/web:
    e2e:
      enabled: true
      base_url: http://localhost:3000
      auth:
        strategy: form
        login_url: /auth/login
        username: admin@test.com
        password: test123
"""
        config_file = tmp_path / ".nit.yml"
        config_file.write_text(config_yaml)

        config = load_config(tmp_path)

        # Global config
        assert config.e2e.enabled is False
        assert config.e2e.auth.strategy == "token"

        # Package-specific config
        web_config = config.get_package_e2e_config("apps/web")
        assert web_config.enabled is True
        assert web_config.base_url == "http://localhost:3000"
        assert web_config.auth.strategy == "form"
        assert web_config.auth.login_url == "/auth/login"
        assert web_config.auth.username == "admin@test.com"
        assert web_config.auth.password == "test123"

    def test_credentials_nested_format(self, tmp_path: Path) -> None:
        """Test parsing auth config with credentials nested under 'credentials' key."""
        config_yaml = """
e2e:
  auth:
    strategy: form
    login_url: /login
    credentials:
      username: user@test.com
      password: secret
"""
        config_file = tmp_path / ".nit.yml"
        config_file.write_text(config_yaml)

        config = load_config(tmp_path)

        assert config.e2e.auth.username == "user@test.com"
        assert config.e2e.auth.password == "secret"


class TestAuthConfigValidation:
    """Test authentication configuration validation."""

    def test_valid_form_auth(self) -> None:
        """Test validation of valid form auth config."""
        auth = AuthConfig(
            strategy="form",
            login_url="/login",
            username="test@example.com",
            password="secret",
        )

        errors = validate_auth_config(auth)
        assert len(errors) == 0

    def test_invalid_strategy(self) -> None:
        """Test validation with invalid strategy."""
        auth = AuthConfig(strategy="invalid")

        errors = validate_auth_config(auth)
        assert len(errors) == 1
        assert "must be one of" in errors[0]

    def test_form_auth_missing_login_url(self) -> None:
        """Test validation of form auth without login URL."""
        auth = AuthConfig(
            strategy="form",
            username="test@example.com",
            password="secret",
        )

        errors = validate_auth_config(auth)
        assert any("login_url is required" in e for e in errors)

    def test_form_auth_missing_credentials(self) -> None:
        """Test validation of form auth without credentials."""
        auth = AuthConfig(
            strategy="form",
            login_url="/login",
        )

        errors = validate_auth_config(auth)
        assert any("username and" in e and "password are required" in e for e in errors)

    def test_token_auth_missing_token(self) -> None:
        """Test validation of token auth without token."""
        auth = AuthConfig(strategy="token")

        errors = validate_auth_config(auth)
        assert any("token is required" in e for e in errors)

    def test_cookie_auth_missing_fields(self) -> None:
        """Test validation of cookie auth without required fields."""
        auth = AuthConfig(strategy="cookie")

        errors = validate_auth_config(auth)
        assert any("cookie_name and" in e and "cookie_value are required" in e for e in errors)

    def test_custom_auth_missing_script(self) -> None:
        """Test validation of custom auth without script."""
        auth = AuthConfig(strategy="custom")

        errors = validate_auth_config(auth)
        assert any("custom_script is required" in e for e in errors)

    def test_timeout_too_small(self) -> None:
        """Test validation with timeout too small."""
        auth = AuthConfig(
            strategy="form",
            login_url="/login",
            username="user",
            password="pass",
            timeout=500,
        )

        errors = validate_auth_config(auth)
        assert any("timeout should be at least 1000ms" in e for e in errors)


class TestAuthStrategies:
    """Test authentication strategy implementations."""

    def test_get_form_strategy(self) -> None:
        """Test getting form auth strategy."""
        config = AuthConfig(strategy="form")
        strategy = get_auth_strategy(config)
        assert isinstance(strategy, FormAuthStrategy)

    def test_get_token_strategy(self) -> None:
        """Test getting token auth strategy."""
        config = AuthConfig(strategy="token")
        strategy = get_auth_strategy(config)
        assert isinstance(strategy, TokenAuthStrategy)

    def test_get_cookie_strategy(self) -> None:
        """Test getting cookie auth strategy."""
        config = AuthConfig(strategy="cookie")
        strategy = get_auth_strategy(config)
        assert isinstance(strategy, CookieAuthStrategy)

    def test_get_oauth_strategy(self) -> None:
        """Test getting OAuth auth strategy."""
        config = AuthConfig(strategy="oauth")
        strategy = get_auth_strategy(config)
        assert isinstance(strategy, OAuthAuthStrategy)

    def test_get_custom_strategy(self) -> None:
        """Test getting custom auth strategy."""
        config = AuthConfig(strategy="custom")
        strategy = get_auth_strategy(config)
        assert isinstance(strategy, CustomAuthStrategy)

    def test_invalid_strategy_raises(self) -> None:
        """Test that invalid strategy raises ValueError."""
        config = AuthConfig(strategy="invalid")
        with pytest.raises(ValueError, match="Invalid auth strategy"):
            get_auth_strategy(config)

    def test_no_strategy_raises(self) -> None:
        """Test that no strategy raises ValueError."""
        config = AuthConfig()
        with pytest.raises(ValueError, match="No authentication strategy configured"):
            get_auth_strategy(config)


class TestFormAuthStrategy:
    """Test form-based authentication strategy."""

    def test_playwright_script_generation(self) -> None:
        """Test Playwright script generation for form auth."""
        config = AuthConfig(
            strategy="form",
            login_url="/auth/login",
            username="test@example.com",
            password="secret123",
            success_indicator="#dashboard",
        )
        context = AuthContext(
            config=config,
            base_url="http://localhost:3000",
            project_root=Path("/tmp/test"),
        )

        strategy = FormAuthStrategy()
        script = strategy.get_playwright_script(context)

        assert 'await page.goto("/auth/login")' in script
        assert 'fill(\'input[name="username"]' in script
        assert '"test@example.com"' in script
        assert 'fill(\'input[name="password"]' in script
        assert '"secret123"' in script
        assert 'waitForSelector("#dashboard")' in script

    def test_playwright_script_with_url_indicator(self) -> None:
        """Test script generation with URL success indicator."""
        config = AuthConfig(
            strategy="form",
            login_url="/login",
            username="user",
            password="pass",
            success_indicator="/dashboard",
        )
        context = AuthContext(
            config=config,
            base_url="http://localhost:3000",
            project_root=Path("/tmp/test"),
        )

        strategy = FormAuthStrategy()
        script = strategy.get_playwright_script(context)

        assert 'waitForURL("/dashboard")' in script


class TestTokenAuthStrategy:
    """Test token-based authentication strategy."""

    async def test_setup_with_bearer_token(self) -> None:
        """Test token auth setup with Bearer prefix."""
        config = AuthConfig(
            strategy="token",
            token="abc123",
            auth_header_name="Authorization",
            auth_prefix="Bearer",
        )
        context = AuthContext(
            config=config,
            base_url="http://localhost:3000",
            project_root=Path("/tmp/test"),
        )

        strategy = TokenAuthStrategy()
        options = await strategy.setup(context)

        assert "extra_http_headers" in options
        assert options["extra_http_headers"]["Authorization"] == "Bearer abc123"

    async def test_setup_without_prefix(self) -> None:
        """Test token auth setup without prefix."""
        config = AuthConfig(
            strategy="token",
            token="xyz789",
            auth_header_name="X-API-Key",
            auth_prefix="",
        )
        context = AuthContext(
            config=config,
            base_url="http://localhost:3000",
            project_root=Path("/tmp/test"),
        )

        strategy = TokenAuthStrategy()
        options = await strategy.setup(context)

        assert options["extra_http_headers"]["X-API-Key"] == "xyz789"


class TestCookieAuthStrategy:
    """Test cookie-based authentication strategy."""

    async def test_setup(self) -> None:
        """Test cookie auth setup."""
        config = AuthConfig(
            strategy="cookie",
            cookie_name="session_id",
            cookie_value="abc123xyz",
        )
        context = AuthContext(
            config=config,
            base_url="http://localhost:3000",
            project_root=Path("/tmp/test"),
        )

        strategy = CookieAuthStrategy()
        options = await strategy.setup(context)

        assert "cookies" in options
        assert len(options["cookies"]) == 1
        cookie = options["cookies"][0]
        assert cookie["name"] == "session_id"
        assert cookie["value"] == "abc123xyz"
        assert cookie["domain"] == "localhost"
        assert cookie["path"] == "/"

    def test_domain_extraction(self) -> None:
        """Test domain extraction from various URLs."""
        strategy = CookieAuthStrategy()

        assert strategy._extract_domain("http://localhost:3000") == "localhost"
        assert strategy._extract_domain("https://example.com") == "example.com"
        assert strategy._extract_domain("https://api.example.com/v1") == "api.example.com"


class TestOAuthAuthStrategy:
    """Test OAuth authentication strategy."""

    async def test_setup_with_token(self) -> None:
        """Test OAuth setup with pre-authenticated token."""
        config = AuthConfig(
            strategy="oauth",
            token="oauth_token_123",
            auth_prefix="Bearer",
        )
        context = AuthContext(
            config=config,
            base_url="http://localhost:3000",
            project_root=Path("/tmp/test"),
        )

        strategy = OAuthAuthStrategy()
        options = await strategy.setup(context)

        assert "extra_http_headers" in options
        assert options["extra_http_headers"]["Authorization"] == "Bearer oauth_token_123"

    async def test_setup_with_cookie(self) -> None:
        """Test OAuth setup with session cookie."""
        config = AuthConfig(
            strategy="oauth",
            cookie_name="oauth_session",
            cookie_value="session_abc",
        )
        context = AuthContext(
            config=config,
            base_url="http://localhost:3000",
            project_root=Path("/tmp/test"),
        )

        strategy = OAuthAuthStrategy()
        options = await strategy.setup(context)

        assert "cookies" in options
        assert options["cookies"][0]["name"] == "oauth_session"


class TestCustomAuthStrategy:
    """Test custom authentication strategy."""

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix shell scripts only")
    async def test_setup_with_valid_script(self, tmp_path: Path) -> None:
        """Test custom auth with a valid script."""
        script = tmp_path / "auth-setup.sh"
        script.write_text("#!/bin/bash\necho '{\"cookies\": []}'")
        script.chmod(0o755)

        config = AuthConfig(
            strategy="custom",
            custom_script=str(script.name),
        )
        context = AuthContext(
            config=config,
            base_url="http://localhost:3000",
            project_root=tmp_path,
        )

        strategy = CustomAuthStrategy()
        options = await strategy.setup(context)

        assert "cookies" in options
        assert options["cookies"] == []

    async def test_setup_with_missing_script(self, tmp_path: Path) -> None:
        """Test custom auth with missing script."""
        config = AuthConfig(
            strategy="custom",
            custom_script="nonexistent.sh",
        )
        context = AuthContext(
            config=config,
            base_url="http://localhost:3000",
            project_root=tmp_path,
        )

        strategy = CustomAuthStrategy()
        with pytest.raises(FileNotFoundError, match="Custom auth script not found"):
            await strategy.setup(context)

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix shell scripts only")
    async def test_setup_with_invalid_json(self, tmp_path: Path) -> None:
        """Test custom auth with script returning invalid JSON."""
        script = tmp_path / "auth-setup.sh"
        script.write_text("#!/bin/bash\necho 'not json'")
        script.chmod(0o755)

        config = AuthConfig(
            strategy="custom",
            custom_script=str(script.name),
        )
        context = AuthContext(
            config=config,
            base_url="http://localhost:3000",
            project_root=tmp_path,
        )

        strategy = CustomAuthStrategy()
        with pytest.raises(ValueError, match="not valid JSON"):
            await strategy.setup(context)
