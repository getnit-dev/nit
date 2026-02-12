"""Python-specific security pattern detection."""

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

# ── Dangerous sinks ──────────────────────────────────────────────

_PYTHON_SINKS: list[DangerousSink] = [
    # SQL Injection — f-string / format / % in execute calls
    DangerousSink(
        vuln_type=VulnerabilityType.SQL_INJECTION,
        pattern=re.compile(
            r"""\.execute\(\s*f["']|\.execute\(\s*["'].*%\s*[(%]|"""
            r"""\.execute\(\s*["'].*\.format\(""",
        ),
        title="SQL injection via string formatting",
        description=(
            "SQL query constructed using string formatting (f-string, %, or .format) "
            "instead of parameterized queries. User input in these strings can alter "
            "the query structure."
        ),
        remediation=(
            "Use parameterized queries: cursor.execute('SELECT * FROM t WHERE id = %s', (id,))"
        ),
        confidence=0.85,
        safe_guards=[
            re.compile(r"\.execute\([^,]+,\s*[\[(]"),  # Already parameterized
        ],
    ),
    # SQL Injection — raw string concatenation
    DangerousSink(
        vuln_type=VulnerabilityType.SQL_INJECTION,
        pattern=re.compile(
            r"""(?:SELECT|INSERT|UPDATE|DELETE|DROP)\s+.*\+\s*(?:str\()?[a-zA-Z_]""",
            re.IGNORECASE,
        ),
        title="SQL injection via string concatenation",
        description=(
            "SQL query built by concatenating variables. This is a classic SQL "
            "injection vector when the variable contains user input."
        ),
        remediation="Use parameterized queries instead of string concatenation.",
        confidence=0.75,
        safe_guards=[],
    ),
    # Command Injection — subprocess with shell=True
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"subprocess\.\w+\(.*shell\s*=\s*True"),
        title="Command injection risk: shell=True",
        description=(
            "subprocess called with shell=True. If the command string includes "
            "user-controlled data, an attacker can inject arbitrary commands."
        ),
        remediation=(
            "Use shell=False (the default) and pass command as a list: "
            "subprocess.run(['cmd', arg1, arg2])"
        ),
        confidence=0.80,
        safe_guards=[
            # If command is a literal string with no variables, it's safe
            re.compile(r"""subprocess\.\w+\(\s*["'][^"']*["']\s*,\s*shell\s*=\s*True"""),
        ],
    ),
    # Command Injection — os.system / os.popen
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"\bos\.(?:system|popen)\("),
        title="Command injection risk: os.system/os.popen",
        description=(
            "os.system() and os.popen() pass commands through the shell. "
            "If the argument includes user input, command injection is possible."
        ),
        remediation="Use subprocess.run() with shell=False instead of os.system/os.popen.",
        confidence=0.75,
        safe_guards=[
            re.compile(r"""os\.(?:system|popen)\(\s*["'][^"']*["']\s*\)"""),
        ],
    ),
    # Insecure Deserialization — pickle
    DangerousSink(
        vuln_type=VulnerabilityType.INSECURE_DESERIALIZATION,
        pattern=re.compile(r"\bpickle\.(?:loads?|Unpickler)\("),
        title="Insecure deserialization: pickle",
        description=(
            "pickle.load/loads can execute arbitrary code when deserializing "
            "untrusted data. This is a critical RCE vector."
        ),
        remediation=(
            "Avoid pickle for untrusted data. Use JSON, MessagePack, or Protocol "
            "Buffers instead. If pickle is required, use hmac to verify integrity."
        ),
        confidence=0.80,
        safe_guards=[],
    ),
    # Insecure Deserialization — yaml.load without SafeLoader
    DangerousSink(
        vuln_type=VulnerabilityType.INSECURE_DESERIALIZATION,
        pattern=re.compile(r"\byaml\.load\("),
        title="Insecure deserialization: yaml.load without SafeLoader",
        description=(
            "yaml.load() without Loader=SafeLoader can execute arbitrary Python "
            "objects embedded in YAML, leading to remote code execution."
        ),
        remediation="Use yaml.safe_load() or yaml.load(data, Loader=SafeLoader).",
        confidence=0.85,
        safe_guards=[
            re.compile(r"yaml\.load\([^)]*Loader\s*=\s*(?:Safe|Base)Loader"),
            re.compile(r"yaml\.safe_load\("),
        ],
    ),
    # Path Traversal
    DangerousSink(
        vuln_type=VulnerabilityType.PATH_TRAVERSAL,
        pattern=re.compile(
            r"""(?:open|Path)\(\s*(?:request\.|params\[|args\[|"""
            r"""os\.path\.join\(\s*\w+\s*,\s*(?:request|params|args))"""
        ),
        title="Path traversal via user-controlled file path",
        description=(
            "A file path constructed from user input (request parameters, args) "
            "without sanitization. An attacker can use '../' sequences to read "
            "or write arbitrary files."
        ),
        remediation=(
            "Validate paths with os.path.realpath() and ensure the resolved path "
            "is within the expected directory. Use pathlib and resolve() + "
            "relative_to() for safe path handling."
        ),
        confidence=0.70,
        safe_guards=[
            re.compile(r"(?:realpath|resolve|relative_to|abspath)"),
        ],
    ),
    # Weak Crypto — MD5/SHA1 for security
    DangerousSink(
        vuln_type=VulnerabilityType.WEAK_CRYPTO,
        pattern=re.compile(r"""hashlib\.(?:md5|sha1)\("""),
        title="Weak hash algorithm: MD5/SHA1",
        description=(
            "MD5 and SHA1 are cryptographically broken and should not be used "
            "for security purposes (password hashing, integrity verification)."
        ),
        remediation="Use SHA-256+ for integrity checks, or bcrypt/scrypt/argon2 for passwords.",
        confidence=0.65,
        safe_guards=[
            # Often used for non-security checksums; lower confidence
            re.compile(r"(?:checksum|fingerprint|etag|cache_key|content_hash)", re.IGNORECASE),
        ],
    ),
    # SSRF — requests with user-controlled URL
    DangerousSink(
        vuln_type=VulnerabilityType.SSRF,
        pattern=re.compile(
            r"""(?:requests|httpx|urllib\.request)\.\w+\(\s*(?:url|request\.|params\[|args\[|f["'])"""
        ),
        title="Potential SSRF: HTTP request with user-controlled URL",
        description=(
            "An HTTP request is made with a URL that may be derived from user "
            "input. An attacker could use this to reach internal services."
        ),
        remediation=(
            "Validate and allowlist URLs before making requests. Block internal "
            "IP ranges (127.0.0.0/8, 10.0.0.0/8, 169.254.169.254, etc.)."
        ),
        confidence=0.65,
        safe_guards=[
            re.compile(r"(?:validate_url|allowlist|whitelist|urlparse)", re.IGNORECASE),
        ],
    ),
    # XSS — mark_safe / Markup with user data
    DangerousSink(
        vuln_type=VulnerabilityType.XSS,
        pattern=re.compile(r"""(?:mark_safe|Markup)\(\s*(?:f["']|.*\.format\(|.*%\s*[(%])"""),
        title="XSS via mark_safe/Markup with dynamic content",
        description=(
            "Marking user-controlled content as safe HTML bypasses Django/Jinja2 "
            "auto-escaping, allowing script injection."
        ),
        remediation=(
            "Never pass user input to mark_safe() or Markup(). Escape user data "
            "before including it in HTML, or use template auto-escaping."
        ),
        confidence=0.80,
        safe_guards=[],
    ),
]


# ── Pattern class ────────────────────────────────────────────────


class PythonSecurityPatterns(LanguageSecurityPatterns):
    """Security patterns for Python source code."""

    @property
    def language(self) -> str:
        return "python"

    def scan(self, source_code: str, code_map: CodeMap) -> list[PatternMatch]:
        """Scan Python source for security vulnerabilities."""
        matches = self._scan_with_sinks(source_code, code_map, _PYTHON_SINKS)
        matches.extend(detect_hardcoded_secrets(source_code, code_map.file_path))
        return matches
