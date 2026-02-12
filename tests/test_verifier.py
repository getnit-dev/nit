"""Tests for the BugVerifier agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.adapters.base import RunResult
from nit.agents.analyzers.bug import BugLocation, BugReport, BugSeverity, BugType
from nit.agents.base import TaskInput, TaskStatus
from nit.agents.debuggers.verifier import (
    BugVerificationTask,
    BugVerifier,
    VerificationResult,
)
from nit.llm.engine import LLMResponse

# ── Helpers ──────────────────────────────────────────────────────


def _make_bug_report(
    *,
    bug_type: BugType = BugType.NULL_DEREFERENCE,
    error_message: str = "Cannot read property 'x' of null",
    file_path: str = "src/app.py",
    function_name: str | None = "process_data",
) -> BugReport:
    return BugReport(
        bug_type=bug_type,
        severity=BugSeverity.HIGH,
        title=f"{bug_type.value} in {function_name or file_path}",
        description="Test bug",
        location=BugLocation(
            file_path=file_path,
            function_name=function_name,
        ),
        error_message=error_message,
    )


def _make_llm_engine(response_text: str = "def test_repro():\n    assert False\n") -> AsyncMock:
    engine = AsyncMock()
    engine.generate.return_value = LLMResponse(
        text=response_text,
        model="test-model",
    )
    return engine


def _make_adapter(
    *,
    run_output: str = "FAILED 1 test",
    success: bool = False,
) -> AsyncMock:
    adapter = AsyncMock()
    adapter.name = "pytest"
    adapter.run_tests.return_value = RunResult(
        failed=1 if not success else 0,
        passed=0 if not success else 1,
        success=success,
        raw_output=run_output,
    )
    return adapter


# ── Agent basics ─────────────────────────────────────────────────


class TestBugVerifierProperties:
    def test_name(self, tmp_path: Path) -> None:
        engine = _make_llm_engine()
        agent = BugVerifier(llm_engine=engine, project_root=tmp_path)
        assert agent.name == "BugVerifier"

    def test_description(self, tmp_path: Path) -> None:
        engine = _make_llm_engine()
        agent = BugVerifier(llm_engine=engine, project_root=tmp_path)
        assert "reproduction" in agent.description.lower()


# ── run() validation ─────────────────────────────────────────────


class TestBugVerifierRunValidation:
    @pytest.mark.asyncio
    async def test_rejects_wrong_task_type(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        result = await agent.run(TaskInput(task_type="wrong", target="t"))
        assert result.status == TaskStatus.FAILED
        assert "BugVerificationTask" in result.errors[0]

    @pytest.mark.asyncio
    async def test_rejects_missing_bug_report(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        task = BugVerificationTask(target="t", bug_report=None, adapter=AsyncMock())
        result = await agent.run(task)
        assert result.status == TaskStatus.FAILED
        assert "required" in result.errors[0].lower()

    @pytest.mark.asyncio
    async def test_rejects_missing_adapter(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        task = BugVerificationTask(target="t", bug_report=_make_bug_report(), adapter=None)
        result = await agent.run(task)
        assert result.status == TaskStatus.FAILED
        assert "required" in result.errors[0].lower()


# ── run() success path ───────────────────────────────────────────


class TestBugVerifierRunSuccess:
    @pytest.mark.asyncio
    async def test_confirmed_bug(self, tmp_path: Path) -> None:
        engine = _make_llm_engine("def test_repro():\n    assert False\n")
        adapter = _make_adapter(
            run_output="FAILED: Cannot read property 'x' of null",
        )
        agent = BugVerifier(llm_engine=engine, project_root=tmp_path)
        task = BugVerificationTask(
            target="src/app.py",
            bug_report=_make_bug_report(),
            source_code="def process_data(d): return d['x']\n",
            adapter=adapter,
        )
        result = await agent.run(task)
        assert result.status == TaskStatus.COMPLETED
        verification = result.result["verification"]
        assert isinstance(verification, VerificationResult)
        assert verification.is_confirmed is True
        assert verification.confidence == 0.95

    @pytest.mark.asyncio
    async def test_not_reproduced(self, tmp_path: Path) -> None:
        engine = _make_llm_engine("def test_repro():\n    pass\n")
        adapter = _make_adapter(run_output="1 passed", success=True)
        agent = BugVerifier(llm_engine=engine, project_root=tmp_path)
        task = BugVerificationTask(
            target="src/app.py",
            bug_report=_make_bug_report(),
            source_code="def f(): return 1\n",
            adapter=adapter,
        )
        result = await agent.run(task)
        assert result.status == TaskStatus.COMPLETED
        verification = result.result["verification"]
        assert verification.is_confirmed is False
        assert verification.confidence == 0.3

    @pytest.mark.asyncio
    async def test_exception_during_run(self, tmp_path: Path) -> None:
        engine = _make_llm_engine()
        engine.generate.side_effect = RuntimeError("llm boom")
        adapter = _make_adapter()
        agent = BugVerifier(llm_engine=engine, project_root=tmp_path)
        task = BugVerificationTask(
            target="t",
            bug_report=_make_bug_report(),
            source_code="x",
            adapter=adapter,
        )
        result = await agent.run(task)
        assert result.status == TaskStatus.FAILED
        assert "Verification error" in result.errors[0]


# ── _generate_reproduction_test ──────────────────────────────────


class TestGenerateReproductionTest:
    @pytest.mark.asyncio
    async def test_strips_code_fences(self, tmp_path: Path) -> None:
        raw = "```python\ndef test_it():\n    assert False\n```"
        engine = _make_llm_engine(raw)
        agent = BugVerifier(llm_engine=engine, project_root=tmp_path)
        adapter = _make_adapter()
        bug = _make_bug_report()
        result = await agent._generate_reproduction_test(bug, "code", adapter)
        assert "```" not in result
        assert "def test_it():" in result

    @pytest.mark.asyncio
    async def test_returns_raw_when_no_fences(self, tmp_path: Path) -> None:
        raw = "def test_it():\n    assert False"
        engine = _make_llm_engine(raw)
        agent = BugVerifier(llm_engine=engine, project_root=tmp_path)
        adapter = _make_adapter()
        bug = _make_bug_report()
        result = await agent._generate_reproduction_test(bug, "code", adapter)
        assert result == raw


# ── _create_temp_test_file ───────────────────────────────────────


class TestCreateTempTestFile:
    def test_creates_pytest_file(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        adapter = MagicMock()
        adapter.name = "pytest"
        path = agent._create_temp_test_file("test code", adapter)
        assert path.exists()
        assert path.suffix == ".py"
        assert path.read_text(encoding="utf-8") == "test code"

    def test_creates_vitest_file(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        adapter = MagicMock()
        adapter.name = "vitest"
        path = agent._create_temp_test_file("test code", adapter)
        assert path.name.endswith(".test.ts")

    def test_creates_go_file(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        adapter = MagicMock()
        adapter.name = "go test"
        path = agent._create_temp_test_file("test code", adapter)
        assert path.name.endswith("_test.go")

    def test_creates_default_extension(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        adapter = MagicMock()
        adapter.name = "unknown_framework"
        path = agent._create_temp_test_file("test code", adapter)
        assert path.name.endswith(".test.txt")


# ── _run_reproduction_test ───────────────────────────────────────


class TestRunReproductionTest:
    @pytest.mark.asyncio
    async def test_returns_raw_output(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        adapter = AsyncMock()
        adapter.run_tests.return_value = RunResult(raw_output="test output here")
        test_file = tmp_path / "test.py"
        test_file.write_text("pass", encoding="utf-8")
        output = await agent._run_reproduction_test(test_file, adapter)
        assert output == "test output here"

    @pytest.mark.asyncio
    async def test_returns_error_on_exception(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        adapter = AsyncMock()
        adapter.run_tests.side_effect = RuntimeError("boom")
        test_file = tmp_path / "test.py"
        test_file.write_text("pass", encoding="utf-8")
        output = await agent._run_reproduction_test(test_file, adapter)
        assert "failed" in output.lower()


# ── _check_bug_reproduced ───────────────────────────────────────


class TestCheckBugReproduced:
    def test_empty_output_returns_false(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        assert agent._check_bug_reproduced("", "error msg") is False

    def test_no_failure_indicator_returns_false(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        assert agent._check_bug_reproduced("all tests passed OK", "some error") is False

    def test_matching_error_returns_true(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        output = "FAILED: Cannot read property 'value' of null"
        error = "Cannot read property 'value' of null"
        assert agent._check_bug_reproduced(output, error) is True

    def test_partial_match_above_threshold(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        output = "Error: something failed with a property issue"
        error = "something failed badly"
        # "something" and "failed" are 4+ chars; both appear in output
        assert agent._check_bug_reproduced(output, error) is True

    def test_no_error_terms_falls_back_to_failure(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        # Error has only short words (< 4 chars)
        output = "Error: oh no"
        error = "oh no"
        # "oh" and "no" are < 4 chars, so no error_terms; fall back to has_failure
        assert agent._check_bug_reproduced(output, error) is True


# ── _generate_verification_notes ─────────────────────────────────


class TestVerificationNotes:
    def test_confirmed_note(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        notes = agent._generate_verification_notes(is_confirmed=True, test_output="failed")
        assert "reproduced" in notes.lower()

    def test_not_confirmed_passed(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        notes = agent._generate_verification_notes(
            is_confirmed=False, test_output="all tests passed"
        )
        assert "could not be reproduced" in notes.lower()

    def test_not_confirmed_timeout(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        notes = agent._generate_verification_notes(
            is_confirmed=False, test_output="timeout reached"
        )
        assert "timed out" in notes.lower()

    def test_not_confirmed_empty_output(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        notes = agent._generate_verification_notes(is_confirmed=False, test_output="")
        assert "no output" in notes.lower()

    def test_not_confirmed_no_match(self, tmp_path: Path) -> None:
        agent = BugVerifier(llm_engine=_make_llm_engine(), project_root=tmp_path)
        notes = agent._generate_verification_notes(
            is_confirmed=False, test_output="some random output"
        )
        assert "conclusively" in notes.lower()


# ── VerificationResult dataclass ─────────────────────────────────


class TestVerificationResultDataclass:
    def test_defaults(self) -> None:
        vr = VerificationResult(
            is_confirmed=True,
            reproduction_test="test code",
            test_output="output",
            confidence=0.9,
        )
        assert vr.notes == ""
        assert vr.is_confirmed is True
