"""Go-specific security pattern detection."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from nit.agents.analyzers.security import VulnerabilityType
from nit.agents.analyzers.security_patterns.base import (
    DangerousSink,
    LanguageSecurityPatterns,
    PatternMatch,
    detect_hardcoded_secrets,
)

if TYPE_CHECKING:
    from nit.agents.analyzers.code import CodeMap

_GO_SINKS: list[DangerousSink] = [
    # SQL Injection — fmt.Sprintf in SQL
    DangerousSink(
        vuln_type=VulnerabilityType.SQL_INJECTION,
        pattern=re.compile(r"""(?:db|tx)\.(?:Query|Exec|QueryRow)\(\s*fmt\.Sprintf\("""),
        title="SQL injection via fmt.Sprintf in query",
        description=(
            "SQL query built with fmt.Sprintf. Variables interpolated into "
            "the format string can alter the query structure."
        ),
        remediation='Use parameterized queries: db.Query("SELECT * FROM t WHERE id = $1", id)',
        confidence=0.85,
        safe_guards=[],
    ),
    # SQL Injection — string concatenation
    DangerousSink(
        vuln_type=VulnerabilityType.SQL_INJECTION,
        pattern=re.compile(r"""(?:db|tx)\.(?:Query|Exec|QueryRow)\(\s*["'].*\+"""),
        title="SQL injection via string concatenation",
        description="SQL query built with string concatenation.",
        remediation="Use parameterized queries with placeholder arguments.",
        confidence=0.80,
        safe_guards=[],
    ),
    # Command Injection — exec.Command with user data
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"""exec\.Command\(\s*(?:fmt\.Sprintf|.*\+)"""),
        title="Command injection via exec.Command with formatted string",
        description=(
            "exec.Command called with a dynamically constructed command. "
            "If user input is included, command injection is possible."
        ),
        remediation="Pass the command and arguments separately to exec.Command().",
        confidence=0.75,
        safe_guards=[],
    ),
    # Path Traversal
    DangerousSink(
        vuln_type=VulnerabilityType.PATH_TRAVERSAL,
        pattern=re.compile(r"""(?:os\.Open|ioutil\.ReadFile|os\.ReadFile)\(\s*(?:r\.|.*\+)"""),
        title="Path traversal via user-controlled file path",
        description="File opened with path from user input.",
        remediation="Use filepath.Clean() and verify the path stays within the expected directory.",
        confidence=0.70,
        safe_guards=[
            re.compile(r"filepath\.(?:Clean|Abs|Rel)"),
        ],
    ),
    # XSS — template.HTML with user data
    DangerousSink(
        vuln_type=VulnerabilityType.XSS,
        pattern=re.compile(r"""template\.HTML\("""),
        title="XSS via template.HTML()",
        description=(
            "template.HTML() marks content as safe HTML, bypassing Go's "
            "template escaping. User data passed here enables XSS."
        ),
        remediation=(
            "Use html/template auto-escaping; do not pass user data to template.HTML()."
        ),
        confidence=0.70,
        safe_guards=[],
    ),
    # SSRF
    DangerousSink(
        vuln_type=VulnerabilityType.SSRF,
        pattern=re.compile(r"""http\.(?:Get|Post|NewRequest)\(\s*(?:r\.|.*\+|fmt\.Sprintf)"""),
        title="Potential SSRF: HTTP request with user-controlled URL",
        description="HTTP request URL derived from user input.",
        remediation="Validate and allowlist URLs before making requests.",
        confidence=0.65,
        safe_guards=[],
    ),
    # Weak Crypto
    DangerousSink(
        vuln_type=VulnerabilityType.WEAK_CRYPTO,
        pattern=re.compile(r"""(?:md5|sha1)\.(?:New|Sum)\("""),
        title="Weak hash algorithm: MD5/SHA1",
        description="MD5 and SHA1 are broken for cryptographic purposes.",
        remediation="Use sha256.New() or sha512.New() for integrity checks.",
        confidence=0.65,
        safe_guards=[
            re.compile(r"(?:checksum|etag|fingerprint)", re.IGNORECASE),
        ],
    ),
]


class GoSecurityPatterns(LanguageSecurityPatterns):
    """Security patterns for Go."""

    @property
    def language(self) -> str:
        return "go"

    def scan(self, source_code: str, code_map: CodeMap) -> list[PatternMatch]:
        matches = self._scan_with_sinks(source_code, code_map, _GO_SINKS)
        matches.extend(detect_hardcoded_secrets(source_code, code_map.file_path))
        return matches
