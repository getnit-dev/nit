"""Framework detector — identify test/doc frameworks used in a project."""

from __future__ import annotations

import contextlib
import fnmatch
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.agents.detectors.signals import (
    CMakePattern,
    ConfigFile,
    Dependency,
    DetectedFramework,
    FilePattern,
    FrameworkCategory,
    FrameworkProfile,
    FrameworkRule,
    ImportPattern,
    PackageJsonField,
    Signal,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Default directories to skip during scanning (same set as stack detector).
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".nit",
        ".next",
        "target",
        "vendor",
    }
)

# Minimum confidence to include a framework in results.
_MIN_CONFIDENCE = 0.3

# Confidence threshold below which we would suggest LLM fallback.
_LLM_FALLBACK_THRESHOLD = 0.8


# ── Built-in framework rules ───────────────────────────────────────


def _js_ts_rules() -> list[FrameworkRule]:
    """Detection rules for JavaScript/TypeScript frameworks."""
    return [
        # ── Vitest ──
        FrameworkRule(
            name="vitest",
            language="javascript",
            category=FrameworkCategory.UNIT_TEST,
            signals=[
                ConfigFile("vitest.config.*"),
                ConfigFile("vitest.workspace.*"),
                Dependency("vitest", dev_only=True),
                ImportPattern(r"""from\s+['"]vitest['"]"""),
                ImportPattern(r"""import\s*\{[^}]*\}\s*from\s+['"]vitest['"]"""),
                FilePattern("**/*.test.ts"),
                FilePattern("**/*.test.tsx"),
                FilePattern("**/*.spec.ts"),
                PackageJsonField("scripts.test", "vitest"),
            ],
        ),
        # ── Jest ──
        FrameworkRule(
            name="jest",
            language="javascript",
            category=FrameworkCategory.UNIT_TEST,
            signals=[
                ConfigFile("jest.config.*"),
                Dependency("jest", dev_only=True),
                Dependency("@jest/core", dev_only=True),
                Dependency("ts-jest", dev_only=True),
                ImportPattern(r"""from\s+['"]@jest/globals['"]"""),
                FilePattern("**/*.test.js"),
                FilePattern("**/*.test.jsx"),
                FilePattern("**/*.spec.js"),
                PackageJsonField("scripts.test", "jest"),
                PackageJsonField("jest", ""),  # presence of "jest" top-level key
            ],
        ),
        # ── Mocha ──
        FrameworkRule(
            name="mocha",
            language="javascript",
            category=FrameworkCategory.UNIT_TEST,
            signals=[
                ConfigFile(".mocharc.*"),
                ConfigFile(".mocharc.yml"),
                Dependency("mocha", dev_only=True),
                ImportPattern(r"""require\s*\(\s*['"]mocha['"]"""),
                PackageJsonField("scripts.test", "mocha"),
            ],
        ),
        # ── Playwright ──
        FrameworkRule(
            name="playwright",
            language="javascript",
            category=FrameworkCategory.E2E_TEST,
            signals=[
                ConfigFile("playwright.config.*"),
                Dependency("@playwright/test", dev_only=True),
                ImportPattern(r"""from\s+['"]@playwright/test['"]"""),
                FilePattern("**/*.spec.ts"),
                FilePattern("**/e2e/**/*.ts"),
            ],
        ),
        # ── Cypress ──
        FrameworkRule(
            name="cypress",
            language="javascript",
            category=FrameworkCategory.E2E_TEST,
            signals=[
                ConfigFile("cypress.config.*"),
                ConfigFile("cypress.json"),
                Dependency("cypress", dev_only=True),
                FilePattern("cypress/e2e/**/*.cy.*"),
                FilePattern("cypress/integration/**/*.spec.*"),
                PackageJsonField("scripts.cypress", "cypress"),
            ],
        ),
    ]


def _python_rules() -> list[FrameworkRule]:
    """Detection rules for Python frameworks."""
    return [
        # ── pytest ──
        FrameworkRule(
            name="pytest",
            language="python",
            category=FrameworkCategory.UNIT_TEST,
            signals=[
                ConfigFile("conftest.py"),
                ConfigFile("pytest.ini"),
                Dependency("pytest", dev_only=True),
                ImportPattern(r"import\s+pytest"),
                ImportPattern(r"from\s+pytest\s+import"),
                FilePattern("**/test_*.py"),
                FilePattern("**/*_test.py"),
            ],
        ),
        # ── unittest ──
        FrameworkRule(
            name="unittest",
            language="python",
            category=FrameworkCategory.UNIT_TEST,
            signals=[
                ImportPattern(r"import\s+unittest"),
                ImportPattern(r"from\s+unittest\s+import"),
                ImportPattern(r"from\s+unittest\.mock\s+import"),
                FilePattern("**/test_*.py"),
            ],
        ),
    ]


def _cpp_rules() -> list[FrameworkRule]:
    """Detection rules for C/C++ frameworks."""
    return [
        # ── Google Test ──
        FrameworkRule(
            name="gtest",
            language="cpp",
            category=FrameworkCategory.UNIT_TEST,
            signals=[
                CMakePattern(r"find_package\s*\(\s*GTest"),
                CMakePattern(r"gtest_discover_tests"),
                CMakePattern(r"target_link_libraries\s*\([^)]*gtest"),
                ImportPattern(r"""#include\s*[<"]gtest/gtest\.h[>"]"""),
                FilePattern("**/*_test.cpp"),
                FilePattern("**/*_test.cc"),
            ],
        ),
        # ── Catch2 ──
        FrameworkRule(
            name="catch2",
            language="cpp",
            category=FrameworkCategory.UNIT_TEST,
            signals=[
                CMakePattern(r"find_package\s*\(\s*Catch2"),
                CMakePattern(r"catch_discover_tests"),
                CMakePattern(r"target_link_libraries\s*\([^)]*Catch2::"),
                ImportPattern(r"""#include\s*[<"](catch2/catch[^">]*|catch\.hpp)[>"]"""),
                FilePattern("**/*.catch2.cpp"),
            ],
        ),
    ]


def builtin_rules() -> list[FrameworkRule]:
    """Return all built-in framework detection rules."""
    return [*_js_ts_rules(), *_python_rules(), *_cpp_rules()]


# ── Manifest helpers ────────────────────────────────────────────────


@dataclass
class _ProjectFiles:
    """Pre-scanned project artefacts used for signal matching."""

    root: Path
    file_names: set[str] = field(default_factory=set)
    relative_paths: list[str] = field(default_factory=list)
    package_json: dict[str, Any] = field(default_factory=dict)
    pyproject_toml_text: str = ""
    requirements_txt_lines: list[str] = field(default_factory=list)
    source_snippets: dict[str, str] = field(default_factory=dict)


def _scan_project(root: Path, skip_dirs: frozenset[str]) -> _ProjectFiles:
    """Walk the project tree once and collect everything we need."""
    pf = _ProjectFiles(root=root)

    for child in _walk(root, skip_dirs):
        rel = str(child.relative_to(root))
        pf.relative_paths.append(rel)
        pf.file_names.add(child.name)

        # Collect small source samples for import pattern matching
        if (
            child.suffix
            in {
                ".py",
                ".js",
                ".ts",
                ".jsx",
                ".tsx",
                ".mjs",
                ".cjs",
                ".cpp",
                ".cc",
                ".cxx",
                ".h",
                ".hpp",
                ".hh",
                ".hxx",
            }
            or child.name == "CMakeLists.txt"
        ):
            with contextlib.suppress(OSError):
                pf.source_snippets[rel] = child.read_text(
                    encoding="utf-8",
                    errors="replace",
                )[:8192]

    # Parse package.json
    pkg_path = root / "package.json"
    if pkg_path.is_file():
        with contextlib.suppress(OSError, json.JSONDecodeError):
            pf.package_json = json.loads(pkg_path.read_text(encoding="utf-8"))

    # Read pyproject.toml as raw text (avoid TOML dependency)
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.is_file():
        with contextlib.suppress(OSError):
            pf.pyproject_toml_text = pyproject_path.read_text(encoding="utf-8")

    # Read requirements files
    for req_name in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt"):
        req_path = root / req_name
        if req_path.is_file():
            with contextlib.suppress(OSError):
                pf.requirements_txt_lines.extend(
                    req_path.read_text(encoding="utf-8").splitlines(),
                )

    return pf


def _walk(root: Path, skip_dirs: frozenset[str]) -> list[Path]:
    """Recursively collect all files under *root*, skipping *skip_dirs*."""
    result: list[Path] = []
    try:
        children = sorted(root.iterdir())
    except OSError:
        return result
    for child in children:
        if child.is_dir():
            if child.name not in skip_dirs:
                result.extend(_walk(child, skip_dirs))
        elif child.is_file():
            result.append(child)
    return result


# ── Signal matchers ─────────────────────────────────────────────────


def _match_config_file(signal: ConfigFile, pf: _ProjectFiles) -> bool:
    """Check whether any file in the project root matches *signal.pattern*."""
    return any(fnmatch.fnmatch(name, signal.pattern) for name in pf.file_names)


def _match_dependency(signal: Dependency, pf: _ProjectFiles) -> bool:
    """Check package.json deps, pyproject.toml, or requirements.txt."""
    # JS/TS: check package.json
    if pf.package_json:
        for section in ("devDependencies", "dependencies"):
            deps = pf.package_json.get(section, {})
            if isinstance(deps, dict) and signal.name in deps:
                return True

    # Python: check pyproject.toml
    if pf.pyproject_toml_text and re.search(
        rf'["\']?{re.escape(signal.name)}["\']?',
        pf.pyproject_toml_text,
    ):
        return True

    # Python: check requirements.txt
    for line in pf.requirements_txt_lines:
        stripped = line.strip().split("#")[0].strip()
        pkg = re.split(r"[<>=!~;\[]", stripped)[0].strip()
        if pkg.lower() == signal.name.lower():
            return True

    return False


def _match_import_pattern(signal: ImportPattern, pf: _ProjectFiles) -> bool:
    """Scan collected source snippets for the import regex."""
    compiled = re.compile(signal.pattern)
    return any(compiled.search(snippet) for snippet in pf.source_snippets.values())


def _match_file_pattern(signal: FilePattern, pf: _ProjectFiles) -> bool:
    """Check whether any relative path matches the glob."""
    return any(fnmatch.fnmatch(rp, signal.glob) for rp in pf.relative_paths)


def _match_cmake_pattern(signal: CMakePattern, pf: _ProjectFiles) -> bool:
    """Search CMakeLists.txt files for the given pattern."""
    for rel, snippet in pf.source_snippets.items():
        if not rel.endswith("CMakeLists.txt"):
            continue
        try:
            if re.search(signal.pattern, snippet, flags=re.IGNORECASE):
                return True
        except re.error:
            if signal.pattern.lower() in snippet.lower():
                return True
    return False


def _match_package_json_field(signal: PackageJsonField, pf: _ProjectFiles) -> bool:
    """Traverse a dot-path into package.json and check the value."""
    if not pf.package_json or not signal.field_path:
        return False
    parts = signal.field_path.split(".")
    obj: Any = pf.package_json
    for part in parts:
        if not isinstance(obj, dict) or part not in obj:
            return False
        obj = obj[part]
    if signal.value_pattern == "":
        # Empty pattern means just check existence of the key
        return True
    if isinstance(obj, str):
        return signal.value_pattern in obj
    return False


_MATCHERS: dict[type[Signal], Callable[..., bool]] = {
    ConfigFile: _match_config_file,
    Dependency: _match_dependency,
    ImportPattern: _match_import_pattern,
    FilePattern: _match_file_pattern,
    CMakePattern: _match_cmake_pattern,
    PackageJsonField: _match_package_json_field,
}


# ── Core scoring logic ──────────────────────────────────────────────


def _evaluate_rule(
    rule: FrameworkRule,
    pf: _ProjectFiles,
) -> DetectedFramework | None:
    """Evaluate a single framework rule against the project.

    Returns a ``DetectedFramework`` if at least one signal matches, or
    ``None`` if no signals match.
    """
    matched: list[Signal] = []
    for signal in rule.signals:
        matcher = _MATCHERS.get(type(signal))
        if matcher is not None and matcher(signal, pf):
            matched.append(signal)

    if not matched:
        return None

    # Confidence = highest matched signal weight, with a small breadth
    # bonus for each additional distinct signal *type* that matches.
    max_weight = max(s.weight for s in matched)
    distinct_types = len({type(s) for s in matched})
    breadth_bonus = min((distinct_types - 1) * 0.02, 0.1)
    confidence = round(min(max_weight + breadth_bonus, 1.0), 4)

    return DetectedFramework(
        name=rule.name,
        language=rule.language,
        category=rule.category,
        confidence=confidence,
        matched_signals=matched,
    )


def _resolve_conflicts(frameworks: list[DetectedFramework]) -> list[DetectedFramework]:
    """When multiple frameworks detected for the same language+category, keep the best.

    For each unique ``(language, category)`` pair, only the framework with
    the highest confidence is retained.
    """
    best: dict[tuple[str, FrameworkCategory], DetectedFramework] = {}
    for fw in frameworks:
        key = (fw.language, fw.category)
        existing = best.get(key)
        if existing is None or fw.confidence > existing.confidence:
            best[key] = fw
    return sorted(best.values(), key=lambda f: (-f.confidence, f.name))


# ── Public API ──────────────────────────────────────────────────────


def detect_frameworks(
    root: str | Path,
    *,
    rules: list[FrameworkRule] | None = None,
    skip_dirs: frozenset[str] | None = None,
    resolve_conflicts: bool = True,
) -> FrameworkProfile:
    """Scan *root* for known frameworks and return a ``FrameworkProfile``.

    Parameters
    ----------
    root:
        Project directory to scan.
    rules:
        Framework rules to evaluate.  Defaults to ``builtin_rules()``.
    skip_dirs:
        Directories to skip.  Defaults to the built-in skip set.
    resolve_conflicts:
        If ``True`` (default), only the highest-confidence framework per
        ``(language, category)`` pair is kept.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise ValueError(f"Not a directory: {root_path}")

    effective_rules = rules if rules is not None else builtin_rules()
    effective_skip = skip_dirs if skip_dirs is not None else _SKIP_DIRS

    pf = _scan_project(root_path, effective_skip)

    detected: list[DetectedFramework] = []
    for rule in effective_rules:
        result = _evaluate_rule(rule, pf)
        if result is not None and result.confidence >= _MIN_CONFIDENCE:
            detected.append(result)

    if resolve_conflicts:
        detected = _resolve_conflicts(detected)

    return FrameworkProfile(frameworks=detected, root=str(root_path))


def needs_llm_fallback(profile: FrameworkProfile) -> list[DetectedFramework]:
    """Return frameworks whose confidence is below the LLM fallback threshold.

    The caller can use these to prompt an LLM with file samples for
    disambiguation.  This function does **not** call any LLM itself — the
    LLM engine (``nit.llm``) is not yet wired up.
    """
    return [fw for fw in profile.frameworks if fw.confidence < _LLM_FALLBACK_THRESHOLD]


# ── Agent wrapper ───────────────────────────────────────────────────


class FrameworkDetector(BaseAgent):
    """Agent that detects test and documentation frameworks in a project."""

    @property
    def name(self) -> str:
        return "framework-detector"

    @property
    def description(self) -> str:
        return "Identify test and documentation frameworks used in a project."

    async def run(self, task: TaskInput) -> TaskOutput:
        """Run framework detection on *task.target*.

        Optional context keys:

        * ``skip_dirs`` — override the default skip-directory set.
        * ``resolve_conflicts`` — ``True`` (default) to keep only best per category.
        """
        target = Path(task.target)
        skip_raw = task.context.get("skip_dirs")
        skip_dirs = frozenset(skip_raw) if skip_raw is not None else None
        resolve = bool(task.context.get("resolve_conflicts", True))

        try:
            profile = detect_frameworks(
                target,
                skip_dirs=skip_dirs,
                resolve_conflicts=resolve,
            )
        except ValueError as exc:
            return TaskOutput(status=TaskStatus.FAILED, errors=[str(exc)])

        ambiguous = needs_llm_fallback(profile)

        return TaskOutput(
            status=TaskStatus.COMPLETED,
            result={
                "root": profile.root,
                "frameworks": [
                    {
                        "name": fw.name,
                        "language": fw.language,
                        "category": fw.category.value,
                        "confidence": fw.confidence,
                        "matched_signals": [type(s).__name__ for s in fw.matched_signals],
                    }
                    for fw in profile.frameworks
                ],
                "needs_llm_fallback": [fw.name for fw in ambiguous],
            },
        )
