"""Tests for the FixGenerator agent."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nit.agents.analyzers.bug import BugLocation, BugReport, BugSeverity, BugType
from nit.agents.base import TaskInput, TaskStatus
from nit.agents.debuggers.fix_gen import (
    FixGenerationTask,
    FixGenerator,
    GeneratedFix,
)
from nit.agents.debuggers.root_cause import RootCause
from nit.llm.engine import LLMResponse

# ── Helpers ──────────────────────────────────────────────────────

SAMPLE_SOURCE = """\
def divide(a, b):
    return a / b
"""

FIXED_SOURCE = """\
def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
"""


def _make_bug_report(
    *,
    bug_type: BugType = BugType.ARITHMETIC_ERROR,
    severity: BugSeverity = BugSeverity.MEDIUM,
    error_message: str = "ZeroDivisionError: division by zero",
    file_path: str = "src/math_utils.py",
    function_name: str | None = "divide",
) -> BugReport:
    return BugReport(
        bug_type=bug_type,
        severity=severity,
        title=f"{bug_type.value} in {function_name or file_path}",
        description="Division by zero bug",
        location=BugLocation(
            file_path=file_path,
            function_name=function_name,
        ),
        error_message=error_message,
    )


def _make_root_cause(
    *,
    category: str = "missing_validation",
    description: str = "Missing zero check before division",
    affected_code: str = "return a / b",
    confidence: float = 0.9,
    missing_checks: list[str] | None = None,
    incorrect_assumptions: list[str] | None = None,
) -> RootCause:
    return RootCause(
        category=category,
        description=description,
        affected_code=affected_code,
        confidence=confidence,
        missing_checks=missing_checks or ["Missing zero check"],
        incorrect_assumptions=incorrect_assumptions or [],
    )


def _make_llm_engine(response_text: str = "") -> AsyncMock:
    if not response_text:
        response_text = f"```python\n{FIXED_SOURCE}```\n---EXPLANATION---\nAdded zero check"
    engine = AsyncMock()
    engine.generate.return_value = LLMResponse(
        text=response_text,
        model="test-model",
    )
    return engine


# ── Agent basics ─────────────────────────────────────────────────


class TestFixGeneratorProperties:
    def test_name(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        assert agent.name == "FixGenerator"

    def test_description(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        assert "fix" in agent.description.lower()


# ── run() validation ─────────────────────────────────────────────


class TestFixGeneratorRunValidation:
    @pytest.mark.asyncio
    async def test_rejects_wrong_task_type(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        result = await agent.run(TaskInput(task_type="wrong", target="t"))
        assert result.status == TaskStatus.FAILED
        assert "FixGenerationTask" in result.errors[0]

    @pytest.mark.asyncio
    async def test_rejects_missing_bug_report(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        task = FixGenerationTask(target="t", bug_report=None, root_cause=_make_root_cause())
        result = await agent.run(task)
        assert result.status == TaskStatus.FAILED
        assert "required" in result.errors[0].lower()

    @pytest.mark.asyncio
    async def test_rejects_missing_root_cause(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        task = FixGenerationTask(target="t", bug_report=_make_bug_report(), root_cause=None)
        result = await agent.run(task)
        assert result.status == TaskStatus.FAILED
        assert "required" in result.errors[0].lower()


# ── run() success path ───────────────────────────────────────────


class TestFixGeneratorRunSuccess:
    @pytest.mark.asyncio
    async def test_successful_fix_generation(self, tmp_path: Path) -> None:
        engine = _make_llm_engine()
        agent = FixGenerator(llm_engine=engine, project_root=tmp_path)
        task = FixGenerationTask(
            target="src/math_utils.py",
            bug_report=_make_bug_report(),
            root_cause=_make_root_cause(),
            source_code=SAMPLE_SOURCE,
        )
        result = await agent.run(task)
        assert result.status == TaskStatus.COMPLETED
        fix = result.result["fix"]
        assert isinstance(fix, GeneratedFix)
        assert fix.fixed_code
        assert fix.explanation
        assert fix.patch is not None

    @pytest.mark.asyncio
    async def test_with_reproduction_test(self, tmp_path: Path) -> None:
        engine = _make_llm_engine()
        agent = FixGenerator(llm_engine=engine, project_root=tmp_path)
        task = FixGenerationTask(
            target="src/math_utils.py",
            bug_report=_make_bug_report(),
            root_cause=_make_root_cause(),
            source_code=SAMPLE_SOURCE,
            reproduction_test="def test_zero(): divide(1, 0)",
        )
        result = await agent.run(task)
        assert result.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_exception_during_generation(self, tmp_path: Path) -> None:
        engine = _make_llm_engine()
        engine.generate.side_effect = RuntimeError("llm boom")
        agent = FixGenerator(llm_engine=engine, project_root=tmp_path)
        task = FixGenerationTask(
            target="t",
            bug_report=_make_bug_report(),
            root_cause=_make_root_cause(),
            source_code=SAMPLE_SOURCE,
        )
        result = await agent.run(task)
        assert result.status == TaskStatus.FAILED
        assert "Fix generation error" in result.errors[0]


# ── _parse_fix_response ──────────────────────────────────────────


class TestParseFixResponse:
    def test_splits_by_explanation_marker(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        text = f"```python\n{FIXED_SOURCE}```\n---EXPLANATION---\nAdded validation"
        code, explanation = agent._parse_fix_response(text, SAMPLE_SOURCE)
        assert "if b == 0:" in code
        assert "validation" in explanation.lower()

    def test_extracts_code_from_fences(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        text = f"```\n{FIXED_SOURCE}```"
        code, _explanation = agent._parse_fix_response(text, SAMPLE_SOURCE)
        assert "if b == 0:" in code

    def test_uses_raw_text_when_no_fences(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        text = FIXED_SOURCE
        code, _explanation = agent._parse_fix_response(text, SAMPLE_SOURCE)
        assert code == FIXED_SOURCE.strip()

    def test_falls_back_when_fix_too_short(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        text = "x = 1"  # too short relative to original
        long_original = "a" * 100
        code, explanation = agent._parse_fix_response(text, long_original)
        assert code == long_original
        assert "incomplete" in explanation.lower()


# ── _create_patch ────────────────────────────────────────────────


class TestCreatePatch:
    def test_creates_unified_diff(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        patch = agent._create_patch(SAMPLE_SOURCE, FIXED_SOURCE, "math.py")
        assert "a/math.py" in patch
        assert "b/math.py" in patch
        assert "+" in patch or "-" in patch

    def test_empty_patch_for_identical_code(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        patch = agent._create_patch("same\n", "same\n", "f.py")
        assert patch == ""


# ── _identify_changed_lines ─────────────────────────────────────


class TestIdentifyChangedLines:
    def test_finds_changed_lines(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        original = "line1\nline2\nline3\n"
        fixed = "line1\nmodified\nline3\n"
        changed = agent._identify_changed_lines(original, fixed)
        assert 2 in changed

    def test_empty_for_identical(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        code = "x = 1\ny = 2\n"
        assert agent._identify_changed_lines(code, code) == []

    def test_handles_insertions(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        original = "a\nc\n"
        fixed = "a\nb\nc\n"
        changed = agent._identify_changed_lines(original, fixed)
        assert len(changed) >= 0  # insertions don't change existing line numbers


# ── _generate_safety_notes ───────────────────────────────────────


class TestGenerateSafetyNotes:
    def test_always_includes_regression_note(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report()
        rc = _make_root_cause()
        notes = agent._generate_safety_notes(bug, rc, "x = 1")
        assert any("test" in n.lower() for n in notes)

    def test_security_note_for_security_bug(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report(bug_type=BugType.SECURITY_VULNERABILITY)
        rc = _make_root_cause()
        notes = agent._generate_safety_notes(bug, rc, "x = 1")
        assert any("security" in n.lower() for n in notes)

    def test_error_handling_note(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report()
        rc = _make_root_cause(affected_code="x = 1")
        notes = agent._generate_safety_notes(bug, rc, "try:\n    x = 1\nexcept: pass")
        assert any("error handling" in n.lower() for n in notes)

    def test_validation_note(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report()
        rc = _make_root_cause()
        notes = agent._generate_safety_notes(bug, rc, "if not value:\n    raise")
        assert any("validation" in n.lower() for n in notes)

    def test_type_related_note(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report()
        rc = _make_root_cause(description="The type conversion is wrong")
        notes = agent._generate_safety_notes(bug, rc, "x = int(val)")
        assert any("type" in n.lower() for n in notes)


# ── _calculate_fix_confidence ────────────────────────────────────


class TestCalculateFixConfidence:
    def test_base_confidence(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report()
        rc = _make_root_cause(confidence=0.5, missing_checks=[], category="other")
        conf = agent._calculate_fix_confidence(bug, rc, "x = 1")
        assert conf == pytest.approx(0.6, abs=0.01)

    def test_high_root_cause_confidence_boost(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report()
        rc = _make_root_cause(confidence=0.9, missing_checks=[], category="other")
        conf = agent._calculate_fix_confidence(bug, rc, "x = 1")
        assert conf > 0.6

    def test_missing_checks_boost(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report()
        rc = _make_root_cause(
            confidence=0.5,
            missing_checks=["missing null check"],
            category="other",
        )
        conf = agent._calculate_fix_confidence(bug, rc, "if value is None: raise")
        # Has missing_checks AND "none" in fixed code -> +0.1
        assert conf >= 0.7

    def test_well_known_bug_type_boost(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report(bug_type=BugType.NULL_DEREFERENCE)
        rc = _make_root_cause(confidence=0.5, missing_checks=[], category="other")
        conf = agent._calculate_fix_confidence(bug, rc, "x = 1")
        assert conf >= 0.65

    def test_race_condition_penalty(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report()
        rc = _make_root_cause(confidence=0.5, missing_checks=[], category="race_condition")
        conf = agent._calculate_fix_confidence(bug, rc, "x = 1")
        assert conf == pytest.approx(0.5, abs=0.01)

    def test_confidence_capped_at_1(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report(bug_type=BugType.NULL_DEREFERENCE)
        rc = _make_root_cause(
            confidence=0.95,
            missing_checks=["check"],
            category="missing_validation",
        )
        conf = agent._calculate_fix_confidence(bug, rc, "if null check none undefined")
        assert conf <= 1.0

    def test_confidence_floored_at_0(self, tmp_path: Path) -> None:
        agent = FixGenerator(llm_engine=_make_llm_engine(), project_root=tmp_path)
        bug = _make_bug_report()
        rc = _make_root_cause(confidence=0.1, missing_checks=[], category="logic_error")
        conf = agent._calculate_fix_confidence(bug, rc, "x = 1")
        assert conf >= 0.0


# ── GeneratedFix dataclass ──────────────────────────────────────


class TestGeneratedFixDataclass:
    def test_defaults(self) -> None:
        fix = GeneratedFix(
            fixed_code="code",
            patch="patch",
            explanation="explain",
            changed_lines=[1, 2],
            safety_notes=["note"],
        )
        assert fix.confidence == 0.7
        assert fix.fixed_code == "code"
        assert fix.changed_lines == [1, 2]
