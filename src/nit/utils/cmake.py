"""CMake integration: parse and modify CMakeLists.txt for C/C++ test targets.

Parses CMakeLists.txt to detect existing test targets, include directories,
and linked libraries. Supports adding new test targets for generated test files
(GTest and Catch2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Parsing patterns: allow multiline; CMake ignores newlines inside parentheses.
_ADD_EXECUTABLE_RE = re.compile(
    r"add_executable\s*\(\s*([A-Za-z0-9_.-]+)\s+([^)]+)\)",
    re.DOTALL,
)
_TARGET_LINK_LIBS_RE = re.compile(
    r"target_link_libraries\s*\(\s*([A-Za-z0-9_.-]+)\s+(?:PRIVATE|PUBLIC|INTERFACE)\s+([^)]+)\)",
    re.DOTALL,
)
_GTEST_DISCOVER_RE = re.compile(
    r"gtest_discover_tests\s*\(\s*([A-Za-z0-9_.-]+)\s*\)",
    re.DOTALL,
)
_CATCH_DISCOVER_RE = re.compile(
    r"catch(?:2)?_discover_tests\s*\(\s*([A-Za-z0-9_.-]+)\s*\)",
    re.DOTALL,
)
_INCLUDE_DIRS_RE = re.compile(
    r"include_directories\s*\(\s*([^)]+)\)",
    re.DOTALL,
)
_TARGET_INCLUDE_DIRS_RE = re.compile(
    r"target_include_directories\s*\(\s*([A-Za-z0-9_.-]+)\s+(?:PRIVATE|PUBLIC|INTERFACE)\s+([^)]+)\)",
    re.DOTALL,
)


def _normalize_cmake_content(content: str) -> str:
    """Collapse line continuations and strip so regex can match across lines."""
    lines: list[str] = []
    current: list[str] = []
    for line in content.splitlines():
        current.append(line.rstrip())
        if not line.rstrip().endswith("\\"):
            lines.append(" ".join(current))
            current = []
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def _split_sources(block: str) -> list[str]:
    """Split CMake source list into trimmed entries (handles newlines)."""
    block = block.strip()
    if not block:
        return []
    parts = re.split(r"\s+", block.replace("\n", " "))
    return [p.strip() for p in parts if p.strip()]


def _split_libs(block: str) -> list[str]:
    """Split target_link_libraries list into trimmed entries."""
    parts = re.split(r"\s+", block.replace("\n", " ").strip())
    return [p.strip() for p in parts if p.strip()]


def _split_dirs(block: str) -> list[str]:
    """Split include_directories list into trimmed entries."""
    parts = re.split(r"\s+", block.replace("\n", " ").strip())
    return [p.strip() for p in parts if p.strip()]


@dataclass
class CMakeTestTarget:
    """A test executable target defined in CMakeLists.txt."""

    name: str
    sources: list[str]
    link_libraries: list[str] = field(default_factory=list)
    discover: Literal["gtest", "catch2"] | None = None


@dataclass
class CMakeParseResult:
    """Result of parsing a CMakeLists.txt file."""

    test_targets: list[CMakeTestTarget] = field(default_factory=list)
    include_directories: list[str] = field(default_factory=list)
    target_include_directories: dict[str, list[str]] = field(default_factory=dict)


def parse_cmake(cmake_path: Path) -> CMakeParseResult:
    """Parse CMakeLists.txt and extract test targets, include dirs, and link libs.

    Args:
        cmake_path: Path to CMakeLists.txt.

    Returns:
        CMakeParseResult with test_targets, include_directories, and
        target_include_directories (target name -> list of dirs).
    """
    result = CMakeParseResult()
    if not cmake_path.is_file():
        return result

    try:
        content = cmake_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result

    normalized = _normalize_cmake_content(content)
    targets_by_name = _parse_targets(normalized)
    _infer_discover_from_libs(targets_by_name)
    result.test_targets = list(targets_by_name.values())
    _parse_include_dirs(normalized, result)
    return result


def _parse_targets(normalized: str) -> dict[str, CMakeTestTarget]:
    targets_by_name: dict[str, CMakeTestTarget] = {}
    for m in _ADD_EXECUTABLE_RE.finditer(normalized):
        name = m.group(1).strip()
        src_block = m.group(2).strip()
        if src_block.endswith(")"):
            src_block = src_block[:-1].strip()
        sources = _split_sources(src_block)
        targets_by_name[name] = CMakeTestTarget(name=name, sources=sources)
    for m in _TARGET_LINK_LIBS_RE.finditer(normalized):
        name = m.group(1).strip()
        libs = _split_libs(m.group(2))
        if name in targets_by_name:
            targets_by_name[name].link_libraries = libs
        else:
            targets_by_name[name] = CMakeTestTarget(name=name, sources=[], link_libraries=libs)
    for m in _GTEST_DISCOVER_RE.finditer(normalized):
        name = m.group(1).strip()
        targets_by_name.setdefault(
            name, CMakeTestTarget(name=name, sources=[], discover="gtest")
        ).discover = "gtest"
    for m in _CATCH_DISCOVER_RE.finditer(normalized):
        name = m.group(1).strip()
        targets_by_name.setdefault(
            name, CMakeTestTarget(name=name, sources=[], discover="catch2")
        ).discover = "catch2"
    return targets_by_name


def _infer_discover_from_libs(
    targets_by_name: dict[str, CMakeTestTarget],
) -> None:
    for t in targets_by_name.values():
        if t.discover is not None:
            continue
        lower_libs = [lb.lower() for lb in t.link_libraries]
        if any("gtest" in lb for lb in lower_libs):
            t.discover = "gtest"
        elif any("catch2" in lb for lb in lower_libs):
            t.discover = "catch2"


def _parse_include_dirs(normalized: str, result: CMakeParseResult) -> None:
    for m in _INCLUDE_DIRS_RE.finditer(normalized):
        result.include_directories.extend(_split_dirs(m.group(1)))
    for m in _TARGET_INCLUDE_DIRS_RE.finditer(normalized):
        name = m.group(1).strip()
        dirs = _split_dirs(m.group(2))
        result.target_include_directories.setdefault(name, []).extend(dirs)


def add_test_target(
    cmake_path: Path,
    test_source_path: str,
    framework: Literal["gtest", "catch2"],
    *,
    target_name: str | None = None,
    link_libraries: list[str] | None = None,
) -> None:
    """Add a new test target to CMakeLists.txt for a generated test file.

    Appends add_executable, target_link_libraries, and (for GTest)
    gtest_discover_tests or (for Catch2) catch_discover_tests. Uses
    forward slashes for the source path so CMake works on all platforms.

    Args:
        cmake_path: Path to CMakeLists.txt to modify.
        test_source_path: Relative path to the new test source file
            (e.g. "tests/foo_test.cpp"). Used as-is; use forward slashes.
        framework: "gtest" or "catch2".
        target_name: CMake target name. Defaults to stem of test_source_path
            with non-alnum replaced by underscore (e.g. foo_test.cpp -> foo_test).
        link_libraries: Libraries to link. Defaults to GTest::gtest_main
            or Catch2::Catch2WithMain.
    """
    if target_name is None:
        stem = Path(test_source_path).stem
        target_name = re.sub(r"[^A-Za-z0-9_.-]", "_", stem)
    if link_libraries is None:
        link_libraries = (
            ["GTest::gtest_main"] if framework == "gtest" else ["Catch2::Catch2WithMain"]
        )

    # Normalize path for CMake (forward slashes)
    src_path = test_source_path.replace("\\", "/")

    lines = [
        "",
        f"# nit: generated test target for {src_path}",
        f"add_executable({target_name} {src_path})",
        f"target_link_libraries({target_name} PRIVATE {' '.join(link_libraries)})",
    ]
    if framework == "gtest":
        lines.append(f"gtest_discover_tests({target_name})")
    else:
        lines.append(f"catch_discover_tests({target_name})")
    block = "\n".join(lines) + "\n"

    try:
        content = cmake_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise OSError(f"Cannot read {cmake_path}") from None

    # Append after last non-empty line (or at end)
    if content and not content.endswith("\n"):
        content += "\n"
    content += block

    cmake_path.write_text(content, encoding="utf-8")


def ensure_enable_testing(cmake_path: Path) -> bool:
    """Ensure CMakeLists.txt contains enable_testing(). Appends if missing.

    Returns True if enable_testing() was already present or was added.
    """
    try:
        content = cmake_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    if re.search(r"enable_testing\s*\(\s*\)", content):
        return True

    # Insert after project(...) if present, else at start
    project_match = re.search(r"project\s*\([^)]*\)", content, re.IGNORECASE)
    if project_match:
        insert_pos = project_match.end()
        # Skip trailing newline
        if insert_pos < len(content) and content[insert_pos] == "\n":
            insert_pos += 1
        content = content[:insert_pos] + "enable_testing()\n" + content[insert_pos:]
    else:
        content = "enable_testing()\n" + content

    try:
        cmake_path.write_text(content, encoding="utf-8")
    except OSError:
        return False
    return True
