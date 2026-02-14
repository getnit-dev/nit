"""SecurityAnalyzer agent — detects security vulnerabilities using heuristics + LLM.

This agent:
1. Scans source files using language-aware AST heuristics (tree-sitter)
2. Validates medium-confidence findings via LLM to reduce false positives
3. Reports precise, actionable security findings with CWE IDs and remediation
4. Supports Python, JS/TS, Java, Go, Rust, C/C++, C#
"""

from __future__ import annotations

import contextlib
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nit.agents.analyzers.security_patterns.base import get_patterns_for_language
from nit.agents.analyzers.security_types import SecuritySeverity, VulnerabilityType
from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.llm.engine import GenerationRequest
from nit.llm.prompts.security_analysis import (
    SecurityAnalysisContext,
    SecurityAnalysisPrompt,
)
from nit.parsing.treesitter import EXTENSION_TO_LANGUAGE

if TYPE_CHECKING:
    from pathlib import Path

    from nit.llm.engine import LLMEngine

logger = logging.getLogger(__name__)

# Re-export enums that were extracted to security_types to break a circular
# import between this module and security_patterns.base.
__all__ = [
    "SecuritySeverity",
    "VulnerabilityType",
]

# ── Confidence thresholds ─────────────────────────────────────────

HIGH_CONFIDENCE_THRESHOLD = 0.8
"""Findings above this skip LLM validation."""

DEFAULT_CONFIDENCE_THRESHOLD = 0.7
"""Minimum confidence to include in final report."""

MAX_LLM_VALIDATIONS = 20
"""Cap on LLM calls per security scan for cost control."""


# ── CWE + severity mappings ──────────────────────────────────────

CWE_MAP: dict[VulnerabilityType, str] = {
    VulnerabilityType.SQL_INJECTION: "CWE-89",
    VulnerabilityType.COMMAND_INJECTION: "CWE-78",
    VulnerabilityType.PATH_TRAVERSAL: "CWE-22",
    VulnerabilityType.XSS: "CWE-79",
    VulnerabilityType.CREDENTIAL_LEAK: "CWE-798",
    VulnerabilityType.WEAK_CRYPTO: "CWE-327",
    VulnerabilityType.INSECURE_DESERIALIZATION: "CWE-502",
    VulnerabilityType.SSRF: "CWE-918",
}

DEFAULT_SEVERITY: dict[VulnerabilityType, SecuritySeverity] = {
    VulnerabilityType.SQL_INJECTION: SecuritySeverity.CRITICAL,
    VulnerabilityType.COMMAND_INJECTION: SecuritySeverity.CRITICAL,
    VulnerabilityType.PATH_TRAVERSAL: SecuritySeverity.HIGH,
    VulnerabilityType.XSS: SecuritySeverity.HIGH,
    VulnerabilityType.CREDENTIAL_LEAK: SecuritySeverity.HIGH,
    VulnerabilityType.WEAK_CRYPTO: SecuritySeverity.MEDIUM,
    VulnerabilityType.INSECURE_DESERIALIZATION: SecuritySeverity.HIGH,
    VulnerabilityType.SSRF: SecuritySeverity.HIGH,
}


# ── Data models ───────────────────────────────────────────────────


@dataclass
class SecurityFinding:
    """A security vulnerability detected in source code."""

    vulnerability_type: VulnerabilityType
    """Type of vulnerability."""

    severity: SecuritySeverity
    """Severity level."""

    file_path: str
    """Path to the file."""

    line_number: int | None
    """Line number where the issue occurs."""

    function_name: str | None
    """Enclosing function name (if known)."""

    title: str
    """Short, descriptive title."""

    description: str
    """Explanation of the vulnerability."""

    remediation: str
    """How to fix the issue."""

    confidence: float
    """Confidence score (0.0-1.0)."""

    cwe_id: str | None = None
    """CWE identifier (e.g., 'CWE-89')."""

    evidence: str = ""
    """Code snippet showing the issue."""

    detection_method: str = "heuristic"
    """How it was detected: 'heuristic' or 'llm_validated'."""


@dataclass
class SecurityReport:
    """Aggregated security analysis results."""

    findings: list[SecurityFinding] = field(default_factory=list)
    """All findings above the confidence threshold."""

    files_scanned: int = 0
    """Number of source files scanned."""

    @property
    def critical_count(self) -> int:
        """Number of CRITICAL findings."""
        return sum(1 for f in self.findings if f.severity == SecuritySeverity.CRITICAL)

    @property
    def high_count(self) -> int:
        """Number of HIGH findings."""
        return sum(1 for f in self.findings if f.severity == SecuritySeverity.HIGH)

    def get_by_severity(self, severity: SecuritySeverity) -> list[SecurityFinding]:
        """Return findings matching the given severity."""
        return [f for f in self.findings if f.severity == severity]


@dataclass
class SecurityAnalysisTask(TaskInput):
    """Task input for security analysis."""

    task_type: str = "analyze_security"
    target: str = ""

    code_maps: dict[str, Any] = field(default_factory=dict)
    """CodeMap objects keyed by file path."""

    project_root: str = ""
    """Project root directory path."""

    enable_llm_validation: bool = True
    """Whether to validate medium-confidence findings via LLM."""

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    """Minimum confidence to report."""


# ── SecurityAnalyzer ──────────────────────────────────────────────


_SEVERITY_ORDER = {
    SecuritySeverity.CRITICAL: 0,
    SecuritySeverity.HIGH: 1,
    SecuritySeverity.MEDIUM: 2,
    SecuritySeverity.LOW: 3,
    SecuritySeverity.INFO: 4,
}

# LLM response parsing patterns
_IS_VALID_PATTERN = re.compile(r"\bIS_VALID\b\s*[:=]?\s*(true|false)", re.IGNORECASE)
_CONFIDENCE_PATTERN = re.compile(r"\bCONFIDENCE\b\s*[:=]?\s*([\d.]+)", re.IGNORECASE)


class SecurityAnalyzer(BaseAgent):
    """Detects security vulnerabilities using AST heuristics and LLM validation."""

    def __init__(
        self,
        project_root: Path,
        llm_engine: LLMEngine | None = None,
        *,
        enable_llm_validation: bool = True,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._project_root = project_root
        self._llm_engine = llm_engine
        self._enable_llm_validation = enable_llm_validation
        self._confidence_threshold = confidence_threshold

    @property
    def name(self) -> str:
        return "SecurityAnalyzer"

    @property
    def description(self) -> str:
        return "Detects security vulnerabilities using heuristics and LLM validation"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute security analysis on code maps."""
        if not isinstance(task, SecurityAnalysisTask):
            return TaskOutput(status=TaskStatus.FAILED, errors=["Invalid task type"])

        try:
            report = await self.analyze(task)
            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={"security_report": report},
            )
        except Exception as exc:
            logger.exception("Security analysis failed: %s", exc)
            return TaskOutput(status=TaskStatus.FAILED, errors=[str(exc)])

    async def analyze(self, task: SecurityAnalysisTask) -> SecurityReport:
        """Scan all code maps and produce a security report."""
        all_findings: list[SecurityFinding] = []

        for file_path, code_map in task.code_maps.items():
            language: str = code_map.language
            patterns = get_patterns_for_language(language)
            if patterns is None:
                continue

            source_code = self._read_source(file_path)
            if not source_code:
                continue

            matches = patterns.scan(source_code, code_map)
            for match in matches:
                finding = SecurityFinding(
                    vulnerability_type=match.vuln_type,
                    severity=DEFAULT_SEVERITY.get(match.vuln_type, SecuritySeverity.MEDIUM),
                    file_path=file_path,
                    line_number=match.line_number,
                    function_name=match.function_name,
                    title=match.title,
                    description=match.description,
                    remediation=match.remediation,
                    confidence=match.confidence,
                    cwe_id=CWE_MAP.get(match.vuln_type),
                    evidence=match.evidence,
                )
                all_findings.append(finding)

        # Deduplicate (same file + line + vuln type)
        all_findings = _deduplicate(all_findings)

        # LLM validation for medium-confidence findings
        if (
            self._enable_llm_validation
            and task.enable_llm_validation
            and self._llm_engine is not None
        ):
            all_findings = await self._validate_with_llm(all_findings)

        # Filter by confidence threshold
        threshold = task.confidence_threshold
        filtered = [f for f in all_findings if f.confidence >= threshold]

        # Sort: severity (critical first), then confidence descending
        filtered.sort(key=lambda f: (_SEVERITY_ORDER.get(f.severity, 99), -f.confidence))

        return SecurityReport(
            findings=filtered,
            files_scanned=len(task.code_maps),
        )

    def _read_source(self, file_path: str) -> str:
        """Read source file content."""
        try:
            return (self._project_root / file_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            logger.debug("Cannot read %s for security scan", file_path)
            return ""

    async def _validate_with_llm(self, findings: list[SecurityFinding]) -> list[SecurityFinding]:
        """Use LLM to validate medium-confidence findings."""
        validated: list[SecurityFinding] = []
        llm_calls = 0
        prompt_template = SecurityAnalysisPrompt()

        for finding in findings:
            # High-confidence findings pass through
            if finding.confidence >= HIGH_CONFIDENCE_THRESHOLD:
                validated.append(finding)
                continue

            # Cap LLM calls
            if llm_calls >= MAX_LLM_VALIDATIONS:
                validated.append(finding)
                continue

            if self._llm_engine is None:
                raise RuntimeError("LLM engine is unexpectedly None")
            try:
                context = SecurityAnalysisContext(
                    vulnerability_type=finding.vulnerability_type.value,
                    code_snippet=finding.evidence,
                    file_path=finding.file_path,
                    language=_language_from_path(finding.file_path),
                    heuristic_description=finding.description,
                )
                rendered = prompt_template.render_validation(context)
                request = GenerationRequest(messages=rendered.messages)
                response = await self._llm_engine.generate(request)
                llm_calls += 1

                is_valid, new_confidence = _parse_llm_validation(response.text)
                if is_valid:
                    finding.confidence = new_confidence
                    finding.detection_method = "llm_validated"
                    validated.append(finding)
                else:
                    logger.debug(
                        "LLM dismissed finding: %s at %s:%s",
                        finding.vulnerability_type.value,
                        finding.file_path,
                        finding.line_number,
                    )
            except Exception as exc:
                logger.debug("LLM validation failed for finding: %s", exc)
                validated.append(finding)

        return validated


# ── Helpers ───────────────────────────────────────────────────────


def _deduplicate(findings: list[SecurityFinding]) -> list[SecurityFinding]:
    """Remove duplicate findings (same file + line + vulnerability type)."""
    seen: set[tuple[str, int | None, str]] = set()
    unique: list[SecurityFinding] = []
    for f in findings:
        key = (f.file_path, f.line_number, f.vulnerability_type.value)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def _language_from_path(file_path: str) -> str:
    """Infer language from file extension."""
    ext = "." + file_path.rsplit(".", 1)[-1] if "." in file_path else ""
    return EXTENSION_TO_LANGUAGE.get(ext, "unknown")


def _parse_llm_validation(text: str) -> tuple[bool, float]:
    """Parse LLM validation response for IS_VALID and CONFIDENCE fields."""
    is_valid = True
    confidence = 0.75

    valid_match = _IS_VALID_PATTERN.search(text)
    if valid_match:
        is_valid = valid_match.group(1).lower() == "true"

    conf_match = _CONFIDENCE_PATTERN.search(text)
    if conf_match:
        with contextlib.suppress(ValueError):
            confidence = min(1.0, max(0.0, float(conf_match.group(1))))

    return is_valid, confidence
