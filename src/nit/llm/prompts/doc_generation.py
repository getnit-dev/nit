"""Doc generation prompt templates for various documentation frameworks.

This module provides prompt templates for generating and updating documentation
(docstrings, comments, API docs) in framework-native formats (task 4.1.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.llm.engine import LLMMessage
from nit.llm.prompts.base import PromptSection, PromptTemplate

if TYPE_CHECKING:
    from nit.llm.context import AssembledContext


@dataclass
class DocChange:
    """Represents a documentation change that needs to be made."""

    function_name: str
    """Name of the function/class/method."""

    change_type: str
    """Type of change: 'new', 'modified', 'removed'."""

    signature: str
    """Current signature of the function/method."""

    existing_doc: str | None = None
    """Existing docstring/comment, if any."""


@dataclass
class DocGenerationContext:
    """Extended context for documentation generation."""

    changes: list[DocChange]
    """List of documentation changes to generate."""

    doc_framework: str
    """Documentation framework (e.g., 'sphinx', 'typedoc', 'doxygen', 'jsdoc')."""

    language: str
    """Programming language (e.g., 'python', 'typescript', 'cpp')."""

    source_path: str
    """Path to the source file."""

    source_code: str
    """Full source code."""

    style_preference: str = ""
    """Docstring style preference (e.g., 'google', 'numpy' for Python)."""


def build_doc_generation_messages(context: DocGenerationContext) -> list[LLMMessage]:
    """Build LLM messages for documentation generation.

    Args:
        context: Documentation generation context with changes and framework info.

    Returns:
        List of LLM messages (system + user).
    """
    system_msg = _build_system_instruction(context)
    user_msg = _build_user_message(context)

    return [
        LLMMessage(role="system", content=system_msg),
        LLMMessage(role="user", content=user_msg),
    ]


def _build_system_instruction(context: DocGenerationContext) -> str:
    """Build system-level instruction for doc generation."""
    framework_instructions = {
        "sphinx": (
            "You generate Google-style or NumPy-style Python docstrings for Sphinx documentation.\n"
            "Use triple-quoted docstrings with proper formatting:\n"
            '"""Brief description.\n\n'
            "Extended description if needed.\n\n"
            "Args:\n"
            "    param1: Description.\n"
            "    param2: Description.\n\n"
            "Returns:\n"
            "    Description of return value.\n\n"
            "Raises:\n"
            "    ExceptionType: When this happens.\n"
            '"""'
        ),
        "typedoc": (
            "You generate TSDoc-style comments for TypeDoc documentation.\n"
            "Use JSDoc-style comments with TypeDoc tags:\n"
            "/**\n"
            " * Brief description.\n"
            " *\n"
            " * Extended description if needed.\n"
            " *\n"
            " * @param param1 - Description.\n"
            " * @param param2 - Description.\n"
            " * @returns Description of return value.\n"
            " * @throws {ErrorType} When this happens.\n"
            " */"
        ),
        "jsdoc": (
            "You generate JSDoc comments for JavaScript/TypeScript documentation.\n"
            "Use standard JSDoc format:\n"
            "/**\n"
            " * Brief description.\n"
            " *\n"
            " * @param {type} param1 - Description.\n"
            " * @param {type} param2 - Description.\n"
            " * @returns {type} Description of return value.\n"
            " */"
        ),
        "doxygen": (
            "You generate Doxygen-style comments for C/C++ documentation.\n"
            "Use Doxygen format with proper tags:\n"
            "/**\n"
            " * @brief Brief description.\n"
            " *\n"
            " * Extended description if needed.\n"
            " *\n"
            " * @param param1 Description.\n"
            " * @param param2 Description.\n"
            " * @return Description of return value.\n"
            " * @throws ExceptionType When this happens.\n"
            " */"
        ),
        "godoc": (
            "You generate Go doc comments.\n"
            "Use simple comment blocks above declarations:\n"
            "// FunctionName does something specific.\n"
            "// It may do additional things.\n"
            "//\n"
            "// Parameters:\n"
            "//   - param1: Description\n"
            "//   - param2: Description\n"
            "//\n"
            "// Returns an error if something fails."
        ),
        "rustdoc": (
            "You generate Rust doc comments using markdown.\n"
            "Use triple-slash comments with markdown:\n"
            "/// Brief description.\n"
            "///\n"
            "/// # Arguments\n"
            "///\n"
            "/// * `param1` - Description.\n"
            "/// * `param2` - Description.\n"
            "///\n"
            "/// # Returns\n"
            "///\n"
            "/// Description of return value.\n"
            "///\n"
            "/// # Errors\n"
            "///\n"
            "/// Returns error when..."
        ),
        "mkdocs": (
            "You generate Markdown pages for MkDocs documentation sites.\n"
            "Use standard Markdown with optional MkDocs extensions:\n"
            "# Page Title\n\n"
            "Brief description.\n\n"
            "## Section\n\n"
            "Content with **bold**, *italic*, `code`, and [links](url).\n\n"
            "- Use headers (# ## ###) for structure\n"
            "- Use fenced code blocks with language tags\n"
            "- Use admonitions (!!! note) if the theme supports them"
        ),
    }

    framework_instruction = framework_instructions.get(
        context.doc_framework.lower(),
        "You generate clear, concise documentation comments for code.",
    )

    # Apply style preference override for sphinx (Python)
    if context.style_preference and context.doc_framework.lower() == "sphinx":
        style = context.style_preference.lower()
        if style == "google":
            framework_instruction = (
                "You generate Google-style Python docstrings for Sphinx documentation.\n"
                "Use triple-quoted docstrings with Google format:\n"
                '"""Brief description.\n\n'
                "Args:\n"
                "    param1: Description.\n"
                "    param2: Description.\n\n"
                "Returns:\n"
                "    Description of return value.\n\n"
                "Raises:\n"
                "    ExceptionType: When this happens.\n"
                '"""'
            )
        elif style == "numpy":
            framework_instruction = (
                "You generate NumPy-style Python docstrings for Sphinx documentation.\n"
                "Use triple-quoted docstrings with NumPy format:\n"
                '"""Brief description.\n\n'
                "Parameters\n"
                "----------\n"
                "param1 : type\n"
                "    Description.\n\n"
                "Returns\n"
                "-------\n"
                "type\n"
                "    Description.\n\n"
                "Raises\n"
                "------\n"
                "ExceptionType\n"
                "    When this happens.\n"
                '"""'
            )

    return (
        f"{framework_instruction}\n\n"
        "CRITICAL RULES:\n"
        "1. Generate ONLY the documentation comments - no other code or explanations\n"
        "2. For each function/class, output ONLY the doc comment block\n"
        "3. Match the existing code style and formatting conventions\n"
        "4. Be concise but complete - describe purpose, parameters, return values, and exceptions\n"
        "5. Do not repeat information that is obvious from the function signature\n"
        "6. Focus on 'why' and 'what', not 'how' (the code shows how)\n"
        "7. For modified functions, update the existing documentation to reflect changes\n"
        "8. Output format: one doc block per function, separated by a marker line:\n"
        "   --- FUNCTION: function_name ---\n"
        "   [doc comment]\n"
        "   --- END ---"
    )


def _build_user_message(context: DocGenerationContext) -> str:
    """Build user message with changes to document."""
    sections: list[str] = []

    # File context
    sections.append("## File Context")
    sections.append("")
    sections.append(f"File: {context.source_path}")
    sections.append(f"Language: {context.language}")
    sections.append(f"Documentation Framework: {context.doc_framework}")
    sections.append("")

    # Source code
    sections.append("## Source Code")
    sections.append("")
    sections.append(f"```{context.language}")
    sections.append(context.source_code)
    sections.append("```")
    sections.append("")

    # Changes to document
    sections.append("## Functions/Classes to Document")
    sections.append("")

    for change in context.changes:
        sections.append(f"### {change.function_name}")
        sections.append("")
        sections.append(f"- **Change Type**: {change.change_type}")
        sections.append(f"- **Signature**: `{change.signature}`")

        if change.existing_doc:
            sections.append("- **Existing Documentation**:")
            sections.append("")
            sections.append("```")
            sections.append(change.existing_doc)
            sections.append("```")
        else:
            sections.append("- **Existing Documentation**: None")

        sections.append("")

    # Instructions
    sections.append("## Task")
    sections.append("")
    sections.append(
        "Generate documentation comments for the functions/classes listed above. "
        "For each one, output:"
    )
    sections.append("")
    sections.append("```")
    sections.append("--- FUNCTION: function_name ---")
    sections.append("[your generated doc comment here]")
    sections.append("--- END ---")
    sections.append("```")
    sections.append("")
    sections.append(
        "Remember: Output ONLY the documentation comments, nothing else. "
        "Match the framework's style precisely."
    )

    return "\n".join(sections)


class DocGenerationTemplate(PromptTemplate):
    """Base template for documentation generation."""

    def __init__(self, doc_context: DocGenerationContext) -> None:
        """Initialize template with doc-specific context.

        Args:
            doc_context: Documentation generation context.
        """
        self._doc_context = doc_context

    @property
    def name(self) -> str:
        """Template name."""
        return f"doc_generation_{self._doc_context.doc_framework}"

    def _system_instruction(self, _context: AssembledContext) -> str:
        """Return system instruction (not used, we use direct messages)."""
        return _build_system_instruction(self._doc_context)

    def _build_sections(self, _context: AssembledContext) -> list[PromptSection]:
        """Build prompt sections (not used, we use direct messages)."""
        return []

    def build_messages(self) -> list[LLMMessage]:
        """Build messages directly from doc context.

        Returns:
            List of LLM messages.
        """
        return build_doc_generation_messages(self._doc_context)


def build_mismatch_detection_messages(
    documented_items: list[tuple[str, str, str]],
    language: str,
    doc_framework: str,
    source_code: str,
    source_path: str,
) -> list[LLMMessage]:
    """Build LLM messages for detecting documentation/code semantic mismatches.

    Args:
        documented_items: List of (name, signature, docstring) tuples.
        language: Programming language.
        doc_framework: Documentation framework.
        source_code: Full source code.
        source_path: Path to source file.

    Returns:
        List of LLM messages (system + user).
    """
    system_msg = (
        "You are a documentation accuracy checker. Given source code and existing "
        "documentation, identify semantic mismatches where the documentation does not "
        "accurately describe the code.\n\n"
        "Look for:\n"
        "- Missing parameters not mentioned in the doc\n"
        "- Parameters documented but not in the signature\n"
        "- Incorrect return type/value descriptions\n"
        "- Stale references to removed functionality\n"
        "- Description that contradicts what the code does\n\n"
        "Return a JSON array of mismatches. If no mismatches are found, return [].\n"
        "Each mismatch should have:\n"
        '- "function": the function/class name\n'
        '- "type": one of "missing_param", "extra_param", "wrong_return", '
        '"semantic_drift", "stale_reference"\n'
        '- "description": brief explanation\n'
        '- "severity": "error" or "warning"\n\n'
        "Return ONLY the JSON array, no other text."
    )

    sections: list[str] = [
        f"## File: {source_path}",
        f"Language: {language}, Framework: {doc_framework}",
        "",
        "## Source Code",
        "",
        f"```{language}",
        source_code,
        "```",
        "",
        "## Documented Functions/Classes to Check",
        "",
    ]

    for name, signature, docstring in documented_items:
        sections.append(f"### {name}")
        sections.append(f"Signature: `{signature}`")
        sections.append(f"Documentation:\n```\n{docstring}\n```")
        sections.append("")

    sections.append("Return a JSON array of mismatches found (or [] if none).")

    return [
        LLMMessage(role="system", content=system_msg),
        LLMMessage(role="user", content="\n".join(sections)),
    ]
