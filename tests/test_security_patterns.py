"""Tests for security pattern detection across all languages.

Covers:
- Python, JavaScript, Java, Go, Rust, C/C++, C# pattern modules
- True positive detection (vulnerable code)
- False positive suppression (safe code with guards)
- Hardcoded secret detection and entropy filtering
- Pattern registry and lazy loading
"""

from __future__ import annotations

from nit.agents.analyzers.code import CodeMap
from nit.agents.analyzers.security import VulnerabilityType
from nit.agents.analyzers.security_patterns.base import (
    PatternMatch,
    detect_hardcoded_secrets,
    get_patterns_for_language,
)
from nit.parsing.treesitter import FunctionInfo

# ── Helpers ──────────────────────────────────────────────────────


def _make_code_map(
    file_path: str, language: str, functions: list[FunctionInfo] | None = None
) -> CodeMap:
    """Build a minimal CodeMap for testing."""
    return CodeMap(
        file_path=file_path,
        language=language,
        functions=functions or [],
    )


def _scan(language: str, source: str, file_path: str = "test.py") -> list[PatternMatch]:
    """Scan source code with the given language's patterns."""
    patterns = get_patterns_for_language(language)
    assert patterns is not None, f"No patterns for {language}"
    code_map = _make_code_map(file_path, language)
    return patterns.scan(source, code_map)


def _has_vuln(matches: list[PatternMatch], vuln_type: VulnerabilityType) -> bool:
    """Check if any match has the given vulnerability type."""
    return any(m.vuln_type == vuln_type for m in matches)


# ── Registry Tests ───────────────────────────────────────────────


def test_registry_loads_all_languages() -> None:
    """All seven language modules are registered."""
    for lang in ("python", "javascript", "java", "go", "rust", "c", "cpp", "csharp"):
        assert get_patterns_for_language(lang) is not None, f"Missing patterns for {lang}"


def test_registry_returns_none_for_unknown() -> None:
    """Unknown languages return None."""
    assert get_patterns_for_language("brainfuck") is None


# ── Python Patterns ──────────────────────────────────────────────


class TestPythonPatterns:
    """Python security pattern detection."""

    def test_sql_injection_fstring(self) -> None:
        code = 'cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")'
        matches = _scan("python", code)
        assert _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_sql_injection_format(self) -> None:
        code = 'cursor.execute("SELECT * FROM users WHERE id = {}".format(user_id))'
        matches = _scan("python", code)
        assert _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_sql_injection_percent(self) -> None:
        code = 'cursor.execute("SELECT * FROM users WHERE id = %s" % (user_id,))'
        matches = _scan("python", code)
        assert _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_sql_injection_safe_parameterized(self) -> None:
        code = "cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))"
        matches = _scan("python", code)
        assert not _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_command_injection_shell_true(self) -> None:
        code = "subprocess.run(cmd, shell=True)"
        matches = _scan("python", code)
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_command_injection_os_system(self) -> None:
        code = "os.system(user_input)"
        matches = _scan("python", code)
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_command_injection_safe_literal(self) -> None:
        code = "subprocess.run('echo hello', shell=True)"
        matches = _scan("python", code)
        assert not _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_pickle_loads(self) -> None:
        code = "data = pickle.loads(untrusted_bytes)"
        matches = _scan("python", code)
        assert _has_vuln(matches, VulnerabilityType.INSECURE_DESERIALIZATION)

    def test_yaml_load_unsafe(self) -> None:
        code = "config = yaml.load(raw_data)"
        matches = _scan("python", code)
        assert _has_vuln(matches, VulnerabilityType.INSECURE_DESERIALIZATION)

    def test_yaml_load_safe_loader(self) -> None:
        code = "config = yaml.load(raw_data, Loader=SafeLoader)"
        matches = _scan("python", code)
        assert not _has_vuln(matches, VulnerabilityType.INSECURE_DESERIALIZATION)

    def test_weak_crypto_md5(self) -> None:
        code = "h = hashlib.md5(data)"
        matches = _scan("python", code)
        assert _has_vuln(matches, VulnerabilityType.WEAK_CRYPTO)

    def test_weak_crypto_sha1(self) -> None:
        code = "h = hashlib.sha1(data)"
        matches = _scan("python", code)
        assert _has_vuln(matches, VulnerabilityType.WEAK_CRYPTO)

    def test_weak_crypto_suppressed_for_checksum(self) -> None:
        code = "checksum = hashlib.md5(data)"
        matches = _scan("python", code)
        assert not _has_vuln(matches, VulnerabilityType.WEAK_CRYPTO)

    def test_xss_mark_safe(self) -> None:
        code = 'html = mark_safe(f"<b>{user_input}</b>")'
        matches = _scan("python", code)
        assert _has_vuln(matches, VulnerabilityType.XSS)

    def test_ssrf_requests_user_url(self) -> None:
        code = 'resp = requests.get(f"http://{user_host}/api")'
        matches = _scan("python", code)
        assert _has_vuln(matches, VulnerabilityType.SSRF)

    def test_no_findings_clean_code(self) -> None:
        code = "result = some_function(arg1, arg2)"
        matches = _scan("python", code)
        assert len(matches) == 0


# ── JavaScript Patterns ──────────────────────────────────────────


class TestJavaScriptPatterns:
    """JavaScript/TypeScript security pattern detection."""

    def test_sql_injection_template_literal(self) -> None:
        code = "db.query(`SELECT * FROM users WHERE id = ${userId}`)"
        matches = _scan("javascript", code, "app.js")
        assert _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_sql_injection_safe_parameterized(self) -> None:
        code = "db.query('SELECT * FROM users WHERE id = $1', [userId])"
        matches = _scan("javascript", code, "app.js")
        assert not _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_command_injection_exec(self) -> None:
        code = "child_process.exec(`ls ${userDir}`)"
        matches = _scan("javascript", code, "app.js")
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_xss_innerhtml(self) -> None:
        code = "element.innerHTML = userContent"
        matches = _scan("javascript", code, "app.js")
        assert _has_vuln(matches, VulnerabilityType.XSS)

    def test_xss_innerhtml_safe_dompurify(self) -> None:
        code = "element.innerHTML = DOMPurify.sanitize(userContent)"
        matches = _scan("javascript", code, "app.js")
        assert not _has_vuln(matches, VulnerabilityType.XSS)

    def test_xss_dangerously_set(self) -> None:
        code = "<div dangerouslySetInnerHTML={{ __html: content }} />"
        matches = _scan("javascript", code, "App.jsx")
        assert _has_vuln(matches, VulnerabilityType.XSS)

    def test_eval_code_injection(self) -> None:
        code = "eval(userCode)"
        matches = _scan("javascript", code, "app.js")
        assert _has_vuln(matches, VulnerabilityType.INSECURE_DESERIALIZATION)

    def test_new_function_injection(self) -> None:
        code = "const fn = new Function(userCode)"
        matches = _scan("javascript", code, "app.js")
        assert _has_vuln(matches, VulnerabilityType.INSECURE_DESERIALIZATION)

    def test_weak_crypto_md5(self) -> None:
        code = "const hash = createHash('md5')"
        matches = _scan("javascript", code, "app.js")
        assert _has_vuln(matches, VulnerabilityType.WEAK_CRYPTO)

    def test_no_findings_clean_code(self) -> None:
        code = "const result = await fetchData(id)"
        matches = _scan("javascript", code, "app.js")
        assert len(matches) == 0


# ── Java Patterns ────────────────────────────────────────────────


class TestJavaPatterns:
    """Java security pattern detection."""

    def test_sql_injection_string_concat(self) -> None:
        code = 'stmt.executeQuery("SELECT * FROM users WHERE id = " + userId);'
        matches = _scan("java", code, "App.java")
        assert _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_sql_injection_safe_prepared(self) -> None:
        code = 'PreparedStatement ps = conn.prepareStatement("SELECT * FROM users WHERE id = ?");'
        matches = _scan("java", code, "App.java")
        assert not _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_command_injection_runtime_exec(self) -> None:
        code = 'Runtime.getRuntime().exec("cmd " + userInput);'
        matches = _scan("java", code, "App.java")
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_insecure_deserialization(self) -> None:
        code = "ObjectInputStream ois = new ObjectInputStream(inputStream);"
        matches = _scan("java", code, "App.java")
        assert _has_vuln(matches, VulnerabilityType.INSECURE_DESERIALIZATION)

    def test_weak_crypto_md5(self) -> None:
        code = 'MessageDigest md = MessageDigest.getInstance("MD5");'
        matches = _scan("java", code, "App.java")
        assert _has_vuln(matches, VulnerabilityType.WEAK_CRYPTO)


# ── Go Patterns ──────────────────────────────────────────────────


class TestGoPatterns:
    """Go security pattern detection."""

    def test_sql_injection_sprintf(self) -> None:
        code = 'rows, err := db.Query(fmt.Sprintf("SELECT * FROM users WHERE id = %s", id))'
        matches = _scan("go", code, "main.go")
        assert _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_sql_injection_concat(self) -> None:
        code = 'rows, err := db.Query("SELECT * FROM users WHERE id = " + id)'
        matches = _scan("go", code, "main.go")
        assert _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_command_injection(self) -> None:
        code = 'cmd := exec.Command(fmt.Sprintf("ls %s", dir))'
        matches = _scan("go", code, "main.go")
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_xss_template_html(self) -> None:
        code = "unsafe := template.HTML(userInput)"
        matches = _scan("go", code, "main.go")
        assert _has_vuln(matches, VulnerabilityType.XSS)

    def test_weak_crypto(self) -> None:
        code = "h := md5.New()"
        matches = _scan("go", code, "main.go")
        assert _has_vuln(matches, VulnerabilityType.WEAK_CRYPTO)


# ── Rust Patterns ────────────────────────────────────────────────


class TestRustPatterns:
    """Rust security pattern detection."""

    def test_sql_injection_format(self) -> None:
        code = 'sqlx::query(&format!("SELECT * FROM users WHERE id = {}", id))'
        matches = _scan("rust", code, "main.rs")
        assert _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_command_injection(self) -> None:
        code = 'Command::new(&format!("ls {}", dir))'
        matches = _scan("rust", code, "main.rs")
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_weak_crypto(self) -> None:
        code = "let digest = Md5::digest(data);"
        matches = _scan("rust", code, "main.rs")
        assert _has_vuln(matches, VulnerabilityType.WEAK_CRYPTO)


# ── C/C++ Patterns ──────────────────────────────────────────────


class TestCCppPatterns:
    """C/C++ security pattern detection."""

    def test_command_injection_system(self) -> None:
        code = "system(user_input);"
        matches = _scan("c", code, "main.c")
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_buffer_overflow_gets(self) -> None:
        code = "gets(buffer);"
        matches = _scan("c", code, "main.c")
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_buffer_overflow_strcpy(self) -> None:
        code = "strcpy(dest, src);"
        matches = _scan("c", code, "main.c")
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_format_string_vuln(self) -> None:
        code = "printf(user_input);"
        matches = _scan("c", code, "main.c")
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_weak_crypto(self) -> None:
        code = "MD5_Init(&ctx);"
        matches = _scan("c", code, "main.c")
        assert _has_vuln(matches, VulnerabilityType.WEAK_CRYPTO)

    def test_cpp_uses_same_patterns(self) -> None:
        code = "system(user_input);"
        matches = _scan("cpp", code, "main.cpp")
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)


# ── C# Patterns ─────────────────────────────────────────────────


class TestCSharpPatterns:
    """C# security pattern detection."""

    def test_sql_injection(self) -> None:
        code = 'new SqlCommand("SELECT * FROM users WHERE id = " + userId, conn);'
        matches = _scan("csharp", code, "App.cs")
        assert _has_vuln(matches, VulnerabilityType.SQL_INJECTION)

    def test_command_injection(self) -> None:
        code = 'Process.Start("cmd.exe", "/c " + userInput);'
        matches = _scan("csharp", code, "App.cs")
        assert _has_vuln(matches, VulnerabilityType.COMMAND_INJECTION)

    def test_insecure_deserialization(self) -> None:
        code = "BinaryFormatter bf = new BinaryFormatter(); bf.Deserialize(stream);"
        matches = _scan("csharp", code, "App.cs")
        assert _has_vuln(matches, VulnerabilityType.INSECURE_DESERIALIZATION)

    def test_xss_html_raw(self) -> None:
        code = "@Html.Raw(userInput)"
        matches = _scan("csharp", code, "View.cshtml")
        assert _has_vuln(matches, VulnerabilityType.XSS)

    def test_weak_crypto(self) -> None:
        code = "MD5.Create();"
        matches = _scan("csharp", code, "App.cs")
        assert _has_vuln(matches, VulnerabilityType.WEAK_CRYPTO)


# ── Hardcoded Secrets ────────────────────────────────────────────


class TestHardcodedSecrets:
    """Cross-language hardcoded secret detection."""

    def test_aws_key_detected(self) -> None:
        code = 'AWS_KEY = "AKIAIOSFODNN7ZRGK4Q3"'
        findings = detect_hardcoded_secrets(code, "config.py")
        assert len(findings) >= 1
        assert findings[0].vuln_type == VulnerabilityType.CREDENTIAL_LEAK

    def test_github_token_detected(self) -> None:
        code = 'token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"'
        findings = detect_hardcoded_secrets(code, "config.py")
        assert len(findings) >= 1
        assert findings[0].vuln_type == VulnerabilityType.CREDENTIAL_LEAK

    def test_stripe_key_detected(self) -> None:
        code = 'STRIPE_KEY = "sk_live_' + "0" * 24 + '"'
        findings = detect_hardcoded_secrets(code, "config.py")
        assert len(findings) >= 1
        assert findings[0].vuln_type == VulnerabilityType.CREDENTIAL_LEAK

    def test_generic_secret_high_entropy(self) -> None:
        code = 'password = "xK9#mP2$vL5nQ8wR"'
        findings = detect_hardcoded_secrets(code, "config.py")
        assert len(findings) >= 1

    def test_placeholder_not_flagged(self) -> None:
        code = 'api_key = "your-api-key-here"'
        findings = detect_hardcoded_secrets(code, "config.py")
        assert len(findings) == 0

    def test_test_file_skipped(self) -> None:
        code = 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"'
        findings = detect_hardcoded_secrets(code, "test_config.py")
        assert len(findings) == 0

    def test_fixture_file_skipped(self) -> None:
        code = 'token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"'
        findings = detect_hardcoded_secrets(code, "fixtures/data.py")
        assert len(findings) == 0

    def test_comment_line_skipped(self) -> None:
        code = '# AWS_KEY = "AKIAIOSFODNN7EXAMPLE"'
        findings = detect_hardcoded_secrets(code, "config.py")
        assert len(findings) == 0

    def test_low_entropy_generic_not_flagged(self) -> None:
        code = 'password = "aaaaaaaa"'
        findings = detect_hardcoded_secrets(code, "config.py")
        assert len(findings) == 0


# ── Pattern Match Structure ──────────────────────────────────────


class TestPatternMatchStructure:
    """Verify PatternMatch objects have expected attributes."""

    def test_match_has_line_number(self) -> None:
        code = "data = pickle.loads(untrusted)\nclean = json.loads(data)"
        matches = _scan("python", code)
        pickle_matches = [
            m for m in matches if m.vuln_type == VulnerabilityType.INSECURE_DESERIALIZATION
        ]
        assert len(pickle_matches) >= 1
        assert pickle_matches[0].line_number == 1

    def test_match_has_evidence(self) -> None:
        code = "os.system(user_input)"
        matches = _scan("python", code)
        assert len(matches) >= 1
        assert "os.system" in matches[0].evidence

    def test_match_has_confidence(self) -> None:
        code = "os.system(user_input)"
        matches = _scan("python", code)
        assert len(matches) >= 1
        assert 0.0 <= matches[0].confidence <= 1.0

    def test_match_has_title_and_description(self) -> None:
        code = "os.system(user_input)"
        matches = _scan("python", code)
        assert len(matches) >= 1
        assert matches[0].title
        assert matches[0].description

    def test_match_enclosing_function(self) -> None:
        code = "def handler():\n    os.system(user_input)"
        func = FunctionInfo(
            name="handler",
            return_type="None",
            start_line=1,
            end_line=2,
            body_text="os.system(user_input)",
        )
        code_map = _make_code_map("app.py", "python", [func])
        patterns = get_patterns_for_language("python")
        assert patterns is not None
        matches = patterns.scan(code, code_map)
        cmd_matches = [m for m in matches if m.vuln_type == VulnerabilityType.COMMAND_INJECTION]
        assert len(cmd_matches) >= 1
        assert cmd_matches[0].function_name == "handler"
