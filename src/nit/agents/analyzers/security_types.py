"""Shared security enums — extracted to break circular imports.

Both ``security.py`` and ``security_patterns/base.py`` depend on these enums.
Keeping them in a leaf module avoids the
``security -> security_patterns.base -> security`` cycle.
"""

from __future__ import annotations

from enum import Enum


class VulnerabilityType(Enum):
    """Types of security vulnerabilities detected."""

    SQL_INJECTION = "sql_injection"
    COMMAND_INJECTION = "command_injection"
    PATH_TRAVERSAL = "path_traversal"
    XSS = "xss"
    CREDENTIAL_LEAK = "credential_leak"
    WEAK_CRYPTO = "weak_crypto"
    INSECURE_DESERIALIZATION = "insecure_deserialization"
    SSRF = "ssrf"


class SecuritySeverity(Enum):
    """Severity levels for security findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
