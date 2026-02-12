"""Java-specific security pattern detection."""

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

_JAVA_SINKS: list[DangerousSink] = [
    # SQL Injection — JDBC string concatenation
    DangerousSink(
        vuln_type=VulnerabilityType.SQL_INJECTION,
        pattern=re.compile(r"""(?:executeQuery|executeUpdate|execute)\(\s*["'].*\+"""),
        title="SQL injection via string concatenation in JDBC",
        description=(
            "SQL query built by concatenating strings in a JDBC call. "
            "User input in these strings can alter the query."
        ),
        remediation="Use PreparedStatement with parameterized queries.",
        confidence=0.85,
        safe_guards=[
            re.compile(r"PreparedStatement|prepareStatement"),
        ],
    ),
    # Command Injection — Runtime.exec
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"""Runtime\.getRuntime\(\)\.exec\(\s*(?!new\s+String)"""),
        title="Command injection via Runtime.exec()",
        description=(
            "Runtime.exec() with a single string argument passes the command "
            "through a shell, enabling injection if user input is included."
        ),
        remediation="Use ProcessBuilder with command and arguments as separate elements.",
        confidence=0.75,
        safe_guards=[],
    ),
    # Insecure Deserialization — ObjectInputStream
    DangerousSink(
        vuln_type=VulnerabilityType.INSECURE_DESERIALIZATION,
        pattern=re.compile(r"""\bnew\s+ObjectInputStream\("""),
        title="Insecure deserialization: ObjectInputStream",
        description=(
            "ObjectInputStream.readObject() can execute arbitrary code when "
            "deserializing untrusted data (gadget chain attacks)."
        ),
        remediation=(
            "Use a serialization filter (ObjectInputFilter) or switch to a "
            "safe format like JSON with Jackson/Gson."
        ),
        confidence=0.80,
        safe_guards=[
            re.compile(r"ObjectInputFilter|setObjectInputFilter"),
        ],
    ),
    # Weak Crypto — MD5/SHA1
    DangerousSink(
        vuln_type=VulnerabilityType.WEAK_CRYPTO,
        pattern=re.compile(r"""MessageDigest\.getInstance\(\s*["'](?:MD5|SHA-?1)["']"""),
        title="Weak hash algorithm: MD5/SHA1",
        description="MD5 and SHA1 are broken for cryptographic purposes.",
        remediation='Use MessageDigest.getInstance("SHA-256") or stronger.',
        confidence=0.65,
        safe_guards=[
            re.compile(r"(?:checksum|etag|fingerprint)", re.IGNORECASE),
        ],
    ),
    # Weak Crypto — DES / ECB
    DangerousSink(
        vuln_type=VulnerabilityType.WEAK_CRYPTO,
        pattern=re.compile(r"""Cipher\.getInstance\(\s*["'](?:DES|DESede|.*ECB)"""),
        title="Weak cipher: DES or ECB mode",
        description="DES is broken and ECB mode leaks patterns in ciphertext.",
        remediation='Use AES with GCM or CBC mode: Cipher.getInstance("AES/GCM/NoPadding").',
        confidence=0.80,
        safe_guards=[],
    ),
    # XXE — XMLInputFactory / DocumentBuilder without DTD disabled
    DangerousSink(
        vuln_type=VulnerabilityType.INSECURE_DESERIALIZATION,
        pattern=re.compile(
            r"""(?:XMLInputFactory|DocumentBuilderFactory|SAXParserFactory)\.newInstance\("""
        ),
        title="Potential XXE: XML parser without DTD restrictions",
        description=(
            "XML parsers without DTD processing disabled are vulnerable to "
            "XML External Entity (XXE) attacks."
        ),
        remediation=(
            "Disable DTDs: factory.setFeature("
            '"http://apache.org/xml/features/disallow-doctype-decl", true)'
        ),
        confidence=0.60,
        safe_guards=[
            re.compile(
                r"disallow-doctype-decl|FEATURE_SECURE_PROCESSING|setExpandEntityReferences"
            ),
        ],
    ),
    # Path Traversal
    DangerousSink(
        vuln_type=VulnerabilityType.PATH_TRAVERSAL,
        pattern=re.compile(r"""new\s+File\(\s*(?:request\.getParameter|.*\+\s*request)"""),
        title="Path traversal via user-controlled File path",
        description="File path from user input without validation.",
        remediation="Canonicalize the path and verify it is within the allowed directory.",
        confidence=0.75,
        safe_guards=[
            re.compile(r"getCanonicalPath|normalize|toRealPath"),
        ],
    ),
    # SSRF
    DangerousSink(
        vuln_type=VulnerabilityType.SSRF,
        pattern=re.compile(r"""new\s+URL\(\s*(?:request\.getParameter|.*\+\s*request)"""),
        title="Potential SSRF: URL from user input",
        description="HTTP request URL derived from user input.",
        remediation="Validate and allowlist URLs before making requests.",
        confidence=0.65,
        safe_guards=[],
    ),
]


class JavaSecurityPatterns(LanguageSecurityPatterns):
    """Security patterns for Java."""

    @property
    def language(self) -> str:
        return "java"

    def scan(self, source_code: str, code_map: CodeMap) -> list[PatternMatch]:
        matches = self._scan_with_sinks(source_code, code_map, _JAVA_SINKS)
        matches.extend(detect_hardcoded_secrets(source_code, code_map.file_path))
        return matches
