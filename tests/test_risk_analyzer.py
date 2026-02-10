"""Tests for the RiskAnalyzer (agents/analyzers/risk.py).

Covers:
- Composite risk scoring based on complexity, coverage, recency, criticality
- Domain criticality detection (auth, payment, PII, encryption, security)
- Recency scoring via git log
- Prioritized risk report generation
- Integration with CodeMap and FunctionGap
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from nit.agents.analyzers.code import CodeMap, ComplexityMetrics
from nit.agents.analyzers.coverage import FunctionGap, GapPriority
from nit.agents.analyzers.risk import (
    CriticalityDomain,
    RecencyInfo,
    RiskAnalysisTask,
    RiskAnalyzer,
    RiskLevel,
    RiskScore,
)
from nit.agents.base import TaskInput, TaskStatus
from nit.parsing.treesitter import FunctionInfo, ImportInfo

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    project = tmp_path / "test_project"
    project.mkdir()
    return project


@pytest.fixture
def risk_analyzer(tmp_project: Path) -> RiskAnalyzer:
    """Create a RiskAnalyzer instance."""
    return RiskAnalyzer(project_root=tmp_project)


@pytest.fixture
def sample_code_map() -> CodeMap:
    """Create a sample code map for testing."""
    return CodeMap(
        file_path="src/auth.py",
        language="python",
        functions=[
            FunctionInfo(
                name="authenticate_user",
                return_type="User",
                start_line=10,
                end_line=25,
                body_text="""
    if username and password:
        user = db.query(User).filter_by(username=username).first()
        if user and bcrypt.verify(password, user.password_hash):
            return user
    return None
                """,
            ),
            FunctionInfo(
                name="generate_token",
                return_type="str",
                start_line=30,
                end_line=40,
                body_text="""
    payload = {'user_id': user.id, 'exp': datetime.utcnow() + timedelta(hours=1)}
    token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
    return token
                """,
            ),
        ],
        imports=[
            ImportInfo(module="bcrypt", names=["verify"]),
            ImportInfo(module="jwt", names=["encode"]),
            ImportInfo(module="sqlalchemy.orm", names=["Session"]),
        ],
        complexity_map={
            "authenticate_user": ComplexityMetrics(cyclomatic=4, decision_points={"if": 2}),
            "generate_token": ComplexityMetrics(cyclomatic=1, decision_points={}),
        },
    )


@pytest.fixture
def payment_code_map() -> CodeMap:
    """Create a code map with payment-related code."""
    return CodeMap(
        file_path="src/payment.py",
        language="python",
        functions=[
            FunctionInfo(
                name="process_payment",
                return_type="bool",
                start_line=10,
                end_line=30,
                body_text="""
    stripe_api = stripe.PaymentIntent.create(
        amount=amount,
        currency='usd',
        payment_method_types=['card']
    )
    return stripe_api.status == 'succeeded'
                """,
            ),
        ],
        imports=[
            ImportInfo(module="stripe", names=["PaymentIntent"]),
        ],
        complexity_map={
            "process_payment": ComplexityMetrics(cyclomatic=2, decision_points={"if": 1}),
        },
    )


@pytest.fixture
def simple_code_map() -> CodeMap:
    """Create a simple code map with no criticality."""
    return CodeMap(
        file_path="src/utils.py",
        language="python",
        functions=[
            FunctionInfo(
                name="format_name",
                return_type="str",
                start_line=5,
                end_line=7,
                body_text="return f'{first} {last}'",
            ),
        ],
        complexity_map={
            "format_name": ComplexityMetrics(cyclomatic=1, decision_points={}),
        },
    )


# ── Risk Score Calculation Tests ─────────────────────────────────


def test_risk_analyzer_initialization(risk_analyzer: RiskAnalyzer, tmp_project: Path) -> None:
    """Test RiskAnalyzer initialization."""
    assert risk_analyzer.name == "risk_analyzer"
    assert "risk" in risk_analyzer.description.lower()
    assert risk_analyzer._root == tmp_project


@pytest.mark.asyncio
async def test_risk_analysis_basic(risk_analyzer: RiskAnalyzer, sample_code_map: CodeMap) -> None:
    """Test basic risk analysis execution."""
    task = RiskAnalysisTask(
        project_root=str(risk_analyzer._root),
        code_maps={"src/auth.py": sample_code_map},
        function_gaps=[
            FunctionGap(
                file_path="src/auth.py",
                function_name="authenticate_user",
                line_number=10,
                end_line=25,
                coverage_percentage=0.0,
                complexity=4,
                is_public=True,
                priority=GapPriority.CRITICAL,
            ),
        ],
    )

    with patch.object(risk_analyzer, "_get_recency_info", return_value=RecencyInfo()):
        output = await risk_analyzer.run(task)

    assert output.status == TaskStatus.COMPLETED
    assert "risk_report" in output.result
    report = output.result["risk_report"]
    assert len(report.file_risks) == 1
    assert report.file_risks[0].file_path == "src/auth.py"


@pytest.mark.asyncio
async def test_invalid_task_type(risk_analyzer: RiskAnalyzer) -> None:
    """Test that invalid task type is rejected."""
    task = TaskInput(task_type="wrong_type", target="dummy")
    output = await risk_analyzer.run(task)

    assert output.status == TaskStatus.FAILED
    assert "RiskAnalysisTask" in output.errors[0]


# ── Domain Criticality Detection Tests ───────────────────────────


def test_detect_auth_criticality(risk_analyzer: RiskAnalyzer, sample_code_map: CodeMap) -> None:
    """Test detection of authentication-related criticality."""
    domains = risk_analyzer._detect_criticality_domains(sample_code_map)

    assert CriticalityDomain.AUTHENTICATION in domains
    assert CriticalityDomain.ENCRYPTION in domains  # bcrypt detected


def test_detect_payment_criticality(risk_analyzer: RiskAnalyzer, payment_code_map: CodeMap) -> None:
    """Test detection of payment-related criticality."""
    domains = risk_analyzer._detect_criticality_domains(payment_code_map)

    assert CriticalityDomain.PAYMENT in domains


def test_detect_no_criticality(risk_analyzer: RiskAnalyzer, simple_code_map: CodeMap) -> None:
    """Test that non-critical code has no detected domains."""
    domains = risk_analyzer._detect_criticality_domains(simple_code_map)

    assert domains == [CriticalityDomain.NONE]


def test_detect_multiple_criticality_domains(risk_analyzer: RiskAnalyzer) -> None:
    """Test detection of multiple criticality domains in one file."""
    code_map = CodeMap(
        file_path="src/security.py",
        language="python",
        functions=[
            FunctionInfo(
                name="secure_payment_with_encryption",
                return_type="bool",
                start_line=10,
                end_line=30,
                body_text="""
    encrypted_card = encrypt_aes(card_data)
    user = get_user_by_email(user_email)
    payment_result = stripe.charge(encrypted_card, amount)
    return payment_result.success
                """,
            ),
        ],
        imports=[
            ImportInfo(module="cryptography.fernet", names=["Fernet"]),
            ImportInfo(module="stripe", names=["charge"]),
        ],
    )

    domains = risk_analyzer._detect_criticality_domains(code_map)

    assert CriticalityDomain.ENCRYPTION in domains
    assert CriticalityDomain.PAYMENT in domains
    # Note: PII is not detected because variable names like "user_email" don't trigger
    # the PII detection (which looks for actual PII handling code)


def test_detect_function_criticality(risk_analyzer: RiskAnalyzer) -> None:
    """Test criticality detection for individual functions."""
    domains = risk_analyzer._detect_function_criticality(
        function_name="validate_password",
        function_body="hash = bcrypt.hash(password); return verify(hash)",
    )

    assert CriticalityDomain.AUTHENTICATION in domains
    assert CriticalityDomain.ENCRYPTION in domains


# ── Recency Scoring Tests ────────────────────────────────────────


def test_get_recency_info_recent_file(risk_analyzer: RiskAnalyzer, tmp_project: Path) -> None:
    """Test recency info for recently modified file."""
    file_path = tmp_project / "src/recent.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("# test file")

    # Mock git log output for recent file (5 days ago)
    now = datetime.now(UTC)
    five_days_ago = now - timedelta(days=5)
    timestamp = int(five_days_ago.timestamp())

    with patch("subprocess.run") as mock_run:
        # Mock last modification time
        mock_run.return_value = Mock(returncode=0, stdout=f"{timestamp}\n", stderr="")
        recency_info = risk_analyzer._get_recency_info(str(file_path))

        assert recency_info.last_modified is not None
        assert recency_info.days_since_modified is not None
        assert recency_info.days_since_modified <= 7


def test_get_recency_info_old_file(risk_analyzer: RiskAnalyzer, tmp_project: Path) -> None:
    """Test recency info for old file."""
    file_path = tmp_project / "src/old.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("# test file")

    # Mock git log output for old file (200 days ago)
    now = datetime.now(UTC)
    old_date = now - timedelta(days=200)
    timestamp = int(old_date.timestamp())

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0, stdout=f"{timestamp}\n", stderr="")
        recency_info = risk_analyzer._get_recency_info(str(file_path))

        assert recency_info.last_modified is not None
        assert recency_info.days_since_modified is not None
        assert recency_info.days_since_modified >= 100


def test_get_recency_info_no_git(risk_analyzer: RiskAnalyzer, tmp_project: Path) -> None:
    """Test recency info when git is not available."""
    file_path = tmp_project / "src/no_git.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("# test file")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="not a git repository")
        recency_info = risk_analyzer._get_recency_info(str(file_path))

        assert recency_info.last_modified is None
        assert recency_info.days_since_modified is None
        assert recency_info.commit_count_90d == 0


def test_get_recency_info_multiple_commits(risk_analyzer: RiskAnalyzer, tmp_project: Path) -> None:
    """Test recency info with multiple recent commits."""
    file_path = tmp_project / "src/active.py"

    # Mock git responses
    def mock_git_command(*args: Any, **kwargs: Any) -> Mock:
        cmd = args[0]
        if "--format=%at" in cmd:
            # Last modification: 3 days ago
            timestamp = int((datetime.now(UTC) - timedelta(days=3)).timestamp())
            return Mock(returncode=0, stdout=f"{timestamp}\n", stderr="")
        if "--format=%H" in cmd:
            # 15 commits in last 90 days
            commits = "\n".join([f"commit{i}" for i in range(15)])
            return Mock(returncode=0, stdout=commits, stderr="")
        if "--format=%an" in cmd:
            # 3 authors
            return Mock(returncode=0, stdout="Alice\nBob\nCharlie\n", stderr="")
        return Mock(returncode=1, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_git_command):
        recency_info = risk_analyzer._get_recency_info(str(file_path))

        assert recency_info.commit_count_90d == 15
        assert len(recency_info.recent_authors) == 3
        assert "Alice" in recency_info.recent_authors


# ── Risk Score Calculation Tests ─────────────────────────────────


def test_calculate_risk_score_high_complexity(risk_analyzer: RiskAnalyzer) -> None:
    """Test risk score for high complexity code."""
    risk_score = risk_analyzer._calculate_risk_score(
        complexity=15.0,  # High complexity
        coverage_percentage=100.0,
        recency_info=RecencyInfo(),
        criticality_domains=[CriticalityDomain.NONE],
    )

    assert risk_score.complexity_score >= 0.8
    assert risk_score.overall_score > 0.0


def test_calculate_risk_score_zero_coverage(risk_analyzer: RiskAnalyzer) -> None:
    """Test risk score for code with zero coverage."""
    risk_score = risk_analyzer._calculate_risk_score(
        complexity=5.0,
        coverage_percentage=0.0,  # No coverage
        recency_info=RecencyInfo(),
        criticality_domains=[CriticalityDomain.NONE],
    )

    assert risk_score.coverage_score == 1.0
    assert risk_score.overall_score > 0.0


def test_calculate_risk_score_recent_changes(risk_analyzer: RiskAnalyzer) -> None:
    """Test risk score for recently changed code."""
    recency_info = RecencyInfo(
        last_modified=datetime.now(UTC) - timedelta(days=3),
        days_since_modified=3,
        commit_count_90d=5,
    )

    risk_score = risk_analyzer._calculate_risk_score(
        complexity=5.0,
        coverage_percentage=100.0,
        recency_info=recency_info,
        criticality_domains=[CriticalityDomain.NONE],
    )

    assert risk_score.recency_score >= 0.8
    assert risk_score.overall_score > 0.0


def test_calculate_risk_score_critical_domain(risk_analyzer: RiskAnalyzer) -> None:
    """Test risk score for code in critical domain."""
    risk_score = risk_analyzer._calculate_risk_score(
        complexity=5.0,
        coverage_percentage=100.0,
        recency_info=RecencyInfo(),
        criticality_domains=[
            CriticalityDomain.AUTHENTICATION,
            CriticalityDomain.ENCRYPTION,
        ],
    )

    assert risk_score.criticality_score > 0.0
    assert risk_score.overall_score > 0.0


def test_calculate_risk_score_maximum_risk(risk_analyzer: RiskAnalyzer) -> None:
    """Test risk score for maximum risk scenario."""
    recency_info = RecencyInfo(
        last_modified=datetime.now(UTC),
        days_since_modified=0,
        commit_count_90d=20,
    )

    risk_score = risk_analyzer._calculate_risk_score(
        complexity=20.0,  # Very high
        coverage_percentage=0.0,  # Zero coverage
        recency_info=recency_info,  # Just changed
        criticality_domains=[
            CriticalityDomain.AUTHENTICATION,
            CriticalityDomain.PAYMENT,
            CriticalityDomain.PII,
        ],
    )

    assert risk_score.overall_score >= 0.8
    assert risk_score.level == RiskLevel.CRITICAL


def test_calculate_risk_score_minimum_risk(risk_analyzer: RiskAnalyzer) -> None:
    """Test risk score for minimum risk scenario."""
    recency_info = RecencyInfo(
        last_modified=datetime.now(UTC) - timedelta(days=365),
        days_since_modified=365,
        commit_count_90d=0,
    )

    risk_score = risk_analyzer._calculate_risk_score(
        complexity=1.0,  # Simple
        coverage_percentage=100.0,  # Full coverage
        recency_info=recency_info,  # Old, stable
        criticality_domains=[CriticalityDomain.NONE],
    )

    assert risk_score.overall_score < 0.4
    assert risk_score.level == RiskLevel.LOW


def test_risk_level_classification() -> None:
    """Test risk level classification boundaries."""
    assert RiskScore.classify_level(0.85) == RiskLevel.CRITICAL
    assert RiskScore.classify_level(0.8) == RiskLevel.CRITICAL
    assert RiskScore.classify_level(0.7) == RiskLevel.HIGH
    assert RiskScore.classify_level(0.6) == RiskLevel.HIGH
    assert RiskScore.classify_level(0.5) == RiskLevel.MEDIUM
    assert RiskScore.classify_level(0.4) == RiskLevel.MEDIUM
    assert RiskScore.classify_level(0.3) == RiskLevel.LOW
    assert RiskScore.classify_level(0.1) == RiskLevel.LOW


# ── Risk Report Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_risk_report_prioritization(
    risk_analyzer: RiskAnalyzer, sample_code_map: CodeMap, simple_code_map: CodeMap
) -> None:
    """Test that risk report prioritizes files correctly."""
    task = RiskAnalysisTask(
        project_root=str(risk_analyzer._root),
        code_maps={
            "src/auth.py": sample_code_map,
            "src/utils.py": simple_code_map,
        },
        function_gaps=[
            FunctionGap(
                file_path="src/auth.py",
                function_name="authenticate_user",
                line_number=10,
                end_line=25,
                coverage_percentage=0.0,
                complexity=4,
                is_public=True,
                priority=GapPriority.CRITICAL,
            ),
            FunctionGap(
                file_path="src/utils.py",
                function_name="format_name",
                line_number=5,
                end_line=7,
                coverage_percentage=100.0,
                complexity=1,
                is_public=True,
                priority=GapPriority.LOW,
            ),
        ],
    )

    with patch.object(risk_analyzer, "_get_recency_info", return_value=RecencyInfo()):
        output = await risk_analyzer.run(task)

    report = output.result["risk_report"]
    prioritized = report.get_prioritized_files()

    # auth.py should be higher risk than utils.py
    assert len(prioritized) == 2
    assert prioritized[0].file_path == "src/auth.py"
    assert prioritized[1].file_path == "src/utils.py"
    assert prioritized[0].risk_score.overall_score > prioritized[1].risk_score.overall_score


@pytest.mark.asyncio
async def test_risk_report_critical_files(
    risk_analyzer: RiskAnalyzer, sample_code_map: CodeMap
) -> None:
    """Test identification of critical files."""
    # Make the code map appear very high risk
    task = RiskAnalysisTask(
        project_root=str(risk_analyzer._root),
        code_maps={"src/auth.py": sample_code_map},
        function_gaps=[
            FunctionGap(
                file_path="src/auth.py",
                function_name="authenticate_user",
                line_number=10,
                end_line=25,
                coverage_percentage=0.0,  # No coverage
                complexity=15,  # High complexity
                is_public=True,
                priority=GapPriority.CRITICAL,
            ),
        ],
    )

    # Mock very recent changes
    recent_recency = RecencyInfo(
        last_modified=datetime.now(UTC),
        days_since_modified=0,
        commit_count_90d=20,
    )

    with patch.object(risk_analyzer, "_get_recency_info", return_value=recent_recency):
        output = await risk_analyzer.run(task)

    report = output.result["risk_report"]

    # Should identify as critical or high risk
    assert len(report.critical_files) > 0 or len(report.high_risk_files) > 0


@pytest.mark.asyncio
async def test_function_risk_analysis(
    risk_analyzer: RiskAnalyzer, sample_code_map: CodeMap
) -> None:
    """Test function-level risk analysis."""
    task = RiskAnalysisTask(
        project_root=str(risk_analyzer._root),
        code_maps={"src/auth.py": sample_code_map},
        function_gaps=[
            FunctionGap(
                file_path="src/auth.py",
                function_name="authenticate_user",
                line_number=10,
                end_line=25,
                coverage_percentage=0.0,
                complexity=4,
                is_public=True,
                priority=GapPriority.CRITICAL,
            ),
            FunctionGap(
                file_path="src/auth.py",
                function_name="generate_token",
                line_number=30,
                end_line=40,
                coverage_percentage=100.0,
                complexity=1,
                is_public=True,
                priority=GapPriority.LOW,
            ),
        ],
    )

    with patch.object(risk_analyzer, "_get_recency_info", return_value=RecencyInfo()):
        output = await risk_analyzer.run(task)

    report = output.result["risk_report"]
    prioritized_functions = report.get_prioritized_functions()

    assert len(prioritized_functions) == 2
    # authenticate_user should be higher risk
    assert prioritized_functions[0].function_name == "authenticate_user"
    assert (
        prioritized_functions[0].risk_score.overall_score
        > prioritized_functions[1].risk_score.overall_score
    )


def test_risk_report_empty(risk_analyzer: RiskAnalyzer) -> None:
    """Test risk report with no code maps."""
    task = RiskAnalysisTask(
        project_root=str(risk_analyzer._root),
        code_maps={},
        function_gaps=[],
    )

    report = risk_analyzer.analyze_risk(task)

    assert len(report.file_risks) == 0
    assert len(report.function_risks) == 0
    assert len(report.critical_files) == 0
