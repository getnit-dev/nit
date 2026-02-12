"""RootCauseAnalyzer agent — traces bugs to their root cause using code analysis + LLM.

This agent (task 3.9.3):
1. Uses tree-sitter to analyze code structure and data flow
2. Traces execution path leading to the bug
3. Identifies missing validations, incorrect assumptions, logic errors
4. Uses LLM to reason about the root cause
5. Provides detailed explanation of why the bug occurs
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.llm.engine import GenerationRequest, LLMMessage
from nit.memory.global_memory import GlobalMemory
from nit.memory.helpers import get_memory_context, inject_memory_into_messages, record_outcome
from nit.parsing.languages import extract_from_file

if TYPE_CHECKING:
    from nit.agents.analyzers.bug import BugReport
    from nit.llm.engine import LLMEngine
    from nit.parsing.treesitter import FunctionInfo, ParseResult

logger = logging.getLogger(__name__)

# Data flow analysis limits
MAX_VARIABLES_TO_ANALYZE = 5  # Limit variables analyzed to keep analysis manageable
MAX_USAGES_PER_VARIABLE = 5  # Limit usages tracked per variable
MAX_DATA_FLOWS_IN_PROMPT = 3  # Limit data flows included in LLM prompt
MAX_SOURCE_CODE_LENGTH = 2000  # Maximum source code length to include in prompt


@dataclass
class DataFlowPath:
    """Represents a data flow path in the code."""

    variable_name: str
    """Name of the variable being tracked."""

    assignments: list[str] = field(default_factory=list)
    """List of assignment statements affecting this variable."""

    conditions: list[str] = field(default_factory=list)
    """Conditional checks on this variable."""

    usages: list[str] = field(default_factory=list)
    """Places where this variable is used."""


@dataclass
class RootCause:
    """Root cause analysis result."""

    category: str
    """Category of root cause (e.g., 'missing_validation', 'logic_error')."""

    description: str
    """Detailed description of the root cause."""

    affected_code: str
    """The specific code causing the issue."""

    data_flow: list[DataFlowPath] = field(default_factory=list)
    """Data flow paths contributing to the bug."""

    missing_checks: list[str] = field(default_factory=list)
    """Missing validation checks."""

    incorrect_assumptions: list[str] = field(default_factory=list)
    """Incorrect assumptions in the code."""

    contributing_factors: list[str] = field(default_factory=list)
    """Other factors contributing to the bug."""

    confidence: float = 0.7
    """Confidence level (0.0-1.0) in this root cause analysis."""


@dataclass
class RootCauseAnalysisTask(TaskInput):
    """Task input for root cause analysis."""

    task_type: str = "analyze_root_cause"
    """Type of task (defaults to 'analyze_root_cause')."""

    target: str = ""
    """Target file being analyzed."""

    bug_report: BugReport | None = None
    """Bug report from BugAnalyzer."""

    reproduction_test: str = ""
    """Reproduction test code (if available)."""

    source_code: str = ""
    """Full source code of the file containing the bug."""


class RootCauseAnalyzer(BaseAgent):
    """Analyzes bugs to identify their root cause using code analysis and LLM reasoning."""

    def __init__(
        self,
        llm_engine: LLMEngine,
        project_root: Path,
        *,
        enable_memory: bool = True,
    ) -> None:
        """Initialize the RootCauseAnalyzer.

        Args:
            llm_engine: LLM engine for reasoning about root causes.
            project_root: Root directory of the project.
            enable_memory: Whether to use GlobalMemory for pattern learning.
        """
        super().__init__()
        self._llm = llm_engine
        self._project_root = project_root
        self._memory = GlobalMemory(project_root) if enable_memory else None

    @property
    def name(self) -> str:
        """Return the agent name."""
        return "RootCauseAnalyzer"

    @property
    def description(self) -> str:
        """Return the agent description."""
        return "Traces bugs to their root cause using code analysis and LLM reasoning"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute root cause analysis.

        Args:
            task: A RootCauseAnalysisTask specifying the bug to analyze.

        Returns:
            TaskOutput with RootCause in result['root_cause'].
        """
        if not isinstance(task, RootCauseAnalysisTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a RootCauseAnalysisTask instance"],
            )

        if not task.bug_report:
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Bug report is required for root cause analysis"],
            )

        try:
            logger.info("Analyzing root cause for: %s", task.bug_report.title)

            # Step 1: Parse source code with tree-sitter
            parse_result = await self._parse_source_code(task.target, task.source_code)

            # Step 2: Analyze data flow to the bug location
            data_flow = await self._analyze_data_flow(
                parse_result, task.bug_report, task.source_code
            )

            # Step 3: Identify missing validations and checks
            missing_checks = self._identify_missing_checks(parse_result, task.bug_report, data_flow)

            # Step 4: Use LLM to reason about root cause
            root_cause = await self._llm_root_cause_analysis(
                task.bug_report,
                parse_result,
                data_flow,
                missing_checks,
                task.source_code,
                task.reproduction_test,
            )

            logger.info(
                "Root cause identified: %s (confidence: %.2f)",
                root_cause.category,
                root_cause.confidence,
            )

            record_outcome(
                self._memory,
                successful=True,
                domain="root_cause_analysis",
                context_dict={"domain": "debugging", "category": root_cause.category},
            )

            return TaskOutput(
                status=TaskStatus.COMPLETED,
                result={
                    "root_cause": root_cause,
                },
            )

        except Exception as e:
            logger.exception("Root cause analysis failed: %s", e)
            record_outcome(
                self._memory,
                successful=False,
                domain="root_cause_analysis",
                context_dict={"domain": "debugging"},
                error_message=str(e),
            )
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Root cause analysis error: {e}"],
            )

    async def _parse_source_code(self, file_path: str, source_code: str) -> ParseResult:
        """Parse source code with tree-sitter.

        Args:
            file_path: Path to the source file.
            source_code: Source code content.

        Returns:
            ParseResult with AST information.
        """
        # Write source to temp file if needed
        if source_code and not Path(file_path).exists():
            temp_file = self._project_root / ".nit" / "tmp" / "analysis" / "source.tmp"
            temp_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file.write_text(source_code, encoding="utf-8")
            file_path = str(temp_file)

        # Parse with tree-sitter (extract_from_file takes only file_path)
        return extract_from_file(file_path)

    async def _analyze_data_flow(
        self,
        parse_result: ParseResult,
        bug_report: BugReport,
        _source_code: str,
    ) -> list[DataFlowPath]:
        """Analyze data flow leading to the bug.

        Args:
            parse_result: Parsed source code.
            bug_report: Bug report with location information.
            _source_code: Source code content (unused, reserved for future use).

        Returns:
            List of data flow paths.
        """
        data_flows: list[DataFlowPath] = []

        # Find the function containing the bug
        target_function = self._find_function_at_location(
            parse_result, bug_report.location.line_number
        )

        if not target_function:
            return data_flows

        # Extract variables used in the function
        variables = self._extract_variables_from_function(target_function)

        # For each variable, trace its data flow
        for var_name in variables[:MAX_VARIABLES_TO_ANALYZE]:
            flow = DataFlowPath(variable_name=var_name)

            # Find assignments
            flow.assignments = self._find_assignments(target_function.body_text, var_name)

            # Find conditional checks
            flow.conditions = self._find_conditions(target_function.body_text, var_name)

            # Find usages
            flow.usages = self._find_usages(target_function.body_text, var_name)

            if flow.assignments or flow.conditions or flow.usages:
                data_flows.append(flow)

        return data_flows

    def _find_function_at_location(
        self, parse_result: ParseResult, line_number: int | None
    ) -> FunctionInfo | None:
        """Find the function containing the bug location.

        Args:
            parse_result: Parsed source code.
            line_number: Line number of the bug.

        Returns:
            FunctionInfo if found, None otherwise.
        """
        if line_number is None:
            # Return the first function if no line number
            return parse_result.functions[0] if parse_result.functions else None

        # Find function containing this line
        for func in parse_result.functions:
            if func.start_line <= line_number <= func.end_line:
                return func

        # Check class methods too
        for cls in parse_result.classes:
            for method in cls.methods:
                if method.start_line <= line_number <= method.end_line:
                    return method

        return None

    def _extract_variables_from_function(self, func: FunctionInfo) -> list[str]:
        """Extract variable names from a function.

        Args:
            func: Function information.

        Returns:
            List of variable names.
        """
        # Simple regex-based extraction
        # This is not perfect but works for common cases
        body = func.body_text

        # Match variable assignments: var_name = ...
        assignments = re.findall(r"\b([a-zA-Z_]\w*)\s*=(?!=)", body)

        # Match parameter names
        params = [p.name for p in func.parameters if p.name]

        # Combine and deduplicate
        return list(set(assignments + params))

    def _find_assignments(self, code: str, var_name: str) -> list[str]:
        """Find all assignments to a variable.

        Args:
            code: Code to search.
            var_name: Variable name.

        Returns:
            List of assignment statements.
        """
        pattern = rf"\b{re.escape(var_name)}\s*=\s*([^;{{}}]+)"
        matches = re.findall(pattern, code)

        return [f"{var_name} = {match.strip()}" for match in matches]

    def _find_conditions(self, code: str, var_name: str) -> list[str]:
        """Find all conditional checks on a variable.

        Args:
            code: Code to search.
            var_name: Variable name.

        Returns:
            List of conditional statements.
        """
        # Look for if/while/for conditions containing the variable
        patterns = [
            rf"if\s*\([^)]*\b{re.escape(var_name)}\b[^)]*\)",
            rf"while\s*\([^)]*\b{re.escape(var_name)}\b[^)]*\)",
            rf"elif\s*\([^)]*\b{re.escape(var_name)}\b[^)]*\)",
        ]

        conditions = []
        for pattern in patterns:
            matches = re.findall(pattern, code, re.IGNORECASE)
            conditions.extend(matches)

        return conditions

    def _find_usages(self, code: str, var_name: str) -> list[str]:
        """Find all usages of a variable.

        Args:
            code: Code to search.
            var_name: Variable name.

        Returns:
            List of usage contexts.
        """
        # Find lines containing the variable (excluding assignments)
        lines = code.split("\n")
        usages = []

        for line in lines:
            # Skip assignment lines
            if re.search(rf"\b{re.escape(var_name)}\s*=", line):
                continue

            # Check if variable is used
            if re.search(rf"\b{re.escape(var_name)}\b", line):
                usages.append(line.strip())

        return usages[:MAX_USAGES_PER_VARIABLE]

    def _identify_missing_checks(
        self,
        _parse_result: ParseResult,
        bug_report: BugReport,
        data_flows: list[DataFlowPath],
    ) -> list[str]:
        """Identify missing validation checks that could prevent the bug.

        Args:
            _parse_result: Parsed source code (unused, reserved for future use).
            bug_report: Bug report.
            data_flows: Data flow analysis results.

        Returns:
            List of missing checks.
        """
        missing: list[str] = []

        # Check for null/undefined dereference bugs
        if bug_report.bug_type.value == "null_dereference":
            for flow in data_flows:
                # Check if there's a null check before usage
                has_null_check = any(
                    flow.variable_name in cond
                    and any(
                        keyword in cond.lower() for keyword in ["null", "none", "undefined", "nil"]
                    )
                    for cond in flow.conditions
                )

                if not has_null_check and flow.usages:
                    missing.append(f"Missing null/undefined check for '{flow.variable_name}'")

        # Check for type errors
        elif bug_report.bug_type.value == "type_error":
            for flow in data_flows:
                has_type_check = any(
                    "type" in cond.lower() or "instanceof" in cond.lower()
                    for cond in flow.conditions
                )

                if not has_type_check and flow.usages:
                    missing.append(f"Missing type check for '{flow.variable_name}'")

        # Check for arithmetic errors
        elif bug_report.bug_type.value == "arithmetic_error":
            for flow in data_flows:
                has_zero_check = any(
                    flow.variable_name in cond and ("0" in cond or "zero" in cond.lower())
                    for cond in flow.conditions
                )

                # Check if variable is used in division
                has_division = any("/" in usage for usage in flow.usages)

                if not has_zero_check and has_division:
                    missing.append(
                        f"Missing zero check before division with '{flow.variable_name}'"
                    )

        # Check for index errors
        elif bug_report.bug_type.value == "index_error":
            for flow in data_flows:
                has_bounds_check = any(
                    "length" in cond.lower() or "size" in cond.lower() or "len(" in cond.lower()
                    for cond in flow.conditions
                )

                # Check if variable is used as index
                has_indexing = any("[" in usage for usage in flow.usages)

                if not has_bounds_check and has_indexing:
                    missing.append(f"Missing bounds check for index '{flow.variable_name}'")

        return missing

    async def _llm_root_cause_analysis(
        self,
        bug_report: BugReport,
        _parse_result: ParseResult,
        data_flows: list[DataFlowPath],
        missing_checks: list[str],
        source_code: str,
        _reproduction_test: str,
    ) -> RootCause:
        """Use LLM to reason about the root cause.

        Args:
            bug_report: Bug report.
            _parse_result: Parsed source code (unused, reserved for future use).
            data_flows: Data flow analysis.
            missing_checks: Identified missing checks.
            source_code: Full source code.
            _reproduction_test: Reproduction test (unused, reserved for future use).

        Returns:
            RootCause analysis.
        """
        # Build analysis context
        context_parts = [
            f"Bug Type: {bug_report.bug_type.value}",
            f"Severity: {bug_report.severity.value}",
            f"Error: {bug_report.error_message}",
            f"Location: {bug_report.location.file_path}",
        ]

        if bug_report.location.function_name:
            context_parts.append(f"Function: {bug_report.location.function_name}")

        if missing_checks:
            context_parts.append("\nMissing Validation Checks:")
            context_parts.extend(f"  - {check}" for check in missing_checks)

        if data_flows:
            context_parts.append("\nData Flow Analysis:")
            for flow in data_flows[:MAX_DATA_FLOWS_IN_PROMPT]:
                context_parts.append(f"  Variable: {flow.variable_name}")
                if flow.assignments:
                    context_parts.append(f"    Assignments: {len(flow.assignments)}")
                if flow.conditions:
                    context_parts.append(f"    Conditions: {', '.join(flow.conditions[:2])}")

        context = "\n".join(context_parts)

        # Truncate source code to manageable size
        code_snippet = (
            source_code[:MAX_SOURCE_CODE_LENGTH]
            if len(source_code) > MAX_SOURCE_CODE_LENGTH
            else source_code
        )

        system_prompt = f"""You are an expert at debugging and root cause analysis.
Analyze the following bug and identify its root cause.

{context}

Source Code:
```
{code_snippet}
```

Provide a concise root cause analysis covering:
1. The specific code pattern causing the bug
2. Why this causes the error
3. Any incorrect assumptions in the code
4. Contributing factors

Format your response as:
Category: <one of: missing_validation, logic_error, incorrect_assumption, race_condition,
          resource_management, other>
Description: <detailed explanation>
Affected Code: <specific code snippet>
Incorrect Assumptions: <list any incorrect assumptions>
Contributing Factors: <list other factors>"""

        user_prompt = "What is the root cause of this bug?"

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        memory_context = get_memory_context(
            self._memory,
            known_filter_key="domain",
            failed_filter_key="domain",
            filter_value="debugging",
        )
        inject_memory_into_messages(messages, memory_context)

        request = GenerationRequest(
            messages=messages,
            temperature=0.3,  # Moderate temperature for reasoning
            max_tokens=1500,
        )

        response = await self._llm.generate(request)
        analysis_text = response.text.strip()

        # Parse LLM response and return directly
        return self._parse_llm_response(analysis_text, bug_report, data_flows, missing_checks)

    def _parse_llm_response(
        self,
        response_text: str,
        _bug_report: BugReport,
        data_flows: list[DataFlowPath],
        missing_checks: list[str],
    ) -> RootCause:
        """Parse LLM response into RootCause object.

        Args:
            response_text: LLM response text.
            _bug_report: Original bug report (unused, reserved for future use).
            data_flows: Data flow analysis.
            missing_checks: Missing checks.

        Returns:
            RootCause object.
        """
        # Extract category
        category_match = re.search(r"Category:\s*(\w+)", response_text, re.IGNORECASE)
        category = category_match.group(1) if category_match else "logic_error"

        # Extract description
        desc_pattern = (
            r"Description:\s*"
            r"([^\n]+(?:\n(?!(?:Category|Affected|Incorrect|Contributing):)[^\n]+)*)"
        )
        desc_match = re.search(desc_pattern, response_text, re.IGNORECASE | re.MULTILINE)
        max_desc_length = 500
        description = desc_match.group(1).strip() if desc_match else response_text[:max_desc_length]

        # Extract affected code
        code_pattern = (
            r"Affected Code:\s*"
            r"([^\n]+(?:\n(?!(?:Category|Description|Incorrect|Contributing):)[^\n]+)*)"
        )
        code_match = re.search(code_pattern, response_text, re.IGNORECASE | re.MULTILINE)
        affected_code = code_match.group(1).strip() if code_match else ""

        # Extract assumptions
        assumptions_pattern = (
            r"Incorrect Assumptions:\s*"
            r"([^\n]+(?:\n(?!(?:Category|Description|Affected|Contributing):)[^\n]+)*)"
        )
        assumptions_match = re.search(
            assumptions_pattern, response_text, re.IGNORECASE | re.MULTILINE
        )
        assumptions_text = assumptions_match.group(1) if assumptions_match else ""
        assumptions = [
            line.strip("- ").strip() for line in assumptions_text.split("\n") if line.strip()
        ]

        # Extract contributing factors
        factors_pattern = (
            r"Contributing Factors:\s*"
            r"([^\n]+(?:\n(?!(?:Category|Description|Affected|Incorrect):)[^\n]+)*)"
        )
        factors_match = re.search(factors_pattern, response_text, re.IGNORECASE | re.MULTILINE)
        factors_text = factors_match.group(1) if factors_match else ""
        factors = [line.strip("- ").strip() for line in factors_text.split("\n") if line.strip()]

        return RootCause(
            category=category,
            description=description,
            affected_code=affected_code,
            data_flow=data_flows,
            missing_checks=missing_checks,
            incorrect_assumptions=assumptions,
            contributing_factors=factors,
            confidence=0.8,  # Base confidence for LLM analysis
        )
