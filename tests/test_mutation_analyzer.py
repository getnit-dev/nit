"""Tests for mutation testing adapters, analyzer, and builder.

Covers:
- StrykerAdapter detection (with fixture package.json containing stryker)
- MutmutAdapter detection (with fixture pyproject.toml containing mutmut)
- PitestAdapter detection (with fixture pom.xml containing pitest)
- MutationTestReport data model
- MutationTestAnalyzer adapter detection and high-priority classification
- MutationTestBuilder test-case generation from surviving mutants
- Mutation test prompt template generation
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nit.adapters.mutation.base import (
    MutationTestingAdapter,
    MutationTestReport,
    SurvivingMutant,
)
from nit.adapters.mutation.mutmut_adapter import MutmutAdapter
from nit.adapters.mutation.pitest_adapter import PitestAdapter
from nit.adapters.mutation.stryker_adapter import StrykerAdapter
from nit.agents.analyzers.mutation import MutationAnalysisResult, MutationTestAnalyzer
from nit.agents.builders.mutation import MutationTestBuilder, MutationTestCase
from nit.llm.prompts.mutation_test_prompt import (
    MutationTestPromptContext,
    build_mutation_test_messages,
)

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture()
def stryker_project(tmp_path: Path) -> Path:
    """Create a temporary project with Stryker configured in package.json."""
    package_json = {
        "name": "test-project",
        "devDependencies": {
            "@stryker-mutator/core": "^7.0.0",
            "@stryker-mutator/mocha-runner": "^7.0.0",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(package_json), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def stryker_config_project(tmp_path: Path) -> Path:
    """Create a temporary project with a stryker.conf.js file."""
    (tmp_path / "stryker.conf.js").write_text(
        "module.exports = { mutate: ['src/**/*.js'] };",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def mutmut_project(tmp_path: Path) -> Path:
    """Create a temporary project with mutmut in pyproject.toml."""
    pyproject = (
        "[project]\n"
        'name = "demo"\n'
        "\n"
        "[project.optional-dependencies]\n"
        'dev = ["mutmut>=2.0"]\n'
    )
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def mutmut_requirements_project(tmp_path: Path) -> Path:
    """Create a temporary project with mutmut in requirements-dev.txt."""
    (tmp_path / "requirements-dev.txt").write_text("mutmut>=2.0\npytest\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def pitest_maven_project(tmp_path: Path) -> Path:
    """Create a temporary project with PIT in pom.xml."""
    pom_xml = (
        "<project>\n"
        "  <build>\n"
        "    <plugins>\n"
        "      <plugin>\n"
        "        <groupId>org.pitest</groupId>\n"
        "        <artifactId>pitest-maven</artifactId>\n"
        "        <version>1.15.0</version>\n"
        "      </plugin>\n"
        "    </plugins>\n"
        "  </build>\n"
        "</project>\n"
    )
    (tmp_path / "pom.xml").write_text(pom_xml, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def pitest_gradle_project(tmp_path: Path) -> Path:
    """Create a temporary project with PIT in build.gradle."""
    gradle = "plugins {\n    id 'info.solidsoft.pitest' version '1.15.0'\n}\n"
    (tmp_path / "build.gradle").write_text(gradle, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def sample_surviving_mutants() -> list[SurvivingMutant]:
    """Return a list of sample surviving mutants."""
    return [
        SurvivingMutant(
            file_path="src/calculator.py",
            line_number=10,
            original_code="if x > 0:",
            mutated_code="if x >= 0:",
            mutation_operator="ConditionalBoundary",
            description="Changed > to >=",
        ),
        SurvivingMutant(
            file_path="src/calculator.py",
            line_number=25,
            original_code="return a + b",
            mutated_code="return a - b",
            mutation_operator="MathMutator",
            description="Replaced + with -",
        ),
        SurvivingMutant(
            file_path="src/utils.py",
            line_number=5,
            original_code="count += 1",
            mutated_code="count -= 1",
            mutation_operator="IncrementsMutator",
            description="Changed += to -=",
        ),
        SurvivingMutant(
            file_path="src/service.py",
            line_number=42,
            original_code="self.save()",
            mutated_code="",
            mutation_operator="VoidMethodCall",
            description="Removed call to save()",
        ),
    ]


@pytest.fixture()
def sample_report(sample_surviving_mutants: list[SurvivingMutant]) -> MutationTestReport:
    """Return a sample mutation test report."""
    return MutationTestReport(
        tool="stryker",
        total_mutants=100,
        killed=85,
        survived=12,
        timed_out=3,
        mutation_score=85.0,
        surviving_mutants=sample_surviving_mutants,
    )


@pytest.fixture()
def sample_analysis(
    sample_report: MutationTestReport,
    sample_surviving_mutants: list[SurvivingMutant],
) -> MutationAnalysisResult:
    """Return a sample mutation analysis result."""
    high_priority = [
        m
        for m in sample_surviving_mutants
        if m.mutation_operator in {"ConditionalBoundary", "MathMutator", "VoidMethodCall"}
    ]
    return MutationAnalysisResult(
        adapter_name="stryker",
        report=sample_report,
        high_priority_mutants=high_priority,
    )


# ── StrykerAdapter tests ─────────────────────────────────────────


def test_stryker_detects_package_json_dependency(stryker_project: Path) -> None:
    """StrykerAdapter detects @stryker-mutator/core in package.json."""
    adapter = StrykerAdapter()
    assert adapter.detect(stryker_project) is True


def test_stryker_detects_config_file(stryker_config_project: Path) -> None:
    """StrykerAdapter detects stryker.conf.js."""
    adapter = StrykerAdapter()
    assert adapter.detect(stryker_config_project) is True


def test_stryker_not_detected_in_empty_project(tmp_path: Path) -> None:
    """StrykerAdapter returns False when no Stryker config exists."""
    adapter = StrykerAdapter()
    assert adapter.detect(tmp_path) is False


def test_stryker_name_and_language() -> None:
    """StrykerAdapter reports correct name and language."""
    adapter = StrykerAdapter()
    assert adapter.name == "stryker"
    assert adapter.language == "javascript"


@patch("nit.adapters.mutation.stryker_adapter.asyncio.create_subprocess_exec")
async def test_stryker_run_npx_not_found(mock_exec: MagicMock, stryker_project: Path) -> None:
    """StrykerAdapter returns empty report when npx is not found."""
    mock_exec.side_effect = FileNotFoundError("npx not found")
    adapter = StrykerAdapter()
    report = await adapter.run_mutation_tests(stryker_project)
    assert report.tool == "stryker"
    assert report.total_mutants == 0


@patch("nit.adapters.mutation.stryker_adapter.asyncio.create_subprocess_exec")
async def test_stryker_parses_json_report(mock_exec: MagicMock, stryker_project: Path) -> None:
    """StrykerAdapter parses a Stryker JSON report correctly."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"")
    mock_exec.return_value = mock_proc

    # Create a fake Stryker JSON report
    report_dir = stryker_project / "reports" / "mutation"
    report_dir.mkdir(parents=True)
    stryker_report = {
        "files": {
            "src/math.js": {
                "mutants": [
                    {
                        "status": "Killed",
                        "mutatorName": "MathMutator",
                        "location": {"start": {"line": 5}},
                    },
                    {
                        "status": "Survived",
                        "mutatorName": "ConditionalBoundary",
                        "location": {"start": {"line": 10}},
                        "originalLines": "if (x > 0)",
                        "mutatedLines": "if (x >= 0)",
                        "description": "Changed > to >=",
                    },
                    {
                        "status": "Timeout",
                        "mutatorName": "InfiniteLoop",
                        "location": {"start": {"line": 15}},
                    },
                ]
            }
        }
    }
    (report_dir / "mutation.json").write_text(json.dumps(stryker_report), encoding="utf-8")

    adapter = StrykerAdapter()
    report = await adapter.run_mutation_tests(stryker_project)

    assert report.tool == "stryker"
    assert report.total_mutants == 3
    assert report.killed == 1
    assert report.survived == 1
    assert report.timed_out == 1
    assert len(report.surviving_mutants) == 1
    assert report.surviving_mutants[0].mutation_operator == "ConditionalBoundary"
    assert report.surviving_mutants[0].line_number == 10


# ── MutmutAdapter tests ─────────────────────────────────────────


def test_mutmut_detects_pyproject_dependency(mutmut_project: Path) -> None:
    """MutmutAdapter detects mutmut in pyproject.toml."""
    adapter = MutmutAdapter()
    assert adapter.detect(mutmut_project) is True


def test_mutmut_detects_requirements_dependency(mutmut_requirements_project: Path) -> None:
    """MutmutAdapter detects mutmut in requirements-dev.txt."""
    adapter = MutmutAdapter()
    assert adapter.detect(mutmut_requirements_project) is True


def test_mutmut_not_detected_in_empty_project(tmp_path: Path) -> None:
    """MutmutAdapter returns False when no mutmut config exists."""
    adapter = MutmutAdapter()
    assert adapter.detect(tmp_path) is False


def test_mutmut_name_and_language() -> None:
    """MutmutAdapter reports correct name and language."""
    adapter = MutmutAdapter()
    assert adapter.name == "mutmut"
    assert adapter.language == "python"


@patch("nit.adapters.mutation.mutmut_adapter.asyncio.create_subprocess_exec")
async def test_mutmut_run_not_found(mock_exec: MagicMock, mutmut_project: Path) -> None:
    """MutmutAdapter returns empty report when mutmut is not found."""
    mock_exec.side_effect = FileNotFoundError("mutmut not found")
    adapter = MutmutAdapter()
    report = await adapter.run_mutation_tests(mutmut_project)
    assert report.tool == "mutmut"
    assert report.total_mutants == 0


def test_mutmut_parses_results_output() -> None:
    """MutmutAdapter parses mutmut results output correctly."""
    adapter = MutmutAdapter()
    output = (
        "Killed 45\n"
        "Survived 3\n"
        "Timeout 2\n"
        "\n"
        "--- src/calculator.py ---\n"
        "10: changed > to >=\n"
        "25: changed + to -\n"
        "--- src/utils.py ---\n"
        "5: changed += to -=\n"
    )
    report = adapter._parse_results_output(output)

    assert report.tool == "mutmut"
    assert report.total_mutants == 50
    assert report.killed == 45
    assert report.survived == 3
    assert report.timed_out == 2
    assert len(report.surviving_mutants) == 3
    assert report.surviving_mutants[0].file_path == "src/calculator.py"
    assert report.surviving_mutants[0].line_number == 10
    assert report.surviving_mutants[2].file_path == "src/utils.py"


# ── PitestAdapter tests ─────────────────────────────────────────


def test_pitest_detects_pom_xml(pitest_maven_project: Path) -> None:
    """PitestAdapter detects pitest in pom.xml."""
    adapter = PitestAdapter()
    assert adapter.detect(pitest_maven_project) is True


def test_pitest_detects_build_gradle(pitest_gradle_project: Path) -> None:
    """PitestAdapter detects pitest in build.gradle."""
    adapter = PitestAdapter()
    assert adapter.detect(pitest_gradle_project) is True


def test_pitest_not_detected_in_empty_project(tmp_path: Path) -> None:
    """PitestAdapter returns False when no PIT config exists."""
    adapter = PitestAdapter()
    assert adapter.detect(tmp_path) is False


def test_pitest_name_and_language() -> None:
    """PitestAdapter reports correct name and language."""
    adapter = PitestAdapter()
    assert adapter.name == "pitest"
    assert adapter.language == "java"


def test_pitest_parses_xml_report(tmp_path: Path) -> None:
    """PitestAdapter parses a PIT XML mutations report correctly."""
    mutations_xml = (
        "<mutations>\n"
        '  <mutation detected="true" status="KILLED">\n'
        "    <sourceFile>Calculator.java</sourceFile>\n"
        "    <lineNumber>15</lineNumber>\n"
        "    <mutator>ConditionalBoundary</mutator>\n"
        "    <description>Changed &gt; to &gt;=</description>\n"
        "  </mutation>\n"
        '  <mutation detected="false" status="SURVIVED">\n'
        "    <sourceFile>Calculator.java</sourceFile>\n"
        "    <lineNumber>22</lineNumber>\n"
        "    <mutator>MathMutator</mutator>\n"
        "    <description>Replaced + with -</description>\n"
        "  </mutation>\n"
        '  <mutation detected="false" status="TIMED_OUT">\n'
        "    <sourceFile>Service.java</sourceFile>\n"
        "    <lineNumber>50</lineNumber>\n"
        "    <mutator>VoidMethodCall</mutator>\n"
        "    <description>Removed call</description>\n"
        "  </mutation>\n"
        "</mutations>\n"
    )
    report_path = tmp_path / "mutations.xml"
    report_path.write_text(mutations_xml, encoding="utf-8")

    report = PitestAdapter._parse_report(report_path)

    assert report.tool == "pitest"
    assert report.total_mutants == 3
    assert report.killed == 1
    assert report.survived == 1
    assert report.timed_out == 1
    assert len(report.surviving_mutants) == 1
    assert report.surviving_mutants[0].file_path == "Calculator.java"
    assert report.surviving_mutants[0].line_number == 22
    assert report.surviving_mutants[0].mutation_operator == "MathMutator"


@patch("nit.adapters.mutation.pitest_adapter.asyncio.create_subprocess_exec")
async def test_pitest_run_maven_not_found(mock_exec: MagicMock, pitest_maven_project: Path) -> None:
    """PitestAdapter returns empty report when mvn is not found."""
    mock_exec.side_effect = FileNotFoundError("mvn not found")
    adapter = PitestAdapter()
    report = await adapter.run_mutation_tests(pitest_maven_project)
    assert report.tool == "pitest"
    assert report.total_mutants == 0


# ── MutationTestReport data model tests ──────────────────────────


def test_mutation_test_report_defaults() -> None:
    """MutationTestReport has sensible defaults."""
    report = MutationTestReport(tool="test")
    assert report.total_mutants == 0
    assert report.killed == 0
    assert report.survived == 0
    assert report.timed_out == 0
    assert report.mutation_score == 0.0
    assert report.surviving_mutants == []


def test_mutation_test_report_with_data(sample_report: MutationTestReport) -> None:
    """MutationTestReport stores data correctly."""
    assert sample_report.tool == "stryker"
    assert sample_report.total_mutants == 100
    assert sample_report.killed == 85
    assert sample_report.survived == 12
    assert sample_report.timed_out == 3
    assert sample_report.mutation_score == 85.0
    assert len(sample_report.surviving_mutants) == 4


def test_surviving_mutant_fields() -> None:
    """SurvivingMutant stores all fields correctly."""
    mutant = SurvivingMutant(
        file_path="src/app.py",
        line_number=42,
        original_code="x > 0",
        mutated_code="x >= 0",
        mutation_operator="ConditionalBoundary",
        description="Changed > to >=",
    )
    assert mutant.file_path == "src/app.py"
    assert mutant.line_number == 42
    assert mutant.original_code == "x > 0"
    assert mutant.mutated_code == "x >= 0"
    assert mutant.mutation_operator == "ConditionalBoundary"
    assert mutant.description == "Changed > to >="


# ── MutationTestAnalyzer tests ───────────────────────────────────


def test_analyzer_detects_stryker(stryker_project: Path) -> None:
    """MutationTestAnalyzer detects and selects StrykerAdapter."""
    analyzer = MutationTestAnalyzer()
    adapter = analyzer._detect_adapter(stryker_project)
    assert adapter is not None
    assert adapter.name == "stryker"


def test_analyzer_detects_mutmut(mutmut_project: Path) -> None:
    """MutationTestAnalyzer detects and selects MutmutAdapter."""
    analyzer = MutationTestAnalyzer()
    adapter = analyzer._detect_adapter(mutmut_project)
    assert adapter is not None
    assert adapter.name == "mutmut"


def test_analyzer_detects_pitest(pitest_maven_project: Path) -> None:
    """MutationTestAnalyzer detects and selects PitestAdapter."""
    analyzer = MutationTestAnalyzer()
    adapter = analyzer._detect_adapter(pitest_maven_project)
    assert adapter is not None
    assert adapter.name == "pitest"


async def test_analyzer_no_adapter_detected(tmp_path: Path) -> None:
    """MutationTestAnalyzer returns 'none' when no adapter is found."""
    analyzer = MutationTestAnalyzer()
    result = await analyzer.analyze(tmp_path)
    assert result.adapter_name == "none"
    assert result.report.tool == "none"
    assert result.report.total_mutants == 0


def test_analyzer_identifies_high_priority(
    sample_surviving_mutants: list[SurvivingMutant],
) -> None:
    """MutationTestAnalyzer correctly classifies high-priority mutants."""
    analyzer = MutationTestAnalyzer()
    high_priority = analyzer._identify_high_priority(sample_surviving_mutants)

    # ConditionalBoundary, MathMutator, IncrementsMutator, VoidMethodCall are all
    # in the high-priority set
    assert len(high_priority) == 4


async def test_analyzer_with_mock_adapter(tmp_path: Path) -> None:
    """MutationTestAnalyzer uses a mock adapter and returns results."""
    mock_adapter = MagicMock(spec=MutationTestingAdapter)
    mock_adapter.name = "mock_tool"
    mock_adapter.language = "python"
    mock_adapter.detect.return_value = True
    mock_adapter.run_mutation_tests = AsyncMock(
        return_value=MutationTestReport(
            tool="mock_tool",
            total_mutants=10,
            killed=7,
            survived=3,
            mutation_score=70.0,
            surviving_mutants=[
                SurvivingMutant(
                    file_path="src/app.py",
                    line_number=5,
                    original_code="x > 0",
                    mutated_code="x >= 0",
                    mutation_operator="ConditionalBoundary",
                    description="Changed > to >=",
                ),
                SurvivingMutant(
                    file_path="src/app.py",
                    line_number=10,
                    original_code="return result",
                    mutated_code="return None",
                    mutation_operator="ReturnValues",
                    description="Replaced return value",
                ),
                SurvivingMutant(
                    file_path="src/app.py",
                    line_number=15,
                    original_code="log(msg)",
                    mutated_code="",
                    mutation_operator="CustomOperator",
                    description="Removed call",
                ),
            ],
        )
    )

    analyzer = MutationTestAnalyzer(adapters=[mock_adapter])
    result = await analyzer.analyze(tmp_path)

    assert result.adapter_name == "mock_tool"
    assert result.report.total_mutants == 10
    assert result.report.killed == 7
    assert result.report.survived == 3
    assert result.report.mutation_score == 70.0
    # ConditionalBoundary and ReturnValues are high-priority; CustomOperator is not
    assert len(result.high_priority_mutants) == 2


# ── MutationTestBuilder tests ───────────────────────────────────


def test_builder_generates_test_cases(sample_analysis: MutationAnalysisResult) -> None:
    """MutationTestBuilder generates a test case for each surviving mutant."""
    builder = MutationTestBuilder()
    cases = builder.generate_test_plan(sample_analysis)

    assert len(cases) == 4  # 4 surviving mutants in sample
    for case in cases:
        assert case.test_name.startswith("test_kill_mutant_")
        assert case.test_strategy
        assert case.description
        assert case.mutant is not None


def test_builder_high_priority_only(sample_analysis: MutationAnalysisResult) -> None:
    """MutationTestBuilder generates only high-priority test cases when asked."""
    builder = MutationTestBuilder()
    cases = builder.generate_test_plan(sample_analysis, high_priority_only=True)

    # sample_analysis has 3 high-priority mutants
    assert len(cases) == 3
    operators = {c.mutant.mutation_operator for c in cases}
    assert "ConditionalBoundary" in operators
    assert "MathMutator" in operators
    assert "VoidMethodCall" in operators


def test_builder_strategy_mapping(sample_surviving_mutants: list[SurvivingMutant]) -> None:
    """MutationTestBuilder uses operator-specific strategies."""
    analysis = MutationAnalysisResult(
        adapter_name="test",
        report=MutationTestReport(
            tool="test",
            surviving_mutants=sample_surviving_mutants,
        ),
    )
    builder = MutationTestBuilder()
    cases = builder.generate_test_plan(analysis)

    # Each operator should have a specific strategy
    strategies_by_operator = {c.mutant.mutation_operator: c.test_strategy for c in cases}
    assert "boundary" in strategies_by_operator["ConditionalBoundary"].lower()
    assert "math" in strategies_by_operator["MathMutator"].lower()
    assert "side-effect" in strategies_by_operator["VoidMethodCall"].lower()


def test_builder_empty_analysis() -> None:
    """MutationTestBuilder returns empty list for no surviving mutants."""
    analysis = MutationAnalysisResult(
        adapter_name="test",
        report=MutationTestReport(tool="test"),
    )
    builder = MutationTestBuilder()
    cases = builder.generate_test_plan(analysis)
    assert cases == []


def test_builder_test_case_fields() -> None:
    """MutationTestCase has all required fields populated."""
    mutant = SurvivingMutant(
        file_path="src/calc.py",
        line_number=10,
        original_code="a + b",
        mutated_code="a - b",
        mutation_operator="MathMutator",
        description="Replaced + with -",
    )
    case = MutationTestCase(
        mutant=mutant,
        test_name="test_kill_mutant_calc_line10",
        test_strategy="Assert exact result",
        description="Kill mutant in calc.py at line 10",
    )
    assert case.mutant is mutant
    assert case.test_name == "test_kill_mutant_calc_line10"
    assert case.test_strategy == "Assert exact result"
    assert case.description == "Kill mutant in calc.py at line 10"


# ── Prompt template tests ────────────────────────────────────────


def test_prompt_builds_messages(sample_analysis: MutationAnalysisResult) -> None:
    """build_mutation_test_messages produces system and user messages."""
    builder = MutationTestBuilder()
    cases = builder.generate_test_plan(sample_analysis)

    context = MutationTestPromptContext(
        language="python",
        test_framework="pytest",
        source_path="src/calculator.py",
        source_code="def add(a, b):\n    return a + b\n",
        test_cases=cases,
    )

    messages = build_mutation_test_messages(context)

    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"

    # System message should mention the framework and language
    assert "pytest" in messages[0].content
    assert "python" in messages[0].content
    assert "mutation" in messages[0].content.lower()

    # User message should contain the source code and mutant info
    assert "src/calculator.py" in messages[1].content
    assert "def add(a, b):" in messages[1].content
    assert "ConditionalBoundary" in messages[1].content


def test_prompt_context_defaults() -> None:
    """MutationTestPromptContext has correct defaults."""
    context = MutationTestPromptContext(
        language="python",
        test_framework="pytest",
        source_path="src/app.py",
        source_code="pass",
    )
    assert context.test_cases == []
    assert context.language == "python"
    assert context.test_framework == "pytest"
