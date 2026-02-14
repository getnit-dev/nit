"""Security pattern detection modules for each supported language.

Patterns are eagerly registered when this package is first imported.
"""

from nit.agents.analyzers.security_patterns.base import (
    _LANGUAGE_PATTERNS,
    register_patterns,
)
from nit.agents.analyzers.security_patterns.c_cpp import CCppSecurityPatterns
from nit.agents.analyzers.security_patterns.csharp import CSharpSecurityPatterns
from nit.agents.analyzers.security_patterns.go import GoSecurityPatterns
from nit.agents.analyzers.security_patterns.java import JavaSecurityPatterns
from nit.agents.analyzers.security_patterns.javascript import JavaScriptSecurityPatterns
from nit.agents.analyzers.security_patterns.python import PythonSecurityPatterns
from nit.agents.analyzers.security_patterns.rust import RustSecurityPatterns

register_patterns(PythonSecurityPatterns())
register_patterns(JavaScriptSecurityPatterns())
register_patterns(JavaSecurityPatterns())
register_patterns(GoSecurityPatterns())
register_patterns(RustSecurityPatterns())
register_patterns(CSharpSecurityPatterns())
_c_cpp = CCppSecurityPatterns()
register_patterns(_c_cpp)
# Register under "cpp" alias so both "c" and "cpp" resolve to the same patterns.
_LANGUAGE_PATTERNS["cpp"] = _c_cpp
