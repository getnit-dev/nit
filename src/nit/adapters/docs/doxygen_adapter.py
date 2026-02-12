"""Doxygen adapter for C/C++ documentation generation.

This adapter (task 4.4):
1. Detects Doxygen presence (Doxyfile, Doxyfile.in, or CMake find_package(Doxygen))
2. Generates Doxygen-format comments for undocumented C/C++ functions/classes
3. Builds documentation using the `doxygen` command
4. Validates Doxygen comment syntax (@param, @return, @brief)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nit.adapters.base import DocFrameworkAdapter, ValidationResult
from nit.llm.prompts.doc_generation import DocGenerationContext, DocGenerationTemplate

if TYPE_CHECKING:
    from pathlib import Path

    from nit.llm.prompts.base import PromptTemplate

logger = logging.getLogger(__name__)


@dataclass
class _CommandResult:
    """Result of a subprocess command execution."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    not_found: bool = False

    @property
    def success(self) -> bool:
        """Return True if the command succeeded."""
        return self.returncode == 0 and not self.timed_out and not self.not_found


async def _run_command(cmd: list[str], *, cwd: Path, timeout: float) -> _CommandResult:
    """Run a command and return the result.

    Args:
        cmd: Command and arguments to run.
        cwd: Working directory for the command.
        timeout: Maximum time in seconds to wait for the command.

    Returns:
        CommandResult with stdout, stderr, and return code.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        return _CommandResult(
            returncode=1,
            stdout="",
            stderr=f"Command timed out after {timeout:.1f}s",
            timed_out=True,
        )
    except FileNotFoundError:
        return _CommandResult(
            returncode=127,
            stdout="",
            stderr=f"Command not found: {cmd[0]}",
            not_found=True,
        )

    return _CommandResult(
        returncode=proc.returncode if proc.returncode is not None else 1,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
    )


def _cmake_uses_doxygen(project_path: Path) -> bool:
    """Return True if any CMakeLists.txt under project_path references Doxygen."""
    for path in project_path.rglob("CMakeLists.txt"):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            if "find_package(Doxygen)" in content or "find_package(Doxygen " in content:
                logger.info("Detected Doxygen via CMake find_package(Doxygen) in %s", path)
                return True
        except OSError:
            continue
    return False


class DoxygenAdapter(DocFrameworkAdapter):
    """Adapter for Doxygen documentation generation.

    Doxygen is the standard documentation generator for C/C++ projects,
    using comment blocks with @param, @return, @brief, etc.
    """

    @property
    def name(self) -> str:
        """Framework identifier."""
        return "doxygen"

    @property
    def language(self) -> str:
        """Primary language."""
        return "cpp"

    def detect(self, project_path: Path) -> bool:
        """Return True if Doxygen is present in the project.

        Detection signals (task 4.4.1):
        1. Doxyfile or Doxyfile.in in project root
        2. CMake find_package(Doxygen) in any CMakeLists.txt

        Args:
            project_path: Root of the project.

        Returns:
            True if Doxygen is detected, False otherwise.
        """
        # Check for Doxyfile or Doxyfile.in in project root
        if (project_path / "Doxyfile").exists():
            logger.info("Detected Doxygen via Doxyfile")
            return True
        if (project_path / "Doxyfile.in").exists():
            logger.info("Detected Doxygen via Doxyfile.in")
            return True

        # Check CMake for find_package(Doxygen)
        return _cmake_uses_doxygen(project_path)

    def get_doc_pattern(self) -> list[str]:
        """Return glob patterns for C/C++ source and header files.

        Returns:
            List of glob patterns matching C/C++ files that may contain Doxygen comments.
        """
        return [
            "**/*.h",
            "**/*.hpp",
            "**/*.hxx",
            "**/*.c",
            "**/*.cpp",
            "**/*.cc",
            "**/*.cxx",
            "!**/build/**",
            "!**/Build/**",
            "!**/out/**",
            "!**/cmake-build-*/**",
        ]

    def get_prompt_template(self) -> PromptTemplate:
        """Return the prompt template for generating Doxygen comments.

        Returns:
            A DocGenerationTemplate configured for Doxygen/C++.
        """
        context = DocGenerationContext(
            changes=[],
            doc_framework="doxygen",
            language="cpp",
            source_path="",
            source_code="",
        )
        return DocGenerationTemplate(context)

    async def build_docs(
        self,
        project_path: Path,
        *,
        timeout: float = 120.0,
    ) -> bool:
        """Build documentation using Doxygen (task 4.4.1).

        Executes `doxygen` (with Doxyfile or Doxyfile.in if present).

        Args:
            project_path: Root of the project containing the documentation.
            timeout: Maximum seconds to wait for doc build.

        Returns:
            True if the documentation built successfully, False otherwise.
        """
        logger.info("Building Doxygen documentation in %s", project_path)

        config_path: Path | None = None
        if (project_path / "Doxyfile").exists():
            config_path = project_path / "Doxyfile"
        elif (project_path / "Doxyfile.in").exists():
            config_path = project_path / "Doxyfile.in"

        cmd: list[str] = ["doxygen"]
        if config_path is not None:
            cmd.append(str(config_path))

        result = await _run_command(
            cmd,
            cwd=project_path,
            timeout=timeout,
        )

        if result.success:
            logger.info("Doxygen build succeeded")
            return True

        logger.error("Doxygen build failed: %s", result.stderr)
        return False

    def validate_doc(self, doc_code: str) -> ValidationResult:
        """Validate that a Doxygen comment block is syntactically correct (task 4.4.2).

        Checks for /** ... */ delimiters and common Doxygen tags (@param, @return, @brief).

        Args:
            doc_code: Doxygen comment block to validate.

        Returns:
            ValidationResult with validity status and any errors/warnings.
        """
        errors: list[str] = []
        warnings: list[str] = []

        stripped = doc_code.strip()
        if not stripped.startswith("/**"):
            errors.append("Doxygen comments must start with /**")
        if not stripped.rstrip().endswith("*/"):
            errors.append("Doxygen comments must end with */")

        # Common Doxygen tags (C/C++ style)
        valid_tags = {
            "@param",
            "@return",
            "@returns",
            "@brief",
            "@details",
            "@see",
            "@note",
            "@warning",
            "@deprecated",
            "@todo",
            "@author",
            "@date",
            "@version",
            "@throws",
            "@exception",
            "@pre",
            "@post",
            "@invariant",
            "@code",
            "@endcode",
        }

        # Extract lines and check for @ tags
        lines = doc_code.split("\n")
        for line in lines:
            # Match @tag at word boundary (start of line after optional * and space)
            for match in re.finditer(r"@(\w+)", line):
                tag = "@" + match.group(1)
                if tag not in valid_tags:
                    warnings.append(f"Unknown or non-standard Doxygen tag: {tag}")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
