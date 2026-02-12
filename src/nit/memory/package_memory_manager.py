"""Manager for per-package memory in monorepos."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nit.memory.package_memory import PackageMemory

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class PackageMemoryManager:
    """Manages per-package memory files in .nit/memory/packages/."""

    def __init__(self, project_root: Path) -> None:
        """Initialize package memory manager.

        Args:
            project_root: Root directory of the project.
        """
        self.project_root = project_root
        self.packages_dir = project_root / ".nit" / "memory" / "packages"
        self._package_memories: dict[str, PackageMemory] = {}

        # Ensure packages directory exists
        self.packages_dir.mkdir(parents=True, exist_ok=True)

    def get_package_memory(self, package_name: str) -> PackageMemory:
        """Get or create memory for a specific package.

        Args:
            package_name: Name of the package.

        Returns:
            PackageMemory instance for the package.
        """
        if package_name not in self._package_memories:
            # Create memory - PackageMemory expects project root, not memory dir
            memory = PackageMemory(self.project_root, package_name)
            self._package_memories[package_name] = memory

        return self._package_memories[package_name]

    def list_packages(self) -> list[str]:
        """List all packages that have memory files.

        Returns:
            List of package names.
        """
        packages: list[str] = []

        if not self.packages_dir.exists():
            return packages

        # Look for package_*.json files
        for file_path in self.packages_dir.glob("package_*.json"):
            # Extract package name from filename
            # Format: package_{sanitized_name}.json
            name = file_path.stem.replace("package_", "", 1)
            # Un-sanitize the name (replace _ with /)
            name = name.replace("_", "/")
            packages.append(name)

        return packages

    def clear_package_memory(self, package_name: str) -> None:
        """Clear memory for a specific package.

        Args:
            package_name: Name of the package.
        """
        if package_name in self._package_memories:
            self._package_memories[package_name].clear()
            del self._package_memories[package_name]

    def clear_all_package_memories(self) -> None:
        """Clear all package memories."""
        for package_name in list(self._package_memories.keys()):
            self.clear_package_memory(package_name)
