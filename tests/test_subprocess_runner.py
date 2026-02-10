"""Tests for subprocess runner utility (task 1.16.6)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nit.utils.subprocess_runner import SubprocessError, run_subprocess

# ── Basic Execution Tests ────────────────────────────────────────────


async def test_run_subprocess_success() -> None:
    """Test successful subprocess execution."""
    result = await run_subprocess(["echo", "hello"])

    assert result.success
    assert result.returncode == 0
    assert "hello" in result.stdout
    assert result.timed_out is False
    assert result.duration_ms > 0


async def test_run_subprocess_with_args() -> None:
    """Test subprocess with multiple arguments."""
    result = await run_subprocess(["echo", "hello", "world"])

    assert result.success
    assert "hello world" in result.stdout


async def test_run_subprocess_with_working_directory(tmp_path: Path) -> None:
    """Test subprocess respects working directory."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")

    result = await run_subprocess(["ls"], cwd=tmp_path)

    assert result.success
    assert "test.txt" in result.stdout


async def test_run_subprocess_captures_stderr() -> None:
    """Test subprocess captures stderr separately."""
    # Use a command that writes to stderr
    result = await run_subprocess(["python3", "-c", "import sys; sys.stderr.write('error msg')"])

    assert result.returncode == 0
    assert "error msg" in result.stderr


async def test_run_subprocess_nonzero_exit_code() -> None:
    """Test subprocess returns non-zero exit code correctly."""
    result = await run_subprocess(["python3", "-c", "import sys; sys.exit(42)"])

    assert not result.success
    assert result.returncode == 42


# ── Error Handling Tests ──────────────────────────────────────────────


async def test_run_subprocess_command_not_found() -> None:
    """Test subprocess handles command not found."""
    with pytest.raises(SubprocessError) as exc_info:
        await run_subprocess(["nonexistent_command_xyz123"])

    assert "Command not found" in str(exc_info.value)
    assert exc_info.value.result.returncode == -1


async def test_run_subprocess_empty_command() -> None:
    """Test subprocess rejects empty command."""
    with pytest.raises(ValueError, match="Command cannot be empty"):
        await run_subprocess([])


async def test_run_subprocess_invalid_timeout() -> None:
    """Test subprocess rejects invalid timeout."""
    with pytest.raises(ValueError, match="Timeout must be positive"):
        await run_subprocess(["echo", "test"], timeout=0)

    with pytest.raises(ValueError, match="Timeout must be positive"):
        await run_subprocess(["echo", "test"], timeout=-1)


async def test_run_subprocess_invalid_working_directory() -> None:
    """Test subprocess rejects non-existent working directory."""
    with pytest.raises(ValueError, match="Working directory does not exist"):
        await run_subprocess(["echo", "test"], cwd=Path("/nonexistent/path/xyz"))


# ── Timeout Tests ─────────────────────────────────────────────────────


async def test_run_subprocess_timeout() -> None:
    """Test subprocess timeout handling."""
    # Command that sleeps for 10 seconds but timeout after 0.1 seconds
    result = await run_subprocess(["python3", "-c", "import time; time.sleep(10)"], timeout=0.1)

    assert not result.success
    assert result.timed_out is True
    assert result.returncode != 0
    assert "timed out" in result.stderr.lower()


async def test_run_subprocess_no_timeout_on_fast_command() -> None:
    """Test fast commands don't trigger timeout."""
    result = await run_subprocess(["echo", "quick"], timeout=10.0)

    assert result.success
    assert not result.timed_out
    assert result.duration_ms < 10000  # Should complete in under 10 seconds


# ── Check Parameter Tests ─────────────────────────────────────────────


async def test_run_subprocess_check_raises_on_failure() -> None:
    """Test check=True raises SubprocessError on non-zero exit."""
    with pytest.raises(SubprocessError) as exc_info:
        await run_subprocess(
            ["python3", "-c", "import sys; sys.exit(1)"],
            check=True,
        )

    assert "Command failed" in str(exc_info.value)
    assert exc_info.value.result.returncode == 1


async def test_run_subprocess_check_passes_on_success() -> None:
    """Test check=True does not raise on success."""
    result = await run_subprocess(["echo", "test"], check=True)

    assert result.success
    assert result.returncode == 0


# ── Environment Variables Tests ────────────────────────────────────────


async def test_run_subprocess_with_environment_variables() -> None:
    """Test subprocess can set environment variables."""
    result = await run_subprocess(
        ["python3", "-c", "import os; print(os.getenv('TEST_VAR', 'not_set'))"],
        env={"TEST_VAR": "test_value"},
    )

    assert result.success
    assert "test_value" in result.stdout


# ── Duration Tracking Tests ───────────────────────────────────────────


async def test_run_subprocess_tracks_duration() -> None:
    """Test subprocess tracks execution duration."""
    result = await run_subprocess(["python3", "-c", "import time; time.sleep(0.05)"])

    assert result.success
    assert result.duration_ms >= 50  # At least 50ms (0.05 seconds)
    assert result.duration_ms < 1000  # But not too long


# ── Edge Cases ────────────────────────────────────────────────────────


async def test_run_subprocess_large_output() -> None:
    """Test subprocess handles large output."""
    # Generate 10KB of output
    result = await run_subprocess(["python3", "-c", "print('x' * 10000)"])

    assert result.success
    assert len(result.stdout) >= 10000


async def test_run_subprocess_unicode_output() -> None:
    """Test subprocess handles Unicode correctly."""
    result = await run_subprocess(["python3", "-c", "print('Hello 世界 🌍')"])

    assert result.success
    assert "世界" in result.stdout
    assert "🌍" in result.stdout


async def test_run_subprocess_concurrent_execution() -> None:
    """Test multiple subprocesses can run concurrently."""
    # Run 5 commands concurrently
    tasks = [run_subprocess(["echo", f"test{i}"]) for i in range(5)]

    results = await asyncio.gather(*tasks)

    assert all(r.success for r in results)
    assert len(results) == 5
