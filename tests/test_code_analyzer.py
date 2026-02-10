"""Tests for the CodeAnalyzer (agents/analyzers/code.py).

Covers:
- Parsing source files with tree-sitter
- Extracting structured code map (functions, classes, imports)
- Calculating cyclomatic complexity per function
- Building call graphs
- Detecting side effects (DB, filesystem, HTTP, external processes)
- Multi-language support (Python, TypeScript, JavaScript)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nit.agents.analyzers.code import (
    CodeAnalysisTask,
    CodeAnalyzer,
    SideEffectType,
)
from nit.agents.base import TaskInput, TaskStatus

# ── Sample source files ──────────────────────────────────────────


_SIMPLE_PYTHON = """
def add(a, b):
    '''Add two numbers.'''
    return a + b

def _private_helper():
    '''Private helper function.'''
    return 42

def process_data(x):
    '''Simple processing.'''
    if x > 0:
        return x * 2
    return 0
"""

_COMPLEX_PYTHON = """
import requests
import sqlite3
from pathlib import Path

def complex_function(x, y, z):
    '''Complex function with multiple branches.'''
    if x > 0:
        if y > 0:
            if z > 0:
                return x + y + z
            else:
                return x + y
        else:
            if z > 0:
                return x + z
            else:
                return x
    else:
        if y > 0 and z > 0:
            return y + z
        elif y > 0:
            return y
        else:
            return 0

def fetch_data(url):
    '''Function with HTTP side effect.'''
    response = requests.get(url)
    return response.json()

def save_to_db(data):
    '''Function with database side effect.'''
    conn = sqlite3.connect('data.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO data VALUES (?)', (data,))
    conn.commit()
    conn.close()

def read_file(path):
    '''Function with filesystem side effect.'''
    p = Path(path)
    return p.read_text()

def helper():
    '''Helper function.'''
    return 42

def caller():
    '''Calls other functions.'''
    result = helper()
    data = fetch_data('https://api.example.com')
    return result + len(data)
"""

_TYPESCRIPT_CODE = """
import axios from 'axios';
import fs from 'fs';

export function calculatePrice(quantity: number, price: number): number {
  if (quantity <= 0) {
    throw new Error('Quantity must be positive');
  }

  if (price < 0) {
    throw new Error('Price cannot be negative');
  }

  let total = quantity * price;

  if (quantity >= 100) {
    total *= 0.9;
  } else if (quantity >= 50) {
    total *= 0.95;
  }

  return total;
}

async function fetchUserData(userId: string): Promise<any> {
  const response = await axios.get(`/api/users/${userId}`);
  return response.data;
}

function saveToFile(data: string, filename: string): void {
  fs.writeFileSync(filename, data);
}

function processUser(userId: string): void {
  const data = fetchUserData(userId);
  const json = JSON.stringify(data);
  saveToFile(json, 'user.json');
}

class Calculator {
  add(a: number, b: number): number {
    return a + b;
  }

  multiply(a: number, b: number): number {
    return a * b;
  }

  complexCalc(x: number, y: number): number {
    if (x > 0) {
      if (y > 0) {
        return this.add(x, y);
      } else {
        return this.multiply(x, -1);
      }
    }
    return 0;
  }
}
"""

_JAVASCRIPT_WITH_SUBPROCESS = """
const { exec } = require('child_process');
const http = require('http');

function runCommand(cmd) {
  exec(cmd, (error, stdout, stderr) => {
    if (error) {
      console.error(`Error: ${error}`);
      return;
    }
    console.log(stdout);
  });
}

function makeRequest(url) {
  http.get(url, (res) => {
    let data = '';
    res.on('data', (chunk) => {
      data += chunk;
    });
    res.on('end', () => {
      console.log(data);
    });
  });
}

function simpleFunction(x, y) {
  return x + y;
}
"""

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a temporary project directory with sample files."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    (src_dir / "simple.py").write_text(_SIMPLE_PYTHON)
    (src_dir / "complex.py").write_text(_COMPLEX_PYTHON)
    (src_dir / "pricing.ts").write_text(_TYPESCRIPT_CODE)
    (src_dir / "subprocess.js").write_text(_JAVASCRIPT_WITH_SUBPROCESS)

    return tmp_path


@pytest.fixture
def analyzer(project_root: Path) -> CodeAnalyzer:
    """Create a CodeAnalyzer instance."""
    return CodeAnalyzer(project_root=project_root)


# ── Tests: Basic parsing and extraction ──────────────────────────


def test_code_analyzer_init(analyzer: CodeAnalyzer) -> None:
    """Test CodeAnalyzer initialization."""
    assert analyzer.name == "code_analyzer"
    assert "code analysis" in analyzer.description.lower()


@pytest.mark.asyncio
async def test_analyze_simple_python(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test analyzing a simple Python file."""
    task = CodeAnalysisTask(file_path=str(project_root / "src" / "simple.py"))
    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    assert "code_map" in result.result

    code_map = result.result["code_map"]
    assert code_map.language == "python"
    assert len(code_map.functions) == 3
    assert code_map.has_errors is False

    # Check function names
    func_names = {f.name for f in code_map.functions}
    assert "add" in func_names
    assert "_private_helper" in func_names
    assert "process_data" in func_names


@pytest.mark.asyncio
async def test_analyze_nonexistent_file(analyzer: CodeAnalyzer, tmp_path: Path) -> None:
    """Test analyzing a file that doesn't exist."""
    task = CodeAnalysisTask(file_path=str(tmp_path / "nonexistent.py"))
    result = await analyzer.run(task)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) > 0
    assert "does not exist" in result.errors[0].lower()


@pytest.mark.asyncio
async def test_analyze_invalid_task_type(analyzer: CodeAnalyzer) -> None:
    """Test with invalid task type."""
    task = TaskInput(task_type="wrong", target="test")
    result = await analyzer.run(task)

    assert result.status == TaskStatus.FAILED
    assert "must be a CodeAnalysisTask" in result.errors[0]


# ── Tests: Complexity calculation ────────────────────────────────


def test_calculate_complexity_simple(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test complexity calculation for simple functions."""
    code_map = analyzer.analyze_file(project_root / "src" / "simple.py")

    # add(): no branches, complexity = 1
    add_complexity = code_map.complexity_map.get("add")
    assert add_complexity is not None
    assert add_complexity.cyclomatic == 1
    assert not add_complexity.is_complex
    assert not add_complexity.is_moderate

    # process_data(): one if, complexity = 2
    process_complexity = code_map.complexity_map.get("process_data")
    assert process_complexity is not None
    assert process_complexity.cyclomatic >= 2
    assert "if" in process_complexity.decision_points


def test_calculate_complexity_complex(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test complexity calculation for complex functions."""
    code_map = analyzer.analyze_file(project_root / "src" / "complex.py")

    # complex_function(): multiple nested ifs
    complex_metrics = code_map.complexity_map.get("complex_function")
    assert complex_metrics is not None
    assert complex_metrics.cyclomatic >= 7  # Has multiple nested branches
    assert "if" in complex_metrics.decision_points
    assert complex_metrics.decision_points["if"] >= 6  # Multiple if/elif/else


def test_calculate_complexity_typescript(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test complexity calculation for TypeScript."""
    code_map = analyzer.analyze_file(project_root / "src" / "pricing.ts")

    # calculatePrice(): multiple branches
    calc_complexity = code_map.complexity_map.get("calculatePrice")
    assert calc_complexity is not None
    assert calc_complexity.cyclomatic >= 4
    assert "if" in calc_complexity.decision_points


# ── Tests: Call graph building ──────────────────────────────────


def test_build_call_graph_python(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test building call graph for Python."""
    code_map = analyzer.analyze_file(project_root / "src" / "complex.py")

    # caller() calls helper() and fetch_data()
    caller_calls = [c for c in code_map.call_graph if c.caller == "caller"]
    assert len(caller_calls) >= 2

    callees = {c.callee for c in caller_calls}
    assert "helper" in callees
    assert "fetch_data" in callees


def test_build_call_graph_typescript_class(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test building call graph for TypeScript class methods."""
    code_map = analyzer.analyze_file(project_root / "src" / "pricing.ts")

    # Calculator.complexCalc() calls this.add()
    complex_calc_calls = [c for c in code_map.call_graph if c.caller == "Calculator.complexCalc"]

    # Should find calls to add and multiply
    callees = {c.callee for c in complex_calc_calls}
    assert "add" in callees or "multiply" in callees


def test_build_call_graph_javascript(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test building call graph for JavaScript."""
    code_map = analyzer.analyze_file(project_root / "src" / "subprocess.js")

    # Functions should be extracted
    func_names = {f.name for f in code_map.functions}
    assert "runCommand" in func_names
    assert "makeRequest" in func_names
    assert "simpleFunction" in func_names


# ── Tests: Side effect detection ─────────────────────────────────


def test_detect_http_side_effects(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test detecting HTTP side effects."""
    code_map = analyzer.analyze_file(project_root / "src" / "complex.py")

    # fetch_data() should have HTTP side effect
    fetch_effects = code_map.side_effects_map.get("fetch_data")
    assert fetch_effects is not None
    assert len(fetch_effects) > 0

    effect_types = {e.type for e in fetch_effects}
    assert SideEffectType.HTTP in effect_types


def test_detect_database_side_effects(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test detecting database side effects."""
    code_map = analyzer.analyze_file(project_root / "src" / "complex.py")

    # save_to_db() should have database side effect
    db_effects = code_map.side_effects_map.get("save_to_db")
    assert db_effects is not None
    assert len(db_effects) > 0

    effect_types = {e.type for e in db_effects}
    assert SideEffectType.DATABASE in effect_types


def test_detect_filesystem_side_effects(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test detecting filesystem side effects."""
    code_map = analyzer.analyze_file(project_root / "src" / "complex.py")

    # read_file() should have filesystem side effect
    file_effects = code_map.side_effects_map.get("read_file")
    assert file_effects is not None
    assert len(file_effects) > 0

    effect_types = {e.type for e in file_effects}
    assert SideEffectType.FILESYSTEM in effect_types


def test_detect_subprocess_side_effects(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test detecting subprocess/external process side effects."""
    code_map = analyzer.analyze_file(project_root / "src" / "subprocess.js")

    # runCommand() should have external process side effect
    run_effects = code_map.side_effects_map.get("runCommand")
    assert run_effects is not None
    assert len(run_effects) > 0

    effect_types = {e.type for e in run_effects}
    assert SideEffectType.EXTERNAL_PROCESS in effect_types


def test_detect_typescript_side_effects(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test detecting side effects in TypeScript."""
    code_map = analyzer.analyze_file(project_root / "src" / "pricing.ts")

    # fetchUserData() should have HTTP side effect
    fetch_effects = code_map.side_effects_map.get("fetchUserData")
    assert fetch_effects is not None
    effect_types = {e.type for e in fetch_effects}
    assert SideEffectType.HTTP in effect_types

    # saveToFile() should have filesystem side effect
    save_effects = code_map.side_effects_map.get("saveToFile")
    assert save_effects is not None
    effect_types = {e.type for e in save_effects}
    assert SideEffectType.FILESYSTEM in effect_types


def test_no_side_effects_for_pure_function(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test that pure functions have no detected side effects."""
    code_map = analyzer.analyze_file(project_root / "src" / "complex.py")

    # helper() is a pure function
    helper_effects = code_map.side_effects_map.get("helper")
    assert helper_effects is None or len(helper_effects) == 0


# ── Tests: Class analysis ────────────────────────────────────────


def test_analyze_typescript_class(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test analyzing TypeScript classes."""
    code_map = analyzer.analyze_file(project_root / "src" / "pricing.ts")

    # Should extract Calculator class
    assert len(code_map.classes) >= 1
    calc_class = next((c for c in code_map.classes if c.name == "Calculator"), None)
    assert calc_class is not None

    # Should have methods
    assert len(calc_class.methods) >= 3
    method_names = {m.name for m in calc_class.methods}
    assert "add" in method_names
    assert "multiply" in method_names
    assert "complexCalc" in method_names

    # Methods should have complexity calculated
    assert "Calculator.complexCalc" in code_map.complexity_map
    complex_calc_complexity = code_map.complexity_map["Calculator.complexCalc"]
    assert complex_calc_complexity.cyclomatic >= 3


# ── Tests: Import extraction ─────────────────────────────────────


def test_extract_imports_python(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test extracting imports from Python."""
    code_map = analyzer.analyze_file(project_root / "src" / "complex.py")

    # Should extract imports
    assert len(code_map.imports) >= 3

    import_modules = {imp.module for imp in code_map.imports}
    assert "requests" in import_modules
    assert "sqlite3" in import_modules
    assert "pathlib" in import_modules


def test_extract_imports_typescript(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test extracting imports from TypeScript."""
    code_map = analyzer.analyze_file(project_root / "src" / "pricing.ts")

    # Should extract imports
    assert len(code_map.imports) >= 2

    import_modules = {imp.module for imp in code_map.imports}
    assert "axios" in import_modules
    assert "fs" in import_modules


# ── Tests: Edge cases ────────────────────────────────────────────


def test_analyze_empty_file(analyzer: CodeAnalyzer, tmp_path: Path) -> None:
    """Test analyzing an empty file."""
    empty_file = tmp_path / "empty.py"
    empty_file.write_text("")

    code_map = analyzer.analyze_file(empty_file)

    assert code_map.language == "python"
    assert len(code_map.functions) == 0
    assert len(code_map.classes) == 0
    assert len(code_map.imports) == 0


def test_analyze_file_with_syntax_error(analyzer: CodeAnalyzer, tmp_path: Path) -> None:
    """Test analyzing a file with syntax errors."""
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def broken(\n  invalid syntax here\n")

    code_map = analyzer.analyze_file(bad_file)

    assert code_map.language == "python"
    # Should still parse what it can
    assert code_map.has_errors is True


def test_analyze_unsupported_language(analyzer: CodeAnalyzer, tmp_path: Path) -> None:
    """Test analyzing a file with unsupported language."""
    unknown_file = tmp_path / "test.xyz"
    unknown_file.write_text("some content")

    code_map = analyzer.analyze_file(unknown_file)

    assert code_map.language == "unknown"
    assert code_map.has_errors is True


# ── Tests: Integration ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_analysis_workflow(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test complete analysis workflow."""
    task = CodeAnalysisTask(file_path=str(project_root / "src" / "complex.py"))
    result = await analyzer.run(task)

    assert result.status == TaskStatus.COMPLETED
    code_map = result.result["code_map"]

    # Verify all components are present
    assert len(code_map.functions) > 0
    assert len(code_map.imports) > 0
    assert len(code_map.complexity_map) > 0
    assert len(code_map.side_effects_map) > 0
    assert len(code_map.call_graph) > 0

    # Verify data quality
    for complexity in code_map.complexity_map.values():
        assert complexity.cyclomatic >= 1
        assert isinstance(complexity.decision_points, dict)

    for effects in code_map.side_effects_map.values():
        assert len(effects) > 0
        for effect in effects:
            assert isinstance(effect.type, SideEffectType)
            assert len(effect.evidence) > 0


def test_analyze_multiple_files(analyzer: CodeAnalyzer, project_root: Path) -> None:
    """Test analyzing multiple files."""
    files = [
        project_root / "src" / "simple.py",
        project_root / "src" / "complex.py",
        project_root / "src" / "pricing.ts",
    ]

    results = []
    for file_path in files:
        code_map = analyzer.analyze_file(file_path)
        results.append(code_map)
        assert not code_map.has_errors
        assert len(code_map.functions) > 0

    # Verify each file was analyzed independently
    assert results[0].language == "python"
    assert results[1].language == "python"
    assert results[2].language == "typescript"
