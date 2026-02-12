"""Drift test specification and execution (tasks 3.11.2, 3.11.3).

Defines the drift test YAML spec and implements execution for different endpoint types:
- function: import and call Python/JS function
- http: send HTTP request
- cli: run CLI command
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import httpx
import yaml

from nit.agents.watchers.drift_comparator import ComparisonType

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class EndpointType(Enum):
    """Type of endpoint to test."""

    FUNCTION = "function"
    HTTP = "http"
    CLI = "cli"


@dataclass
class DriftTestSpec:
    """Specification for a single drift test (task 3.11.2)."""

    id: str
    name: str
    endpoint_type: EndpointType
    comparison_type: ComparisonType
    endpoint_config: dict[str, Any] = field(default_factory=dict)
    comparison_config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    timeout: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)


class DriftTestParser:
    """Parse drift test YAML specification (task 3.11.2)."""

    @staticmethod
    def parse_file(file_path: Path) -> list[DriftTestSpec]:
        """Parse drift tests from YAML file.

        Args:
            file_path: Path to .nit/drift-tests.yml

        Returns:
            List of drift test specifications.
        """
        if not file_path.exists():
            logger.warning("Drift tests file not found: %s", file_path)
            return []

        try:
            content = file_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)

            if not data or "tests" not in data:
                logger.warning("No tests found in drift tests file")
                return []

            tests = []
            for test_data in data["tests"]:
                try:
                    spec = DriftTestParser._parse_test(test_data)
                    tests.append(spec)
                except Exception as e:
                    logger.error("Failed to parse test %s: %s", test_data.get("id", "unknown"), e)

            logger.info("Parsed %d drift tests from %s", len(tests), file_path)
            return tests

        except Exception as e:
            logger.error("Failed to parse drift tests file: %s", e)
            return []

    @staticmethod
    def _parse_test(data: dict[str, Any]) -> DriftTestSpec:
        """Parse a single test specification.

        Args:
            data: Test data from YAML.

        Returns:
            Parsed drift test spec.
        """
        # Parse endpoint type
        endpoint_type_str = data.get("endpoint_type", "function")
        try:
            endpoint_type = EndpointType(endpoint_type_str)
        except ValueError:
            logger.warning("Unknown endpoint type: %s, defaulting to function", endpoint_type_str)
            endpoint_type = EndpointType.FUNCTION

        # Parse comparison type
        comparison_type_str = data.get("comparison_type", "semantic")
        try:
            comparison_type = ComparisonType(comparison_type_str)
        except ValueError:
            logger.warning(
                "Unknown comparison type: %s, defaulting to semantic", comparison_type_str
            )
            comparison_type = ComparisonType.SEMANTIC

        return DriftTestSpec(
            id=data["id"],
            name=data.get("name", data["id"]),
            endpoint_type=endpoint_type,
            comparison_type=comparison_type,
            endpoint_config=data.get("endpoint_config", {}),
            comparison_config=data.get("comparison_config", {}),
            enabled=data.get("enabled", True),
            timeout=data.get("timeout", 30.0),
            metadata=data.get("metadata", {}),
        )


class DriftTestExecutor:
    """Execute drift tests (task 3.11.3)."""

    async def execute_test(self, spec: DriftTestSpec) -> str:
        """Execute a drift test and return the output.

        Args:
            spec: Test specification.

        Returns:
            Output string from the test.
        """
        if not spec.enabled:
            logger.info("Test %s is disabled, skipping", spec.id)
            return ""

        if spec.endpoint_type == EndpointType.FUNCTION:
            return await self._execute_function(spec)
        if spec.endpoint_type == EndpointType.HTTP:
            return await self._execute_http(spec)
        return await self._execute_cli(spec)

    async def _execute_function(self, spec: DriftTestSpec) -> str:
        """Execute a Python/JS function (task 3.11.3).

        Endpoint config format:
        {
            "module": "my_module.my_submodule",
            "function": "my_function",
            "args": [...],
            "kwargs": {...}
        }

        Args:
            spec: Test specification.

        Returns:
            JSON-serialized function output.
        """
        config = spec.endpoint_config
        module_name = config.get("module")
        function_name = config.get("function")

        if not module_name or not function_name:
            msg = "Function endpoint requires 'module' and 'function' in config"
            raise ValueError(msg)

        try:
            # Import module
            module = importlib.import_module(module_name)

            # Get function
            func = getattr(module, function_name)

            # Get args and kwargs
            args = config.get("args", [])
            kwargs = config.get("kwargs", {})

            # Call function (with timeout)
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(func, *args, **kwargs),
                    timeout=spec.timeout,
                )
            except TimeoutError as e:
                msg = f"Function execution timed out after {spec.timeout}s"
                raise TimeoutError(msg) from e

            # Serialize result
            if isinstance(result, str):
                return result
            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error("Function execution failed for test %s: %s", spec.id, e)
            raise

    async def _execute_http(self, spec: DriftTestSpec) -> str:
        """Execute an HTTP request (task 3.11.3).

        Endpoint config format:
        {
            "url": "https://api.example.com/endpoint",
            "method": "POST",
            "headers": {...},
            "body": {...} or "..."
        }

        Args:
            spec: Test specification.

        Returns:
            HTTP response body.
        """
        config = spec.endpoint_config
        url = config.get("url")
        method = config.get("method", "GET").upper()

        if not url:
            msg = "HTTP endpoint requires 'url' in config"
            raise ValueError(msg)

        try:
            # Prepare request
            headers = config.get("headers", {})
            body = config.get("body")

            # Serialize body if it's a dict
            if isinstance(body, dict):
                body = json.dumps(body)
                headers.setdefault("Content-Type", "application/json")

            # Make request (with timeout)
            async with httpx.AsyncClient(timeout=spec.timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    content=body,
                )

                # Return response text
                return response.text

        except Exception as e:
            logger.error("HTTP request failed for test %s: %s", spec.id, e)
            raise

    async def _execute_cli(self, spec: DriftTestSpec) -> str:
        """Execute a CLI command (task 3.11.3).

        Endpoint config format:
        {
            "command": ["python", "script.py", "--arg", "value"],
            "cwd": "/path/to/working/dir",
            "env": {...}
        }

        Args:
            spec: Test specification.

        Returns:
            Command stdout.
        """
        config = spec.endpoint_config
        command = config.get("command")

        if not command:
            msg = "CLI endpoint requires 'command' in config"
            raise ValueError(msg)

        try:
            # Prepare environment
            env = config.get("env")
            cwd = config.get("cwd")

            # Run command (with timeout)
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                )

                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=spec.timeout,
                )

            except TimeoutError as e:
                msg = f"Command execution timed out after {spec.timeout}s"
                raise TimeoutError(msg) from e

            # Check return code
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace")
                msg = f"Command failed with exit code {process.returncode}: {error_msg}"
                raise RuntimeError(msg)

            return stdout.decode("utf-8", errors="replace")

        except Exception as e:
            logger.error("CLI execution failed for test %s: %s", spec.id, e)
            raise
