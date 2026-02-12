"""C#-specific security pattern detection."""

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

_CSHARP_SINKS: list[DangerousSink] = [
    # SQL Injection — SqlCommand with string concatenation
    DangerousSink(
        vuln_type=VulnerabilityType.SQL_INJECTION,
        pattern=re.compile(r"""(?:SqlCommand|OleDbCommand)\(\s*(?:\$"|.*\+|string\.Format)"""),
        title="SQL injection via string interpolation in SqlCommand",
        description=(
            "SQL query built with string interpolation or concatenation in "
            "a SqlCommand. User input can alter the query."
        ),
        remediation='Use SqlCommand with SqlParameter: cmd.Parameters.AddWithValue("@id", id)',
        confidence=0.85,
        safe_guards=[
            re.compile(r"Parameters\.Add|SqlParameter"),
        ],
    ),
    # Command Injection — Process.Start
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"""Process\.Start\(\s*(?:\$"|.*\+|string\.Format)"""),
        title="Command injection via Process.Start()",
        description="Process.Start() with dynamically constructed arguments.",
        remediation=(
            "Use ProcessStartInfo with FileName and Arguments set separately. "
            "Avoid passing user input directly into the command string."
        ),
        confidence=0.75,
        safe_guards=[],
    ),
    # Insecure Deserialization — BinaryFormatter
    DangerousSink(
        vuln_type=VulnerabilityType.INSECURE_DESERIALIZATION,
        pattern=re.compile(r"""\bBinaryFormatter\b.*\.Deserialize\("""),
        title="Insecure deserialization: BinaryFormatter",
        description=(
            "BinaryFormatter.Deserialize() can execute arbitrary code. "
            "Microsoft has deprecated it due to security risks."
        ),
        remediation="Use System.Text.Json or JsonSerializer instead of BinaryFormatter.",
        confidence=0.90,
        safe_guards=[],
    ),
    # Weak Crypto — MD5/SHA1
    DangerousSink(
        vuln_type=VulnerabilityType.WEAK_CRYPTO,
        pattern=re.compile(r"""(?:MD5|SHA1)\.Create\("""),
        title="Weak hash algorithm: MD5/SHA1",
        description="MD5 and SHA1 are broken for cryptographic purposes.",
        remediation="Use SHA256.Create() or SHA512.Create().",
        confidence=0.65,
        safe_guards=[
            re.compile(r"(?:checksum|etag|fingerprint)", re.IGNORECASE),
        ],
    ),
    # Weak Crypto — DES
    DangerousSink(
        vuln_type=VulnerabilityType.WEAK_CRYPTO,
        pattern=re.compile(r"""\b(?:DES|TripleDES|RC2)\.Create\("""),
        title="Weak cipher: DES/TripleDES/RC2",
        description="DES, TripleDES, and RC2 are outdated and insecure.",
        remediation="Use Aes.Create() with a strong key size (256-bit).",
        confidence=0.80,
        safe_guards=[],
    ),
    # XXE — XmlReader without DTD restrictions
    DangerousSink(
        vuln_type=VulnerabilityType.INSECURE_DESERIALIZATION,
        pattern=re.compile(r"""\bXmlReader\.Create\("""),
        title="Potential XXE: XmlReader without safe settings",
        description=(
            "XmlReader without DtdProcessing.Prohibit is vulnerable to "
            "XML External Entity attacks."
        ),
        remediation="Set DtdProcessing = DtdProcessing.Prohibit in XmlReaderSettings.",
        confidence=0.55,
        safe_guards=[
            re.compile(r"DtdProcessing\.Prohibit|DtdProcessing\.Ignore"),
        ],
    ),
    # Path Traversal
    DangerousSink(
        vuln_type=VulnerabilityType.PATH_TRAVERSAL,
        pattern=re.compile(
            r"""(?:File\.(?:ReadAll|Open|WriteAll)|StreamReader\()\s*\(\s*(?:\$"|.*\+|Request\.)"""
        ),
        title="Path traversal via user-controlled file path",
        description="File operation with path from user input.",
        remediation="Use Path.GetFullPath() and verify the result is within the allowed directory.",
        confidence=0.70,
        safe_guards=[
            re.compile(r"GetFullPath|Path\.Combine.*StartsWith"),
        ],
    ),
    # SSRF
    DangerousSink(
        vuln_type=VulnerabilityType.SSRF,
        pattern=re.compile(
            r"""(?:HttpClient\.GetAsync|WebRequest\.Create)\(\s*(?:\$"|.*\+|Request\.)"""
        ),
        title="Potential SSRF: HTTP request with user-controlled URL",
        description="HTTP request URL derived from user input.",
        remediation="Validate and allowlist URLs before making requests.",
        confidence=0.65,
        safe_guards=[],
    ),
    # XSS — Html.Raw
    DangerousSink(
        vuln_type=VulnerabilityType.XSS,
        pattern=re.compile(r"""Html\.Raw\("""),
        title="XSS via Html.Raw()",
        description=(
            "Html.Raw() bypasses Razor auto-escaping. User-controlled data "
            "passed here enables cross-site scripting."
        ),
        remediation="Encode user input with Html.Encode() or let Razor auto-escape.",
        confidence=0.70,
        safe_guards=[
            re.compile(r"Html\.Encode|HtmlEncoder|sanitize", re.IGNORECASE),
        ],
    ),
]


class CSharpSecurityPatterns(LanguageSecurityPatterns):
    """Security patterns for C#."""

    @property
    def language(self) -> str:
        return "csharp"

    def scan(self, source_code: str, code_map: CodeMap) -> list[PatternMatch]:
        matches = self._scan_with_sinks(source_code, code_map, _CSHARP_SINKS)
        matches.extend(detect_hardcoded_secrets(source_code, code_map.file_path))
        return matches
