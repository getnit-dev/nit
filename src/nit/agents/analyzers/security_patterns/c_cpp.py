"""C/C++-specific security pattern detection."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from nit.agents.analyzers.security_patterns.base import (
    DangerousSink,
    LanguageSecurityPatterns,
    PatternMatch,
    detect_hardcoded_secrets,
)
from nit.agents.analyzers.security_types import VulnerabilityType

if TYPE_CHECKING:
    from nit.agents.analyzers.code import CodeMap

_C_CPP_SINKS: list[DangerousSink] = [
    # Command Injection — system()
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"""\bsystem\(\s*(?!["'][^"']*["']\s*\))"""),
        title="Command injection via system()",
        description=(
            "system() passes the command through a shell. If the argument "
            "includes user input, arbitrary commands can be injected."
        ),
        remediation="Use execvp() or posix_spawn() with separate arguments.",
        confidence=0.80,
        safe_guards=[],
    ),
    # Command Injection — popen
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"""\bpopen\(\s*(?!["'][^"']*["']\s*,)"""),
        title="Command injection via popen()",
        description="popen() passes commands through a shell.",
        remediation="Use pipe()/fork()/exec() with separate arguments.",
        confidence=0.75,
        safe_guards=[],
    ),
    # Buffer overflow — gets()
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"""\bgets\s*\("""),
        title="Buffer overflow via gets()",
        description=(
            "gets() reads input without bounds checking, guaranteed buffer "
            "overflow if input exceeds buffer size. Removed in C11."
        ),
        remediation="Use fgets(buf, sizeof(buf), stdin) instead.",
        confidence=0.95,
        safe_guards=[],
    ),
    # Buffer overflow — strcpy without bounds
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"""\bstrcpy\s*\("""),
        title="Buffer overflow risk: strcpy()",
        description="strcpy() does not check destination buffer size.",
        remediation="Use strncpy() or strlcpy() with explicit size limits.",
        confidence=0.70,
        safe_guards=[
            re.compile(r"strlen.*<|sizeof"),
        ],
    ),
    # Format string — printf(user_controlled)
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"""\b(?:printf|fprintf|sprintf)\(\s*[a-zA-Z_]\w*\s*\)"""),
        title="Format string vulnerability",
        description=(
            "printf-family call with a non-literal format string. If "
            "user-controlled, this enables memory read/write exploits."
        ),
        remediation='Use a literal format string: printf("%s", user_input)',
        confidence=0.80,
        safe_guards=[],
    ),
    # SQL Injection — sprintf into SQL
    DangerousSink(
        vuln_type=VulnerabilityType.SQL_INJECTION,
        pattern=re.compile(r"""sprintf\(.*(?:SELECT|INSERT|UPDATE|DELETE)\s""", re.IGNORECASE),
        title="SQL injection via sprintf",
        description="SQL query constructed with sprintf, allowing injection.",
        remediation="Use prepared statements with the database library's parameterized API.",
        confidence=0.80,
        safe_guards=[],
    ),
    # Weak Crypto — MD5/SHA1
    DangerousSink(
        vuln_type=VulnerabilityType.WEAK_CRYPTO,
        pattern=re.compile(r"""\b(?:MD5_Init|SHA1_Init|MD5\(|SHA1\()"""),
        title="Weak hash algorithm: MD5/SHA1",
        description="MD5 and SHA1 are broken for cryptographic purposes.",
        remediation="Use SHA256_Init() or stronger hash functions.",
        confidence=0.65,
        safe_guards=[
            re.compile(r"(?:checksum|etag|fingerprint)", re.IGNORECASE),
        ],
    ),
    # Path Traversal
    DangerousSink(
        vuln_type=VulnerabilityType.PATH_TRAVERSAL,
        pattern=re.compile(r"""\bfopen\(\s*(?!["'][^"']*["'])"""),
        title="Potential path traversal via fopen()",
        description="fopen() with a non-literal path may allow path traversal.",
        remediation="Validate and canonicalize the path (realpath()) before opening.",
        confidence=0.60,
        safe_guards=[
            re.compile(r"realpath"),
        ],
    ),
]


class CCppSecurityPatterns(LanguageSecurityPatterns):
    """Security patterns for C and C++."""

    @property
    def language(self) -> str:
        return "c"

    def scan(self, source_code: str, code_map: CodeMap) -> list[PatternMatch]:
        matches = self._scan_with_sinks(source_code, code_map, _C_CPP_SINKS)
        matches.extend(detect_hardcoded_secrets(source_code, code_map.file_path))
        return matches
