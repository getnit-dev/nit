"""Tests for the PatternAnalyzer (agents/analyzers/pattern.py).

Covers pattern extraction from various test file styles:
- Python pytest (function-based, assert statements)
- Python unittest (class-based, assertEqual methods)
- JavaScript/TypeScript Vitest (describe/it, expect assertions)
- Mocking patterns (pytest.fixture, vi.mock, unittest.mock)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from nit.agents.analyzers.pattern import (
    ConventionProfile,
    PatternAnalysisTask,
    PatternAnalyzer,
)
from nit.agents.base import TaskStatus
from nit.memory.conventions import ConventionStore

# ── Sample test file contents ────────────────────────────────────


_PYTEST_FUNCTION_STYLE = """
import pytest
from myapp.calculator import add, subtract

def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0

def test_subtract():
    result = subtract(10, 3)
    assert result == 7
    assert subtract(0, 5) == -5

@pytest.fixture
def sample_data():
    return {"value": 42}

def test_with_fixture(sample_data):
    assert sample_data["value"] == 42
"""

_PYTEST_CLASS_STYLE = """
import pytest
from myapp.auth import AuthService

class TestAuthService:
    def test_login_success(self):
        service = AuthService()
        result = service.login("user", "pass")
        assert result is True

    def test_login_failure(self):
        service = AuthService()
        result = service.login("user", "wrongpass")
        assert result is False
"""

_UNITTEST_STYLE = """
import unittest
from unittest.mock import Mock, patch
from myapp.database import Database

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.db = Database()

    def test_connect(self):
        self.assertTrue(self.db.connect())

    @patch('myapp.database.Connection')
    def test_query_with_mock(self, mock_conn):
        mock_conn.return_value.execute.return_value = [1, 2, 3]
        result = self.db.query("SELECT *")
        self.assertEqual(result, [1, 2, 3])
"""

_VITEST_DESCRIBE_STYLE = """
import { describe, it, expect, vi } from 'vitest';
import { fetchUser } from './api';

describe('fetchUser', () => {
  it('should fetch user data successfully', async () => {
    const user = await fetchUser(1);
    expect(user).toBeDefined();
    expect(user.id).toBe(1);
  });

  it('should handle errors', async () => {
    vi.mock('./api', () => ({
      fetchUser: vi.fn().mockRejectedValue(new Error('Network error')),
    }));

    await expect(fetchUser(999)).rejects.toThrow('Network error');
  });
});
"""

_VITEST_TEST_STYLE = """
import { test, expect } from 'vitest';
import { sum, multiply } from './math';

test('sum adds two numbers', () => {
  expect(sum(2, 3)).toBe(5);
  expect(sum(-1, 1)).toBe(0);
});

test('multiply multiplies two numbers', () => {
  const result = multiply(4, 5);
  expect(result).toBe(20);
});
"""

_MIXED_MOCKING_PYTHON = """
import pytest
from unittest import mock
from unittest.mock import patch
from myapp.service import Service

@pytest.fixture
def service():
    return Service()

@mock.patch('myapp.service.external_api')
def test_with_mock_decorator(mock_api, service):
    mock_api.return_value = "mocked"
    assert service.call_api() == "mocked"

def test_with_mock_object(service):
    with patch('myapp.service.external_api') as mock_api:
        mock_api.return_value = "patched"
        assert service.call_api() == "patched"
"""


# ── Helpers ──────────────────────────────────────────────────────


def _write_test_file(root: Path, rel_path: str, content: str) -> None:
    """Write a test file with the given content."""
    file_path = root / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


# ── Tests: PatternAnalyzer ───────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_pytest_function_style(tmp_path: Path) -> None:
    """Test pattern extraction from pytest function-style tests."""
    # Create a test file
    _write_test_file(tmp_path, "tests/test_calculator.py", _PYTEST_FUNCTION_STYLE)

    # Run analysis
    analyzer = PatternAnalyzer(max_files=10, sample_size=3)
    task = PatternAnalysisTask(
        project_root=str(tmp_path),
        language="python",
    )

    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    profile: ConventionProfile = result.result["profile"]

    # Check naming style
    assert profile.naming_style == "function"
    assert profile.naming_counts["function"] >= 3  # test_add, test_subtract, test_with_fixture

    # Check assertion style
    assert profile.assertion_style == "assert"
    assert profile.assertion_counts["assert"] >= 4

    # Check mocking patterns
    assert "pytest.fixture" in profile.mocking_patterns

    # Check files analyzed
    assert profile.files_analyzed == 1


@pytest.mark.asyncio
async def test_analyze_pytest_class_style(tmp_path: Path) -> None:
    """Test pattern extraction from pytest class-based tests."""
    _write_test_file(tmp_path, "tests/test_auth.py", _PYTEST_CLASS_STYLE)

    analyzer = PatternAnalyzer()
    task = PatternAnalysisTask(project_root=str(tmp_path), language="python")
    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    profile: ConventionProfile = result.result["profile"]

    # Should detect class-based tests
    assert profile.naming_style in ("class", "function")  # May detect both
    assert "class" in profile.naming_counts

    # Check assertion style
    assert profile.assertion_style == "assert"


@pytest.mark.asyncio
async def test_analyze_unittest_style(tmp_path: Path) -> None:
    """Test pattern extraction from unittest-style tests."""
    _write_test_file(tmp_path, "tests/test_database.py", _UNITTEST_STYLE)

    analyzer = PatternAnalyzer()
    task = PatternAnalysisTask(project_root=str(tmp_path), language="python")
    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    profile: ConventionProfile = result.result["profile"]

    # Should detect class-based tests
    assert "class" in profile.naming_counts

    # Check mocking patterns
    assert "unittest.mock" in profile.mocking_patterns or "mock.patch" in profile.mocking_patterns


@pytest.mark.asyncio
async def test_analyze_vitest_describe_style(tmp_path: Path) -> None:
    """Test pattern extraction from Vitest describe/it tests."""
    _write_test_file(tmp_path, "tests/api.test.ts", _VITEST_DESCRIBE_STYLE)

    analyzer = PatternAnalyzer()
    task = PatternAnalysisTask(project_root=str(tmp_path), language="typescript")
    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    profile: ConventionProfile = result.result["profile"]

    # Check naming style
    assert profile.naming_style == "describe"
    assert profile.naming_counts["describe"] >= 1

    # Check assertion style
    assert profile.assertion_style == "expect"
    assert profile.assertion_counts["expect"] >= 2

    # Check mocking patterns
    assert "vi.mock" in profile.mocking_patterns


@pytest.mark.asyncio
async def test_analyze_vitest_test_style(tmp_path: Path) -> None:
    """Test pattern extraction from Vitest test()-style tests."""
    _write_test_file(tmp_path, "tests/math.test.ts", _VITEST_TEST_STYLE)

    analyzer = PatternAnalyzer()
    task = PatternAnalysisTask(project_root=str(tmp_path), language="typescript")
    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    profile: ConventionProfile = result.result["profile"]

    # Check assertion style (even without describe blocks)
    assert profile.assertion_style == "expect"


@pytest.mark.asyncio
async def test_analyze_mixed_mocking_patterns(tmp_path: Path) -> None:
    """Test detection of multiple mocking patterns in the same file."""
    _write_test_file(tmp_path, "tests/test_service.py", _MIXED_MOCKING_PYTHON)

    analyzer = PatternAnalyzer()
    task = PatternAnalysisTask(project_root=str(tmp_path), language="python")
    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    profile: ConventionProfile = result.result["profile"]

    # Should detect multiple mocking patterns
    assert "pytest.fixture" in profile.mocking_patterns
    assert "unittest.mock" in profile.mocking_patterns or "mock.patch" in profile.mocking_patterns


@pytest.mark.asyncio
async def test_analyze_multiple_files(tmp_path: Path) -> None:
    """Test aggregation across multiple test files."""
    _write_test_file(tmp_path, "tests/test_calc.py", _PYTEST_FUNCTION_STYLE)
    _write_test_file(tmp_path, "tests/test_auth.py", _PYTEST_CLASS_STYLE)
    _write_test_file(tmp_path, "tests/test_db.py", _UNITTEST_STYLE)

    analyzer = PatternAnalyzer(max_files=10)
    task = PatternAnalysisTask(project_root=str(tmp_path), language="python")
    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    profile: ConventionProfile = result.result["profile"]

    # Should have analyzed all 3 files
    assert profile.files_analyzed == 3

    # Should aggregate counts
    assert profile.naming_counts["function"] >= 3
    assert profile.naming_counts["class"] >= 2

    # Should detect multiple mocking patterns
    assert len(profile.mocking_patterns) >= 2


@pytest.mark.asyncio
async def test_analyze_no_test_files(tmp_path: Path) -> None:
    """Test behavior when no test files are found."""
    # Create a non-test file
    (tmp_path / "src" / "main.py").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text("print('hello')", encoding="utf-8")

    analyzer = PatternAnalyzer()
    task = PatternAnalysisTask(project_root=str(tmp_path), language="python")
    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    profile: ConventionProfile = result.result["profile"]

    # Should return empty profile
    assert profile.files_analyzed == 0
    assert profile.naming_style == "unknown"
    assert profile.assertion_style == "unknown"


@pytest.mark.asyncio
async def test_analyze_invalid_project_root(tmp_path: Path) -> None:
    """Test behavior with invalid project root."""
    analyzer = PatternAnalyzer()
    task = PatternAnalysisTask(
        project_root=str(tmp_path / "nonexistent"),
        language="python",
    )
    result = await analyzer.run(task)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) > 0
    assert "does not exist" in result.errors[0]


@pytest.mark.asyncio
async def test_analyze_with_max_files_limit(tmp_path: Path) -> None:
    """Test that max_files limit is respected."""
    # Create 5 test files
    for i in range(5):
        _write_test_file(
            tmp_path,
            f"tests/test_{i}.py",
            f"def test_function_{i}():\n    assert True\n",
        )

    # Analyze with limit of 3
    analyzer = PatternAnalyzer(max_files=3)
    task = PatternAnalysisTask(project_root=str(tmp_path), max_files=3)
    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    profile: ConventionProfile = result.result["profile"]

    # Should only analyze 3 files
    assert profile.files_analyzed == 3


@pytest.mark.asyncio
async def test_to_test_pattern_conversion(tmp_path: Path) -> None:
    """Test conversion of ConventionProfile to DetectedTestPattern."""
    _write_test_file(tmp_path, "tests/test_example.py", _PYTEST_FUNCTION_STYLE)

    analyzer = PatternAnalyzer()
    task = PatternAnalysisTask(project_root=str(tmp_path), language="python")
    result = await analyzer.run(task)

    profile: ConventionProfile = result.result["profile"]
    test_pattern = profile.to_test_pattern()

    # Check that DetectedTestPattern has the right fields
    assert test_pattern.naming_style == profile.naming_style
    assert test_pattern.assertion_style == profile.assertion_style
    assert test_pattern.mocking_patterns == profile.mocking_patterns
    assert len(test_pattern.imports) <= 5  # Top 5 imports
    assert test_pattern.sample_test != "" or len(profile.sample_tests) == 0


# ── Tests: ConventionStore ───────────────────────────────────────


def test_convention_store_save_and_load(tmp_path: Path) -> None:
    """Test saving and loading convention profiles."""
    store = ConventionStore(tmp_path)

    # Create a sample profile
    profile = ConventionProfile(
        language="python",
        naming_style="function",
        naming_counts={"function": 10, "class": 2},
        assertion_style="assert",
        assertion_counts={"assert": 15, "expect": 1},
        mocking_patterns=["pytest.fixture", "unittest.mock"],
        mocking_counts={"pytest.fixture": 3, "unittest.mock": 2},
        common_imports=["import pytest", "from unittest import mock"],
        sample_tests=["def test_example():\n    assert True"],
        files_analyzed=5,
    )

    # Save
    store.save(profile)
    assert store.exists()

    # Load
    loaded = store.load()
    assert loaded is not None
    assert loaded.language == "python"
    assert loaded.naming_style == "function"
    assert loaded.assertion_style == "assert"
    assert loaded.files_analyzed == 5
    assert loaded.mocking_patterns == ["pytest.fixture", "unittest.mock"]


def test_convention_store_load_nonexistent(tmp_path: Path) -> None:
    """Test loading when no profile exists."""
    store = ConventionStore(tmp_path)
    assert not store.exists()

    loaded = store.load()
    assert loaded is None


def test_convention_store_clear(tmp_path: Path) -> None:
    """Test clearing stored convention profile."""
    store = ConventionStore(tmp_path)

    # Create and save a profile
    profile = ConventionProfile(
        language="python",
        naming_style="function",
        files_analyzed=1,
    )
    store.save(profile)
    assert store.exists()

    # Clear
    store.clear()
    assert not store.exists()
    assert store.load() is None
