"""CLI tool adapters for delegating LLM generation to external tools.

This module provides adapters for using external CLI tools (Claude Code, OpenAI
Codex, custom commands) as LLM backends. These adapters implement the LLMEngine
interface and handle subprocess execution, response parsing, error detection, and
token usage tracking.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nit.llm.engine import (
    GenerationRequest,
    LLMConnectionError,
    LLMEngine,
    LLMError,
    LLMMessage,
    LLMResponse,
)
from nit.llm.usage_callback import report_cli_usage_event

logger = logging.getLogger(__name__)


def _parse_int_pattern(text: str, patterns: list[str]) -> int:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue

        try:
            return max(int(match.group(1)), 0)
        except ValueError:
            continue

    return 0


def _parse_float_pattern(text: str, patterns: list[str]) -> float:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue

        try:
            return max(float(match.group(1)), 0.0)
        except ValueError:
            continue

    return 0.0


def _parse_bool_pattern(text: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue

        value = match.group(1).strip().lower()
        if value in {"1", "true", "yes", "hit"}:
            return True
        if value in {"0", "false", "no", "miss"}:
            return False

    return False


def _parse_model_pattern(text: str) -> str | None:
    match = re.search(r"(?:^|\b)(?:model|model_name)\s*[:=]\s*([\w./:\-]+)", text, re.IGNORECASE)
    if not match:
        return None

    value = match.group(1).strip()
    return value or None


@dataclass
class CLIToolConfig:
    """Configuration for CLI tool adapters."""

    command: str
    """The command to execute (e.g., 'claude', 'codex', custom script path)."""

    model: str
    """Model identifier to pass to the CLI tool."""

    timeout: int = 300
    """Maximum execution time in seconds."""

    extra_args: list[str] = field(default_factory=list)
    """Additional command-line arguments."""


@dataclass
class CLIResponse:
    """Parsed response from a CLI tool execution."""

    text: str
    """The generated text content."""

    model: str
    """Model that produced the response."""

    prompt_tokens: int = 0
    """Estimated prompt tokens (may be parsed or estimated)."""

    completion_tokens: int = 0
    """Estimated completion tokens (may be parsed or estimated)."""

    cost_usd: float = 0.0
    """Estimated/parsed cost in USD, if available."""

    provider: str | None = None
    """Provider hint, if parsed from output."""

    cache_hit: bool = False
    """Whether CLI output indicates a cache hit."""

    duration_ms: int = 0
    """Command execution duration in milliseconds."""

    error: str | None = None
    """Error message if execution failed."""

    exit_code: int = 0
    """Process exit code."""

    stderr: str = ""
    """Standard error output."""


class CLIToolAdapter(LLMEngine, ABC):
    """Abstract base class for CLI tool-based LLM adapters.

    Subclasses must implement ``_build_command()`` and ``_parse_output()`` to
    handle tool-specific command construction and response parsing.
    """

    def __init__(self, config: CLIToolConfig) -> None:
        self._config = config
        self._validate_command()

    @property
    def model_name(self) -> str:
        return self._config.model

    async def generate(self, request: GenerationRequest) -> LLMResponse:
        """Execute the CLI tool and parse the response."""
        model = request.model or self._config.model

        # Build the command with tool-specific arguments
        cmd, context_file = self._build_command(request, model)

        try:
            # Execute the command
            cli_response = await self._execute(cmd)

            # Check for errors
            if cli_response.error:
                self._handle_error(cli_response)

            # Convert to LLMResponse
            self._report_usage(request, cli_response, model)
            return LLMResponse(
                text=cli_response.text,
                model=cli_response.model or model,
                prompt_tokens=cli_response.prompt_tokens,
                completion_tokens=cli_response.completion_tokens,
            )
        finally:
            # Clean up temp files
            if context_file and context_file.exists():
                with contextlib.suppress(Exception):
                    context_file.unlink()

    async def generate_text(self, prompt: str, *, context: str = "") -> str:
        """Simple text generation using CLI tool."""
        messages: list[LLMMessage] = []
        if context:
            messages.append(LLMMessage(role="system", content=context))
        messages.append(LLMMessage(role="user", content=prompt))

        response = await self.generate(GenerationRequest(messages=messages))
        return response.text

    # ── Abstract methods to be implemented by subclasses ──

    @abstractmethod
    def _build_command(
        self, request: GenerationRequest, model: str
    ) -> tuple[list[str], Path | None]:
        """Build the command to execute.

        Args:
            request: The generation request with messages and parameters.
            model: The model identifier to use.

        Returns:
            A tuple of (command_args, temp_file_path). The temp_file_path may be
            None if no temp file was created.
        """

    @abstractmethod
    def _parse_output(self, stdout: str, stderr: str, exit_code: int, model: str) -> CLIResponse:
        """Parse the tool's output into a structured response.

        Args:
            stdout: Standard output from the command.
            stderr: Standard error from the command.
            exit_code: Process exit code.
            model: The model that was requested.

        Returns:
            A CLIResponse with parsed text, tokens, and any errors.
        """

    # ── Internal helpers ──

    def _validate_command(self) -> None:
        """Check that the configured command exists in PATH."""
        if not shutil.which(self._config.command):
            raise LLMError(
                f"CLI tool '{self._config.command}' not found in PATH. "
                f"Please install it or check your configuration."
            )

    async def _execute(self, cmd: list[str]) -> CLIResponse:
        """Execute the CLI command with timeout and capture output."""
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self._config.timeout
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise LLMConnectionError(
                    f"CLI tool '{self._config.command}' timed out after "
                    f"{self._config.timeout} seconds"
                ) from None

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode or 0

            response = self._parse_output(stdout, stderr, exit_code, self._config.model)
            response.duration_ms = max(int((time.monotonic() - started) * 1000), 0)
            return response

        except FileNotFoundError as exc:
            raise LLMError(f"Failed to execute '{self._config.command}': {exc}") from exc
        except Exception as exc:
            raise LLMConnectionError(f"CLI tool execution failed: {exc}") from exc

    def _handle_error(self, response: CLIResponse) -> None:
        """Raise appropriate LLMError based on CLI response error."""
        error = response.error or "Unknown error"

        # Detect specific error patterns
        error_lower = error.lower()
        if "model" in error_lower and ("not found" in error_lower or "unknown" in error_lower):
            raise LLMError(f"Model not found: {response.model}. Error: {error}")
        if "authentication" in error_lower or "api key" in error_lower:
            raise LLMError(f"Authentication failed: {error}")
        if "rate limit" in error_lower or "quota" in error_lower:
            raise LLMError(f"Rate limit exceeded: {error}")

        raise LLMError(f"CLI tool error (exit code {response.exit_code}): {error}")

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimation: ~4 characters per token."""
        return max(1, len(text) // 4)

    @staticmethod
    def _infer_provider_from_model(model: str) -> str:
        normalized = model.lower()
        if "/" in normalized:
            return normalized.split("/", 1)[0]

        if "claude" in normalized:
            return "anthropic"
        if "gpt" in normalized or "o1" in normalized or "o3" in normalized:
            return "openai"
        if "gemini" in normalized:
            return "google"
        if "mistral" in normalized:
            return "mistral"

        return "unknown"

    def _default_provider(self) -> str:
        return self._infer_provider_from_model(self._config.model)

    def _report_usage(self, request: GenerationRequest, response: CLIResponse, model: str) -> None:
        if response.error:
            return

        prompt_tokens = response.prompt_tokens
        if prompt_tokens <= 0:
            prompt_tokens = self._estimate_tokens(self._format_messages_as_text(request.messages))

        completion_tokens = response.completion_tokens
        if completion_tokens <= 0 and response.text:
            completion_tokens = self._estimate_tokens(response.text)

        provider = response.provider or self._default_provider()

        report_cli_usage_event(
            provider=provider,
            model=response.model or model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=max(response.cost_usd, 0.0),
            cache_hit=response.cache_hit,
            source="cli",
            duration_ms=response.duration_ms,
            metadata={
                "nit_cli_command": self._config.command,
                "nit_usage_mode": "cli",
            },
        )

    @staticmethod
    def _format_messages_as_text(messages: list[LLMMessage]) -> str:
        """Format conversation messages as plain text."""
        parts = []
        for msg in messages:
            if msg.role == "system":
                parts.append(f"System: {msg.content}")
            elif msg.role == "user":
                parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                parts.append(f"Assistant: {msg.content}")
        return "\n\n".join(parts)


class ClaudeCodeAdapter(CLIToolAdapter):
    """Adapter for Claude Code CLI (``claude --print``).

    Invokes the Claude Code CLI with a structured prompt and parses the
    response, including error detection and token usage tracking.
    """

    def _build_command(
        self, request: GenerationRequest, model: str
    ) -> tuple[list[str], Path | None]:
        """Build ``claude --print`` command."""
        # Create a temp file with the conversation
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            prompt_text = self._format_messages_as_text(request.messages)
            f.write(prompt_text)
            temp_file = Path(f.name)

        cmd = [
            self._config.command,
            "--print",
            "--model",
            model,
            str(temp_file),
        ]
        cmd.extend(self._config.extra_args)

        return cmd, temp_file

    def _parse_output(self, stdout: str, stderr: str, exit_code: int, model: str) -> CLIResponse:
        """Parse Claude Code output.

        Claude Code typically outputs:
        - The response text on stdout
        - Errors on stderr
        - May include token usage info in stderr (e.g., "tokens used: 1234")
        """
        # Check for errors
        error = None
        if exit_code != 0:
            error = stderr.strip() or "Command failed with no error message"

        prompt_tokens = _parse_int_pattern(
            stderr,
            [
                r"prompt[_\s\-]*tokens?\s*[:=]\s*(\d+)",
                r"input[_\s\-]*tokens?\s*[:=]\s*(\d+)",
            ],
        )
        completion_tokens = _parse_int_pattern(
            stderr,
            [
                r"completion[_\s\-]*tokens?\s*[:=]\s*(\d+)",
                r"output[_\s\-]*tokens?\s*[:=]\s*(\d+)",
            ],
        )
        total_tokens = _parse_int_pattern(
            stderr,
            [r"total[_\s\-]*tokens?\s*[:=]\s*(\d+)", r"tokens[_\s\-]*used\s*[:=]\s*(\d+)"],
        )
        if completion_tokens == 0 and total_tokens > prompt_tokens:
            completion_tokens = total_tokens - prompt_tokens

        cost_usd = _parse_float_pattern(
            stderr,
            [
                r"(?:response[_\s\-]*cost|total[_\s\-]*cost|cost[_\s\-]*usd|cost)\s*[:=]\s*\$?([0-9]+(?:\.[0-9]+)?)",
                r"\$([0-9]+(?:\.[0-9]+)?)\s*(?:usd|dollars?)",
            ],
        )
        cache_hit = _parse_bool_pattern(
            stderr,
            [r"cache[_\s\-]*hit\s*[:=]\s*(true|false|1|0|yes|no|hit|miss)"],
        )
        parsed_model = _parse_model_pattern(stderr) or model

        # If no token info found, estimate
        text = stdout.strip()
        if not prompt_tokens and not completion_tokens:
            completion_tokens = self._estimate_tokens(text)

        return CLIResponse(
            text=text,
            model=parsed_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            provider="anthropic",
            cache_hit=cache_hit,
            error=error,
            exit_code=exit_code,
            stderr=stderr,
        )

    def _default_provider(self) -> str:
        return "anthropic"


class CodexAdapter(CLIToolAdapter):
    """Adapter for OpenAI Codex CLI.

    Invokes a hypothetical ``codex`` CLI tool with prompt context and parses
    the JSON response.
    """

    def _build_command(
        self, request: GenerationRequest, model: str
    ) -> tuple[list[str], Path | None]:
        """Build ``codex --prompt`` command."""
        # Create temp file with prompt
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            prompt_text = self._format_messages_as_text(request.messages)
            f.write(prompt_text)
            temp_file = Path(f.name)

        cmd = [
            self._config.command,
            "--prompt",
            str(temp_file),
            "--model",
            model,
            "--output",
            "json",
        ]
        cmd.extend(self._config.extra_args)

        return cmd, temp_file

    def _parse_output(self, stdout: str, stderr: str, exit_code: int, model: str) -> CLIResponse:
        """Parse Codex CLI output (expects JSON format)."""
        # Check for errors
        error = None
        if exit_code != 0:
            error = stderr.strip() or stdout.strip() or "Command failed"

        text = ""
        parsed_model = model
        prompt_tokens = 0
        completion_tokens = 0
        cost_usd = 0.0
        provider = "openai"
        cache_hit = False

        # Try to parse JSON response
        try:
            data: dict[str, Any] = json.loads(stdout)
            text = str(data.get("text") or data.get("output_text") or data.get("output") or "")
            usage_raw = data.get("usage")
            usage: dict[str, Any] = usage_raw if isinstance(usage_raw, dict) else {}
            prompt_tokens = int(
                usage.get("prompt_tokens", data.get("prompt_tokens", usage.get("input_tokens", 0)))
            )
            completion_tokens = int(
                usage.get(
                    "completion_tokens",
                    data.get("completion_tokens", usage.get("output_tokens", 0)),
                )
            )
            total_tokens = int(usage.get("total_tokens", data.get("total_tokens", 0)))
            if completion_tokens <= 0 and total_tokens > prompt_tokens:
                completion_tokens = total_tokens - prompt_tokens
            cost_usd = float(
                data.get(
                    "response_cost",
                    data.get("cost", data.get("cost_usd", data.get("total_cost", 0.0))),
                )
            )
            parsed_model = str(data.get("model", model))
            provider = str(data.get("provider", provider))
            cache_hit = bool(data.get("cache_hit", False))
        except json.JSONDecodeError, TypeError, ValueError:
            # Fall back to raw stdout if not JSON
            text = stdout.strip()
            if not error and exit_code == 0:
                completion_tokens = self._estimate_tokens(text)

        if prompt_tokens <= 0:
            prompt_tokens = _parse_int_pattern(
                stderr,
                [
                    r"prompt[_\s\-]*tokens?\s*[:=]\s*(\d+)",
                    r"input[_\s\-]*tokens?\s*[:=]\s*(\d+)",
                ],
            )

        if completion_tokens <= 0:
            completion_tokens = _parse_int_pattern(
                stderr,
                [
                    r"completion[_\s\-]*tokens?\s*[:=]\s*(\d+)",
                    r"output[_\s\-]*tokens?\s*[:=]\s*(\d+)",
                ],
            )

        if cost_usd <= 0:
            cost_usd = _parse_float_pattern(
                stderr,
                [
                    r"(?:response[_\s\-]*cost|cost[_\s\-]*usd|cost)\s*[:=]\s*\$?([0-9]+(?:\.[0-9]+)?)"
                ],
            )

        parsed_model = _parse_model_pattern(stderr) or parsed_model
        cache_hit = cache_hit or _parse_bool_pattern(
            stderr,
            [r"cache[_\s\-]*hit\s*[:=]\s*(true|false|1|0|yes|no|hit|miss)"],
        )

        return CLIResponse(
            text=text,
            model=parsed_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=max(cost_usd, 0.0),
            provider=provider or self._infer_provider_from_model(parsed_model),
            cache_hit=cache_hit,
            error=error,
            exit_code=exit_code,
            stderr=stderr,
        )

    def _default_provider(self) -> str:
        return "openai"


class CustomCommandAdapter(CLIToolAdapter):
    """Adapter for user-defined custom commands.

    Supports template placeholders:
    - ``{context_file}``: Path to temp file with conversation messages
    - ``{source_file}``: Alias for context_file
    - ``{output_file}``: Path to temp file where output should be written
    - ``{prompt}``: The user prompt text (last user message)
    - ``{model}``: The model identifier
    """

    def _build_command(
        self, request: GenerationRequest, model: str
    ) -> tuple[list[str], Path | None]:
        """Build custom command with template substitution."""
        # Create context file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            prompt_text = self._format_messages_as_text(request.messages)
            f.write(prompt_text)
            context_file = Path(f.name)

        # Create output file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            output_file = Path(f.name)

        # Extract last user message as prompt
        user_msgs = [m for m in request.messages if m.role == "user"]
        prompt = user_msgs[-1].content if user_msgs else ""

        # Build command with substitutions
        cmd_template = self._config.command
        cmd_str = cmd_template.format(
            context_file=str(context_file),
            source_file=str(context_file),
            output_file=str(output_file),
            prompt=prompt,
            model=model,
        )

        # Parse into args (simple split, shell=True would be insecure)
        cmd = cmd_str.split()
        cmd.extend(self._config.extra_args)

        # Store output file path for reading later
        self._output_file = output_file

        return cmd, context_file

    def _parse_output(self, stdout: str, stderr: str, exit_code: int, model: str) -> CLIResponse:
        """Parse custom command output.

        Reads from output_file if it exists, otherwise uses stdout.
        """
        error = None
        if exit_code != 0:
            error = stderr.strip() or "Custom command failed"

        # Try to read from output file first
        text = ""
        if hasattr(self, "_output_file") and self._output_file.exists():
            try:
                text = self._output_file.read_text(encoding="utf-8").strip()
            except Exception as exc:
                logger.warning("Failed to read output file: %s", exc)
                text = stdout.strip()
            finally:
                with contextlib.suppress(Exception):
                    self._output_file.unlink()
        else:
            text = stdout.strip()

        # Estimate tokens (no usage info from custom commands)
        completion_tokens = self._estimate_tokens(text) if text else 0

        return CLIResponse(
            text=text,
            model=model,
            prompt_tokens=0,  # Unknown
            completion_tokens=completion_tokens,
            provider=self._infer_provider_from_model(model),
            error=error,
            exit_code=exit_code,
            stderr=stderr,
        )
