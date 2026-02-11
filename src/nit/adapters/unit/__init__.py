"""Unit test framework adapters."""

from nit.adapters.unit.cargo_test_adapter import CargoTestAdapter
from nit.adapters.unit.catch2_adapter import Catch2Adapter
from nit.adapters.unit.go_test_adapter import GoTestAdapter
from nit.adapters.unit.gtest_adapter import GTestAdapter
from nit.adapters.unit.junit5_adapter import JUnit5Adapter
from nit.adapters.unit.pytest_adapter import PytestAdapter
from nit.adapters.unit.testify_adapter import TestifyAdapter
from nit.adapters.unit.vitest_adapter import VitestAdapter
from nit.adapters.unit.xunit_adapter import XUnitAdapter

__all__ = [
    "CargoTestAdapter",
    "Catch2Adapter",
    "GTestAdapter",
    "GoTestAdapter",
    "JUnit5Adapter",
    "PytestAdapter",
    "TestifyAdapter",
    "VitestAdapter",
    "XUnitAdapter",
]
