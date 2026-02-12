"""Shared fixtures for integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# ── Marker registration ──────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``integration`` marker."""
    config.addinivalue_line("markers", "integration: integration tests")


# ── File creation helpers ────────────────────────────────────────


def make_files(root: Path, rel_paths: list[str]) -> None:
    """Create empty files (with parent directories) under *root*."""
    for rel in rel_paths:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()


def write_file(root: Path, rel: str, content: str) -> None:
    """Write *content* to a file under *root*."""
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def write_json(root: Path, rel: str, data: dict[str, Any]) -> None:
    """Write a JSON file under *root*."""
    write_file(root, rel, json.dumps(data, indent=2))


# ── Project scaffolding fixtures ─────────────────────────────────


@pytest.fixture()
def vitest_project(tmp_path: Path) -> Path:
    """Create a minimal Vitest project directory."""
    write_json(
        tmp_path,
        "package.json",
        {
            "name": "test-vitest",
            "devDependencies": {"vitest": "^1.0.0"},
            "scripts": {"test": "vitest"},
        },
    )
    write_file(tmp_path, "vitest.config.ts", 'import { defineConfig } from "vitest/config";\n')
    write_file(
        tmp_path,
        "src/math.test.ts",
        'import { describe, it, expect } from "vitest";\n'
        'describe("math", () => { it("adds", () => expect(1+1).toBe(2)); });\n',
    )
    return tmp_path


@pytest.fixture()
def py_test_project(tmp_path: Path) -> Path:
    """Create a minimal pytest project directory."""
    write_file(
        tmp_path,
        "pyproject.toml",
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
        '[project.optional-dependencies]\ndev = ["pytest"]\n',
    )
    write_file(tmp_path, "conftest.py", "")
    write_file(
        tmp_path,
        "tests/test_sample.py",
        "import pytest\n\ndef test_one():\n    assert 1 + 1 == 2\n",
    )
    return tmp_path


@pytest.fixture()
def cargo_project(tmp_path: Path) -> Path:
    """Create a minimal Cargo (Rust) project directory."""
    write_file(
        tmp_path,
        "Cargo.toml",
        '[package]\nname = "demo"\nversion = "0.1.0"\nedition = "2021"\n',
    )
    write_file(
        tmp_path,
        "src/lib.rs",
        "pub fn add(a: i32, b: i32) -> i32 { a + b }\n\n"
        "#[cfg(test)]\nmod tests {\n    use super::*;\n\n"
        "    #[test]\n    fn it_works() {\n        assert_eq!(add(2, 2), 4);\n    }\n}\n",
    )
    make_files(tmp_path, ["tests/integration_test.rs"])
    return tmp_path


@pytest.fixture()
def go_project(tmp_path: Path) -> Path:
    """Create a minimal Go project directory."""
    write_file(tmp_path, "go.mod", "module example.com/demo\n\ngo 1.21\n")
    write_file(tmp_path, "main.go", "package main\n\nfunc Add(a, b int) int { return a + b }\n")
    write_file(
        tmp_path,
        "main_test.go",
        'package main\n\nimport "testing"\n\n'
        "func TestAdd(t *testing.T) {\n    if Add(1, 2) != 3 { t.Fail() }\n}\n",
    )
    return tmp_path


@pytest.fixture()
def gtest_project(tmp_path: Path) -> Path:
    """Create a minimal Google Test project directory."""
    write_file(
        tmp_path,
        "CMakeLists.txt",
        "cmake_minimum_required(VERSION 3.14)\nproject(demo)\n"
        "find_package(GTest REQUIRED)\n"
        "add_executable(demo_test test/demo_test.cpp)\n"
        "target_link_libraries(demo_test gtest_main)\n"
        "gtest_discover_tests(demo_test)\n",
    )
    write_file(
        tmp_path,
        "test/demo_test.cpp",
        "#include <gtest/gtest.h>\n\nTEST(DemoTest, Add) {\n  EXPECT_EQ(1+1, 2);\n}\n",
    )
    return tmp_path


@pytest.fixture()
def catch2_project(tmp_path: Path) -> Path:
    """Create a minimal Catch2 project directory."""
    write_file(
        tmp_path,
        "CMakeLists.txt",
        "cmake_minimum_required(VERSION 3.14)\nproject(demo)\n"
        "find_package(Catch2 REQUIRED)\n"
        "add_executable(demo_test test/demo_test.cpp)\n"
        "target_link_libraries(demo_test Catch2::Catch2WithMain)\n"
        "catch_discover_tests(demo_test)\n",
    )
    write_file(
        tmp_path,
        "test/demo_test.cpp",
        '#include <catch2/catch_test_macros.hpp>\n\nTEST_CASE("Add", "[math]") {\n'
        "  REQUIRE(1 + 1 == 2);\n}\n",
    )
    return tmp_path


@pytest.fixture()
def junit5_project(tmp_path: Path) -> Path:
    """Create a minimal JUnit 5 (Gradle) project directory."""
    write_file(
        tmp_path,
        "build.gradle",
        "plugins { id 'java' }\n\ndependencies {\n"
        "    testImplementation 'org.junit.jupiter:junit-jupiter:5.10.0'\n}\n\n"
        "test { useJUnitPlatform() }\n",
    )
    write_file(
        tmp_path,
        "src/test/java/com/example/DemoTest.java",
        "package com.example;\n\nimport org.junit.jupiter.api.Test;\n"
        "import static org.junit.jupiter.api.Assertions.*;\n\n"
        "class DemoTest {\n    @Test\n    void addsNumbers() {\n"
        "        assertEquals(2, 1 + 1);\n    }\n}\n",
    )
    return tmp_path


@pytest.fixture()
def xunit_project(tmp_path: Path) -> Path:
    """Create a minimal xUnit (.NET) project directory."""
    write_file(
        tmp_path,
        "MyTests/MyTests.csproj",
        '<Project Sdk="Microsoft.NET.Sdk">\n  <ItemGroup>\n'
        '    <PackageReference Include="xunit" Version="2.6.0" />\n'
        '    <PackageReference Include="xunit.runner.visualstudio" Version="2.5.3" />\n'
        "  </ItemGroup>\n</Project>\n",
    )
    write_file(
        tmp_path,
        "MyTests/CalculatorTests.cs",
        "using Xunit;\n\npublic class CalculatorTests\n{\n"
        "    [Fact]\n    public void Add_ReturnsSum()\n    {\n"
        "        Assert.Equal(2, 1 + 1);\n    }\n}\n",
    )
    return tmp_path
