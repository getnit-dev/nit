"""Adapter registry — auto-discovery and selection of framework adapters.

The registry scans available adapters at runtime and provides methods
to select the appropriate adapter(s) based on a project profile.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

import nit.adapters.docs as docs_package
import nit.adapters.e2e as e2e_package
import nit.adapters.mutation as mutation_package
import nit.adapters.unit as unit_package

if TYPE_CHECKING:
    from nit.models.profile import ProjectProfile

from nit.adapters.base import DocFrameworkAdapter, TestFrameworkAdapter
from nit.adapters.mutation.base import MutationTestingAdapter
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
        self._mutation_adapters: dict[str, type[MutationTestingAdapter]] = {}
        self._discover_adapters()

    def _discover_adapters(self) -> None:
        """Discover all adapter classes by scanning the adapters package.

        Scans the ``nit.adapters.unit`` subpackage for unit test adapters,
        ``nit.adapters.e2e`` for E2E test adapters,
        ``nit.adapters.docs`` for documentation adapters, and
        ``nit.adapters.mutation`` for mutation testing adapters.

        Also discovers adapters registered via Python entry points for
        community-contributed adapter packages.
        """
        # Discover built-in adapters from nit package
        self._discover_test_adapters()
        self._discover_e2e_adapters()
        self._discover_doc_adapters()
        self._discover_mutation_adapters()

        # Discover external adapters via entry points
        self._discover_entry_point_adapters()

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

    def _discover_mutation_adapters(self) -> None:
        """Scan ``nit.adapters.mutation`` for ``MutationTestingAdapter`` subclasses."""
        try:
            for _, module_name, _ in pkgutil.iter_modules(mutation_package.__path__):
                if module_name.startswith("_") or not module_name.endswith("_adapter"):
                    continue

                try:
                    module = importlib.import_module(f"nit.adapters.mutation.{module_name}")
                    self._register_adapters_from_module(module, "mutation")
                except Exception as exc:
                    logger.warning(
                        "Failed to import mutation adapter module %s: %s",
                        module_name,
                        exc,
                    )
        except (ImportError, AttributeError) as exc:
            logger.debug("No mutation adapters package found: %s", exc)

    def _register_adapters_from_module(self, module: object, adapter_type: str) -> None:
        """Register all adapter classes found in *module*.

        Args:
            module: The Python module to scan for adapter classes.
            adapter_type: One of ``"test"``, ``"doc"``, or ``"mutation"``.
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
            elif adapter_type == "mutation":
                if not issubclass(attr, MutationTestingAdapter):
                    continue
                if attr is MutationTestingAdapter:
                    continue
                try:
                    mut_adapter_class: type[MutationTestingAdapter] = attr
                    mut_instance = mut_adapter_class()
                    adapter_name = mut_instance.name
                    self._mutation_adapters[adapter_name] = mut_adapter_class
                    logger.debug("Registered mutation adapter: %s", adapter_name)
                except Exception as exc:
                    logger.warning(
                        "Failed to instantiate mutation adapter %s: %s",
                        attr_name,
                        exc,
                    )

    def _discover_entry_point_adapters(self) -> None:
        """Discover adapters registered via Python entry points.

        Scans four entry point groups:
        - ``nit.adapters.unit`` for unit/integration test adapters
        - ``nit.adapters.e2e`` for E2E test adapters
        - ``nit.adapters.docs`` for documentation adapters
        - ``nit.adapters.mutation`` for mutation testing adapters

        External packages can register adapters by adding entry points
        in their ``pyproject.toml`` or ``setup.py``.
        """
        # Discover unit test adapters from entry points
        try:
            for entry_point in importlib.metadata.entry_points(group="nit.adapters.unit"):
                self._load_entry_point_adapter(entry_point, "test")
        except Exception as exc:
            logger.debug("Failed to load entry points for nit.adapters.unit: %s", exc)

        # Discover E2E test adapters from entry points
        try:
            for entry_point in importlib.metadata.entry_points(group="nit.adapters.e2e"):
                self._load_entry_point_adapter(entry_point, "test")
        except Exception as exc:
            logger.debug("Failed to load entry points for nit.adapters.e2e: %s", exc)

        # Discover doc adapters from entry points
        try:
            for entry_point in importlib.metadata.entry_points(group="nit.adapters.docs"):
                self._load_entry_point_adapter(entry_point, "doc")
        except Exception as exc:
            logger.debug("Failed to load entry points for nit.adapters.docs: %s", exc)

        # Discover mutation adapters from entry points
        try:
            for entry_point in importlib.metadata.entry_points(group="nit.adapters.mutation"):
                self._load_entry_point_adapter(entry_point, "mutation")
        except Exception as exc:
            logger.debug("Failed to load entry points for nit.adapters.mutation: %s", exc)

    def _load_entry_point_adapter(
        self, entry_point: importlib.metadata.EntryPoint, adapter_type: str
    ) -> None:
        """Load and register an adapter from an entry point.

        Args:
            entry_point: The entry point to load.
            adapter_type: One of ``"test"``, ``"doc"``, or ``"mutation"``.
        """
        try:
            # Load the adapter class from the entry point
            adapter_class = entry_point.load()

            # Verify it's a class
            if not isinstance(adapter_class, type):
                logger.warning(
                    "Entry point %s does not refer to a class: %s",
                    entry_point.name,
                    adapter_class,
                )
                return

            # Register based on adapter type
            if adapter_type == "test":
                if not issubclass(adapter_class, TestFrameworkAdapter):
                    logger.warning(
                        "Entry point %s does not refer to a TestFrameworkAdapter: %s",
                        entry_point.name,
                        adapter_class,
                    )
                    return

                # Instantiate to get the name
                try:
                    test_instance = adapter_class()
                    adapter_name = test_instance.name

                    # Avoid overwriting built-in adapters
                    if adapter_name in self._test_adapters:
                        logger.warning(
                            "Test adapter %s from entry point %s conflicts with existing "
                            "adapter, skipping",
                            adapter_name,
                            entry_point.name,
                        )
                        return

                    self._test_adapters[adapter_name] = adapter_class
                    logger.info(
                        "Registered test adapter %s from entry point %s",
                        adapter_name,
                        entry_point.name,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to instantiate test adapter from entry point %s: %s",
                        entry_point.name,
                        exc,
                    )

            elif adapter_type == "doc":
                if not issubclass(adapter_class, DocFrameworkAdapter):
                    logger.warning(
                        "Entry point %s does not refer to a DocFrameworkAdapter: %s",
                        entry_point.name,
                        adapter_class,
                    )
                    return

                # Instantiate to get the name
                try:
                    doc_instance = adapter_class()
                    adapter_name = doc_instance.name

                    # Avoid overwriting built-in adapters
                    if adapter_name in self._doc_adapters:
                        logger.warning(
                            "Doc adapter %s from entry point %s conflicts with existing "
                            "adapter, skipping",
                            adapter_name,
                            entry_point.name,
                        )
                        return

                    self._doc_adapters[adapter_name] = adapter_class
                    logger.info(
                        "Registered doc adapter %s from entry point %s",
                        adapter_name,
                        entry_point.name,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to instantiate doc adapter from entry point %s: %s",
                        entry_point.name,
                        exc,
                    )

            elif adapter_type == "mutation":
                if not issubclass(adapter_class, MutationTestingAdapter):
                    logger.warning(
                        "Entry point %s does not refer to a MutationTestingAdapter: %s",
                        entry_point.name,
                        adapter_class,
                    )
                    return

                try:
                    mut_instance = adapter_class()
                    adapter_name = mut_instance.name

                    if adapter_name in self._mutation_adapters:
                        logger.warning(
                            "Mutation adapter %s from entry point %s conflicts with "
                            "existing adapter, skipping",
                            adapter_name,
                            entry_point.name,
                        )
                        return

                    self._mutation_adapters[adapter_name] = adapter_class
                    logger.info(
                        "Registered mutation adapter %s from entry point %s",
                        adapter_name,
                        entry_point.name,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to instantiate mutation adapter from entry point %s: %s",
                        entry_point.name,
                        exc,
                    )

        except Exception as exc:
            logger.warning(
                "Failed to load entry point %s: %s",
                entry_point.name,
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

    def get_mutation_adapter(self, name: str) -> MutationTestingAdapter | None:
        """Get a mutation testing adapter by name.

        Args:
            name: The tool name (e.g. ``"stryker"``, ``"mutmut"``, ``"pitest"``).

        Returns:
            An instance of the mutation adapter, or ``None`` if not found.
        """
        adapter_class = self._mutation_adapters.get(name)
        if adapter_class is None:
            return None
        try:
            return adapter_class()
        except Exception as exc:
            logger.error("Failed to instantiate mutation adapter %s: %s", name, exc)
            return None

    def list_test_adapters(self) -> list[str]:
        """Return a list of all registered test adapter names."""
        return list(self._test_adapters.keys())

    def list_doc_adapters(self) -> list[str]:
        """Return a list of all registered doc adapter names."""
        return list(self._doc_adapters.keys())

    def list_mutation_adapters(self) -> list[str]:
        """Return a list of all registered mutation adapter names."""
        return list(self._mutation_adapters.keys())

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
