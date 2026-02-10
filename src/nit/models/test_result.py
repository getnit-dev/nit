"""Test result models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TestResult:
    """Result of a single test execution."""

    name: str
    """Test name."""

    passed: bool
    """Whether the test passed."""

    duration: float | None = None
    """Test duration in seconds."""

    error_message: str | None = None
    """Error message if the test failed."""

    file_path: str | None = None
    """Path to the test file."""
