"""SemanticGapDetector agent — identifies missing test scenarios beyond code coverage.

This agent uses LLM-powered analysis to find semantic test gaps:
1. Edge cases not covered by existing tests
2. Error paths and exception handling scenarios
3. Integration points with external systems
4. Behavioral scenarios for business logic
5. Concurrency and race conditions
6. Security vulnerabilities and input validation

Unlike coverage-based analysis, this focuses on high-value test scenarios
that would catch real bugs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.llm.engine import GenerationRequest
from nit.llm.prompts.semantic_gap import SemanticGapContext, SemanticGapPrompt

if TYPE_CHECKING:
    from nit.agents.analyzers.coverage import CoverageGapReport, FunctionGap
    from nit.llm.context import ContextAssembler
    from nit.llm.engine import LLMEngine

logger = logging.getLogger(__name__)

# Analysis configuration
DEFAULT_CONFIDENCE_THRESHOLD = 0.6  # Minimum confidence to report a gap
MAX_FUNCTIONS_TO_ANALYZE = 10  # Limit LLM calls for cost control
MIN_COMPLEXITY_FOR_ANALYSIS = 3  # Skip trivial functions
MAX_COVERAGE_FOR_ANALYSIS = 90.0  # Skip well-tested functions
MAX_FUNCTION_SNIPPET_LENGTH = 1000  # Maximum length for function code snippet


class GapCategory(Enum):
    """Categories of semantic test gaps."""

    EDGE_CASE = "edge_case"
    ERROR_PATH = "error_path"
    INTEGRATION = "integration"
    BEHAVIORAL = "behavioral"
    CONCURRENCY = "concurrency"
    SECURITY = "security"


@dataclass
class SemanticGap:
    """A semantic test gap identified by LLM analysis."""

    category: GapCategory
    """Category of the gap."""

    description: str
    """Description of what's missing."""

    function_name: str
    """Function where the gap exists."""

    file_path: str
    """File containing the function."""

    line_number: int | None = None
    """Line number (if available)."""

    severity: str = "medium"
    """Severity: high, medium, or low."""

    suggested_test_cases: list[str] = field(default_factory=list)
    """Specific test cases that would fill this gap."""

    confidence: float = 0.7
    """Confidence level (0.0-1.0) that this is a real gap."""

    reasoning: str = ""
    """Why this gap exists and why it matters."""


@dataclass
class SemanticGapTask(TaskInput):
    """Task input for semantic gap detection."""

    coverage_gap_report: CoverageGapReport | None = None
    """Coverage gap report with function-level gaps."""

    function_gaps: list[FunctionGap] = field(default_factory=list)
    """Specific function gaps to analyze."""


class SemanticGapDetector(BaseAgent):
    """Detects semantic test gaps using LLM analysis."""

    def __init__(
        self,
        llm_engine: LLMEngine,
        project_root: Path,
        context_assembler: ContextAssembler | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        max_functions: int = MAX_FUNCTIONS_TO_ANALYZE,
    ) -> None:
        """Initialize the SemanticGapDetector.

        Args:
            llm_engine: LLM engine for semantic analysis.
            project_root: Project root directory.
            context_assembler: Context assembler for code context.
            confidence_threshold: Minimum confidence to report gaps.
            max_functions: Maximum functions to analyze (cost control).
        """
        super().__init__()
        self.llm_engine = llm_engine
        self.project_root = project_root
        self.context_assembler = context_assembler
        self.confidence_threshold = confidence_threshold
        self.max_functions = max_functions
        self._cache: dict[str, list[SemanticGap]] = {}

    @property
    def name(self) -> str:
        """Return the agent name."""
        return "SemanticGapDetector"

    @property
    def description(self) -> str:
        """Return the agent description."""
        return "Identifies semantic test gaps using LLM-powered analysis"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute semantic gap detection.

        Args:
            task: A SemanticGapTask specifying what to analyze.

        Returns:
            TaskOutput with semantic_gaps list in result.
        """
        if not isinstance(task, SemanticGapTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a SemanticGapTask instance"],
            )

        try:
            gaps: list[SemanticGap] = []

            # Get function gaps to analyze
            function_gaps = task.function_gaps
            if not function_gaps and task.coverage_gap_report:
                function_gaps = task.coverage_gap_report.function_gaps

            if not function_gaps:
                logger.info("No function gaps to analyze")
                return TaskOutput(
                    status=TaskStatus.COMPLETED,
                    result={"semantic_gaps": gaps},
                )

            # Prioritize and limit functions
            prioritized = self._prioritize_gaps(function_gaps)

            # Analyze each function
            for gap in prioritized[: self.max_functions]:
                # Skip if already cached
                cache_key = f"{gap.file_path}:{gap.function_name}"
                if cache_key in self._cache:
                    gaps.extend(self._cache[cache_key])
                    continue

                # Skip trivial or well-tested functions
                if gap.complexity < MIN_COMPLEXITY_FOR_ANALYSIS:
                    continue
                if gap.coverage_percentage > MAX_COVERAGE_FOR_ANALYSIS:
                    continue

                # Analyze function for semantic gaps
                function_gaps_found = await self._analyze_function(gap)

                # Filter by confidence
                high_confidence = [
                    g for g in function_gaps_found if g.confidence >= self.confidence_threshold
                ]

                # Cache results
                self._cache[cache_key] = high_confidence
                gaps.extend(high_confidence)

            logger.info("Found %d semantic gaps", len(gaps))

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "semantic_gaps": gaps,
                    "functions_analyzed": min(len(prioritized), self.max_functions),
                },
            )

        except Exception as e:
            logger.exception("Semantic gap detection failed: %s", e)
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[str(e)],
            )

    def _prioritize_gaps(self, function_gaps: list[FunctionGap]) -> list[FunctionGap]:
        """Prioritize function gaps for analysis.

        Already prioritized by CoverageAnalyzer, so just return sorted.

        Args:
            function_gaps: List of function gaps.

        Returns:
            Sorted list with highest priority first.
        """
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(
            function_gaps,
            key=lambda g: (
                priority_order.get(g.priority.value, 3),
                -g.complexity,
                g.coverage_percentage,
            ),
        )

    async def _analyze_function(self, gap: FunctionGap) -> list[SemanticGap]:
        """Analyze a function for semantic gaps.

        Args:
            gap: Function gap from coverage analysis.

        Returns:
            List of semantic gaps found.
        """
        try:
            # Assemble context for the function
            context = await self._assemble_function_context(gap)

            # Call LLM for semantic analysis
            response = await self._call_llm_analysis(context)

            # Parse LLM response into SemanticGap objects
            return self._parse_llm_response(response, gap.function_name, gap.file_path)

        except Exception as e:
            logger.warning(
                "Failed to analyze function %s in %s: %s", gap.function_name, gap.file_path, e
            )
            return []

    async def _assemble_function_context(self, gap: FunctionGap) -> dict[str, Any]:
        """Assemble context for function analysis.

        Args:
            gap: Function gap to analyze.

        Returns:
            Context dictionary with function details.
        """
        # Read source file
        source_path = self.project_root / gap.file_path
        source_code = ""
        if source_path.exists():
            source_code = source_path.read_text(encoding="utf-8", errors="ignore")

        # Extract function from source (simplified - would use AST in production)
        function_code = self._extract_function_code(source_code, gap.function_name)

        # Build AST structure summary
        ast_structure = self._build_ast_structure(function_code)

        # Detect language from file extension
        language = self._detect_language(gap.file_path)

        return {
            "source_code": function_code,
            "language": language,
            "file_path": gap.file_path,
            "function_name": gap.function_name,
            "complexity": gap.complexity,
            "coverage_percentage": gap.coverage_percentage,
            "existing_test_patterns": [],  # Could be enhanced to detect patterns
            "related_tests": "",  # Could be enhanced to find test files
            "ast_structure": ast_structure,
        }

    def _extract_function_code(self, source_code: str, function_name: str) -> str:
        """Extract function code from source.

        Simplified implementation - would use language-specific AST parsing in production.

        Args:
            source_code: Full source code.
            function_name: Function name to extract.

        Returns:
            Function code snippet.
        """
        # Try to find function definition
        patterns = [
            rf"(def {function_name}\([^)]*\):.*?)(?=\ndef|\nclass|\Z)",  # Python
            rf"(function {function_name}\([^)]*\){{.*?}})",  # JavaScript
            rf"(fn {function_name}\([^)]*\).*?{{.*?}})",  # Rust
            rf"(func {function_name}\([^)]*\).*?{{.*?}})",  # Go
        ]

        for pattern in patterns:
            match = re.search(pattern, source_code, re.DOTALL)
            if match:
                return match.group(1)

        # Fallback: return a portion of the source
        if len(source_code) > MAX_FUNCTION_SNIPPET_LENGTH:
            return source_code[:MAX_FUNCTION_SNIPPET_LENGTH]
        return source_code

    def _build_ast_structure(self, function_code: str) -> str:
        """Build control flow summary from function code.

        Simplified implementation - would use AST analysis in production.

        Args:
            function_code: Function source code.

        Returns:
            Control flow summary.
        """
        # Count control flow constructs
        if_count = len(re.findall(r"\bif\b", function_code))
        loop_count = len(re.findall(r"\b(for|while|loop)\b", function_code))
        try_count = len(re.findall(r"\btry\b", function_code))
        return_count = len(re.findall(r"\breturn\b", function_code))

        summary_parts = []
        if if_count > 0:
            summary_parts.append(f"{if_count} conditional branches")
        if loop_count > 0:
            summary_parts.append(f"{loop_count} loops")
        if try_count > 0:
            summary_parts.append(f"{try_count} try-catch blocks")
        if return_count > 0:
            summary_parts.append(f"{return_count} return statements")

        return ", ".join(summary_parts) if summary_parts else "simple function"

    def _detect_language(self, file_path: str) -> str:
        """Detect language from file extension.

        Args:
            file_path: Path to the file.

        Returns:
            Language name.
        """
        ext = Path(file_path).suffix.lower()
        language_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".rs": "rust",
            ".go": "go",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
        }
        return language_map.get(ext, "unknown")

    async def _call_llm_analysis(self, context: dict[str, Any]) -> str:
        """Call LLM for semantic gap analysis.

        Args:
            context: Function context dictionary.

        Returns:
            LLM response text.
        """
        # Build prompt context
        gap_context = SemanticGapContext(
            source_code=context["source_code"],
            language=context["language"],
            file_path=context["file_path"],
            function_name=context["function_name"],
            complexity=context["complexity"],
            coverage_percentage=context["coverage_percentage"],
            existing_test_patterns=context.get("existing_test_patterns", []),
            related_tests=context.get("related_tests", ""),
            ast_structure=context.get("ast_structure", ""),
        )

        # Render prompt
        prompt_template = SemanticGapPrompt()
        rendered = prompt_template.render_gap_analysis(gap_context)

        # Call LLM
        request = GenerationRequest(messages=rendered.messages)
        response = await self.llm_engine.generate(request)
        return response.text

    def _parse_llm_response(
        self, response: str, function_name: str, file_path: str
    ) -> list[SemanticGap]:
        """Parse LLM response into SemanticGap objects.

        Args:
            response: LLM response text.
            function_name: Function name being analyzed.
            file_path: File path.

        Returns:
            List of semantic gaps.
        """
        gaps: list[SemanticGap] = []

        # Split by delimiter
        gap_sections = response.split("---")

        for section in gap_sections:
            if not section.strip():
                continue

            try:
                gap = self._parse_gap_section(section, function_name, file_path)
                if gap:
                    gaps.append(gap)
            except Exception as e:
                logger.warning("Failed to parse gap section: %s", e)
                continue

        return gaps

    def _parse_gap_section(
        self, section: str, function_name: str, file_path: str
    ) -> SemanticGap | None:
        """Parse a single gap section.

        Args:
            section: Gap section text.
            function_name: Function name.
            file_path: File path.

        Returns:
            SemanticGap object or None if parsing fails.
        """
        # Extract fields using regex
        category_match = re.search(r"\*\*CATEGORY\*\*:\s*(\w+)", section, re.IGNORECASE)
        severity_match = re.search(r"\*\*SEVERITY\*\*:\s*(\w+)", section, re.IGNORECASE)
        desc_match = re.search(
            r"\*\*DESCRIPTION\*\*:\s*(.+?)(?=\*\*|$)", section, re.IGNORECASE | re.DOTALL
        )
        test_cases_match = re.search(
            r"\*\*TEST_CASES\*\*:\s*(.+?)(?=\*\*|$)", section, re.IGNORECASE | re.DOTALL
        )
        confidence_match = re.search(r"\*\*CONFIDENCE\*\*:\s*([\d.]+)", section, re.IGNORECASE)
        reasoning_match = re.search(
            r"\*\*REASONING\*\*:\s*(.+?)(?=\*\*|$)", section, re.IGNORECASE | re.DOTALL
        )

        if not category_match or not desc_match:
            return None

        # Parse category
        category_str = category_match.group(1).lower()
        try:
            category = GapCategory(category_str)
        except ValueError:
            category = GapCategory.EDGE_CASE  # Default

        # Parse test cases
        test_cases: list[str] = []
        if test_cases_match:
            cases_text = test_cases_match.group(1)
            test_cases = [
                line.strip("- ").strip()
                for line in cases_text.split("\n")
                if line.strip() and line.strip().startswith("-")
            ]

        # Parse confidence
        confidence = float(confidence_match.group(1)) if confidence_match else 0.7

        return SemanticGap(
            category=category,
            description=desc_match.group(1).strip(),
            function_name=function_name,
            file_path=file_path,
            severity=severity_match.group(1).lower() if severity_match else "medium",
            suggested_test_cases=test_cases,
            confidence=confidence,
            reasoning=reasoning_match.group(1).strip() if reasoning_match else "",
        )
