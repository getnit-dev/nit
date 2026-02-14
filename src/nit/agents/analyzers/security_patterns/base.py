"""Base framework for language-aware security pattern detection."""

from __future__ import annotations

import logging
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nit.agents.analyzers.security_types import VulnerabilityType

if TYPE_CHECKING:
    from nit.agents.analyzers.code import CodeMap

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────


@dataclass
class PatternMatch:
    """A single heuristic match from scanning source code."""

    vuln_type: VulnerabilityType
    """Vulnerability type detected."""

    line_number: int | None
    """Source line where the issue was found."""

    evidence: str
    """Code snippet showing the vulnerable pattern."""

    confidence: float
    """Initial confidence score (0.0-1.0)."""

    title: str
    """Short human-readable title."""

    description: str
    """Detailed explanation of why this is flagged."""

    remediation: str
    """Suggested fix."""

    function_name: str | None = None
    """Enclosing function, if determinable."""


# ── Dangerous-sink / safe-pattern definitions ─────────────────────


@dataclass
class DangerousSink:
    """A function or pattern that is dangerous when fed untrusted data."""

    vuln_type: VulnerabilityType
    """Which vulnerability this sink relates to."""

    pattern: re.Pattern[str]
    """Regex pattern to match the dangerous call or construct."""

    title: str
    """Title for findings from this sink."""

    description: str
    """Description template."""

    remediation: str
    """Remediation advice."""

    confidence: float = 0.75
    """Default confidence when matched."""

    safe_guards: list[re.Pattern[str]] = field(default_factory=list)
    """If any of these patterns are found near the match, suppress it."""


# ── Hardcoded secret detection (cross-language) ──────────────────

# Known API key format patterns (high precision)
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS Access Key", re.compile(r"""(?:"|')?(AKIA[0-9A-Z]{16})(?:"|')?""")),
    ("GitHub Token", re.compile(r"""(?:"|')?(ghp_[a-zA-Z0-9]{36})(?:"|')?""")),
    ("GitHub OAuth", re.compile(r"""(?:"|')?(gho_[a-zA-Z0-9]{36})(?:"|')?""")),
    ("Stripe Secret Key", re.compile(r"""(?:"|')?(sk_live_[a-zA-Z0-9]{24,})(?:"|')?""")),
    ("Slack Token", re.compile(r"""(?:"|')?(xox[bpoas]-[a-zA-Z0-9-]+)(?:"|')?""")),
    (
        "Generic Secret Assignment",
        re.compile(
            r"""(?:password|secret|api_key|apikey|auth_token|access_token)"""
            r"""\s*[=:]\s*(?:"|')([^"']{8,})(?:"|')""",
            re.IGNORECASE,
        ),
    ),
]

# Variable name patterns that suggest secret context
_SECRET_VAR_RE = re.compile(
    r"\b(?:password|secret|api_?key|auth_?token|access_?token|private_?key"
    r"|credentials?|passwd|jwt_?secret)\b",
    re.IGNORECASE,
)

# Values that are obviously placeholders (not real secrets)
_PLACEHOLDER_RE = re.compile(
    r"(?:xxx|your[_-]|example|placeholder|changeme|fixme|todo|dummy|test|fake|<|>|\*{3,})",
    re.IGNORECASE,
)

# Minimum entropy for generic secret detection
_MIN_ENTROPY = 3.5


def _shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in freq.values())


def detect_hardcoded_secrets(source_code: str, file_path: str) -> list[PatternMatch]:
    """Detect hardcoded secrets across any language."""
    # Skip test files and fixtures
    lower_path = file_path.lower()
    if any(
        part in lower_path
        for part in ("test_", "_test.", ".test.", "spec.", "fixture", "mock", "fake")
    ):
        return []

    findings: list[PatternMatch] = []
    lines = source_code.splitlines()

    for line_idx, line in enumerate(lines, 1):
        # Skip comments
        stripped = line.strip()
        if stripped.startswith(("#", "//", "*", "/*")):
            continue

        for name, pattern in _SECRET_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue

            secret_value = match.group(1)

            # Skip placeholders
            if _PLACEHOLDER_RE.search(secret_value):
                continue

            # For generic secrets, require high entropy
            if (
                name == "Generic Secret Assignment"
                and _shannon_entropy(secret_value) < _MIN_ENTROPY
            ):
                continue

            findings.append(
                PatternMatch(
                    vuln_type=VulnerabilityType.CREDENTIAL_LEAK,
                    line_number=line_idx,
                    evidence=line.strip()[:200],
                    confidence=0.85 if name != "Generic Secret Assignment" else 0.7,
                    title=f"Hardcoded secret: {name}",
                    description=(
                        f"A {name.lower()} appears to be hardcoded in source code. "
                        "Secrets in source code can be leaked through version control."
                    ),
                    remediation=(
                        "Move the secret to an environment variable or a secrets "
                        "manager. Reference it via os.environ, process.env, or "
                        "equivalent."
                    ),
                )
            )

    return findings


# ── Base class for language patterns ─────────────────────────────


class LanguageSecurityPatterns(ABC):
    """Abstract base for language-specific security pattern detection."""

    @property
    @abstractmethod
    def language(self) -> str:
        """Tree-sitter language name this module handles."""

    @abstractmethod
    def scan(self, source_code: str, code_map: CodeMap) -> list[PatternMatch]:
        """Scan source code for security vulnerabilities.

        Args:
            source_code: Raw source text.
            code_map: Parsed code map with AST info.

        Returns:
            List of pattern matches found.
        """

    def _find_enclosing_function(self, code_map: CodeMap, line_number: int) -> str | None:
        """Find the function enclosing a given line number."""
        for func in code_map.functions:
            if func.start_line <= line_number <= func.end_line:
                return func.name
        return None

    def _scan_with_sinks(
        self,
        source_code: str,
        code_map: CodeMap,
        sinks: list[DangerousSink],
    ) -> list[PatternMatch]:
        """Generic scan: match dangerous sinks against source lines."""
        matches: list[PatternMatch] = []
        lines = source_code.splitlines()

        for line_idx, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip comments
            if stripped.startswith(("#", "//", "*", "/*")):
                continue

            for sink in sinks:
                if not sink.pattern.search(line):
                    continue

                # Check safe guards — look at surrounding lines for mitigation
                context_start = max(0, line_idx - 4)
                context_end = min(len(lines), line_idx + 2)
                context_block = "\n".join(lines[context_start:context_end])

                suppressed = any(guard.search(context_block) for guard in sink.safe_guards)
                if suppressed:
                    continue

                func_name = self._find_enclosing_function(code_map, line_idx)

                matches.append(
                    PatternMatch(
                        vuln_type=sink.vuln_type,
                        line_number=line_idx,
                        evidence=stripped[:200],
                        confidence=sink.confidence,
                        title=sink.title,
                        description=sink.description,
                        remediation=sink.remediation,
                        function_name=func_name,
                    )
                )

        return matches


# ── Registry ─────────────────────────────────────────────────────

_LANGUAGE_PATTERNS: dict[str, LanguageSecurityPatterns] = {}


def register_patterns(patterns: LanguageSecurityPatterns) -> None:
    """Register a language pattern module."""
    _LANGUAGE_PATTERNS[patterns.language] = patterns


def get_patterns_for_language(language: str) -> LanguageSecurityPatterns | None:
    """Get the pattern module for a language.

    Patterns are registered eagerly when the ``security_patterns`` package
    is first imported (see ``__init__.py``).
    """
    return _LANGUAGE_PATTERNS.get(language)
