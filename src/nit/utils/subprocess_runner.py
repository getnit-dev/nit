"""Subprocess-based test runner with safe execution, timeout, and error handling.

This module provides a robust subprocess runner for executing tests
and other commands with proper isolation, timeout handling, output capture,
and working directory management (task 1.16.1).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


@dataclass
class SubprocessResult:
    """Result of subprocess execution."""

    returncode: int
    """Exit code of the process."""

    stdout: str
    """Standard output captured from the process."""

    stderr: str
    """Standard error captured from the process."""

    success: bool
    """True if returncode is 0."""

    timed_out: bool = False
    """True if the process was terminated due to timeout."""

    duration_ms: float = 0.0
    """Actual duration of execution in milliseconds."""


async def run_subprocess(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = 120.0,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> SubprocessResult:
    """Execute a command in a subprocess with timeout and error handling.

    This is a safe subprocess runner that:
    - Executes commands with a configurable timeout
    - Captures stdout and stderr separately
    - Manages working directory
    - Handles environment variables
    - Returns structured results

    Args:
        command: Command and arguments as a sequence (e.g. ['pytest', '--json-report']).
        cwd: Working directory for the subprocess. Defaults to current directory.
        timeout: Maximum seconds to wait for completion. Defaults to 120.
        env: Environment variables to set. Merges with current environment.
        check: If True, raise SubprocessError on non-zero exit code.

    Returns:
        SubprocessResult with exit code, output, and metadata.

    Raises:
        SubprocessError: If check=True and command returns non-zero exit code.
        ValueError: If command is empty or timeout is invalid.

    Example:
        >>> result = await run_subprocess(
        ...     ['pytest', 'tests/', '--json-report'],
        ...     cwd=Path('/path/to/project'),
        ...     timeout=60.0
        ... )
        >>> if result.success:
        ...     print(f"Tests passed: {result.stdout}")
    """
    if not command:
        raise ValueError("Command cannot be empty")

    if timeout <= 0:
        raise ValueError(f"Timeout must be positive, got {timeout}")

    # Resolve working directory
    work_dir = cwd.resolve() if cwd else Path.cwd()
    if not work_dir.exists():
        raise ValueError(f"Working directory does not exist: {work_dir}")

    # Merge environment variables
    full_env = dict(env) if env else {}

    logger.debug(
        "Running subprocess: %s (cwd=%s, timeout=%s)",
        " ".join(str(c) for c in command),
        work_dir,
        timeout,
    )

    # Track execution time
    start_time = time.perf_counter()
    timed_out = False

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env=full_env or None,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except TimeoutError:
            # Timeout occurred - kill the process
            logger.warning("Subprocess timed out after %s seconds", timeout)
            timed_out = True
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass  # Process already terminated

            stdout_bytes = b""
            stderr_bytes = b"Process timed out and was killed"

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Decode output
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        returncode = process.returncode or (-1 if timed_out else 0)

        result = SubprocessResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            success=(returncode == 0 and not timed_out),
            timed_out=timed_out,
            duration_ms=duration_ms,
        )

        logger.debug(
            "Subprocess completed: returncode=%d, duration=%.2fms, success=%s",
            returncode,
            duration_ms,
            result.success,
        )

        if check and not result.success:
            raise SubprocessError(
                f"Command failed with exit code {returncode}: {' '.join(str(c) for c in command)}",
                result=result,
            )

        return result

    except SubprocessError:
        # Re-raise SubprocessError from check=True without wrapping
        raise

    except FileNotFoundError as exc:
        logger.error("Command not found: %s", command[0])
        raise SubprocessError(
            f"Command not found: {command[0]}",
            result=SubprocessResult(
                returncode=-1,
                stdout="",
                stderr=str(exc),
                success=False,
            ),
        ) from exc

    except Exception as exc:
        logger.exception("Unexpected error running subprocess")
        raise SubprocessError(
            f"Subprocess execution failed: {exc}",
            result=SubprocessResult(
                returncode=-1,
                stdout="",
                stderr=str(exc),
                success=False,
            ),
        ) from exc


class SubprocessError(Exception):
    """Exception raised when subprocess execution fails."""

    def __init__(self, message: str, result: SubprocessResult) -> None:
        """Initialize with error message and result.

        Args:
            message: Error description.
            result: The SubprocessResult from the failed execution.
        """
        super().__init__(message)
        self.result = result
