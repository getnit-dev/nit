"""Tests for the StackDetector agent and detect_languages function."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from nit.agents.base import TaskInput, TaskStatus
from nit.agents.detectors.stack import (
    LanguageInfo,
    LanguageProfile,
    StackDetector,
    detect_languages,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_files(root: Path, rel_paths: list[str]) -> None:
    """Create empty files at the given relative paths under *root*."""
    for rel in rel_paths:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()


def _write_file(root: Path, rel: str, content: str) -> None:
    """Write *content* to a file at *root/rel*."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# detect_languages — basic counting
# ---------------------------------------------------------------------------


class TestDetectLanguages:
    def test_empty_directory(self, tmp_path: Path) -> None:
        profile = detect_languages(tmp_path)
        assert profile.total_files == 0
        assert profile.languages == []
        assert profile.primary_language is None

    def test_single_language_python(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["main.py", "utils.py", "lib/helpers.py"])
        profile = detect_languages(tmp_path)
        assert profile.total_files == 3
        assert len(profile.languages) == 1
        assert profile.languages[0].language == "python"
        assert profile.languages[0].file_count == 3
        assert profile.primary_language == "python"

    def test_single_language_javascript(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["index.js", "app.mjs", "lib/util.cjs"])
        profile = detect_languages(tmp_path)
        assert profile.total_files == 3
        assert profile.primary_language == "javascript"
        assert profile.languages[0].extensions[".js"] == 1
        assert profile.languages[0].extensions[".mjs"] == 1
        assert profile.languages[0].extensions[".cjs"] == 1

    def test_mixed_languages(self, tmp_path: Path) -> None:
        _make_files(
            tmp_path,
            [
                "main.py",
                "utils.py",
                "index.ts",
                "app.tsx",
                "lib.go",
            ],
        )
        profile = detect_languages(tmp_path)
        assert profile.total_files == 5
        # Python should be first (2 files)
        assert profile.languages[0].language == "python"
        assert profile.languages[0].file_count == 2
        # Go last (1 file)
        go_info = next(li for li in profile.languages if li.language == "go")
        assert go_info.file_count == 1

    def test_unsupported_extensions_ignored(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["main.py", "data.csv", "notes.txt", "image.png"])
        profile = detect_languages(tmp_path)
        assert profile.total_files == 1
        assert profile.primary_language == "python"

    def test_skip_dirs_default(self, tmp_path: Path) -> None:
        _make_files(
            tmp_path,
            [
                "src/main.py",
                "node_modules/pkg/index.js",
                ".git/hooks/pre-commit.py",
                "__pycache__/cached.py",
                ".venv/lib/site.py",
            ],
        )
        profile = detect_languages(tmp_path)
        assert profile.total_files == 1
        assert profile.primary_language == "python"

    def test_skip_dirs_custom(self, tmp_path: Path) -> None:
        _make_files(
            tmp_path,
            [
                "src/main.py",
                "vendor/lib.go",
            ],
        )
        # Only skip "vendor", not the defaults
        profile = detect_languages(tmp_path, skip_dirs=frozenset({"vendor"}))
        assert profile.total_files == 1
        assert profile.primary_language == "python"

    def test_non_directory_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.touch()
        with pytest.raises(ValueError, match="Not a directory"):
            detect_languages(f)

    def test_nested_directories(self, tmp_path: Path) -> None:
        _make_files(
            tmp_path,
            [
                "a/b/c/deep.py",
                "a/b/mid.js",
                "a/top.go",
            ],
        )
        profile = detect_languages(tmp_path)
        assert profile.total_files == 3
        assert len(profile.languages) == 3

    def test_confidence_scores(self, tmp_path: Path) -> None:
        _make_files(
            tmp_path,
            [
                "a.py",
                "b.py",
                "c.py",
                "d.py",
                "e.py",
                "f.js",
                "g.js",
                "h.go",
            ],
        )
        profile = detect_languages(tmp_path)
        py_info = profile.languages[0]
        assert py_info.language == "python"
        # 5/8 = 0.625
        assert py_info.confidence == pytest.approx(0.625, abs=0.001)

    def test_single_file_confidence_penalty(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["main.py", "lib.go"])
        profile = detect_languages(tmp_path)
        # Both have 1 file each.  Confidence = (1/2)*0.9 = 0.45
        for li in profile.languages:
            assert li.confidence == pytest.approx(0.45, abs=0.001)

    def test_extensions_tracked(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["a.ts", "b.tsx", "c.ts"])
        profile = detect_languages(tmp_path)
        ts_info = next(li for li in profile.languages if li.language == "typescript")
        assert ts_info.extensions[".ts"] == 2
        tsx_info = next(li for li in profile.languages if li.language == "tsx")
        assert tsx_info.extensions[".tsx"] == 1

    def test_root_recorded(self, tmp_path: Path) -> None:
        profile = detect_languages(tmp_path)
        assert profile.root == str(tmp_path)

    def test_sorted_by_file_count(self, tmp_path: Path) -> None:
        _make_files(
            tmp_path,
            [
                "a.go",
                "b.py",
                "c.py",
                "d.rs",
                "e.rs",
                "f.rs",
            ],
        )
        profile = detect_languages(tmp_path)
        counts = [li.file_count for li in profile.languages]
        assert counts == sorted(counts, reverse=True)

    def test_all_supported_languages(self, tmp_path: Path) -> None:
        _make_files(
            tmp_path,
            [
                "a.py",
                "b.js",
                "c.ts",
                "d.tsx",
                "e.c",
                "f.cpp",
                "g.java",
                "h.go",
                "i.rs",
            ],
        )
        profile = detect_languages(tmp_path)
        detected = {li.language for li in profile.languages}
        assert detected == {
            "python",
            "javascript",
            "typescript",
            "tsx",
            "c",
            "cpp",
            "java",
            "go",
            "rust",
        }


# ---------------------------------------------------------------------------
# Ambiguous extension disambiguation (.h files)
# ---------------------------------------------------------------------------


class TestAmbiguousExtensions:
    def test_h_file_pure_c(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "lib.h",
            """\
#ifndef LIB_H
#define LIB_H

int add(int a, int b);
void greet(const char *name);

typedef struct {
    int x;
    int y;
} Point;

#endif
""",
        )
        profile = detect_languages(tmp_path)
        assert profile.total_files == 1
        assert profile.primary_language == "c"

    def test_h_file_cpp_class(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "widget.h",
            """\
#pragma once

class Widget {
public:
    Widget();
    ~Widget();
    void draw();
private:
    int m_x;
};
""",
        )
        profile = detect_languages(tmp_path)
        assert profile.total_files == 1
        assert profile.primary_language == "cpp"

    def test_h_file_cpp_namespace(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "util.h",
            """\
#pragma once
namespace util {
    int helper();
}
""",
        )
        profile = detect_languages(tmp_path)
        assert profile.primary_language == "cpp"

    def test_h_file_cpp_template(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "vec.h",
            """\
#pragma once
template <typename T>
T max_val(T a, T b) { return a > b ? a : b; }
""",
        )
        profile = detect_languages(tmp_path)
        assert profile.primary_language == "cpp"

    def test_mixed_h_files(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "pure_c.h", "int foo(void);")
        _write_file(tmp_path, "cpp_stuff.h", "class Foo {};")
        profile = detect_languages(tmp_path)
        assert profile.total_files == 2
        detected = {li.language for li in profile.languages}
        assert "c" in detected
        assert "cpp" in detected

    def test_h_alongside_c_and_cpp(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "main.c", "int main() { return 0; }")
        _write_file(tmp_path, "lib.cpp", "void foo() {}")
        _write_file(tmp_path, "header.h", "int bar(void);")
        profile = detect_languages(tmp_path)
        detected = {li.language for li in profile.languages}
        assert "c" in detected
        assert "cpp" in detected

    def test_empty_h_file_defaults_to_c(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "empty.h", "")
        profile = detect_languages(tmp_path)
        assert profile.primary_language == "c"


# ---------------------------------------------------------------------------
# LanguageProfile dataclass
# ---------------------------------------------------------------------------


class TestLanguageProfile:
    def test_primary_language_returns_first(self) -> None:
        profile = LanguageProfile(
            languages=[
                LanguageInfo("python", 10, 0.5),
                LanguageInfo("javascript", 5, 0.25),
            ],
            total_files=20,
        )
        assert profile.primary_language == "python"

    def test_primary_language_empty(self) -> None:
        profile = LanguageProfile()
        assert profile.primary_language is None


# ---------------------------------------------------------------------------
# StackDetector agent interface
# ---------------------------------------------------------------------------


class TestStackDetectorAgent:
    def test_run_success(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["app.py", "lib.py", "index.js"])
        agent = StackDetector()
        task = TaskInput(task_type="detect-stack", target=str(tmp_path))
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.COMPLETED
        assert output.result["total_files"] == 3
        assert output.result["primary_language"] == "python"
        assert len(output.result["languages"]) == 2

    def test_run_invalid_target(self, tmp_path: Path) -> None:
        agent = StackDetector()
        task = TaskInput(task_type="detect-stack", target=str(tmp_path / "nope"))
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.FAILED
        assert len(output.errors) == 1
        assert "Not a directory" in output.errors[0]

    def test_run_empty_directory(self, tmp_path: Path) -> None:
        agent = StackDetector()
        task = TaskInput(task_type="detect-stack", target=str(tmp_path))
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.COMPLETED
        assert output.result["total_files"] == 0
        assert output.result["primary_language"] is None

    def test_agent_properties(self) -> None:
        agent = StackDetector()
        assert agent.name == "stack-detector"
        assert "language" in agent.description.lower() or "scan" in agent.description.lower()

    def test_run_with_custom_skip_dirs(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["src/main.py", "ignored/lib.go"])
        agent = StackDetector()
        task = TaskInput(
            task_type="detect-stack",
            target=str(tmp_path),
            context={"skip_dirs": ["ignored"]},
        )
        output = asyncio.run(agent.run(task))

        assert output.status == TaskStatus.COMPLETED
        assert output.result["total_files"] == 1
        assert output.result["primary_language"] == "python"

    def test_output_language_fields(self, tmp_path: Path) -> None:
        _make_files(tmp_path, ["a.py", "b.py", "c.rs"])
        agent = StackDetector()
        task = TaskInput(task_type="detect-stack", target=str(tmp_path))
        output = asyncio.run(agent.run(task))

        langs = output.result["languages"]
        py_lang = next(lang for lang in langs if lang["language"] == "python")
        assert py_lang["file_count"] == 2
        assert 0 < py_lang["confidence"] <= 1.0
        assert ".py" in py_lang["extensions"]
