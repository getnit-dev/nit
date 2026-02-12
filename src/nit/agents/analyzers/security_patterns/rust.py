"""Rust-specific security pattern detection."""

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

_RUST_SINKS: list[DangerousSink] = [
    # SQL Injection — format! in query
    DangerousSink(
        vuln_type=VulnerabilityType.SQL_INJECTION,
        pattern=re.compile(r"""(?:query|execute)\(\s*&?format!\("""),
        title="SQL injection via format! in query",
        description=(
            "SQL query built with format!(). Variables interpolated into "
            "the query string can alter its structure."
        ),
        remediation='Use query parameters: sqlx::query("SELECT * FROM t WHERE id = $1").bind(id)',
        confidence=0.85,
        safe_guards=[],
    ),
    # Command Injection — Command::new with format!
    DangerousSink(
        vuln_type=VulnerabilityType.COMMAND_INJECTION,
        pattern=re.compile(r"""Command::new\(\s*(?:&?format!\(|.*\+)"""),
        title="Command injection via dynamically constructed command",
        description="Command::new() with a formatted string allows command injection.",
        remediation='Use Command::new("cmd").arg(user_input) with separate arguments.',
        confidence=0.75,
        safe_guards=[],
    ),
    # Insecure Deserialization — serde with untrusted data
    DangerousSink(
        vuln_type=VulnerabilityType.INSECURE_DESERIALIZATION,
        pattern=re.compile(r"""serde_(?:yaml|json|pickle)::from_(?:str|reader|slice)\("""),
        title="Deserialization of potentially untrusted data",
        description=(
            "Deserializing data from external sources. While Rust's serde is "
            "generally safer than pickle/eval, complex types with custom "
            "Deserialize impls can still cause issues."
        ),
        remediation="Validate and sanitize input before deserialization. Use strict schemas.",
        confidence=0.50,
        safe_guards=[],
    ),
    # Path Traversal
    DangerousSink(
        vuln_type=VulnerabilityType.PATH_TRAVERSAL,
        pattern=re.compile(r"""(?:File::open|read_to_string|fs::read)\(\s*(?:&?format!\(|.*\+)"""),
        title="Path traversal via user-controlled file path",
        description="File opened with a path constructed from potentially untrusted data.",
        remediation="Canonicalize the path and verify it stays within the intended directory.",
        confidence=0.70,
        safe_guards=[
            re.compile(r"canonicalize|strip_prefix"),
        ],
    ),
    # Weak Crypto
    DangerousSink(
        vuln_type=VulnerabilityType.WEAK_CRYPTO,
        pattern=re.compile(r"""(?:Md5|Sha1)::(?:new|digest)\("""),
        title="Weak hash algorithm: MD5/SHA1",
        description="MD5 and SHA1 are broken for cryptographic purposes.",
        remediation="Use Sha256::new() or stronger hash functions.",
        confidence=0.65,
        safe_guards=[
            re.compile(r"(?:checksum|etag|fingerprint)", re.IGNORECASE),
        ],
    ),
]


class RustSecurityPatterns(LanguageSecurityPatterns):
    """Security patterns for Rust."""

    @property
    def language(self) -> str:
        return "rust"

    def scan(self, source_code: str, code_map: CodeMap) -> list[PatternMatch]:
        matches = self._scan_with_sinks(source_code, code_map, _RUST_SINKS)
        matches.extend(detect_hardcoded_secrets(source_code, code_map.file_path))
        return matches
