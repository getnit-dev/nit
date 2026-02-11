"""Tests for CMake integration (parse and modify CMakeLists.txt)."""

from __future__ import annotations

from pathlib import Path

from nit.utils.cmake import (
    add_test_target,
    ensure_enable_testing,
    parse_cmake,
)


def _write_file(root: Path, path: str, content: str) -> Path:
    full = root / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


# ── parse_cmake ─────────────────────────────────────────────────────────────


class TestParseCMake:
    def test_missing_file_returns_empty_result(self, tmp_path: Path) -> None:
        result = parse_cmake(tmp_path / "CMakeLists.txt")
        assert result.test_targets == []
        assert result.include_directories == []
        assert result.target_include_directories == {}

    def test_empty_file_returns_empty_result(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "CMakeLists.txt", "")
        result = parse_cmake(tmp_path / "CMakeLists.txt")
        assert result.test_targets == []
        assert result.include_directories == []

    def test_parses_single_gtest_target(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            """\
cmake_minimum_required(VERSION 3.20)
project(sample)
enable_testing()
find_package(GTest REQUIRED)
add_executable(math_test tests/math_test.cpp)
target_link_libraries(math_test PRIVATE GTest::gtest_main)
gtest_discover_tests(math_test)
""",
        )
        result = parse_cmake(tmp_path / "CMakeLists.txt")
        assert len(result.test_targets) == 1
        t = result.test_targets[0]
        assert t.name == "math_test"
        assert t.sources == ["tests/math_test.cpp"]
        assert "GTest::gtest_main" in t.link_libraries
        assert t.discover == "gtest"

    def test_parses_multiple_sources_add_executable(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "add_executable(multi tests/a.cpp tests/b.cpp)\n"
            "target_link_libraries(multi PRIVATE GTest::gtest_main)\n"
            "gtest_discover_tests(multi)\n",
        )
        result = parse_cmake(tmp_path / "CMakeLists.txt")
        assert len(result.test_targets) == 1
        t = result.test_targets[0]
        assert t.name == "multi"
        assert t.sources == ["tests/a.cpp", "tests/b.cpp"]
        assert t.discover == "gtest"

    def test_parses_catch2_target(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            """\
find_package(Catch2 REQUIRED)
add_executable(unit_tests tests/unit_tests.cpp)
target_link_libraries(unit_tests PRIVATE Catch2::Catch2WithMain)
catch_discover_tests(unit_tests)
""",
        )
        result = parse_cmake(tmp_path / "CMakeLists.txt")
        assert len(result.test_targets) == 1
        t = result.test_targets[0]
        assert t.name == "unit_tests"
        assert t.sources == ["tests/unit_tests.cpp"]
        assert any("Catch2" in lb for lb in t.link_libraries)
        assert t.discover == "catch2"

    def test_infers_gtest_from_link_libraries(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "add_executable(foo tests/foo.cpp)\n"
            "target_link_libraries(foo PRIVATE GTest::gtest_main)\n",
        )
        result = parse_cmake(tmp_path / "CMakeLists.txt")
        assert len(result.test_targets) == 1
        assert result.test_targets[0].discover == "gtest"

    def test_infers_catch2_from_link_libraries(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "add_executable(bar tests/bar.cpp)\n"
            "target_link_libraries(bar PRIVATE Catch2::Catch2WithMain)\n",
        )
        result = parse_cmake(tmp_path / "CMakeLists.txt")
        assert len(result.test_targets) == 1
        assert result.test_targets[0].discover == "catch2"

    def test_parses_include_directories(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "include_directories(${CMAKE_SOURCE_DIR}/include ${PROJECT_BINARY_DIR})\n"
            "add_executable(app src/main.cpp)\n",
        )
        result = parse_cmake(tmp_path / "CMakeLists.txt")
        assert "${CMAKE_SOURCE_DIR}/include" in result.include_directories
        assert "${PROJECT_BINARY_DIR}" in result.include_directories

    def test_parses_target_include_directories(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "add_executable(mylib src/lib.cpp)\n"
            "target_include_directories(mylib PRIVATE include)\n",
        )
        result = parse_cmake(tmp_path / "CMakeLists.txt")
        assert "mylib" in result.target_include_directories
        assert "include" in result.target_include_directories["mylib"]

    def test_multiline_add_executable(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            """\
add_executable(
  long_target
  tests/one.cpp
  tests/two.cpp
)
""",
        )
        result = parse_cmake(tmp_path / "CMakeLists.txt")
        assert len(result.test_targets) == 1
        assert result.test_targets[0].name == "long_target"
        assert "tests/one.cpp" in result.test_targets[0].sources
        assert "tests/two.cpp" in result.test_targets[0].sources


# ── add_test_target ───────────────────────────────────────────────────────────


class TestAddTestTarget:
    def test_adds_gtest_target(self, tmp_path: Path) -> None:
        cmake = tmp_path / "CMakeLists.txt"
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "cmake_minimum_required(VERSION 3.20)\nproject(sample)\nenable_testing()\n"
            "find_package(GTest REQUIRED)\n",
        )
        add_test_target(cmake, "tests/generated_foo_test.cpp", "gtest")
        content = cmake.read_text(encoding="utf-8")
        assert "add_executable(generated_foo_test tests/generated_foo_test.cpp)" in content
        assert "target_link_libraries(generated_foo_test PRIVATE GTest::gtest_main)" in content
        assert "gtest_discover_tests(generated_foo_test)" in content

    def test_adds_catch2_target(self, tmp_path: Path) -> None:
        cmake = tmp_path / "CMakeLists.txt"
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "find_package(Catch2 REQUIRED)\n",
        )
        add_test_target(cmake, "tests/new_test.cpp", "catch2")
        content = cmake.read_text(encoding="utf-8")
        assert "add_executable(new_test tests/new_test.cpp)" in content
        assert "Catch2::Catch2WithMain" in content
        assert "catch_discover_tests(new_test)" in content

    def test_custom_target_name(self, tmp_path: Path) -> None:
        cmake = tmp_path / "CMakeLists.txt"
        _write_file(tmp_path, "CMakeLists.txt", "project(x)\n")
        add_test_target(
            cmake,
            "tests/foo_test.cpp",
            "gtest",
            target_name="my_foo_tests",
        )
        content = cmake.read_text(encoding="utf-8")
        assert "add_executable(my_foo_tests tests/foo_test.cpp)" in content
        assert "gtest_discover_tests(my_foo_tests)" in content

    def test_custom_link_libraries(self, tmp_path: Path) -> None:
        cmake = tmp_path / "CMakeLists.txt"
        _write_file(tmp_path, "CMakeLists.txt", "project(x)\n")
        add_test_target(
            cmake,
            "tests/foo.cpp",
            "gtest",
            link_libraries=["GTest::gtest_main", "mylib"],
        )
        content = cmake.read_text(encoding="utf-8")
        assert "GTest::gtest_main" in content
        assert "mylib" in content

    def test_normalizes_backslashes_to_forward_slashes(self, tmp_path: Path) -> None:
        cmake = tmp_path / "CMakeLists.txt"
        _write_file(tmp_path, "CMakeLists.txt", "project(x)\n")
        add_test_target(cmake, "tests\\foo_test.cpp", "gtest")
        content = cmake.read_text(encoding="utf-8")
        assert "tests/foo_test.cpp" in content

    def test_parsed_after_add_includes_new_target(self, tmp_path: Path) -> None:
        cmake = tmp_path / "CMakeLists.txt"
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "enable_testing()\nfind_package(GTest REQUIRED)\n"
            "add_executable(old_test tests/old_test.cpp)\n"
            "target_link_libraries(old_test PRIVATE GTest::gtest_main)\n"
            "gtest_discover_tests(old_test)\n",
        )
        add_test_target(cmake, "tests/new_test.cpp", "gtest")
        result = parse_cmake(cmake)
        names = [t.name for t in result.test_targets]
        assert "old_test" in names
        assert "new_test" in names


# ── ensure_enable_testing ────────────────────────────────────────────────────


class TestEnsureEnableTesting:
    def test_returns_true_when_already_present(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "CMakeLists.txt", "project(x)\nenable_testing()\n")
        cmake = tmp_path / "CMakeLists.txt"
        assert ensure_enable_testing(cmake) is True
        assert cmake.read_text(encoding="utf-8").count("enable_testing()") == 1

    def test_appends_after_project_when_missing(self, tmp_path: Path) -> None:
        _write_file(
            tmp_path,
            "CMakeLists.txt",
            "cmake_minimum_required(VERSION 3.20)\nproject(sample)\nfind_package(GTest)\n",
        )
        cmake = tmp_path / "CMakeLists.txt"
        assert ensure_enable_testing(cmake) is True
        content = cmake.read_text(encoding="utf-8")
        assert "enable_testing()" in content
        assert content.index("enable_testing()") < content.index("find_package(GTest)")

    def test_prepends_when_no_project(self, tmp_path: Path) -> None:
        _write_file(tmp_path, "CMakeLists.txt", "find_package(GTest)\n")
        cmake = tmp_path / "CMakeLists.txt"
        assert ensure_enable_testing(cmake) is True
        assert cmake.read_text(encoding="utf-8").startswith("enable_testing()")

    def test_returns_false_for_missing_file(self, tmp_path: Path) -> None:
        assert ensure_enable_testing(tmp_path / "CMakeLists.txt") is False
