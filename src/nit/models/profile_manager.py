"""Profile manager for handling per-package detection in monorepos."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from nit.agents.detectors.signals import DetectedFramework
    from nit.agents.detectors.stack import LanguageInfo
    from nit.models.profile import ProjectProfile

from nit.agents.detectors.framework import detect_frameworks
from nit.agents.detectors.stack import detect_languages

logger = logging.getLogger(__name__)


@dataclass
class PackageProfile:
    """Profile for a single package in a monorepo."""

    name: str
    """Package name."""
    path: str
    """Path relative to workspace root."""
    languages: list[LanguageInfo] = field(default_factory=list)
    """Languages detected in this package."""
    frameworks: list[DetectedFramework] = field(default_factory=list)
    """Frameworks detected in this package."""
    dependencies: list[str] = field(default_factory=list)
    """Internal package dependencies."""

    def to_dict(self) -> dict[str, object]:
        """Serialize to dict."""
        return {
            "name": self.name,
            "path": self.path,
            "languages": [
                {
                    "language": li.language,
                    "file_count": li.file_count,
                    "confidence": li.confidence,
                    "extensions": li.extensions,
                }
                for li in self.languages
            ],
            "frameworks": [
                {
                    "name": fw.name,
                    "language": fw.language,
                    "category": fw.category.value,
                    "confidence": fw.confidence,
                }
                for fw in self.frameworks
            ],
            "dependencies": self.dependencies,
        }


class ProfileManager:
    """Manager for building and caching per-package profiles in monorepos."""

    def __init__(self, project_root: Path) -> None:
        """Initialize profile manager.

        Args:
            project_root: Root directory of the project.
        """
        self.project_root = project_root
        self._package_profiles: dict[str, PackageProfile] = {}

    def build_project_profile(
        self,
        project_profile: ProjectProfile,
    ) -> dict[str, PackageProfile]:
        """Build per-package profiles for all packages in a monorepo.

        Args:
            project_profile: The overall project profile with workspace info.

        Returns:
            Dict mapping package name to PackageProfile.
        """
        if not project_profile.is_monorepo:
            # Single-repo: create one package profile for the root
            logger.info("Single-repo detected, creating root package profile")
            root_profile = self._detect_package(
                package_name=project_profile.packages[0].name,
                package_path=".",
                dependencies=project_profile.packages[0].dependencies,
            )
            self._package_profiles = {root_profile.name: root_profile}
            return self._package_profiles

        # Monorepo: detect each package independently
        logger.info("Monorepo detected with %d packages", len(project_profile.packages))
        for pkg_info in project_profile.packages:
            logger.info("Detecting profile for package: %s (%s)", pkg_info.name, pkg_info.path)
            pkg_profile = self._detect_package(
                package_name=pkg_info.name,
                package_path=pkg_info.path,
                dependencies=pkg_info.dependencies,
            )
            self._package_profiles[pkg_info.name] = pkg_profile

        return self._package_profiles

    def _detect_package(
        self,
        package_name: str,
        package_path: str,
        dependencies: list[str],
    ) -> PackageProfile:
        """Run detection for a single package.

        Args:
            package_name: Name of the package.
            package_path: Path relative to project root.
            dependencies: Internal package dependencies.

        Returns:
            PackageProfile with detected languages and frameworks.
        """
        # Resolve package directory
        pkg_dir = self.project_root if package_path == "." else self.project_root / package_path

        if not pkg_dir.is_dir():
            logger.warning("Package directory does not exist: %s", pkg_dir)
            return PackageProfile(
                name=package_name,
                path=package_path,
                dependencies=dependencies,
            )

        # Run language detection for this package
        try:
            lang_profile = detect_languages(str(pkg_dir))
            languages = lang_profile.languages
        except Exception as e:
            logger.error("Language detection failed for %s: %s", package_name, e)
            languages = []

        # Run framework detection for this package
        try:
            fw_profile = detect_frameworks(str(pkg_dir))
            frameworks = fw_profile.frameworks
        except Exception as e:
            logger.error("Framework detection failed for %s: %s", package_name, e)
            frameworks = []

        return PackageProfile(
            name=package_name,
            path=package_path,
            languages=languages,
            frameworks=frameworks,
            dependencies=dependencies,
        )

    def get_package_profile(self, package_name: str) -> PackageProfile | None:
        """Get profile for a specific package.

        Args:
            package_name: Name of the package.

        Returns:
            PackageProfile if found, None otherwise.
        """
        return self._package_profiles.get(package_name)

    def get_all_package_profiles(self) -> dict[str, PackageProfile]:
        """Get all package profiles.

        Returns:
            Dict mapping package name to PackageProfile.
        """
        return self._package_profiles

    def filter_packages_by_path(self, package_path: str) -> list[PackageProfile]:
        """Filter packages by path prefix.

        Args:
            package_path: Path prefix to match.

        Returns:
            List of matching PackageProfiles.
        """
        return [
            profile
            for profile in self._package_profiles.values()
            if profile.path == package_path or profile.path.startswith(f"{package_path}/")
        ]
