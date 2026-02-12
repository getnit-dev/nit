"""Tests for the FixVerifier agent."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.adapters.base import CaseResult, CaseStatus, RunResult
from nit.agents.base import TaskInput, TaskStatus
from nit.agents.debuggers.fix_verify import (
    FixVerificationTask,
    FixVerifier,
    VerificationReport,
    _remove_sentinel,
    _restore_pending_fixes,
    _sentinel_path,
    _write_sentinel,
)

# ── Helpers ──────────────────────────────────────────────────────


def _make_generated_fix(
    fixed_code: str = "def f():\n    return 42\n",
) -> MagicMock:
    fix = MagicMock()
    fix.fixed_code = fixed_code
    return fix


def _make_adapter(
    *,
    run_result: RunResult | None = None,
    repro_result: RunResult | None = None,
) -> AsyncMock:
    adapter = AsyncMock()
    adapter.name = "pytest"

    if repro_result is None:
        repro_result = RunResult(
            passed=1,
            success=True,
            test_cases=[CaseResult(name="test_repro", status=CaseStatus.PASSED)],
        )

    if run_result is None:
        run_result = RunResult(
            passed=5,
            success=True,
            raw_output="5 passed",
            test_cases=[CaseResult(name=f"test_{i}", status=CaseStatus.PASSED) for i in range(5)],
        )

    # First call = repro test, second call = full suite
    adapter.run_tests.side_effect = [repro_result, run_result]
    return adapter


# ── Agent basics ─────────────────────────────────────────────────


class TestFixVerifierProperties:
    def test_name(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        assert agent.name == "FixVerifier"

    def test_description(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        assert "regression" in agent.description.lower()

    def test_creates_backup_dir(self, tmp_path: Path) -> None:
        FixVerifier(project_root=tmp_path)
        assert (tmp_path / ".nit" / "tmp" / "fix_backups").exists()


# ── run() validation ─────────────────────────────────────────────


class TestFixVerifierRunValidation:
    @pytest.mark.asyncio
    async def test_rejects_wrong_task_type(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        wrong_task = TaskInput(task_type="wrong", target="test")
        result = await agent.run(wrong_task)
        assert result.status == TaskStatus.FAILED
        assert "FixVerificationTask" in result.errors[0]

    @pytest.mark.asyncio
    async def test_rejects_missing_fix(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        task = FixVerificationTask(target="test.py", fix=None, adapter=AsyncMock())
        result = await agent.run(task)
        assert result.status == TaskStatus.FAILED
        assert "required" in result.errors[0].lower()

    @pytest.mark.asyncio
    async def test_rejects_missing_adapter(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        task = FixVerificationTask(target="test.py", fix=_make_generated_fix(), adapter=None)
        result = await agent.run(task)
        assert result.status == TaskStatus.FAILED
        assert "required" in result.errors[0].lower()


# ── run() success ────────────────────────────────────────────────


class TestFixVerifierRunSuccess:
    @pytest.mark.asyncio
    async def test_verified_fix(self, tmp_path: Path) -> None:
        # Create actual target file
        target_file = tmp_path / "src" / "app.py"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("def f():\n    return None\n", encoding="utf-8")

        # Create repro test file
        repro_file = tmp_path / "test_repro.py"
        repro_file.write_text("def test_it(): pass\n", encoding="utf-8")

        adapter = _make_adapter()
        agent = FixVerifier(project_root=tmp_path)
        task = FixVerificationTask(
            target=str(target_file),
            fix=_make_generated_fix(),
            original_code="def f():\n    return None\n",
            reproduction_test_file=str(repro_file),
            adapter=adapter,
        )
        result = await agent.run(task)
        assert result.status == TaskStatus.COMPLETED
        report = result.result["verification"]
        assert isinstance(report, VerificationReport)
        assert report.is_verified is True
        assert report.bug_fixed is True
        assert report.regressions_found is False

        # Original file should be restored
        assert target_file.read_text(encoding="utf-8") == "def f():\n    return None\n"

    @pytest.mark.asyncio
    async def test_fix_not_verified_bug_not_fixed(self, tmp_path: Path) -> None:
        target_file = tmp_path / "app.py"
        target_file.write_text("x = 1\n", encoding="utf-8")

        repro_file = tmp_path / "test_repro.py"
        repro_file.write_text("def test_it(): pass\n", encoding="utf-8")

        # Repro test still fails
        repro_result = RunResult(
            failed=1,
            success=False,
            test_cases=[CaseResult(name="test_repro", status=CaseStatus.FAILED)],
        )
        adapter = _make_adapter(repro_result=repro_result)
        agent = FixVerifier(project_root=tmp_path)
        task = FixVerificationTask(
            target=str(target_file),
            fix=_make_generated_fix(),
            original_code="x = 1\n",
            reproduction_test_file=str(repro_file),
            adapter=adapter,
        )
        result = await agent.run(task)
        assert result.status == TaskStatus.COMPLETED
        report = result.result["verification"]
        assert report.bug_fixed is False
        assert report.is_verified is False

    @pytest.mark.asyncio
    async def test_fix_not_verified_regressions(self, tmp_path: Path) -> None:
        target_file = tmp_path / "app.py"
        target_file.write_text("x = 1\n", encoding="utf-8")

        repro_file = tmp_path / "test_repro.py"
        repro_file.write_text("def test_it(): pass\n", encoding="utf-8")

        # Full suite has regressions
        suite_result = RunResult(
            passed=3,
            failed=2,
            success=False,
            raw_output="3 passed, 2 failed",
            test_cases=[
                CaseResult(name="test_ok", status=CaseStatus.PASSED),
                CaseResult(name="test_broken", status=CaseStatus.FAILED),
                CaseResult(name="test_broken2", status=CaseStatus.FAILED),
            ],
        )
        adapter = _make_adapter(run_result=suite_result)
        agent = FixVerifier(project_root=tmp_path)
        task = FixVerificationTask(
            target=str(target_file),
            fix=_make_generated_fix(),
            original_code="x = 1\n",
            reproduction_test_file=str(repro_file),
            adapter=adapter,
        )
        result = await agent.run(task)
        assert result.status == TaskStatus.COMPLETED
        report = result.result["verification"]
        assert report.regressions_found is True
        assert "test_broken" in report.failing_tests

    @pytest.mark.asyncio
    async def test_exception_during_verification(self, tmp_path: Path) -> None:
        target_file = tmp_path / "app.py"
        target_file.write_text("x = 1\n", encoding="utf-8")

        adapter = AsyncMock()
        adapter.run_tests.side_effect = RuntimeError("boom")
        agent = FixVerifier(project_root=tmp_path)
        task = FixVerificationTask(
            target=str(target_file),
            fix=_make_generated_fix(),
            original_code="x = 1\n",
            reproduction_test_file="",
            adapter=adapter,
        )
        result = await agent.run(task)
        # The outer exception handler catches the regression check failure
        assert result.status in (TaskStatus.FAILED, TaskStatus.COMPLETED)


# ── _resolve_target ──────────────────────────────────────────────


class TestResolveTarget:
    def test_absolute_path(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        abs_path = "/absolute/path/to/file.py"
        assert agent._resolve_target(abs_path) == Path(abs_path)

    def test_relative_path(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        result = agent._resolve_target("src/app.py")
        assert result == tmp_path / "src" / "app.py"


# ── _backup_file / _restore_backup ──────────────────────────────


class TestBackupRestore:
    def test_backup_creates_file(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        backup = agent._backup_file("app.py", "original content")
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == "original content"

    def test_restore_restores_content(self, tmp_path: Path) -> None:
        target = tmp_path / "app.py"
        target.write_text("modified content", encoding="utf-8")
        agent = FixVerifier(project_root=tmp_path)
        backup = agent._backup_file("app.py", "original content")
        agent._restore_backup(str(target), backup)
        assert target.read_text(encoding="utf-8") == "original content"


# ── _apply_fix ───────────────────────────────────────────────────


class TestApplyFix:
    def test_writes_fixed_code(self, tmp_path: Path) -> None:
        target = tmp_path / "app.py"
        target.write_text("old", encoding="utf-8")
        agent = FixVerifier(project_root=tmp_path)
        agent._apply_fix(str(target), "new fixed code")
        assert target.read_text(encoding="utf-8") == "new fixed code"


# ── _verify_bug_fixed ────────────────────────────────────────────


class TestVerifyBugFixed:
    @pytest.mark.asyncio
    async def test_returns_true_when_no_test_file(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        adapter = AsyncMock()
        assert await agent._verify_bug_fixed("", adapter) is True

    @pytest.mark.asyncio
    async def test_returns_true_when_all_pass(self, tmp_path: Path) -> None:
        repro_file = tmp_path / "test_repro.py"
        repro_file.write_text("test", encoding="utf-8")

        adapter = AsyncMock()
        adapter.run_tests.return_value = RunResult(
            passed=1,
            success=True,
            test_cases=[CaseResult(name="t", status=CaseStatus.PASSED)],
        )
        agent = FixVerifier(project_root=tmp_path)
        assert await agent._verify_bug_fixed(str(repro_file), adapter) is True

    @pytest.mark.asyncio
    async def test_returns_false_when_test_fails(self, tmp_path: Path) -> None:
        repro_file = tmp_path / "test_repro.py"
        repro_file.write_text("test", encoding="utf-8")

        adapter = AsyncMock()
        adapter.run_tests.return_value = RunResult(
            failed=1,
            success=False,
            test_cases=[CaseResult(name="t", status=CaseStatus.FAILED)],
        )
        agent = FixVerifier(project_root=tmp_path)
        assert await agent._verify_bug_fixed(str(repro_file), adapter) is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, tmp_path: Path) -> None:
        repro_file = tmp_path / "test_repro.py"
        repro_file.write_text("test", encoding="utf-8")

        adapter = AsyncMock()
        adapter.run_tests.side_effect = RuntimeError("boom")
        agent = FixVerifier(project_root=tmp_path)
        assert await agent._verify_bug_fixed(str(repro_file), adapter) is False

    @pytest.mark.asyncio
    async def test_no_test_cases_uses_success_flag(self, tmp_path: Path) -> None:
        repro_file = tmp_path / "test_repro.py"
        repro_file.write_text("test", encoding="utf-8")

        adapter = AsyncMock()
        adapter.run_tests.return_value = RunResult(success=True, test_cases=[])
        agent = FixVerifier(project_root=tmp_path)
        assert await agent._verify_bug_fixed(str(repro_file), adapter) is True


# ── _check_regressions ──────────────────────────────────────────


class TestCheckRegressions:
    @pytest.mark.asyncio
    async def test_no_regressions(self, tmp_path: Path) -> None:
        adapter = AsyncMock()
        adapter.run_tests.return_value = RunResult(
            passed=5,
            success=True,
            raw_output="5 passed",
            test_cases=[CaseResult(name=f"t{i}", status=CaseStatus.PASSED) for i in range(5)],
        )
        agent = FixVerifier(project_root=tmp_path)
        found, _output, failing = await agent._check_regressions(adapter)
        assert found is False
        assert failing == []

    @pytest.mark.asyncio
    async def test_with_regressions(self, tmp_path: Path) -> None:
        adapter = AsyncMock()
        adapter.run_tests.return_value = RunResult(
            passed=3,
            failed=2,
            success=False,
            raw_output="3 passed, 2 failed",
            test_cases=[
                CaseResult(name="ok", status=CaseStatus.PASSED),
                CaseResult(name="broken", status=CaseStatus.FAILED),
            ],
        )
        agent = FixVerifier(project_root=tmp_path)
        found, _output, failing = await agent._check_regressions(adapter)
        assert found is True
        assert "broken" in failing

    @pytest.mark.asyncio
    async def test_no_test_cases_but_failure(self, tmp_path: Path) -> None:
        adapter = AsyncMock()
        adapter.run_tests.return_value = RunResult(
            success=False,
            raw_output="error output",
            test_cases=[],
        )
        agent = FixVerifier(project_root=tmp_path)
        found, _output, failing = await agent._check_regressions(adapter)
        assert found is True
        assert len(failing) == 1

    @pytest.mark.asyncio
    async def test_exception_during_run(self, tmp_path: Path) -> None:
        adapter = AsyncMock()
        adapter.run_tests.side_effect = RuntimeError("boom")
        agent = FixVerifier(project_root=tmp_path)
        found, output, _failing = await agent._check_regressions(adapter)
        assert found is True
        assert "failed" in output.lower()


# ── _generate_verification_notes ─────────────────────────────────


class TestGenerateVerificationNotes:
    def test_verified_note(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        notes = agent._generate_verification_notes(
            is_verified=True, bug_fixed=True, regressions_found=False, failing_tests=[]
        )
        assert "verified successfully" in notes.lower()

    def test_bug_not_fixed_note(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        notes = agent._generate_verification_notes(
            is_verified=False, bug_fixed=False, regressions_found=False, failing_tests=[]
        )
        assert "not fixed" in notes.lower()

    def test_regressions_note(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        notes = agent._generate_verification_notes(
            is_verified=False,
            bug_fixed=True,
            regressions_found=True,
            failing_tests=["test_a", "test_b"],
        )
        assert "regression" in notes.lower()
        assert "test_a" in notes

    def test_many_regressions_truncated(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        failing = [f"test_{i}" for i in range(10)]
        notes = agent._generate_verification_notes(
            is_verified=False,
            bug_fixed=True,
            regressions_found=True,
            failing_tests=failing,
        )
        assert "more" in notes.lower()

    def test_inconclusive_note(self, tmp_path: Path) -> None:
        agent = FixVerifier(project_root=tmp_path)
        notes = agent._generate_verification_notes(
            is_verified=False, bug_fixed=True, regressions_found=False, failing_tests=[]
        )
        assert "inconclusive" in notes.lower()


# ── Sentinel / crash-recovery helpers ────────────────────────────


class TestSentinelHelpers:
    def test_write_and_remove_sentinel(self, tmp_path: Path) -> None:
        _write_sentinel(tmp_path, "/orig.py", "/back.bak")
        sp = _sentinel_path(tmp_path)
        assert sp.exists()
        data = json.loads(sp.read_text(encoding="utf-8"))
        assert data["original_path"] == "/orig.py"
        _remove_sentinel(tmp_path)
        assert not sp.exists()

    def test_remove_sentinel_noop_when_absent(self, tmp_path: Path) -> None:
        _remove_sentinel(tmp_path)  # should not raise

    def test_restore_pending_fixes_no_sentinel(self, tmp_path: Path) -> None:
        assert _restore_pending_fixes(tmp_path) is False

    def test_restore_pending_fixes_with_backup(self, tmp_path: Path) -> None:
        original = tmp_path / "orig.py"
        original.write_text("modified", encoding="utf-8")
        backup = tmp_path / "orig.bak"
        backup.write_text("original", encoding="utf-8")
        _write_sentinel(tmp_path, str(original), str(backup))
        assert _restore_pending_fixes(tmp_path) is True
        assert original.read_text(encoding="utf-8") == "original"

    def test_restore_pending_fixes_missing_backup(self, tmp_path: Path) -> None:
        original = tmp_path / "orig.py"
        original.write_text("content", encoding="utf-8")
        _write_sentinel(tmp_path, str(original), "/nonexistent/backup.bak")
        assert _restore_pending_fixes(tmp_path) is True  # returns True (sentinel cleaned)
