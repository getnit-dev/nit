"""JavaScript/TypeScript security pattern detection."""

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

_JS_SINKS: list[DangerousSink] = [
    # SQL Injection — template literal / string concat in query
    DangerousSink(
        vuln_type=VulnerabilityType.SQL_INJECTION,
        pattern=re.compile(r"""\.query\(\s*`|\.query\(\s*["'].*\+|\.execute\(\s*`|\.raw\(\s*`"""),
        title="SQL injection via template literal or concatenation",
        description=(
            "SQL query built using template literals or string concatenation. "
            "If variables contain user input, the query structure can be altered."
        ),
        remediation="Use parameterized queries: db.query('SELECT * FROM t WHERE id = $1', [id])",
        confidence=0.80,
        safe_guards=[
            re.compile(r"\.query\([^,]+,\s*\["),  # parameterized
        ],
    ),
    # Command Injection — child_process.exec
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"""(?:child_process\.)?exec\(\s*(?:`|.*\+|.*\$\{)"""),
        title="Command injection via child_process.exec",
        description=(
            "exec() passes the command through a shell. Template literals or "
            "string concatenation with user input allow command injection."
        ),
        remediation="Use execFile() or spawn() with arguments as an array instead of exec().",
        confidence=0.80,
        safe_guards=[],
    ),
    # XSS — innerHTML
    DangerousSink(
        vuln_type=VulnerabilityType.XSS,
        pattern=re.compile(r"\.innerHTML\s*=\s*(?!['\"]\s*$)"),
        title="XSS via innerHTML assignment",
        description=(
            "Setting innerHTML with dynamic content allows script injection. "
            "Any user-controlled data in the assigned value is an XSS vector."
        ),
        remediation="Use textContent for text, or sanitize HTML with DOMPurify before assignment.",
        confidence=0.75,
        safe_guards=[
            re.compile(r"DOMPurify\.sanitize|sanitizeHtml|xss\("),
        ],
    ),
    # XSS — dangerouslySetInnerHTML (React)
    DangerousSink(
        vuln_type=VulnerabilityType.XSS,
        pattern=re.compile(r"dangerouslySetInnerHTML"),
        title="XSS via dangerouslySetInnerHTML",
        description=(
            "dangerouslySetInnerHTML bypasses React's XSS protections. "
            "User-controlled data passed here enables script injection."
        ),
        remediation="Sanitize HTML with DOMPurify before using dangerouslySetInnerHTML.",
        confidence=0.70,
        safe_guards=[
            re.compile(r"DOMPurify\.sanitize|sanitize"),
        ],
    ),
    # Insecure Deserialization — eval
    DangerousSink(
        vuln_type=VulnerabilityType.INSECURE_DESERIALIZATION,
        pattern=re.compile(r"""\beval\(\s*(?!['"])"""),
        title="Code injection via eval()",
        description=(
            "eval() executes arbitrary JavaScript. If the argument includes "
            "user input, an attacker can run any code."
        ),
        remediation="Avoid eval(). Use JSON.parse() for data, or Function() with strict input.",
        confidence=0.80,
        safe_guards=[],
    ),
    # Insecure Deserialization — new Function
    DangerousSink(
        vuln_type=VulnerabilityType.INSECURE_DESERIALIZATION,
        pattern=re.compile(r"""\bnew\s+Function\(\s*(?!['"])"""),
        title="Code injection via new Function()",
        description=(
            "new Function() compiles and runs arbitrary code, similar to eval(). "
            "User input in the argument enables code injection."
        ),
        remediation="Avoid new Function() with dynamic input. Use safer alternatives.",
        confidence=0.75,
        safe_guards=[],
    ),
    # Path Traversal
    DangerousSink(
        vuln_type=VulnerabilityType.PATH_TRAVERSAL,
        pattern=re.compile(
            r"""(?:readFile|readFileSync|createReadStream)\(\s*(?:req\.|params\.|`|.*\+)"""
        ),
        title="Path traversal via user-controlled file path",
        description=(
            "File read with a path derived from user input. '../' sequences "
            "can escape the intended directory."
        ),
        remediation=(
            "Use path.resolve() and verify the result stays within the allowed directory."
        ),
        confidence=0.70,
        safe_guards=[
            re.compile(r"path\.resolve|path\.normalize|\.startsWith\("),
        ],
    ),
    # SSRF
    DangerousSink(
        vuln_type=VulnerabilityType.SSRF,
        pattern=re.compile(r"""(?:fetch|axios\.\w+|got|request)\(\s*(?:`|req\.|params\.|.*\+)"""),
        title="Potential SSRF: HTTP request with user-controlled URL",
        description=(
            "An HTTP request is made with a URL that may come from user input. "
            "This could be used to probe internal services."
        ),
        remediation="Validate and allowlist URLs. Block internal IP ranges.",
        confidence=0.65,
        safe_guards=[
            re.compile(r"(?:validateUrl|allowlist|whitelist)", re.IGNORECASE),
        ],
    ),
    # Weak Crypto
    DangerousSink(
        vuln_type=VulnerabilityType.WEAK_CRYPTO,
        pattern=re.compile(r"""createHash\(\s*['"](?:md5|sha1)['"]"""),
        title="Weak hash algorithm: MD5/SHA1",
        description="MD5 and SHA1 are cryptographically broken for security uses.",
        remediation="Use SHA-256+ for integrity, or bcrypt/scrypt for passwords.",
        confidence=0.65,
        safe_guards=[
            re.compile(r"(?:checksum|etag|cache)", re.IGNORECASE),
        ],
    ),
]


class JavaScriptSecurityPatterns(LanguageSecurityPatterns):
    """Security patterns for JavaScript and TypeScript."""

    @property
    def language(self) -> str:
        return "javascript"

    def scan(self, source_code: str, code_map: CodeMap) -> list[PatternMatch]:
        matches = self._scan_with_sinks(source_code, code_map, _JS_SINKS)
        matches.extend(detect_hardcoded_secrets(source_code, code_map.file_path))
        return matches
