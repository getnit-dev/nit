"""TestMapper — maps test files to the source files they exercise.

Uses naming conventions and import analysis to discover which source files
a given test file covers.  The mapping is used by the risk-based test
prioritizer to propagate risk scores from source files to tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ── Confidence levels ─────────────────────────────────────────────

CONFIDENCE_NAMING = 0.9
"""Confidence when a source file is found via naming convention."""

CONFIDENCE_IMPORT = 0.7
"""Confidence when a source file is found via import analysis."""

# ── Import-parsing regexes ────────────────────────────────────────

_PYTHON_FROM_IMPORT = re.compile(r"^\s*from\s+([\w.]+)\s+import\b", re.MULTILINE)
_PYTHON_IMPORT = re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE)
_JS_IMPORT_FROM = re.compile(r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"])""", re.MULTILINE)
_JS_REQUIRE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE)

# ── Data models ───────────────────────────────────────────────────


@dataclass
class TestMapping:
    """Result of mapping a single test file to its source files."""

    test_file: str
    """Path to the test file (as given)."""

    source_files: list[str] = field(default_factory=list)
    """Source files that this test exercises."""

    confidence: float = 0.0
    """Highest confidence among all mappings (0.0-1.0)."""


# ── TestMapper ────────────────────────────────────────────────────


class TestMapper:
    """Maps test files to the source files they cover."""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root

    # -- public API ------------------------------------------------

    def map_test_to_sources(self, test_file: Path) -> TestMapping:
        """Map a single test file to its source files.

        Tries naming conventions first, then falls back to import analysis.

        Args:
            test_file: Path to the test file.

        Returns:
            TestMapping with discovered source files and confidence.
        """
        mapping = TestMapping(test_file=str(test_file))

        naming_sources = self._map_by_naming(test_file)
        import_sources = self._map_by_imports(test_file)

        seen: set[str] = set()
        if naming_sources:
            mapping.confidence = CONFIDENCE_NAMING
            for src in naming_sources:
                if src not in seen:
                    seen.add(src)
                    mapping.source_files.append(src)

        if import_sources:
            if not mapping.confidence:
                mapping.confidence = CONFIDENCE_IMPORT
            for src in import_sources:
                if src not in seen:
                    seen.add(src)
                    mapping.source_files.append(src)

        return mapping

    def map_all_tests(self, test_files: list[Path]) -> list[TestMapping]:
        """Map multiple test files to their source files.

        Args:
            test_files: List of test file paths.

        Returns:
            List of TestMapping, one per test file.
        """
        return [self.map_test_to_sources(tf) for tf in test_files]

    # -- private helpers -------------------------------------------

    def _map_by_naming(self, test_file: Path) -> list[str]:
        """Find source files by naming convention.

        Supported conventions:
        - ``test_foo.py``  ->  ``foo.py``
        - ``test_foo_bar.py``  ->  ``foo_bar.py``
        - ``foo.test.ts``  ->  ``foo.ts``
        - ``foo.spec.js``  ->  ``foo.js``
        - ``foo_test.go``  ->  ``foo.go``
        """
        name = test_file.name
        suffix = test_file.suffix
        sources: list[str] = []

        # Python: test_foo.py -> foo.py
        if suffix == ".py" and name.startswith("test_"):
            candidate = name[len("test_") :]
            found = self._find_source_file(
                candidate,
                [self._root / "src", self._root / "lib", self._root],
            )
            if found:
                sources.append(found)

        # JS/TS: foo.test.ts -> foo.ts  /  foo.spec.js -> foo.js
        elif suffix in {".ts", ".js", ".tsx", ".jsx"}:
            stem = test_file.stem  # e.g. "foo.test"
            for marker in (".test", ".spec"):
                if stem.endswith(marker):
                    base_name = stem[: -len(marker)] + suffix
                    found = self._find_source_file(
                        base_name,
                        [self._root / "src", self._root],
                    )
                    if found:
                        sources.append(found)
                    break

        # Go: foo_test.go -> foo.go (same directory)
        elif suffix == ".go" and name.endswith("_test.go"):
            candidate = name[: -len("_test.go")] + ".go"
            search_dirs = [test_file.parent] if test_file.is_absolute() else [self._root]
            found = self._find_source_file(candidate, search_dirs)
            if found:
                sources.append(found)

        return sources

    def _map_by_imports(self, test_file: Path) -> list[str]:
        """Parse imports from a test file and resolve them to source paths."""
        full_path = test_file if test_file.is_absolute() else self._root / test_file
        if not full_path.exists():
            return []

        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []

        suffix = full_path.suffix
        sources: list[str] = []

        if suffix == ".py":
            sources = self._parse_python_imports(content)
        elif suffix in {".ts", ".js", ".tsx", ".jsx"}:
            sources = self._parse_js_imports(content, full_path)

        return sources

    def _parse_python_imports(self, content: str) -> list[str]:
        """Extract source file paths from Python import statements."""
        results: list[str] = []
        seen: set[str] = set()

        for pattern in (_PYTHON_FROM_IMPORT, _PYTHON_IMPORT):
            for match in pattern.finditer(content):
                module = match.group(1)
                resolved = self._resolve_python_module(module)
                if resolved and resolved not in seen:
                    seen.add(resolved)
                    results.append(resolved)

        return results

    def _resolve_python_module(self, module: str) -> str | None:
        """Convert a dotted Python module to a file path if it exists."""
        parts = module.replace(".", "/")
        candidates = [
            f"{parts}.py",
            f"{parts}/__init__.py",
        ]

        for base in (self._root / "src", self._root / "lib", self._root):
            for candidate in candidates:
                full = base / candidate
                if full.exists():
                    try:
                        return full.relative_to(self._root).as_posix()
                    except ValueError:
                        return full.as_posix()

        return None

    def _parse_js_imports(self, content: str, test_path: Path) -> list[str]:
        """Extract source file paths from JS/TS import statements."""
        results: list[str] = []
        seen: set[str] = set()

        for pattern in (_JS_IMPORT_FROM, _JS_REQUIRE):
            for match in pattern.finditer(content):
                specifier = match.group(1)
                resolved = self._resolve_js_import(specifier, test_path)
                if resolved and resolved not in seen:
                    seen.add(resolved)
                    results.append(resolved)

        return results

    def _resolve_js_import(self, specifier: str, test_path: Path) -> str | None:
        """Resolve a JS/TS import specifier to a file path."""
        # Only resolve relative imports
        if not specifier.startswith("."):
            return None

        base_dir = test_path.parent
        target = (base_dir / specifier).resolve()

        # Try exact path and common extensions
        extensions = ["", ".ts", ".js", ".tsx", ".jsx"]
        for ext in extensions:
            candidate = Path(str(target) + ext)
            if candidate.exists() and candidate.is_file():
                try:
                    return candidate.relative_to(self._root).as_posix()
                except ValueError:
                    return candidate.as_posix()

        return None

    def _find_source_file(self, name: str, search_dirs: list[Path]) -> str | None:
        """Search for a source file by name in the given directories.

        Searches recursively within each directory.

        Args:
            name: File name to search for (e.g. ``foo.py``).
            search_dirs: Directories to search in.

        Returns:
            Relative path from project root, or None if not found.
        """
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for match in search_dir.rglob(name):
                if match.is_file():
                    try:
                        return match.relative_to(self._root).as_posix()
                    except ValueError:
                        return match.as_posix()

        return None
