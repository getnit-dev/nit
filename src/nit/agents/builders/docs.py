"""DocBuilder agent — generates and updates documentation using LLM.

This agent (task 4.1):
1. Receives changed files or scans all files
2. Compares current code AST against last documented state (stored in memory)
3. Identifies new functions, modified signatures, removed endpoints
4. Detects doc framework (Sphinx, TypeDoc, Doxygen, JSDoc, GoDoc, RustDoc)
5. Generates documentation comments in target framework format
6. Detects semantic mismatches between existing docs and code
7. Optionally writes generated docs back to source files or output directory
8. Returns generated docs or reports outdated docs (check mode)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any

from nit.adapters.registry import get_registry
from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.llm.engine import GenerationRequest, LLMError
from nit.llm.prompts.doc_generation import (
    DocChange,
    DocGenerationContext,
    build_doc_generation_messages,
    build_mismatch_detection_messages,
)
from nit.memory.store import MemoryStore
from nit.parsing.languages import extract_from_file
from nit.parsing.treesitter import detect_language

if TYPE_CHECKING:
    from nit.config import DocsConfig
    from nit.llm.engine import LLMEngine
    from nit.parsing.treesitter import ClassInfo, FunctionInfo, ParseResult

logger = logging.getLogger(__name__)

# Doc state memory filename
_DOC_STATE_FILE = "doc_state.json"


class DocFramework(Enum):
    """Supported documentation frameworks."""

    SPHINX = "sphinx"
    TYPEDOC = "typedoc"
    JSDOC = "jsdoc"
    DOXYGEN = "doxygen"
    GODOC = "godoc"
    RUSTDOC = "rustdoc"
    MKDOCS = "mkdocs"
    UNKNOWN = "unknown"


@dataclass
class FunctionState:
    """State of a function/method for tracking documentation changes."""

    name: str
    """Function/method name."""

    signature: str
    """Function signature (includes parameters, return type)."""

    docstring: str | None = None
    """Current docstring/comment."""

    line_number: int = 0
    """Line number in source file."""


@dataclass
class FileDocState:
    """Documentation state for a single file."""

    file_path: str
    """Relative path to the file."""

    language: str
    """Programming language."""

    doc_framework: str
    """Detected documentation framework."""

    functions: dict[str, FunctionState] = field(default_factory=dict)
    """Map of function name to state."""

    classes: dict[str, FunctionState] = field(default_factory=dict)
    """Map of class name to state."""

    last_updated: str = ""
    """Timestamp of last documentation update."""


@dataclass
class DocMismatch:
    """A semantic mismatch between documentation and code."""

    function_name: str
    """Name of the function/class/method."""

    file_path: str
    """File path where the mismatch was found."""

    mismatch_type: str
    """Type: 'semantic_drift', 'missing_param', 'wrong_return', 'stale_reference'."""

    description: str
    """Human-readable description of the mismatch."""

    severity: str = "warning"
    """Severity: 'error' or 'warning'."""


@dataclass
class DocBuildTask(TaskInput):
    """Task input for generating documentation."""

    task_type: str = "build_docs"
    """Type of task."""

    target: str = ""
    """Target file path."""

    source_files: list[str] = field(default_factory=list)
    """List of source files to document (or empty for all)."""

    check_only: bool = False
    """If True, only check for outdated docs without generating."""

    doc_framework: str | None = None
    """Override doc framework detection."""

    def __post_init__(self) -> None:
        """Initialize base TaskInput fields."""
        if not self.target and self.source_files:
            self.target = ", ".join(self.source_files[:3])


@dataclass
class DocBuildResult:
    """Result of documentation generation."""

    file_path: str
    """File that was documented."""

    changes: list[DocChange]
    """List of documentation changes detected."""

    generated_docs: dict[str, str]
    """Map of function name to generated doc comment."""

    outdated: bool
    """Whether documentation was outdated."""

    mismatches: list[DocMismatch] = field(default_factory=list)
    """Semantic mismatches between documentation and code."""

    errors: list[str] = field(default_factory=list)
    """Any errors encountered."""

    files_written: list[str] = field(default_factory=list)
    """Files that were written back to (source or output dir)."""


class DocBuilder(BaseAgent):
    """Agent that generates and updates documentation.

    Uses diff-based detection to compare current code AST against
    last documented state (stored in memory), identifies changes,
    and generates documentation in target framework format.
    """

    def __init__(
        self,
        llm_engine: LLMEngine,
        project_root: Path,
        *,
        max_tokens: int = 4096,
        docs_config: DocsConfig | None = None,
    ) -> None:
        """Initialize the DocBuilder agent.

        Args:
            llm_engine: The LLM engine to use for generation.
            project_root: Root directory of the project.
            max_tokens: Maximum tokens for doc generation.
            docs_config: Documentation generation configuration.
        """
        self._llm = llm_engine
        self._root = project_root
        self._docs_config = docs_config
        self._max_tokens = docs_config.max_tokens if docs_config else max_tokens
        self._registry = get_registry()

        # Doc state memory store
        self._doc_state_store: MemoryStore[dict[str, dict[str, Any]]] = MemoryStore(
            project_root, _DOC_STATE_FILE
        )
        self._doc_states: dict[str, FileDocState] = {}
        self._load_doc_states()

    @property
    def name(self) -> str:
        """Unique name identifying this agent."""
        return "doc_builder"

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return "Generates and updates documentation for source files"

    def _load_doc_states(self) -> None:
        """Load documented states from memory."""
        data = self._doc_state_store.load()
        if not data:
            return

        for file_path, state_dict in data.items():
            # Reconstruct FileDocState from dict
            functions = {
                name: FunctionState(**func_dict)
                for name, func_dict in state_dict.get("functions", {}).items()
            }
            classes = {
                name: FunctionState(**cls_dict)
                for name, cls_dict in state_dict.get("classes", {}).items()
            }

            self._doc_states[file_path] = FileDocState(
                file_path=state_dict["file_path"],
                language=state_dict["language"],
                doc_framework=state_dict["doc_framework"],
                functions=functions,
                classes=classes,
                last_updated=state_dict.get("last_updated", ""),
            )

    def _save_doc_states(self) -> None:
        """Save documented states to memory."""
        data: dict[str, dict[str, Any]] = {}
        for file_path, state in self._doc_states.items():
            data[file_path] = {
                "file_path": state.file_path,
                "language": state.language,
                "doc_framework": state.doc_framework,
                "functions": {
                    name: {
                        "name": func.name,
                        "signature": func.signature,
                        "docstring": func.docstring,
                        "line_number": func.line_number,
                    }
                    for name, func in state.functions.items()
                },
                "classes": {
                    name: {
                        "name": cls.name,
                        "signature": cls.signature,
                        "docstring": cls.docstring,
                        "line_number": cls.line_number,
                    }
                    for name, cls in state.classes.items()
                },
                "last_updated": state.last_updated,
            }
        self._doc_state_store.save(data)

    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute the documentation generation pipeline.

        Args:
            task: A DocBuildTask specifying files and options.

        Returns:
            TaskOutput with generated docs in result['results'],
            or errors if generation failed.
        """
        if not isinstance(task, DocBuildTask):
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=["Task must be a DocBuildTask instance"],
            )

        try:
            results: list[DocBuildResult] = []

            # Determine files to process
            source_files = task.source_files
            if not source_files:
                # Scan all supported source files in project
                source_files = self._discover_source_files()

            # Apply exclude patterns from config
            if self._docs_config and self._docs_config.exclude_patterns:
                patterns = self._docs_config.exclude_patterns
                source_files = [
                    f for f in source_files if not any(PurePath(f).match(pat) for pat in patterns)
                ]

            for file_path in source_files:
                result = await self._process_file(
                    file_path,
                    check_only=task.check_only,
                    doc_framework_override=task.doc_framework,
                )
                results.append(result)

            # Save updated doc states
            if not task.check_only:
                self._save_doc_states()

            # Determine overall status
            has_errors = any(r.errors for r in results)
            status = TaskStatus.FAILED if has_errors else TaskStatus.COMPLETED

            return TaskOutput(
                status=status,
                result={"results": [self._result_to_dict(r) for r in results]},
                errors=[],
            )

        except Exception as e:
            logger.exception("Documentation generation failed")
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Documentation generation failed: {e}"],
            )

    async def _process_file(
        self,
        file_path: str,
        *,
        check_only: bool = False,
        doc_framework_override: str | None = None,
    ) -> DocBuildResult:
        """Process a single file for documentation.

        Args:
            file_path: Path to the source file (relative to project root).
            check_only: If True, only report outdated docs without generating.
            doc_framework_override: Override doc framework detection.

        Returns:
            DocBuildResult with changes and generated docs.
        """
        source_path = self._root / file_path
        if not source_path.is_file():
            return DocBuildResult(
                file_path=file_path,
                changes=[],
                generated_docs={},
                outdated=False,
                errors=[f"File not found: {file_path}"],
            )

        # Detect language
        language = detect_language(source_path)
        if not language:
            return DocBuildResult(
                file_path=file_path,
                changes=[],
                generated_docs={},
                outdated=False,
                errors=[f"Could not detect language for {file_path}"],
            )

        # Parse source file
        parse_result = extract_from_file(str(source_path))

        # Detect doc framework (CLI override > config override > auto-detect)
        if doc_framework_override:
            doc_framework = doc_framework_override
        elif self._docs_config and self._docs_config.framework:
            doc_framework = self._docs_config.framework
        else:
            doc_framework = self._detect_doc_framework(language)

        # Get previous state
        prev_state = self._doc_states.get(file_path)

        # Build current state
        current_state = self._build_current_state(file_path, language, doc_framework, parse_result)

        # Compare states and detect changes (task 4.1.2)
        changes = self._detect_changes(prev_state, current_state)

        # Run mismatch detection for documented functions
        mismatches: list[DocMismatch] = []
        check_mismatch = self._docs_config.check_mismatch if self._docs_config else True
        if check_mismatch and self._llm is not None:
            mismatches = await self._check_mismatches(
                file_path, language, doc_framework, current_state, source_path
            )

        if not changes and not mismatches:
            logger.info("No documentation changes detected for %s", file_path)
            return DocBuildResult(
                file_path=file_path,
                changes=[],
                generated_docs={},
                outdated=False,
            )

        logger.info("Detected %d documentation changes in %s", len(changes), file_path)
        if mismatches:
            logger.info("Detected %d doc/code mismatches in %s", len(mismatches), file_path)

        # If check-only mode, return without generating
        if check_only:
            return DocBuildResult(
                file_path=file_path,
                changes=changes,
                generated_docs={},
                outdated=bool(changes),
                mismatches=mismatches,
            )

        # Generate documentation
        generated_docs = await self._generate_docs(
            file_path, language, doc_framework, changes, source_path
        )

        # Update doc state
        self._update_doc_state(file_path, current_state, generated_docs)

        # Write-back: source files and/or output directory
        files_written: list[str] = []
        write_to_source = self._docs_config.write_to_source if self._docs_config else False
        output_dir = self._docs_config.output_dir if self._docs_config else ""

        if write_to_source and generated_docs:
            written = self._write_docs_to_source(
                source_path, language, generated_docs, current_state
            )
            files_written.extend(written)

        if output_dir and generated_docs:
            written = self._write_docs_to_output_dir(file_path, generated_docs, output_dir)
            files_written.extend(written)

        return DocBuildResult(
            file_path=file_path,
            changes=changes,
            generated_docs=generated_docs,
            outdated=True,
            mismatches=mismatches,
            files_written=files_written,
        )

    def _discover_source_files(self) -> list[str]:
        """Discover all supported source files in the project.

        Returns:
            List of relative file paths.
        """
        patterns = [
            "**/*.py",
            "**/*.ts",
            "**/*.tsx",
            "**/*.js",
            "**/*.jsx",
            "**/*.cpp",
            "**/*.cc",
            "**/*.cxx",
            "**/*.c",
            "**/*.h",
            "**/*.hpp",
            "**/*.go",
            "**/*.rs",
            "**/*.java",
        ]

        files: list[str] = []
        for pattern in patterns:
            for path in self._root.glob(pattern):
                # Skip test files, node_modules, build directories
                path_str = str(path)
                if any(
                    skip in path_str
                    for skip in ["test", "node_modules", "build", "dist", ".venv", "venv"]
                ):
                    continue

                rel_path = path.relative_to(self._root)
                files.append(str(rel_path))

        return files

    def _detect_doc_framework(self, language: str) -> str:
        """Detect documentation framework based on language and project structure.

        Args:
            language: Programming language.

        Returns:
            Documentation framework name.
        """
        # Map language to framework with defaults
        has_typedoc = (self._root / "typedoc.json").exists()
        jsdoc_default = DocFramework.TYPEDOC.value if has_typedoc else DocFramework.JSDOC.value

        framework_map = {
            "python": DocFramework.SPHINX.value,
            "typescript": jsdoc_default,
            "javascript": jsdoc_default,
            "cpp": DocFramework.DOXYGEN.value,
            "c": DocFramework.DOXYGEN.value,
            "go": DocFramework.GODOC.value,
            "rust": DocFramework.RUSTDOC.value,
        }

        return framework_map.get(language, DocFramework.UNKNOWN.value)

    def _build_current_state(
        self,
        file_path: str,
        language: str,
        doc_framework: str,
        parse_result: ParseResult,
    ) -> FileDocState:
        """Build current documentation state from parsed source.

        Args:
            file_path: Relative file path.
            language: Programming language.
            doc_framework: Documentation framework.
            parse_result: Tree-sitter parse result.

        Returns:
            Current file documentation state.
        """
        functions: dict[str, FunctionState] = {}
        classes: dict[str, FunctionState] = {}

        # Extract function states
        for func in parse_result.functions:
            signature = self._build_signature(func)
            docstring = func.docstring if hasattr(func, "docstring") else None

            functions[func.name] = FunctionState(
                name=func.name,
                signature=signature,
                docstring=docstring,
                line_number=func.start_line,
            )

        # Extract class states
        for cls in parse_result.classes:
            signature = self._build_class_signature(cls)
            docstring = cls.docstring if hasattr(cls, "docstring") else None

            classes[cls.name] = FunctionState(
                name=cls.name,
                signature=signature,
                docstring=docstring,
                line_number=cls.start_line,
            )

        return FileDocState(
            file_path=file_path,
            language=language,
            doc_framework=doc_framework,
            functions=functions,
            classes=classes,
            last_updated="",
        )

    def _build_signature(self, func: FunctionInfo) -> str:
        """Build function signature string.

        Args:
            func: Function info from tree-sitter.

        Returns:
            Signature string.
        """
        params = ", ".join(p.name for p in func.parameters)
        return_type = func.return_type if hasattr(func, "return_type") else ""
        if return_type:
            return f"{func.name}({params}) -> {return_type}"
        return f"{func.name}({params})"

    def _build_class_signature(self, cls: ClassInfo) -> str:
        """Build class signature string.

        Args:
            cls: Class info from tree-sitter.

        Returns:
            Signature string.
        """
        base_classes = getattr(cls, "base_classes", [])
        if base_classes:
            return f"class {cls.name}({', '.join(base_classes)})"
        return f"class {cls.name}"

    def _detect_changes(
        self,
        prev_state: FileDocState | None,
        current_state: FileDocState,
    ) -> list[DocChange]:
        """Detect documentation changes between states (task 4.1.2).

        Args:
            prev_state: Previous documented state (None if first time).
            current_state: Current source state.

        Returns:
            List of documentation changes.
        """
        changes: list[DocChange] = []

        if prev_state is None:
            # All functions/classes are new
            changes.extend(
                DocChange(
                    function_name=func.name,
                    change_type="new",
                    signature=func.signature,
                    existing_doc=None,
                )
                for func in current_state.functions.values()
                if not func.docstring
            )

            changes.extend(
                DocChange(
                    function_name=cls.name,
                    change_type="new",
                    signature=cls.signature,
                    existing_doc=None,
                )
                for cls in current_state.classes.values()
                if not cls.docstring
            )

            return changes

        # Compare functions
        for name, curr_func in current_state.functions.items():
            prev_func = prev_state.functions.get(name)

            if prev_func is None:
                # New function
                if not curr_func.docstring:
                    changes.append(
                        DocChange(
                            function_name=name,
                            change_type="new",
                            signature=curr_func.signature,
                            existing_doc=None,
                        )
                    )
            elif prev_func.signature != curr_func.signature:
                # Modified function
                changes.append(
                    DocChange(
                        function_name=name,
                        change_type="modified",
                        signature=curr_func.signature,
                        existing_doc=curr_func.docstring,
                    )
                )
            elif not curr_func.docstring:
                # Undocumented function
                changes.append(
                    DocChange(
                        function_name=name,
                        change_type="new",
                        signature=curr_func.signature,
                        existing_doc=None,
                    )
                )

        # Compare classes
        for name, curr_cls in current_state.classes.items():
            prev_cls = prev_state.classes.get(name)

            if prev_cls is None:
                if not curr_cls.docstring:
                    changes.append(
                        DocChange(
                            function_name=name,
                            change_type="new",
                            signature=curr_cls.signature,
                            existing_doc=None,
                        )
                    )
            elif prev_cls.signature != curr_cls.signature:
                changes.append(
                    DocChange(
                        function_name=name,
                        change_type="modified",
                        signature=curr_cls.signature,
                        existing_doc=curr_cls.docstring,
                    )
                )
            elif not curr_cls.docstring:
                changes.append(
                    DocChange(
                        function_name=name,
                        change_type="new",
                        signature=curr_cls.signature,
                        existing_doc=None,
                    )
                )

        return changes

    async def _generate_docs(
        self,
        file_path: str,
        language: str,
        doc_framework: str,
        changes: list[DocChange],
        source_path: Path,
    ) -> dict[str, str]:
        """Generate documentation using LLM.

        Args:
            file_path: File path.
            language: Programming language.
            doc_framework: Documentation framework.
            changes: List of changes to document.
            source_path: Full path to source file.

        Returns:
            Map of function name to generated doc comment.
        """
        source_code = source_path.read_text(encoding="utf-8")
        style = self._docs_config.style if self._docs_config else ""

        doc_context = DocGenerationContext(
            changes=changes,
            doc_framework=doc_framework,
            language=language,
            source_path=file_path,
            source_code=source_code,
            style_preference=style,
        )

        messages = build_doc_generation_messages(doc_context)

        request = GenerationRequest(
            messages=messages,
            max_tokens=self._max_tokens,
            temperature=0.3,
        )

        try:
            response = await self._llm.generate(request)
            generated_text = response.text.strip()

            # Parse generated docs
            return self._parse_generated_docs(generated_text)

        except LLMError as e:
            logger.error("LLM generation failed for %s: %s", file_path, e)
            return {}

    def _parse_generated_docs(self, generated_text: str) -> dict[str, str]:
        """Parse generated documentation into function -> doc map.

        Args:
            generated_text: Raw LLM output.

        Returns:
            Map of function name to doc comment.
        """
        docs: dict[str, str] = {}

        # Split by marker
        pattern = r"--- FUNCTION: (.+?) ---\n(.*?)\n--- END ---"
        matches = re.finditer(pattern, generated_text, re.DOTALL)

        for match in matches:
            function_name = match.group(1).strip()
            doc_comment = match.group(2).strip()
            docs[function_name] = doc_comment

        return docs

    def _update_doc_state(
        self,
        file_path: str,
        current_state: FileDocState,
        generated_docs: dict[str, str],
    ) -> None:
        """Update doc state with generated documentation.

        Args:
            file_path: File path.
            current_state: Current state.
            generated_docs: Generated doc comments.
        """
        # Update docstrings in state
        for func_name, doc_comment in generated_docs.items():
            if func_name in current_state.functions:
                current_state.functions[func_name].docstring = doc_comment
            elif func_name in current_state.classes:
                current_state.classes[func_name].docstring = doc_comment

        current_state.last_updated = datetime.now(UTC).isoformat()
        self._doc_states[file_path] = current_state

    def _result_to_dict(self, result: DocBuildResult) -> dict[str, Any]:
        """Convert DocBuildResult to dict for JSON serialization.

        Args:
            result: Build result.

        Returns:
            Dict representation.
        """
        return {
            "file_path": result.file_path,
            "changes": [
                {
                    "function_name": c.function_name,
                    "change_type": c.change_type,
                    "signature": c.signature,
                    "existing_doc": c.existing_doc,
                }
                for c in result.changes
            ],
            "generated_docs": result.generated_docs,
            "outdated": result.outdated,
            "mismatches": [
                {
                    "function_name": m.function_name,
                    "file_path": m.file_path,
                    "mismatch_type": m.mismatch_type,
                    "description": m.description,
                    "severity": m.severity,
                }
                for m in result.mismatches
            ],
            "files_written": result.files_written,
            "errors": result.errors,
        }

    # ------------------------------------------------------------------
    # Mismatch detection
    # ------------------------------------------------------------------

    async def _check_mismatches(
        self,
        file_path: str,
        language: str,
        doc_framework: str,
        current_state: FileDocState,
        source_path: Path,
    ) -> list[DocMismatch]:
        """Detect semantic mismatches between existing docs and code.

        Checks functions/classes that already have documentation to see if
        the docs are semantically accurate (correct params, returns, etc.).

        Args:
            file_path: Relative file path.
            language: Programming language.
            doc_framework: Documentation framework.
            current_state: Current parsed state of the file.
            source_path: Full path to source file.

        Returns:
            List of detected mismatches.
        """
        # Collect documented functions/classes for mismatch checking
        documented: list[tuple[str, str, str]] = []  # (name, signature, docstring)
        for name, func in current_state.functions.items():
            if func.docstring:
                documented.append((name, func.signature, func.docstring))
        for name, cls in current_state.classes.items():
            if cls.docstring:
                documented.append((name, cls.signature, cls.docstring))

        if not documented:
            return []

        source_code = source_path.read_text(encoding="utf-8")

        messages = build_mismatch_detection_messages(
            documented_items=documented,
            language=language,
            doc_framework=doc_framework,
            source_code=source_code,
            source_path=file_path,
        )

        request = GenerationRequest(
            messages=messages,
            max_tokens=2048,
            temperature=0.1,
        )

        try:
            response = await self._llm.generate(request)
            return self._parse_mismatch_response(response.text.strip(), file_path)
        except LLMError as e:
            logger.error("Mismatch detection failed for %s: %s", file_path, e)
            return []

    def _parse_mismatch_response(self, response_text: str, file_path: str) -> list[DocMismatch]:
        """Parse LLM mismatch detection response into DocMismatch objects.

        Args:
            response_text: Raw LLM output (expected JSON array).
            file_path: File path for context.

        Returns:
            List of DocMismatch objects.
        """
        # Extract JSON array from response (may be wrapped in markdown code block)
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            json_lines = [line for line in lines if not line.startswith("```")]
            cleaned = "\n".join(json_lines).strip()

        try:
            items = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            logger.debug("Could not parse mismatch response as JSON: %s", response_text[:200])
            return []

        if not isinstance(items, list):
            return []

        mismatches: list[DocMismatch] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            mismatches.append(
                DocMismatch(
                    function_name=str(item.get("function", "")),
                    file_path=file_path,
                    mismatch_type=str(item.get("type", "semantic_drift")),
                    description=str(item.get("description", "")),
                    severity=str(item.get("severity", "warning")),
                )
            )
        return mismatches

    # ------------------------------------------------------------------
    # Write-back to source files
    # ------------------------------------------------------------------

    def _write_docs_to_source(
        self,
        source_path: Path,
        language: str,
        generated_docs: dict[str, str],
        current_state: FileDocState,
    ) -> list[str]:
        """Write generated documentation back into the source file.

        Args:
            source_path: Full path to the source file.
            language: Programming language.
            generated_docs: Map of function name to generated doc comment.
            current_state: Current state with line numbers.

        Returns:
            List of files written.
        """
        lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
        insertions: list[tuple[int, str]] = []

        for func_name, doc_comment in generated_docs.items():
            state = current_state.functions.get(func_name) or current_state.classes.get(func_name)
            if not state or state.line_number <= 0:
                continue

            # Line number is 1-based
            target_line = state.line_number - 1
            if target_line < 0 or target_line >= len(lines):
                continue

            formatted = self._format_doc_for_insertion(doc_comment, language, lines, target_line)
            insertions.append((target_line, formatted))

        if not insertions:
            return []

        # Apply insertions in reverse order to preserve line numbers
        insertions.sort(key=lambda x: x[0], reverse=True)
        for line_idx, doc_text in insertions:
            lines.insert(line_idx, doc_text)

        source_path.write_text("".join(lines), encoding="utf-8")
        logger.info("Wrote documentation back to %s", source_path)
        return [str(source_path)]

    def _format_doc_for_insertion(
        self,
        doc_comment: str,
        language: str,
        lines: list[str],
        target_line: int,
    ) -> str:
        """Format a doc comment for insertion into source code.

        Args:
            doc_comment: The raw doc comment text.
            language: Programming language.
            lines: Source file lines.
            target_line: Line index where the function/class is defined.

        Returns:
            Formatted doc comment string ready for insertion.
        """
        # Detect indentation from the target line
        if target_line < len(lines):
            target = lines[target_line]
            indent = target[: len(target) - len(target.lstrip())]
        else:
            indent = ""

        if language == "python":
            # Python: doc goes inside the function body, after the def line
            body_indent = indent + "    "
            doc_lines = doc_comment.strip().splitlines()
            if len(doc_lines) == 1:
                return f'{body_indent}"""{doc_lines[0]}"""\n'
            formatted = f'{body_indent}"""{doc_lines[0]}\n'
            for dline in doc_lines[1:]:
                formatted += f"{body_indent}{dline}\n"
            formatted += f'{body_indent}"""\n'
            return formatted

        # For other languages, doc goes above the function definition
        doc_lines = doc_comment.strip().splitlines()
        formatted_lines = [f"{indent}{dline}\n" for dline in doc_lines]
        return "".join(formatted_lines)

    # ------------------------------------------------------------------
    # Write docs to output directory
    # ------------------------------------------------------------------

    def _write_docs_to_output_dir(
        self,
        file_path: str,
        generated_docs: dict[str, str],
        output_dir: str,
    ) -> list[str]:
        """Write generated documentation as markdown to an output directory.

        Creates one markdown file per source file, organized by directory structure.

        Args:
            file_path: Relative source file path.
            generated_docs: Map of function name to generated doc comment.
            output_dir: Output directory path (relative to project root or absolute).

        Returns:
            List of files written.
        """
        out_root = Path(output_dir) if Path(output_dir).is_absolute() else self._root / output_dir
        # Mirror the source file path structure
        source_stem = Path(file_path).with_suffix(".md")
        out_file = out_root / source_stem
        out_file.parent.mkdir(parents=True, exist_ok=True)

        sections: list[str] = [f"# {Path(file_path).name}\n"]
        for func_name, doc_comment in generated_docs.items():
            sections.append(f"\n## `{func_name}`\n")
            sections.append(f"\n```\n{doc_comment}\n```\n")

        out_file.write_text("\n".join(sections), encoding="utf-8")
        logger.info("Wrote documentation to %s", out_file)
        return [str(out_file)]
