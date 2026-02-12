"""LLM Usage Detector — find AI/LLM integrations in a codebase (task 3.13.1).

Scans for OpenAI/Anthropic/Ollama SDK imports, HTTP calls to LLM endpoints,
and prompt template files. Maps detected LLM usage to drift test candidates.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import yaml

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Default directories to skip during scanning.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".nit",
        ".next",
        "target",
        "vendor",
    }
)

# Max file size to scan (10MB)
_MAX_FILE_SIZE = 10 * 1024 * 1024


@dataclass
class LLMUsageLocation:
    """A single location where LLM usage was detected."""

    file_path: Path
    line_number: int
    usage_type: str  # "import", "http_call", "prompt_template"
    provider: str  # "openai", "anthropic", "ollama", "gemini", etc.
    function_name: str | None = None
    endpoint_url: str | None = None
    context: str = ""  # Surrounding code snippet


@dataclass
class LLMUsageProfile:
    """Full LLM usage detection result."""

    locations: list[LLMUsageLocation] = field(default_factory=list)
    providers: set[str] = field(default_factory=set)
    total_usages: int = 0

    def add_location(self, location: LLMUsageLocation) -> None:
        """Add a detected usage location."""
        self.locations.append(location)
        self.providers.add(location.provider)
        self.total_usages += 1


class LLMUsageDetector(BaseAgent):
    """Detector for LLM/AI integrations in code (task 3.13.1)."""

    # SDK import patterns by provider
    _SDK_PATTERNS: ClassVar[dict[str, list[str]]] = {
        "openai": [
            # Python
            r"from\s+openai\s+import",
            r"import\s+openai",
            # JavaScript/TypeScript
            r"from\s+['\"]openai['\"]",
            r"require\(['\"]openai['\"]\)",
        ],
        "anthropic": [
            # Python
            r"from\s+anthropic\s+import",
            r"import\s+anthropic",
            # JavaScript/TypeScript
            r"from\s+['\"]@anthropic-ai/sdk['\"]",
            r"require\(['\"]@anthropic-ai/sdk['\"]\)",
        ],
        "ollama": [
            # Python
            r"from\s+ollama\s+import",
            r"import\s+ollama",
            # JavaScript/TypeScript
            r"from\s+['\"]ollama['\"]",
            r"require\(['\"]ollama['\"]\)",
        ],
        "gemini": [
            # Python
            r"from\s+google\.generativeai\s+import",
            r"import\s+google\.generativeai",
            # JavaScript/TypeScript
            r"from\s+['\"]@google/generative-ai['\"]",
            r"require\(['\"]@google/generative-ai['\"]\)",
        ],
        "cohere": [
            # Python
            r"from\s+cohere\s+import",
            r"import\s+cohere",
            # JavaScript/TypeScript
            r"from\s+['\"]cohere-ai['\"]",
            r"require\(['\"]cohere-ai['\"]\)",
        ],
        "huggingface": [
            # Python
            r"from\s+transformers\s+import",
            r"import\s+transformers",
            r"from\s+huggingface_hub\s+import",
        ],
        "litellm": [
            r"from\s+litellm\s+import",
            r"import\s+litellm",
        ],
    }

    # HTTP endpoint patterns by provider
    _ENDPOINT_PATTERNS: ClassVar[dict[str, list[str]]] = {
        "openai": [
            r"https?://api\.openai\.com/v\d+",
            r"['\"]openai['\"].*['\"]https?://[^'\"]+['\"]",
        ],
        "anthropic": [
            r"https?://api\.anthropic\.com/v\d+",
            r"['\"]anthropic['\"].*['\"]https?://[^'\"]+['\"]",
        ],
        "ollama": [
            r"https?://[^/]+:\d+/api/generate",
            r"https?://localhost:\d+/api",
        ],
        "gemini": [
            r"https?://generativelanguage\.googleapis\.com/v\d+",
        ],
        "azure_openai": [
            r"https?://[^/]+\.openai\.azure\.com",
        ],
    }

    # Prompt template file patterns
    _PROMPT_FILE_PATTERNS: ClassVar[list[str]] = [
        "**/prompts/*.txt",
        "**/prompts/*.md",
        "**/templates/*.prompt",
        "**/*_prompt.py",
        "**/*_prompt.ts",
        "**/*_prompt.js",
    ]

    def __init__(self) -> None:
        """Initialize the LLM usage detector."""
        super().__init__()
        self._compiled_patterns: dict[str, list[re.Pattern[str]]] = {}
        self._compiled_endpoints: dict[str, list[re.Pattern[str]]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile all regex patterns for performance."""
        for provider, patterns in self._SDK_PATTERNS.items():
            self._compiled_patterns[provider] = [re.compile(p, re.IGNORECASE) for p in patterns]

        for provider, patterns in self._ENDPOINT_PATTERNS.items():
            self._compiled_endpoints[provider] = [re.compile(p, re.IGNORECASE) for p in patterns]

    @property
    def name(self) -> str:
        """Agent name."""
        return "LLMUsageDetector"

    @property
    def description(self) -> str:
        """Agent description."""
        return "Detects LLM/AI integrations in code"

    async def run(self, task: TaskInput) -> TaskOutput:
        """Scan for LLM usage in the project.

        Args:
            task: Input task. task.target should be the project directory path.
                  Optional task.context["skip_dirs"] overrides default skip dirs.

        Returns:
            TaskOutput with result containing LLMUsageProfile data.
        """
        logger.info("Starting LLM usage detection")

        root_path = Path(task.target)
        if not root_path.exists():
            return TaskOutput(
                status=TaskStatus.FAILED,
                errors=[f"Root path does not exist: {root_path}"],
            )

        profile = LLMUsageProfile()

        # Scan for SDK imports and HTTP calls
        await self._scan_source_files(root_path, profile)

        # Scan for prompt template files
        await self._scan_prompt_files(root_path, profile)

        logger.info(
            "LLM usage detection complete: %d usages found, providers: %s",
            profile.total_usages,
            ", ".join(sorted(profile.providers)) if profile.providers else "none",
        )

        return TaskOutput(
            status=TaskStatus.COMPLETED,
            result={
                "total_usages": profile.total_usages,
                "providers": list(profile.providers),
                "locations": [
                    {
                        "file_path": str(loc.file_path),
                        "line_number": loc.line_number,
                        "usage_type": loc.usage_type,
                        "provider": loc.provider,
                        "function_name": loc.function_name,
                        "endpoint_url": loc.endpoint_url,
                        "context": loc.context,
                    }
                    for loc in profile.locations
                ],
            },
        )

    async def _scan_source_files(self, root_path: Path, profile: LLMUsageProfile) -> None:
        """Scan source files for SDK imports and HTTP calls.

        Args:
            root_path: Project root directory.
            profile: Profile to populate with findings.
        """
        source_extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java"}

        for file_path in root_path.rglob("*"):
            # Skip directories and non-source files
            if not file_path.is_file():
                continue
            if file_path.suffix not in source_extensions:
                continue

            # Skip excluded directories
            if any(part in _SKIP_DIRS for part in file_path.parts):
                continue

            # Skip large files
            try:
                if file_path.stat().st_size > _MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            # Scan file content
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                await self._scan_file_content(file_path, content, profile)
            except Exception as e:
                logger.debug("Error reading file %s: %s", file_path, e)

    async def _scan_file_content(
        self, file_path: Path, content: str, profile: LLMUsageProfile
    ) -> None:
        """Scan a single file's content for LLM usage.

        Args:
            file_path: Path to the file.
            content: File content.
            profile: Profile to populate with findings.
        """
        lines = content.splitlines()

        for line_num, line in enumerate(lines, start=1):
            # Check for SDK imports
            for provider, patterns in self._compiled_patterns.items():
                for pattern in patterns:
                    if pattern.search(line):
                        # Extract context (3 lines before and after)
                        start = max(0, line_num - 4)
                        end = min(len(lines), line_num + 3)
                        context = "\n".join(lines[start:end])

                        location = LLMUsageLocation(
                            file_path=(
                                file_path.relative_to(Path.cwd())
                                if file_path.is_relative_to(Path.cwd())
                                else file_path
                            ),
                            line_number=line_num,
                            usage_type="import",
                            provider=provider,
                            context=context,
                        )
                        profile.add_location(location)

            # Check for HTTP endpoint calls
            for provider, patterns in self._compiled_endpoints.items():
                for pattern in patterns:
                    match = pattern.search(line)
                    if match:
                        start = max(0, line_num - 4)
                        end = min(len(lines), line_num + 3)
                        context = "\n".join(lines[start:end])

                        location = LLMUsageLocation(
                            file_path=(
                                file_path.relative_to(Path.cwd())
                                if file_path.is_relative_to(Path.cwd())
                                else file_path
                            ),
                            line_number=line_num,
                            usage_type="http_call",
                            provider=provider,
                            endpoint_url=match.group(0),
                            context=context,
                        )
                        profile.add_location(location)

    async def _scan_prompt_files(self, root_path: Path, profile: LLMUsageProfile) -> None:
        """Scan for prompt template files.

        Args:
            root_path: Project root directory.
            profile: Profile to populate with findings.
        """
        for pattern in self._PROMPT_FILE_PATTERNS:
            # Use rglob for simple patterns
            if "**/" in pattern:
                glob_pattern = pattern.replace("**/", "")
                for file_path in root_path.rglob(glob_pattern):
                    if file_path.is_file() and not any(
                        part in _SKIP_DIRS for part in file_path.parts
                    ):
                        location = LLMUsageLocation(
                            file_path=(
                                file_path.relative_to(Path.cwd())
                                if file_path.is_relative_to(Path.cwd())
                                else file_path
                            ),
                            line_number=1,
                            usage_type="prompt_template",
                            provider="generic",  # Can't determine provider from template file alone
                            context=f"Prompt template file: {file_path.name}",
                        )
                        profile.add_location(location)

    def generate_drift_test_candidates(self, profile: LLMUsageProfile) -> list[dict[str, Any]]:
        """Map detected LLM usage to drift test candidates (task 3.13.2).

        Args:
            profile: LLM usage profile from detection.

        Returns:
            List of drift test candidate specifications.
        """
        candidates = []

        # Group locations by file and function
        for location in profile.locations:
            if location.usage_type in ("import", "http_call"):
                # Try to extract function name from context
                function_name = self._extract_function_name(location.context)

                candidate = {
                    "name": f"{location.provider} integration in {location.file_path.name}",
                    "file": str(location.file_path),
                    "line": location.line_number,
                    "provider": location.provider,
                    "function": function_name,
                    "endpoint": location.endpoint_url,
                    "suggested_type": "semantic",  # Default to semantic comparison
                }
                candidates.append(candidate)

        return candidates

    def _extract_function_name(self, context: str) -> str | None:
        """Extract function name from code context.

        Args:
            context: Code snippet.

        Returns:
            Function name if found, None otherwise.
        """
        # Python function pattern
        py_match = re.search(r"def\s+(\w+)\s*\(", context)
        if py_match:
            return py_match.group(1)

        # JavaScript/TypeScript function pattern
        js_match = re.search(r"(?:function\s+(\w+)|const\s+(\w+)\s*=)", context)
        if js_match:
            return js_match.group(1) or js_match.group(2)

        return None

    def generate_drift_test_skeleton(
        self, candidates: Sequence[dict[str, Any]], output_path: Path
    ) -> str:
        """Auto-generate drift test skeleton YAML (task 3.13.3).

        Args:
            candidates: List of drift test candidates.
            output_path: Path to write the drift test YAML.

        Returns:
            Generated YAML content.
        """
        tests = []

        for i, candidate in enumerate(candidates):
            test_id = f"llm_test_{i + 1}"
            test_spec = {
                "id": test_id,
                "name": candidate["name"],
                "enabled": True,
                "endpoint": {
                    "type": "function",
                    "module": str(candidate["file"]).replace("/", ".").replace(".py", ""),
                    "function": candidate.get("function", "unknown"),
                },
                "comparison": {
                    "type": candidate["suggested_type"],
                    "threshold": 0.85,  # Default semantic similarity threshold
                },
                "metadata": {
                    "provider": candidate["provider"],
                    "source_file": candidate["file"],
                    "source_line": candidate["line"],
                    "auto_generated": True,
                },
            }
            tests.append(test_spec)

        output_data = {
            "version": "1.0",
            "tests": tests,
        }

        # Write to file
        yaml_content = yaml.dump(output_data, default_flow_style=False, sort_keys=False)

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(yaml_content, encoding="utf-8")
            logger.info("Generated drift test skeleton at %s", output_path)

        return yaml_content
