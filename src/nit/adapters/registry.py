"""Adapter registry — auto-discovery and selection of framework adapters.

The registry scans available adapters at runtime and provides methods
to select the appropriate adapter(s) based on a project profile.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

import nit.adapters.docs as docs_package
import nit.adapters.e2e as e2e_package
import nit.adapters.unit as unit_package

if TYPE_CHECKING:
    from nit.adapters.base import DocFrameworkAdapter, TestFrameworkAdapter
    from nit.models.profile import ProjectProfile

from nit.adapters.base import DocFrameworkAdapter, TestFrameworkAdapter
from nit.agents.detectors.signals import FrameworkCategory

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """Registry for discovering and selecting framework adapters.

    Automatically discovers all available adapters by scanning the
    ``nit.adapters`` package structure. Provides methods to select
    the correct adapter(s) for a given project profile.
    """

    def __init__(self) -> None:
        """Initialize the adapter registry and discover all available adapters."""
        self._test_adapters: dict[str, type[TestFrameworkAdapter]] = {}
        self._doc_adapters: dict[str, type[DocFrameworkAdapter]] = {}
        self._discover_adapters()

    def _discover_adapters(self) -> None:
        """Discover all adapter classes by scanning the adapters package.

        Scans the ``nit.adapters.unit`` subpackage for unit test adapters,
        ``nit.adapters.e2e`` for E2E test adapters, and
        ``nit.adapters.docs`` for documentation adapters.
        """
        self._discover_test_adapters()
        self._discover_e2e_adapters()
        self._discover_doc_adapters()

    def _discover_test_adapters(self) -> None:
        """Scan ``nit.adapters.unit`` for ``TestFrameworkAdapter`` subclasses."""
        try:
            for _, module_name, _ in pkgutil.iter_modules(unit_package.__path__):
                # Skip __init__ and non-adapter modules
                if module_name.startswith("_") or not module_name.endswith("_adapter"):
                    continue

                try:
                    module = importlib.import_module(f"nit.adapters.unit.{module_name}")
                    self._register_adapters_from_module(module, "test")
                except Exception as exc:
                    logger.warning(
                        "Failed to import adapter module %s: %s",
                        module_name,
                        exc,
                    )
        except (ImportError, AttributeError) as exc:
            logger.warning("Failed to import nit.adapters.unit package: %s", exc)

    def _discover_e2e_adapters(self) -> None:
        """Scan ``nit.adapters.e2e`` for ``TestFrameworkAdapter`` subclasses."""
        try:
            for _, module_name, _ in pkgutil.iter_modules(e2e_package.__path__):
                # Skip __init__ and non-adapter modules
                if module_name.startswith("_") or not module_name.endswith("_adapter"):
                    continue

                try:
                    module = importlib.import_module(f"nit.adapters.e2e.{module_name}")
                    self._register_adapters_from_module(module, "test")
                except Exception as exc:
                    logger.warning(
                        "Failed to import adapter module %s: %s",
                        module_name,
                        exc,
                    )
        except (ImportError, AttributeError) as exc:
            logger.warning("Failed to import nit.adapters.e2e package: %s", exc)

    def _discover_doc_adapters(self) -> None:
        """Scan ``nit.adapters.docs`` for ``DocFrameworkAdapter`` subclasses."""
        try:
            for _, module_name, _ in pkgutil.iter_modules(docs_package.__path__):
                # Skip __init__ and non-adapter modules
                if module_name.startswith("_") or not module_name.endswith("_adapter"):
                    continue

                try:
                    module = importlib.import_module(f"nit.adapters.docs.{module_name}")
                    self._register_adapters_from_module(module, "doc")
                except Exception as exc:
                    logger.warning(
                        "Failed to import adapter module %s: %s",
                        module_name,
                        exc,
                    )
        except (ImportError, AttributeError) as exc:
            logger.debug("No doc adapters package found: %s", exc)

    def _register_adapters_from_module(self, module: object, adapter_type: str) -> None:
        """Register all adapter classes found in *module*.

        Args:
            module: The Python module to scan for adapter classes.
            adapter_type: Either ``"test"`` or ``"doc"``.
        """
        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)
            if not isinstance(attr, type):
                continue

            # Check if it's a concrete adapter class (not the base class)
            if adapter_type == "test":
                if not issubclass(attr, TestFrameworkAdapter):
                    continue
                if attr is TestFrameworkAdapter:
                    continue
                # Instantiate to get the name
                try:
                    test_adapter_class: type[TestFrameworkAdapter] = attr
                    test_instance = test_adapter_class()
                    adapter_name = test_instance.name
                    self._test_adapters[adapter_name] = test_adapter_class
                    logger.debug("Registered test adapter: %s", adapter_name)
                except Exception as exc:
                    logger.warning(
                        "Failed to instantiate adapter %s: %s",
                        attr_name,
                        exc,
                    )
            elif adapter_type == "doc":
                if not issubclass(attr, DocFrameworkAdapter):
                    continue
                if attr is DocFrameworkAdapter:
                    continue
                try:
                    doc_adapter_class: type[DocFrameworkAdapter] = attr
                    doc_instance = doc_adapter_class()
                    adapter_name = doc_instance.name
                    self._doc_adapters[adapter_name] = doc_adapter_class
                    logger.debug("Registered doc adapter: %s", adapter_name)
                except Exception as exc:
                    logger.warning(
                        "Failed to instantiate adapter %s: %s",
                        attr_name,
                        exc,
                    )

    def get_test_adapter(self, name: str) -> TestFrameworkAdapter | None:
        """Get a test adapter by name.

        Args:
            name: The framework name (e.g. ``"vitest"``, ``"pytest"``).

        Returns:
            An instance of the test adapter, or ``None`` if not found.
        """
        adapter_class = self._test_adapters.get(name)
        if adapter_class is None:
            return None
        try:
            return adapter_class()
        except Exception as exc:
            logger.error("Failed to instantiate test adapter %s: %s", name, exc)
            return None

    def get_doc_adapter(self, name: str) -> DocFrameworkAdapter | None:
        """Get a documentation adapter by name.

        Args:
            name: The framework name (e.g. ``"typedoc"``, ``"sphinx"``).

        Returns:
            An instance of the doc adapter, or ``None`` if not found.
        """
        adapter_class = self._doc_adapters.get(name)
        if adapter_class is None:
            return None
        try:
            return adapter_class()
        except Exception as exc:
            logger.error("Failed to instantiate doc adapter %s: %s", name, exc)
            return None

    def list_test_adapters(self) -> list[str]:
        """Return a list of all registered test adapter names."""
        return list(self._test_adapters.keys())

    def list_doc_adapters(self) -> list[str]:
        """Return a list of all registered doc adapter names."""
        return list(self._doc_adapters.keys())

    def select_adapters_for_profile(
        self,
        profile: ProjectProfile,
    ) -> dict[str, list[TestFrameworkAdapter | DocFrameworkAdapter]]:
        """Select appropriate adapters for the given project profile.

        Analyzes the detected frameworks in the profile and returns
        matching adapters for each package.

        Args:
            profile: The project profile with detected frameworks.

        Returns:
            A dictionary mapping package paths to lists of adapters.
            For single-repo projects, the key is the project root.
        """
        result: dict[str, list[TestFrameworkAdapter | DocFrameworkAdapter]] = {}

        # For each package in the profile, find matching adapters
        if not profile.packages:
            # Single-repo case: treat root as the only package
            package_path = profile.root
            result[package_path] = self._select_adapters_for_package(
                Path(package_path),
                profile,
            )
        else:
            # Monorepo case: process each package
            for pkg in profile.packages:
                package_path = pkg.path
                result[package_path] = self._select_adapters_for_package(
                    Path(package_path),
                    profile,
                )

        return result

    def _select_adapters_for_package(
        self,
        package_path: Path,
        profile: ProjectProfile,
    ) -> list[TestFrameworkAdapter | DocFrameworkAdapter]:
        """Select adapters for a single package.

        Args:
            package_path: Path to the package directory.
            profile: The project profile.

        Returns:
            A list of adapter instances that match the detected frameworks.
        """
        adapters: list[TestFrameworkAdapter | DocFrameworkAdapter] = []

        # Get unit test frameworks
        unit_frameworks = profile.frameworks_by_category(FrameworkCategory.UNIT_TEST)
        for framework in unit_frameworks:
            test_adapter = self.get_test_adapter(framework.name)
            # Verify the adapter actually detects the framework in this package
            if test_adapter is not None and test_adapter.detect(package_path):
                adapters.append(test_adapter)
                logger.debug(
                    "Selected test adapter %s for package %s",
                    framework.name,
                    package_path,
                )

        # Get doc frameworks
        doc_frameworks = profile.frameworks_by_category(FrameworkCategory.DOC)
        for framework in doc_frameworks:
            doc_adapter = self.get_doc_adapter(framework.name)
            # Verify the adapter actually detects the framework in this package
            if doc_adapter is not None and doc_adapter.detect(package_path):
                adapters.append(doc_adapter)
                logger.debug(
                    "Selected doc adapter %s for package %s",
                    framework.name,
                    package_path,
                )

        return adapters


class _RegistrySingleton:
    """Singleton holder for the adapter registry."""

    _instance: AdapterRegistry | None = None

    @classmethod
    def get(cls) -> AdapterRegistry:
        """Get the global adapter registry instance.

        Creates the registry on first call and caches it for subsequent calls.

        Returns:
            The global ``AdapterRegistry`` instance.
        """
        if cls._instance is None:
            cls._instance = AdapterRegistry()
        return cls._instance


def get_registry() -> AdapterRegistry:
    """Get the global adapter registry instance.

    Creates the registry on first call and caches it for subsequent calls.

    Returns:
        The global ``AdapterRegistry`` instance.
    """
    return _RegistrySingleton.get()
