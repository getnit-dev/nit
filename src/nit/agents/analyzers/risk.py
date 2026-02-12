"""RiskAnalyzer agent — computes composite risk scores for prioritization.

This agent (task 1.21):
1. Composite risk scoring: combines complexity, coverage, recency, criticality
2. Domain criticality detection: identifies auth, payment, PII, encryption code
3. Recency scoring: weights recently changed files higher via git log
4. Outputs prioritized risk report for orchestrator task ordering
5. Provides per-file and per-function risk metrics
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus

if TYPE_CHECKING:
    from pathlib import Path

    from nit.agents.analyzers.code import CodeMap
    from nit.agents.analyzers.coverage import FunctionGap

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

# Risk scoring weights (sum to 1.0)
WEIGHT_COMPLEXITY = 0.3  # Cyclomatic complexity weight
WEIGHT_COVERAGE = 0.25  # Coverage gap weight
WEIGHT_RECENCY = 0.25  # Recent changes weight
WEIGHT_CRITICALITY = 0.2  # Domain criticality weight

# Risk level classification thresholds
RISK_LEVEL_CRITICAL = 0.8  # Score >= 0.8 is CRITICAL
RISK_LEVEL_HIGH = 0.6  # Score >= 0.6 is HIGH
RISK_LEVEL_MEDIUM = 0.4  # Score >= 0.4 is MEDIUM

# Recency scoring thresholds (days)
RECENCY_VERY_RECENT = 7  # Changed in last week
RECENCY_RECENT = 30  # Changed in last month
RECENCY_MODERATE = 90  # Changed in last 3 months

# Commit frequency thresholds (for 90-day window)
COMMITS_HIGH_ACTIVITY = 10  # Many recent commits
COMMITS_MODERATE_ACTIVITY = 5  # Some recent commits

# Complexity scoring thresholds
COMPLEXITY_HIGH = 10
COMPLEXITY_MODERATE = 5

# Coverage scoring thresholds
COVERAGE_NONE = 0.0
COVERAGE_LOW = 25.0
COVERAGE_MODERATE = 50.0


class RiskLevel(Enum):
    """Risk level classification."""

    CRITICAL = "critical"  # Risk score >= 0.8
    HIGH = "high"  # Risk score >= 0.6
    MEDIUM = "medium"  # Risk score >= 0.4
    LOW = "low"  # Risk score < 0.4


class CriticalityDomain(Enum):
    """Critical code domains requiring extra attention."""

    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    PAYMENT = "payment"
    PII = "pii"  # Personally Identifiable Information
    ENCRYPTION = "encryption"
    SECURITY = "security"
    NONE = "none"


# Domain criticality detection patterns (task 1.21.2)
CRITICALITY_PATTERNS = {
    CriticalityDomain.AUTHENTICATION: [
        r"\bauth\b",
        r"\blogin\b",
        r"\bsignin\b",
        r"\bsignup\b",
        r"\bregister\b",
        r"\bpassword\b",
        r"\bcredential\b",
        r"\btoken\b",
        r"\bjwt\b",
        r"\bsession\b",
        r"\bcookie\b",
        r"\boauth\b",
        r"\bsaml\b",
        r"\bldap\b",
    ],
    CriticalityDomain.AUTHORIZATION: [
        r"\bpermission\b",
        r"\brole\b",
        r"\baccess\b",
        r"\brbac\b",
        r"\bpolicy\b",
        r"\bauthorize\b",
        r"\ballow\b",
        r"\bdeny\b",
        r"\bgrant\b",
        r"\bscope\b",
    ],
    CriticalityDomain.PAYMENT: [
        r"\bpayment\b",
        r"\bcharge\b",
        r"\bbilling\b",
        r"\binvoice\b",
        r"\bstripe\b",
        r"\bpaypal\b",
        r"\bcredit\s*card\b",
        r"\bcard\s*number\b",
        r"\btransaction\b",
        r"\brefund\b",
        r"\bpurchase\b",
        r"\bcheckout\b",
    ],
    CriticalityDomain.PII: [
        r"\bemail\b",
        r"\bphone\b",
        r"\baddress\b",
        r"\bssn\b",
        r"\bsocial\s*security\b",
        r"\bpii\b",
        r"\bpersonally\s*identifiable\b",
        r"\buser\s*data\b",
        r"\bprofile\b",
        r"\bcontact\b",
        r"\bgdpr\b",
        r"\bccpa\b",
    ],
    CriticalityDomain.ENCRYPTION: [
        r"\bencrypt",  # matches encrypt, encryption, encrypted, etc.
        r"\bdecrypt",  # matches decrypt, decryption, decrypted, etc.
        r"\bhash\b",
        r"\bcrypto",  # matches crypto, cryptography, etc.
        r"\baes\b",
        r"\brsa\b",
        r"\bsha\d+\b",
        r"\bmd5\b",
        r"\bbcrypt\b",
        r"\bscrypt\b",
        r"\bpbkdf2\b",
        r"\bcipher\b",
        r"\bkey\s*derivation\b",
    ],
    CriticalityDomain.SECURITY: [
        r"\bsecurity\b",
        r"\bvulnerable\b",
        r"\bsanitize\b",
        r"\bvalidate\b",
        r"\bescape\b",
        r"\bxss\b",
        r"\bsql\s*injection\b",
        r"\bcsrf\b",
        r"\bcors\b",
        r"\bcsp\b",
        r"\bcontent\s*security\s*policy\b",
    ],
}


# ── Data models ──────────────────────────────────────────────────


@dataclass
class RecencyInfo:
    """Information about recent changes to a file."""

    last_modified: datetime | None = None
    """Last modification timestamp from git."""

    days_since_modified: int | None = None
    """Days since last modification."""

    commit_count_90d: int = 0
    """Number of commits touching this file in last 90 days."""

    recent_authors: list[str] = field(default_factory=list)
    """Authors who modified this file recently."""


@dataclass
class RiskScore:
    """Composite risk score for a file or function."""

    overall_score: float
    """Overall risk score (0.0-1.0)."""

    complexity_score: float
    """Complexity contribution (0.0-1.0)."""

    coverage_score: float
    """Coverage gap contribution (0.0-1.0)."""

    recency_score: float
    """Recency contribution (0.0-1.0)."""

    criticality_score: float
    """Domain criticality contribution (0.0-1.0)."""

    level: RiskLevel
    """Risk level classification."""

    criticality_domains: list[CriticalityDomain] = field(default_factory=list)
    """Detected critical domains."""

    @staticmethod
    def classify_level(score: float) -> RiskLevel:
        """Classify risk level based on score."""
        if score >= RISK_LEVEL_CRITICAL:
            return RiskLevel.CRITICAL
        if score >= RISK_LEVEL_HIGH:
            return RiskLevel.HIGH
        if score >= RISK_LEVEL_MEDIUM:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


@dataclass
class FileRisk:
    """Risk assessment for a single file."""

    file_path: str
    """Path to the source file."""

    risk_score: RiskScore
    """Composite risk score."""

    recency_info: RecencyInfo
    """Recent change information."""

    avg_complexity: float = 0.0
    """Average complexity of functions in this file."""

    coverage_percentage: float = 0.0
    """Overall coverage percentage for this file."""

    function_count: int = 0
    """Number of functions in this file."""


@dataclass
class FunctionRisk:
    """Risk assessment for a single function."""

    file_path: str
    """Path to the source file."""

    function_name: str
    """Name of the function."""

    risk_score: RiskScore
    """Composite risk score."""

    complexity: int = 0
    """Cyclomatic complexity."""

    coverage_percentage: float = 0.0
    """Coverage percentage for this function."""

    is_public: bool = True
    """Whether this is a public function."""


@dataclass
class RiskReport:
    """Complete risk analysis report."""

    file_risks: list[FileRisk] = field(default_factory=list)
    """Per-file risk assessments, sorted by risk score (highest first)."""

    function_risks: list[FunctionRisk] = field(default_factory=list)
    """Per-function risk assessments, sorted by risk score (highest first)."""

    critical_files: list[str] = field(default_factory=list)
    """Files with CRITICAL risk level."""

    high_risk_files: list[str] = field(default_factory=list)
    """Files with HIGH risk level."""

    def get_prioritized_files(self) -> list[FileRisk]:
        """Return files sorted by risk score (highest first)."""
        return sorted(self.file_risks, key=lambda f: f.risk_score.overall_score, reverse=True)

    def get_prioritized_functions(self) -> list[FunctionRisk]:
        """Return functions sorted by risk score (highest first)."""
        return sorted(self.function_risks, key=lambda f: f.risk_score.overall_score, reverse=True)


@dataclass
class RiskAnalysisTask(TaskInput):
    """Task input for risk analysis."""

    task_type: str = "analyze_risk"
    """Type of task (defaults to 'analyze_risk')."""

    target: str = ""
    """Target for the task (defaults to project_root)."""

    project_root: str = ""
    """Root directory of the project to analyze."""

    code_maps: dict[str, CodeMap] = field(default_factory=dict)
    """Code analysis results keyed by file path."""

    function_gaps: list[FunctionGap] = field(default_factory=list)
    """Coverage gaps from CoverageAnalyzer."""

    def __post_init__(self) -> None:
        """Initialize base TaskInput fields if not already set."""
        if not self.target and self.project_root:
            self.target = self.project_root


# ── RiskAnalyzer ─────────────────────────────────────────────────


class RiskAnalyzer(BaseAgent):
    """Agent that computes composite risk scores for prioritization.

    Combines complexity, coverage, recency, and domain criticality
    to produce prioritized risk reports for orchestrator task ordering.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the RiskAnalyzer.

        Args:
            project_root: Root directory of the project.
        """
        self._root = project_root
        self._git_path = shutil.which("git") or "git"

    @property
    def name(self) -> str:
        """Unique name identifying this agent."""
        return "risk_analyzer"

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return (
            "Computes composite risk scores based on complexity, coverage, recency, and criticality"
        )

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute risk analysis.

        Args:
            task: A RiskAnalysisTask with code maps and coverage gaps.

        Returns:
            TaskOutput with RiskReport in result['risk_report'].
        """
        if not isinstance(task, RiskAnalysisTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a RiskAnalysisTask instance"],
            )

        try:
            logger.info("Starting risk analysis for %s", task.project_root)

            # Build risk report (task 1.21.1 & 1.21.4)
            report = self.analyze_risk(task)

            logger.info(
                "Risk analysis complete: %d files, %d critical, %d high risk",
                len(report.file_risks),
                len(report.critical_files),
                len(report.high_risk_files),
            )

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={"risk_report": report},
            )

        except Exception as exc:
            logger.exception("Unexpected error during risk analysis")
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Unexpected error: {exc}"],
            )

    def analyze_risk(self, task: RiskAnalysisTask) -> RiskReport:
        """Perform risk analysis and generate report.

        Args:
            task: Risk analysis task with input data.

        Returns:
            Complete risk report with prioritized files and functions.
        """
        report = RiskReport()

        # Build file-level risk assessments
        for file_path, code_map in task.code_maps.items():
            file_risk = self._analyze_file_risk(
                file_path=file_path,
                code_map=code_map,
                function_gaps=task.function_gaps,
            )
            report.file_risks.append(file_risk)

            # Track critical/high risk files
            if file_risk.risk_score.level == RiskLevel.CRITICAL:
                report.critical_files.append(file_path)
            elif file_risk.risk_score.level == RiskLevel.HIGH:
                report.high_risk_files.append(file_path)

        # Build function-level risk assessments
        for file_path, code_map in task.code_maps.items():
            function_risks = self._analyze_function_risks(
                file_path=file_path,
                code_map=code_map,
                function_gaps=task.function_gaps,
            )
            report.function_risks.extend(function_risks)

        return report

    def _analyze_file_risk(
        self,
        file_path: str,
        code_map: CodeMap,
        function_gaps: list[FunctionGap],
    ) -> FileRisk:
        """Analyze risk for a single file.

        Args:
            file_path: Path to the file.
            code_map: Code analysis results.
            function_gaps: Coverage gaps.

        Returns:
            FileRisk assessment.
        """
        # Task 1.21.3: Get recency information
        recency_info = self._get_recency_info(file_path)

        # Calculate average complexity
        complexities = list(code_map.complexity_map.values())
        avg_complexity = (
            sum(c.cyclomatic for c in complexities) / len(complexities) if complexities else 0.0
        )

        # Calculate coverage percentage
        file_gaps = [g for g in function_gaps if g.file_path == file_path]
        if file_gaps:
            avg_coverage = sum(g.coverage_percentage for g in file_gaps) / len(file_gaps)
        else:
            avg_coverage = 100.0  # Assume full coverage if no gaps reported

        # Task 1.21.2: Detect criticality domains
        criticality_domains = self._detect_criticality_domains(code_map)

        # Calculate composite risk score
        risk_score = self._calculate_risk_score(
            complexity=avg_complexity,
            coverage_percentage=avg_coverage,
            recency_info=recency_info,
            criticality_domains=criticality_domains,
        )

        return FileRisk(
            file_path=file_path,
            risk_score=risk_score,
            recency_info=recency_info,
            avg_complexity=avg_complexity,
            coverage_percentage=avg_coverage,
            function_count=len(code_map.functions),
        )

    def _analyze_function_risks(
        self,
        file_path: str,
        code_map: CodeMap,
        function_gaps: list[FunctionGap],
    ) -> list[FunctionRisk]:
        """Analyze risk for all functions in a file.

        Args:
            file_path: Path to the file.
            code_map: Code analysis results.
            function_gaps: Coverage gaps.

        Returns:
            List of FunctionRisk assessments.
        """
        function_risks: list[FunctionRisk] = []
        recency_info = self._get_recency_info(file_path)

        for func in code_map.functions:
            # Get complexity
            complexity_metrics = code_map.complexity_map.get(func.name)
            complexity = complexity_metrics.cyclomatic if complexity_metrics else 1

            # Get coverage
            matching_gaps = [
                g
                for g in function_gaps
                if g.file_path == file_path and g.function_name == func.name
            ]
            coverage_percentage = matching_gaps[0].coverage_percentage if matching_gaps else 100.0

            # Detect criticality for this function
            func_criticality = self._detect_function_criticality(func.name, func.body_text)

            # Calculate risk score
            risk_score = self._calculate_risk_score(
                complexity=float(complexity),
                coverage_percentage=coverage_percentage,
                recency_info=recency_info,
                criticality_domains=func_criticality,
            )

            # Determine if public (simple heuristic: doesn't start with _)
            is_public = not func.name.startswith("_")

            function_risks.append(
                FunctionRisk(
                    file_path=file_path,
                    function_name=func.name,
                    risk_score=risk_score,
                    complexity=complexity,
                    coverage_percentage=coverage_percentage,
                    is_public=is_public,
                )
            )

        return function_risks

    def _safe_git_run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Execute git command safely with validated inputs.

        This method centralizes subprocess calls to git, ensuring:
        - Full executable path (no shell injection via PATH)
        - List-based arguments (no shell parsing)
        - Explicit shell=False
        - Controlled working directory

        Args:
            args: Git command arguments (without git executable itself).

        Returns:
            CompletedProcess with command results.
        """
        return subprocess.run(
            [self._git_path, *args],
            cwd=self._root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def _validate_file_path(self, file_path: str) -> bool:
        """Validate that file path is safe for subprocess execution.

        Args:
            file_path: Path to validate.

        Returns:
            True if path is safe, False otherwise.
        """
        # Reject paths with shell metacharacters or null bytes
        dangerous_chars = [";", "&", "|", "`", "$", "(", ")", "<", ">", "\n", "\0"]
        return not any(char in file_path for char in dangerous_chars)

    def _get_recency_info(self, file_path: str) -> RecencyInfo:
        """Get recency information for a file from git log (task 1.21.3).

        Args:
            file_path: Path to the file.

        Returns:
            RecencyInfo with git history data.
        """
        # Validate file path for security
        if not self._validate_file_path(file_path):
            logger.warning("Invalid file path detected: %s", file_path)
            return RecencyInfo()

        try:
            # Get last modification time
            result = self._safe_git_run(["log", "-1", "--format=%at", "--", file_path])

            if result.returncode == 0 and result.stdout.strip():
                timestamp = int(result.stdout.strip())
                last_modified = datetime.fromtimestamp(timestamp, tz=UTC)
                now = datetime.now(UTC)
                days_since = (now - last_modified).days
            else:
                last_modified = None
                days_since = None

            # Get commit count in last 90 days
            result = self._safe_git_run(
                ["log", "--since=90 days ago", "--format=%H", "--", file_path]
            )
            commit_count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0

            # Get recent authors
            result = self._safe_git_run(
                ["log", "--since=90 days ago", "--format=%an", "--", file_path]
            )
            authors = list(set(result.stdout.strip().split("\n"))) if result.stdout.strip() else []

            return RecencyInfo(
                last_modified=last_modified,
                days_since_modified=days_since,
                commit_count_90d=commit_count,
                recent_authors=authors,
            )

        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError) as exc:
            logger.debug("Could not get git recency info for %s: %s", file_path, exc)
            return RecencyInfo()

    def _detect_criticality_domains(self, code_map: CodeMap) -> list[CriticalityDomain]:
        """Detect critical domains in code (task 1.21.2).

        Args:
            code_map: Code analysis results.

        Returns:
            List of detected critical domains.
        """
        domains: set[CriticalityDomain] = set()

        # Check imports
        import_text = " ".join(imp.module.lower() for imp in code_map.imports)
        import_text += " " + " ".join(
            " ".join(imp.names).lower() for imp in code_map.imports if imp.names
        )

        # Check function/class names and bodies
        code_text = ""
        for func in code_map.functions:
            code_text += f" {func.name.lower()} {func.body_text.lower()}"
        for cls in code_map.classes:
            code_text += f" {cls.name.lower()}"

        combined_text = f"{import_text} {code_text}"

        # Match against patterns
        for domain, patterns in CRITICALITY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, combined_text, re.IGNORECASE):
                    domains.add(domain)
                    break  # Found match for this domain, move to next

        return list(domains) if domains else [CriticalityDomain.NONE]

    def _detect_function_criticality(
        self, function_name: str, function_body: str
    ) -> list[CriticalityDomain]:
        """Detect critical domains for a specific function.

        Args:
            function_name: Name of the function.
            function_body: Body text of the function.

        Returns:
            List of detected critical domains.
        """
        domains: set[CriticalityDomain] = set()
        combined_text = f"{function_name.lower()} {function_body.lower()}"

        for domain, patterns in CRITICALITY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, combined_text, re.IGNORECASE):
                    domains.add(domain)
                    break

        return list(domains) if domains else [CriticalityDomain.NONE]

    def _score_complexity(self, complexity: float) -> float:
        """Calculate complexity score component (0.0-1.0).

        Args:
            complexity: Cyclomatic complexity value.

        Returns:
            Normalized complexity score.
        """
        if complexity >= COMPLEXITY_HIGH:
            return 1.0
        if complexity >= COMPLEXITY_MODERATE:
            return (
                0.5
                + (complexity - COMPLEXITY_MODERATE) / (COMPLEXITY_HIGH - COMPLEXITY_MODERATE) * 0.5
            )
        return complexity / COMPLEXITY_MODERATE * 0.5

    def _score_coverage(self, coverage_percentage: float) -> float:
        """Calculate coverage score component (0.0-1.0).

        Args:
            coverage_percentage: Test coverage percentage.

        Returns:
            Normalized coverage score (higher is worse).
        """
        if coverage_percentage <= COVERAGE_NONE:
            return 1.0
        if coverage_percentage <= COVERAGE_LOW:
            return 0.8
        if coverage_percentage <= COVERAGE_MODERATE:
            return 0.5
        # Linear decay from 0.5 to 0.0 as coverage goes from 50% to 100%
        return max(0.0, 0.5 * (100 - coverage_percentage) / 50)

    def _score_recency(self, recency_info: RecencyInfo) -> float:
        """Calculate recency score component (0.0-1.0).

        Args:
            recency_info: Recent change information.

        Returns:
            Normalized recency score.
        """
        if recency_info.days_since_modified is None:
            base_score = 0.0  # No git history, assume low risk
        elif recency_info.days_since_modified <= RECENCY_VERY_RECENT:
            base_score = 1.0
        elif recency_info.days_since_modified <= RECENCY_RECENT:
            base_score = 0.7
        elif recency_info.days_since_modified <= RECENCY_MODERATE:
            base_score = 0.4
        else:
            base_score = 0.1

        # Boost recency score if many recent commits
        if recency_info.commit_count_90d > COMMITS_HIGH_ACTIVITY:
            return min(1.0, base_score * 1.3)
        if recency_info.commit_count_90d > COMMITS_MODERATE_ACTIVITY:
            return min(1.0, base_score * 1.15)
        return base_score

    def _score_criticality(self, criticality_domains: list[CriticalityDomain]) -> float:
        """Calculate criticality score component (0.0-1.0).

        Args:
            criticality_domains: Detected critical domains.

        Returns:
            Normalized criticality score.
        """
        if CriticalityDomain.NONE in criticality_domains and len(criticality_domains) == 1:
            return 0.0
        # Filter out NONE
        real_domains = [d for d in criticality_domains if d != CriticalityDomain.NONE]
        # More critical domains = higher score
        return min(1.0, len(real_domains) * 0.4)

    def _calculate_risk_score(
        self,
        complexity: float,
        coverage_percentage: float,
        recency_info: RecencyInfo,
        criticality_domains: list[CriticalityDomain],
    ) -> RiskScore:
        """Calculate composite risk score (task 1.21.1).

        Args:
            complexity: Cyclomatic complexity.
            coverage_percentage: Test coverage percentage.
            recency_info: Recent change information.
            criticality_domains: Detected critical domains.

        Returns:
            Complete RiskScore with breakdown.
        """
        # Calculate component scores
        complexity_score = self._score_complexity(complexity)
        coverage_score = self._score_coverage(coverage_percentage)
        recency_score = self._score_recency(recency_info)
        criticality_score = self._score_criticality(criticality_domains)

        # Composite score (weighted sum)
        overall_score = (
            WEIGHT_COMPLEXITY * complexity_score
            + WEIGHT_COVERAGE * coverage_score
            + WEIGHT_RECENCY * recency_score
            + WEIGHT_CRITICALITY * criticality_score
        )

        # Classify risk level
        level = RiskScore.classify_level(overall_score)

        return RiskScore(
            overall_score=overall_score,
            complexity_score=complexity_score,
            coverage_score=coverage_score,
            recency_score=recency_score,
            criticality_score=criticality_score,
            level=level,
            criticality_domains=criticality_domains,
        )
