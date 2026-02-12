# Unit Testing Adapters

nit includes adapters for 11 unit testing frameworks across 8 languages.

## Python

### pytest

The default adapter for Python projects.

**Detection signals:**

- `pytest.ini`, `pyproject.toml` with `[tool.pytest]`, `setup.cfg` with `[tool:pytest]`
- `conftest.py` files
- `requirements.txt` or `pyproject.toml` listing `pytest` as a dependency

**Test patterns:** `test_*.py`, `*_test.py`

**Coverage integration:** coverage.py

**Example generated test:**

```python
import pytest
from myapp.calculator import Calculator

class TestCalculator:
    def test_add_positive_numbers(self):
        calc = Calculator()
        assert calc.add(2, 3) == 5

    def test_add_negative_numbers(self):
        calc = Calculator()
        assert calc.add(-1, -2) == -3
```

---

## JavaScript / TypeScript

### Vitest

Primary adapter for Vite-based JavaScript/TypeScript projects.

**Detection signals:**

- `vitest.config.ts`, `vitest.config.js`
- `vite.config.ts` with vitest plugin
- `package.json` listing `vitest` as a dependency

**Test patterns:** `*.test.ts`, `*.test.js`, `*.spec.ts`, `*.spec.js`

**Coverage integration:** Istanbul (via `@vitest/coverage-istanbul` or `@vitest/coverage-v8`)

### Jest

Adapter for Jest-based projects (via xUnit output parsing).

**Detection signals:**

- `jest.config.js`, `jest.config.ts`
- `package.json` with `jest` configuration

**Test patterns:** `*.test.js`, `*.test.ts`, `*.spec.js`, `*.spec.ts`

---

## Go

### go test

Built-in Go test framework adapter.

**Detection signals:**

- `go.mod` file
- `*_test.go` files

**Test patterns:** `*_test.go`

**Coverage integration:** `go cover`

**Example generated test:**

```go
func TestAdd(t *testing.T) {
    tests := []struct {
        name string
        a, b int
        want int
    }{
        {"positive", 2, 3, 5},
        {"negative", -1, -2, -3},
        {"zero", 0, 0, 0},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got := Add(tt.a, tt.b)
            if got != tt.want {
                t.Errorf("Add(%d, %d) = %d, want %d", tt.a, tt.b, got, tt.want)
            }
        })
    }
}
```

### Testify

Adapter for Go projects using the `testify` assertion library.

**Detection signals:**

- `go.mod` referencing `github.com/stretchr/testify`
- Imports of `testify/assert` or `testify/require` in test files

---

## C/C++

### Google Test (GTest)

Adapter for C++ projects using Google Test.

**Detection signals:**

- `CMakeLists.txt` referencing `GTest` or `gtest`
- `#include <gtest/gtest.h>` in source files

**Test patterns:** `*_test.cpp`, `*_test.cc`, `test_*.cpp`

**Coverage integration:** gcov

### Catch2

Adapter for C++ projects using Catch2.

**Detection signals:**

- `CMakeLists.txt` referencing `Catch2`
- `#include <catch2/catch_test_macros.hpp>` in source files

**Test patterns:** `*_test.cpp`, `test_*.cpp`

**Coverage integration:** gcov

---

## Java

### JUnit 5

Adapter for Java projects using JUnit 5.

**Detection signals:**

- `pom.xml` or `build.gradle` with JUnit 5 dependencies
- `@Test` annotations from `org.junit.jupiter`

**Test patterns:** `*Test.java`, `*Tests.java`

**Coverage integration:** JaCoCo

---

## Kotlin

### Kotest

Adapter for Kotlin projects using Kotest.

**Detection signals:**

- `build.gradle.kts` with Kotest dependencies
- `io.kotest` imports in test files

**Test patterns:** `*Test.kt`, `*Spec.kt`

**Coverage integration:** JaCoCo

---

## Rust

### Cargo test

Built-in Rust test framework adapter.

**Detection signals:**

- `Cargo.toml` file
- `#[cfg(test)]` modules in source files

**Test patterns:** Inline `#[test]` functions and `tests/` directory

**Coverage integration:** tarpaulin

---

## C# / .NET

### xUnit

Adapter for .NET projects using xUnit.

**Detection signals:**

- `.csproj` files referencing `xunit`
- `[Fact]` and `[Theory]` attributes in test files

**Test patterns:** `*Tests.cs`, `*Test.cs`

**Coverage integration:** Coverlet
