"""Tests for the SecurityAnalyzer agent (agents/analyzers/security.py).

Covers:
- Heuristic scanning via analyze()
- LLM validation flow (mocked)
- Confidence filtering and deduplication
- SecurityReport properties
- SecurityFinding data model
- Helper functions (_parse_llm_validation, _deduplicate, _language_from_path)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nit.agents.analyzers.code import CodeMap
from nit.agents.analyzers.security import (
    CWE_MAP,
    DEFAULT_SEVERITY,
    MAX_LLM_VALIDATIONS,
    SecurityAnalysisTask,
    SecurityAnalyzer,
    SecurityFinding,
    SecurityReport,
    SecuritySeverity,
    VulnerabilityType,
    _deduplicate,
    _language_from_path,
    _parse_llm_validation,
)
from nit.agents.base import TaskInput, TaskStatus
from nit.parsing.treesitter import FunctionInfo

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project with vulnerable files."""
    project = tmp_path / "project"
    project.mkdir()

    # Python file with SQL injection
    py_file = project / "app.py"
    py_file.write_text(
        "import sqlite3\n"
        "def get_user(user_id):\n"
        '    conn = sqlite3.connect("db.sqlite")\n'
        "    cursor = conn.cursor()\n"
        '    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")\n'
        "    return cursor.fetchone()\n"
    )

    # Clean Python file (no vulns)
    clean_file = project / "utils.py"
    clean_file.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")

    return project


@pytest.fixture
def code_maps_with_vuln() -> dict[str, Any]:
    """Code maps with a Python file containing SQL injection."""
    return {
        "app.py": CodeMap(
            file_path="app.py",
            language="python",
            functions=[
                FunctionInfo(
                    name="get_user",
                    return_type="Any",
                    start_line=2,
                    end_line=6,
                    body_text='cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")',
                ),
            ],
        ),
    }


@pytest.fixture
def code_maps_clean() -> dict[str, Any]:
    """Code maps with no vulnerabilities."""
    return {
        "utils.py": CodeMap(
            file_path="utils.py",
            language="python",
            functions=[
                FunctionInfo(
                    name="add",
                    return_type="int",
                    start_line=1,
                    end_line=2,
                    body_text="return a + b",
                ),
            ],
        ),
    }


@pytest.fixture
def analyzer(tmp_project: Path) -> SecurityAnalyzer:
    """Create a SecurityAnalyzer without LLM engine."""
    return SecurityAnalyzer(
        project_root=tmp_project,
        llm_engine=None,
        enable_llm_validation=False,
    )


def _make_finding(
    vuln_type: VulnerabilityType = VulnerabilityType.SQL_INJECTION,
    severity: SecuritySeverity = SecuritySeverity.CRITICAL,
    confidence: float = 0.85,
    file_path: str = "app.py",
    line_number: int = 5,
) -> SecurityFinding:
    """Create a SecurityFinding for testing."""
    return SecurityFinding(
        vulnerability_type=vuln_type,
        severity=severity,
        file_path=file_path,
        line_number=line_number,
        function_name="get_user",
        title="SQL injection test",
        description="Test finding",
        remediation="Fix it",
        confidence=confidence,
        cwe_id=CWE_MAP.get(vuln_type),
        evidence='cursor.execute(f"SELECT...")',
    )


# ── VulnerabilityType / SecuritySeverity ─────────────────────────


class TestEnums:
    """Test enum values and mappings."""

    def test_vulnerability_types(self) -> None:
        assert len(VulnerabilityType) == 8
        assert VulnerabilityType.SQL_INJECTION.value == "sql_injection"
        assert VulnerabilityType.CREDENTIAL_LEAK.value == "credential_leak"

    def test_severity_levels(self) -> None:
        assert len(SecuritySeverity) == 5
        assert SecuritySeverity.CRITICAL.value == "critical"
        assert SecuritySeverity.INFO.value == "info"

    def test_cwe_map_complete(self) -> None:
        for vtype in VulnerabilityType:
            assert vtype in CWE_MAP, f"Missing CWE for {vtype}"

    def test_default_severity_complete(self) -> None:
        for vtype in VulnerabilityType:
            assert vtype in DEFAULT_SEVERITY, f"Missing severity for {vtype}"


# ── SecurityFinding ──────────────────────────────────────────────


class TestSecurityFinding:
    """SecurityFinding data model."""

    def test_finding_defaults(self) -> None:
        finding = _make_finding()
        assert finding.detection_method == "heuristic"
        assert finding.cwe_id == "CWE-89"

    def test_finding_all_fields(self) -> None:
        finding = SecurityFinding(
            vulnerability_type=VulnerabilityType.XSS,
            severity=SecuritySeverity.HIGH,
            file_path="view.js",
            line_number=10,
            function_name="render",
            title="XSS test",
            description="desc",
            remediation="fix",
            confidence=0.9,
            cwe_id="CWE-79",
            evidence="innerHTML = data",
            detection_method="llm_validated",
        )
        assert finding.detection_method == "llm_validated"
        assert finding.evidence == "innerHTML = data"


# ── SecurityReport ───────────────────────────────────────────────


class TestSecurityReport:
    """SecurityReport aggregation."""

    def test_empty_report(self) -> None:
        report = SecurityReport()
        assert report.critical_count == 0
        assert report.high_count == 0
        assert len(report.findings) == 0

    def test_critical_count(self) -> None:
        report = SecurityReport(
            findings=[
                _make_finding(severity=SecuritySeverity.CRITICAL),
                _make_finding(severity=SecuritySeverity.HIGH, line_number=10),
                _make_finding(severity=SecuritySeverity.CRITICAL, line_number=20),
            ],
            files_scanned=1,
        )
        assert report.critical_count == 2
        assert report.high_count == 1

    def test_get_by_severity(self) -> None:
        report = SecurityReport(
            findings=[
                _make_finding(severity=SecuritySeverity.MEDIUM, line_number=1),
                _make_finding(severity=SecuritySeverity.MEDIUM, line_number=2),
                _make_finding(severity=SecuritySeverity.LOW, line_number=3),
            ],
        )
        mediums = report.get_by_severity(SecuritySeverity.MEDIUM)
        assert len(mediums) == 2
        lows = report.get_by_severity(SecuritySeverity.LOW)
        assert len(lows) == 1


# ── Helper Functions ─────────────────────────────────────────────


class TestHelpers:
    """Test _deduplicate, _parse_llm_validation, _language_from_path."""

    def test_deduplicate_removes_same_location(self) -> None:
        findings = [
            _make_finding(line_number=5),
            _make_finding(line_number=5),
        ]
        result = _deduplicate(findings)
        assert len(result) == 1

    def test_deduplicate_keeps_different_lines(self) -> None:
        findings = [
            _make_finding(line_number=5),
            _make_finding(line_number=10),
        ]
        result = _deduplicate(findings)
        assert len(result) == 2

    def test_deduplicate_keeps_different_vuln_types(self) -> None:
        findings = [
            _make_finding(vuln_type=VulnerabilityType.SQL_INJECTION),
            _make_finding(vuln_type=VulnerabilityType.COMMAND_INJECTION),
        ]
        result = _deduplicate(findings)
        assert len(result) == 2

    def test_parse_llm_valid_true(self) -> None:
        text = "IS_VALID: true\nCONFIDENCE: 0.90\nREASONING: Real vuln."
        is_valid, confidence = _parse_llm_validation(text)
        assert is_valid is True
        assert confidence == pytest.approx(0.9)

    def test_parse_llm_valid_false(self) -> None:
        text = "IS_VALID: false\nCONFIDENCE: 0.2\nREASONING: False positive."
        is_valid, confidence = _parse_llm_validation(text)
        assert is_valid is False
        assert confidence == pytest.approx(0.2)

    def test_parse_llm_clamps_confidence(self) -> None:
        text = "IS_VALID: true\nCONFIDENCE: 1.5"
        _, confidence = _parse_llm_validation(text)
        assert confidence == 1.0

    def test_parse_llm_defaults_when_missing(self) -> None:
        text = "Some random text without the expected fields"
        is_valid, confidence = _parse_llm_validation(text)
        # Defaults: valid=True, confidence=0.75
        assert is_valid is True
        assert confidence == pytest.approx(0.75)

    def test_language_from_path_python(self) -> None:
        assert _language_from_path("src/app.py") == "python"

    def test_language_from_path_javascript(self) -> None:
        assert _language_from_path("src/app.js") == "javascript"

    def test_language_from_path_unknown(self) -> None:
        assert _language_from_path("README.md") == "unknown"

    def test_language_from_path_no_extension(self) -> None:
        assert _language_from_path("Makefile") == "unknown"


# ── SecurityAnalyzer.run() ───────────────────────────────────────


class TestSecurityAnalyzerRun:
    """Test the agent run() method."""

    @pytest.mark.asyncio
    async def test_run_invalid_task_type(self, analyzer: SecurityAnalyzer) -> None:
        task = TaskInput(task_type="other", target="x")
        result = await analyzer.run(task)
        assert result.status == TaskStatus.FAILED
        assert "Invalid task type" in result.errors[0]

    @pytest.mark.asyncio
    async def test_run_returns_report(
        self, analyzer: SecurityAnalyzer, code_maps_with_vuln: dict[str, Any]
    ) -> None:
        task = SecurityAnalysisTask(
            code_maps=code_maps_with_vuln,
            project_root=str(analyzer._project_root),
        )
        result = await analyzer.run(task)
        assert result.status == TaskStatus.COMPLETED
        assert "security_report" in result.result


# ── SecurityAnalyzer.analyze() ──────────────────────────────────


class TestSecurityAnalyzerAnalyze:
    """Test the analyze() method with heuristic scanning."""

    @pytest.mark.asyncio
    async def test_finds_sql_injection(
        self, analyzer: SecurityAnalyzer, code_maps_with_vuln: dict[str, Any]
    ) -> None:
        task = SecurityAnalysisTask(
            code_maps=code_maps_with_vuln,
            project_root=str(analyzer._project_root),
        )
        report = await analyzer.analyze(task)
        assert report.files_scanned == 1
        sql_findings = [
            f for f in report.findings if f.vulnerability_type == VulnerabilityType.SQL_INJECTION
        ]
        assert len(sql_findings) >= 1

    @pytest.mark.asyncio
    async def test_clean_code_no_findings(
        self, analyzer: SecurityAnalyzer, code_maps_clean: dict[str, Any]
    ) -> None:
        task = SecurityAnalysisTask(
            code_maps=code_maps_clean,
            project_root=str(analyzer._project_root),
        )
        report = await analyzer.analyze(task)
        assert len(report.findings) == 0

    @pytest.mark.asyncio
    async def test_skips_unknown_language(self, tmp_project: Path) -> None:
        analyzer = SecurityAnalyzer(project_root=tmp_project, enable_llm_validation=False)
        code_maps: dict[str, Any] = {
            "readme.md": CodeMap(
                file_path="readme.md",
                language="markdown",
                functions=[],
            ),
        }
        task = SecurityAnalysisTask(code_maps=code_maps)
        report = await analyzer.analyze(task)
        assert len(report.findings) == 0

    @pytest.mark.asyncio
    async def test_confidence_threshold_filters(
        self, tmp_project: Path, code_maps_with_vuln: dict[str, Any]
    ) -> None:
        analyzer = SecurityAnalyzer(
            project_root=tmp_project,
            enable_llm_validation=False,
            confidence_threshold=0.99,
        )
        task = SecurityAnalysisTask(
            code_maps=code_maps_with_vuln,
            project_root=str(tmp_project),
            confidence_threshold=0.99,
        )
        report = await analyzer.analyze(task)
        # With threshold 0.99, most heuristic findings should be filtered
        for f in report.findings:
            assert f.confidence >= 0.99

    @pytest.mark.asyncio
    async def test_findings_sorted_by_severity(
        self, analyzer: SecurityAnalyzer, code_maps_with_vuln: dict[str, Any]
    ) -> None:
        task = SecurityAnalysisTask(
            code_maps=code_maps_with_vuln,
            project_root=str(analyzer._project_root),
            confidence_threshold=0.0,
        )
        report = await analyzer.analyze(task)
        if len(report.findings) >= 2:
            severity_order = {
                SecuritySeverity.CRITICAL: 0,
                SecuritySeverity.HIGH: 1,
                SecuritySeverity.MEDIUM: 2,
                SecuritySeverity.LOW: 3,
                SecuritySeverity.INFO: 4,
            }
            for i in range(len(report.findings) - 1):
                curr = severity_order[report.findings[i].severity]
                nxt = severity_order[report.findings[i + 1].severity]
                assert curr <= nxt


# ── LLM Validation ──────────────────────────────────────────────


class TestLLMValidation:
    """Test LLM validation flow with mocked engine."""

    @pytest.mark.asyncio
    async def test_llm_validates_medium_confidence(self, tmp_project: Path) -> None:
        """Medium-confidence findings are sent to LLM for validation."""
        mock_engine = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "IS_VALID: true\nCONFIDENCE: 0.85\nREASONING: Real."
        mock_engine.generate = AsyncMock(return_value=mock_response)

        analyzer = SecurityAnalyzer(
            project_root=tmp_project,
            llm_engine=mock_engine,
            enable_llm_validation=True,
            confidence_threshold=0.5,
        )

        # Create a finding with medium confidence (below HIGH_CONFIDENCE_THRESHOLD)
        findings = [_make_finding(confidence=0.7)]

        result = await analyzer._validate_with_llm(findings)
        assert len(result) == 1
        assert result[0].confidence == pytest.approx(0.85)
        assert result[0].detection_method == "llm_validated"
        mock_engine.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_dismisses_false_positive(self, tmp_project: Path) -> None:
        """LLM can dismiss findings as false positives."""
        mock_engine = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "IS_VALID: false\nCONFIDENCE: 0.1\nREASONING: False positive."
        mock_engine.generate = AsyncMock(return_value=mock_response)

        analyzer = SecurityAnalyzer(
            project_root=tmp_project,
            llm_engine=mock_engine,
            enable_llm_validation=True,
        )

        findings = [_make_finding(confidence=0.7)]
        result = await analyzer._validate_with_llm(findings)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_high_confidence_skips_llm(self, tmp_project: Path) -> None:
        """Findings above HIGH_CONFIDENCE_THRESHOLD skip LLM."""
        mock_engine = AsyncMock()
        analyzer = SecurityAnalyzer(
            project_root=tmp_project,
            llm_engine=mock_engine,
            enable_llm_validation=True,
        )

        findings = [_make_finding(confidence=0.9)]
        result = await analyzer._validate_with_llm(findings)
        assert len(result) == 1
        assert result[0].detection_method == "heuristic"
        mock_engine.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_error_preserves_finding(self, tmp_project: Path) -> None:
        """If LLM call fails, the finding is preserved as-is."""
        mock_engine = AsyncMock()
        mock_engine.generate = AsyncMock(side_effect=RuntimeError("API error"))

        analyzer = SecurityAnalyzer(
            project_root=tmp_project,
            llm_engine=mock_engine,
            enable_llm_validation=True,
        )

        findings = [_make_finding(confidence=0.7)]
        result = await analyzer._validate_with_llm(findings)
        assert len(result) == 1
        assert result[0].detection_method == "heuristic"

    @pytest.mark.asyncio
    async def test_llm_call_cap(self, tmp_project: Path) -> None:
        """LLM calls are capped at MAX_LLM_VALIDATIONS."""
        mock_engine = AsyncMock()
        mock_response = MagicMock()
        mock_response.text = "IS_VALID: true\nCONFIDENCE: 0.85"
        mock_engine.generate = AsyncMock(return_value=mock_response)

        analyzer = SecurityAnalyzer(
            project_root=tmp_project,
            llm_engine=mock_engine,
            enable_llm_validation=True,
        )

        # Create more findings than the cap
        findings = [
            _make_finding(confidence=0.7, line_number=i) for i in range(MAX_LLM_VALIDATIONS + 5)
        ]
        await analyzer._validate_with_llm(findings)
        assert mock_engine.generate.call_count == MAX_LLM_VALIDATIONS
