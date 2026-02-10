"""Integration dependency analyzer — detects integration test candidates.

This module (task 2.11.2):
1. Detects DB calls, HTTP clients, filesystem, message queues via import/call analysis
2. Identifies which functions/methods need integration testing
3. Determines appropriate mocking strategy for each dependency
4. Maps dependencies to test data factory requirements
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from nit.parsing.treesitter import ImportInfo, ParseResult

logger = logging.getLogger(__name__)


class IntegrationDependencyType(Enum):
    """Types of external dependencies requiring integration tests."""

    DATABASE = "database"
    """Database connections (SQL, NoSQL)."""

    HTTP_CLIENT = "http_client"
    """HTTP/REST API clients."""

    FILESYSTEM = "filesystem"
    """File system operations."""

    MESSAGE_QUEUE = "message_queue"
    """Message queues (RabbitMQ, Kafka, Redis, SQS)."""

    CACHE = "cache"
    """Caching systems (Redis, Memcached)."""

    EXTERNAL_API = "external_api"
    """Third-party API SDKs (Stripe, AWS, GCP)."""

    UNKNOWN = "unknown"


# Dependency detection patterns (module name patterns)
DEPENDENCY_PATTERNS = {
    IntegrationDependencyType.DATABASE: [
        # Python
        r"\bsqlalchemy\b",
        r"\bdjango\.db\b",
        r"\bpsycopg\d?\b",
        r"\bmysql\b",
        r"\bpymongo\b",
        r"\bsqlite3\b",
        r"\basyncpg\b",
        r"\baiomysql\b",
        # JavaScript/TypeScript
        r"\bsequelize\b",
        r"\bmongoose\b",
        r"\bprisma\b",
        r"\bdrizzle\b",
        r"\btypeorm\b",
        r"\bknex\b",
        r"\bmongodb\b",
        r"\bmysql2\b",
        r"\bpg\b",
        # Go
        r"\bdatabase/sql\b",
        r"\bgorm\.io\b",
        r"\bmongo-go-driver\b",
        # Java
        r"\bjava\.sql\b",
        r"\bhibernate\b",
        r"\bjdbc\b",
    ],
    IntegrationDependencyType.HTTP_CLIENT: [
        # Python
        r"\brequests\b",
        r"\bhttpx\b",
        r"\baiohttp\b",
        r"\burllib\b",
        # JavaScript/TypeScript
        r"\baxios\b",
        r"\bfetch\b",
        r"\bgot\b",
        r"\bnode-fetch\b",
        r"\bsuperagent\b",
        # Go
        r"\bnet/http\b",
        r"\bresty\b",
        # Java
        r"\bHttpClient\b",
        r"\bOkHttp\b",
        r"\bRestTemplate\b",
    ],
    IntegrationDependencyType.FILESYSTEM: [
        # Python
        r"\bos\b",
        r"\bshutil\b",
        r"\bpathlib\b",
        r"\baiofiles\b",
        # JavaScript/TypeScript
        r"\bfs\b",
        r"\bfs-extra\b",
        r"\bfs/promises\b",
        # Go
        r"\bos\b",
        r"\bio/ioutil\b",
        r"\bio/fs\b",
        # Java
        r"\bjava\.io\b",
        r"\bjava\.nio\b",
    ],
    IntegrationDependencyType.MESSAGE_QUEUE: [
        # Python
        r"\bpika\b",  # RabbitMQ
        r"\bkafka-python\b",
        r"\baiokafka\b",
        r"\bcelery\b",
        r"\bboto3\b.*sqs",
        # JavaScript/TypeScript
        r"\bamqplib\b",
        r"\bkafkajs\b",
        r"\bbull\b",
        r"\bbee-queue\b",
        # Go
        r"\bsarama\b",  # Kafka
        r"\bamqp\b",
        # Java
        r"\bspring-kafka\b",
        r"\bramqp\b",
    ],
    IntegrationDependencyType.CACHE: [
        # Python
        r"\bredis\b",
        r"\baioredis\b",
        r"\bmemcache\b",
        r"\bpymemcache\b",
        # JavaScript/TypeScript
        r"\bioredis\b",
        r"\bnode-cache\b",
        # Go
        r"\bgo-redis\b",
        # Java
        r"\bjedis\b",
        r"\blettuce\b",
    ],
    IntegrationDependencyType.EXTERNAL_API: [
        # Payment processors
        r"\bstripe\b",
        r"\bpaypal\b",
        # Cloud providers
        r"\bboto3\b",  # AWS
        r"\bgoogle-cloud\b",  # GCP
        r"\bazure\b",
        # Communication
        r"\btwilio\b",
        r"\bsendgrid\b",
        r"\bmailgun\b",
    ],
}

# Mocking strategies per dependency type per language
MOCK_STRATEGIES = {
    "python": {
        IntegrationDependencyType.DATABASE: ["unittest.mock", "pytest-mock", "SQLAlchemy mock"],
        IntegrationDependencyType.HTTP_CLIENT: [
            "responses",
            "httpretty",
            "unittest.mock",
        ],
        IntegrationDependencyType.FILESYSTEM: ["pytest tmp_path", "unittest.mock"],
        IntegrationDependencyType.MESSAGE_QUEUE: ["unittest.mock", "fakeredis"],
        IntegrationDependencyType.CACHE: ["fakeredis", "unittest.mock"],
        IntegrationDependencyType.EXTERNAL_API: ["unittest.mock", "responses"],
    },
    "javascript": {
        IntegrationDependencyType.DATABASE: ["jest.mock", "sinon", "mock-knex"],
        IntegrationDependencyType.HTTP_CLIENT: ["msw", "nock", "jest.mock"],
        IntegrationDependencyType.FILESYSTEM: ["mock-fs", "memfs"],
        IntegrationDependencyType.MESSAGE_QUEUE: ["jest.mock", "ioredis-mock"],
        IntegrationDependencyType.CACHE: ["ioredis-mock", "jest.mock"],
        IntegrationDependencyType.EXTERNAL_API: ["msw", "nock"],
    },
    "typescript": {
        IntegrationDependencyType.DATABASE: ["vi.mock", "sinon", "mock-knex"],
        IntegrationDependencyType.HTTP_CLIENT: ["msw", "nock", "vi.mock"],
        IntegrationDependencyType.FILESYSTEM: ["mock-fs", "memfs"],
        IntegrationDependencyType.MESSAGE_QUEUE: ["vi.mock", "ioredis-mock"],
        IntegrationDependencyType.CACHE: ["ioredis-mock", "vi.mock"],
        IntegrationDependencyType.EXTERNAL_API: ["msw", "nock"],
    },
    "go": {
        IntegrationDependencyType.DATABASE: ["sqlmock", "go-sqlmock", "testify/mock"],
        IntegrationDependencyType.HTTP_CLIENT: ["httpmock", "httptest", "gock"],
        IntegrationDependencyType.FILESYSTEM: ["afero", "testify/mock"],
        IntegrationDependencyType.MESSAGE_QUEUE: ["testify/mock"],
        IntegrationDependencyType.CACHE: ["miniredis", "testify/mock"],
        IntegrationDependencyType.EXTERNAL_API: ["httpmock", "testify/mock"],
    },
    "java": {
        IntegrationDependencyType.DATABASE: ["H2 database", "Mockito", "Testcontainers"],
        IntegrationDependencyType.HTTP_CLIENT: ["WireMock", "MockWebServer", "Mockito"],
        IntegrationDependencyType.FILESYSTEM: ["Jimfs", "Mockito"],
        IntegrationDependencyType.MESSAGE_QUEUE: ["Testcontainers", "Mockito"],
        IntegrationDependencyType.CACHE: ["Testcontainers", "Mockito"],
        IntegrationDependencyType.EXTERNAL_API: ["WireMock", "Mockito"],
    },
}


@dataclass
class DetectedDependency:
    """A detected external dependency requiring integration testing."""

    dependency_type: IntegrationDependencyType
    """The type of external dependency."""

    module_name: str
    """The imported module name."""

    pattern_matched: str
    """The regex pattern that matched this dependency."""

    used_in_functions: list[str] = field(default_factory=list)
    """Names of functions using this dependency."""

    mock_strategies: list[str] = field(default_factory=list)
    """Recommended mocking strategies for this dependency."""


@dataclass
class IntegrationDependencyReport:
    """Analysis report of integration testing dependencies in a source file."""

    source_path: Path
    """Path to the analyzed source file."""

    language: str
    """Programming language detected."""

    dependencies: list[DetectedDependency] = field(default_factory=list)
    """All detected external dependencies."""

    needs_integration_tests: bool = False
    """Whether this file needs integration tests."""

    recommended_fixtures: list[str] = field(default_factory=list)
    """Recommended test fixtures/factories based on detected types."""


def detect_integration_dependencies(
    source_path: Path,
    parse_result: ParseResult,
    language: str,
) -> IntegrationDependencyReport:
    """Detect integration testing dependencies in a source file.

    Args:
        source_path: Path to the source file.
        parse_result: Parsed AST result from tree-sitter.
        language: Programming language (python, javascript, typescript, go, java).

    Returns:
        IntegrationDependencyReport with detected dependencies and recommendations.
    """
    logger.debug("Analyzing integration dependencies for %s", source_path)

    report = IntegrationDependencyReport(
        source_path=source_path,
        language=language,
    )

    # Step 1: Analyze imports
    detected: dict[str, DetectedDependency] = {}
    for imp in parse_result.imports:
        dep = _analyze_import(imp)
        if dep:
            detected[dep.module_name] = dep

    # Step 2: Map dependencies to functions that use them
    _map_dependencies_to_functions(detected, parse_result)

    # Step 3: Generate mocking strategies
    for dep in detected.values():
        dep.mock_strategies = _get_mock_strategies(dep.dependency_type, language)

    report.dependencies = list(detected.values())
    report.needs_integration_tests = len(report.dependencies) > 0

    # Step 4: Generate fixture recommendations
    if report.needs_integration_tests:
        report.recommended_fixtures = _generate_fixture_recommendations(
            report.dependencies, language
        )

    logger.info(
        "Found %d integration dependencies in %s",
        len(report.dependencies),
        source_path.name,
    )

    return report


def _analyze_import(imp: ImportInfo) -> DetectedDependency | None:
    """Analyze a single import to detect external dependencies.

    Args:
        imp: Import information from tree-sitter.

    Returns:
        DetectedDependency if this import indicates an integration dependency, None otherwise.
    """
    module = imp.module

    # Check against all dependency patterns
    for dep_type, patterns in DEPENDENCY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, module, re.IGNORECASE):
                return DetectedDependency(
                    dependency_type=dep_type,
                    module_name=module,
                    pattern_matched=pattern,
                )

    return None


def _map_dependencies_to_functions(
    dependencies: dict[str, DetectedDependency],
    parse_result: ParseResult,
) -> None:
    """Map detected dependencies to the functions that use them.

    Args:
        dependencies: Map of module name to DetectedDependency.
        parse_result: Parsed AST result.
    """
    # Simple heuristic: if a function's code contains the module name,
    # assume it uses that dependency
    for func in parse_result.functions:
        func_code = func.body if hasattr(func, "body") else ""
        for module_name, dep in dependencies.items():
            # Extract the base module name (e.g., "requests" from "requests.get")
            base_module = module_name.split(".")[0].split("/")[-1]
            if base_module in func_code or module_name in func_code:
                dep.used_in_functions.append(func.name)


def _get_mock_strategies(dep_type: IntegrationDependencyType, language: str) -> list[str]:
    """Get recommended mocking strategies for a dependency type.

    Args:
        dep_type: The type of external dependency.
        language: Programming language.

    Returns:
        List of recommended mocking strategies/libraries.
    """
    # Normalize language for lookup
    lang_key = language.lower()
    if lang_key not in MOCK_STRATEGIES:
        return []

    return MOCK_STRATEGIES[lang_key].get(dep_type, [])


def _generate_fixture_recommendations(
    dependencies: list[DetectedDependency], language: str
) -> list[str]:
    """Generate test fixture/factory recommendations based on dependencies.

    Args:
        dependencies: List of detected dependencies.
        language: Programming language.

    Returns:
        List of recommended fixtures/factories to create.
    """
    recommendations: list[str] = []

    for dep in dependencies:
        if dep.dependency_type == IntegrationDependencyType.DATABASE:
            if language == "python":
                recommendations.append("Database session fixture")
                recommendations.append("Sample model factories")
            elif language in ("javascript", "typescript"):
                recommendations.append("Database connection mock")
                recommendations.append("Sample data fixtures")
            elif language == "go":
                recommendations.append("Test database setup/teardown")
            elif language == "java":
                recommendations.append("@DataJpaTest setup")

        elif dep.dependency_type == IntegrationDependencyType.HTTP_CLIENT:
            if language == "python":
                recommendations.append("HTTP response fixtures")
            elif language in ("javascript", "typescript"):
                recommendations.append("MSW handlers")
            elif language == "go":
                recommendations.append("httptest.Server")
            elif language == "java":
                recommendations.append("WireMock stubs")

        elif dep.dependency_type == IntegrationDependencyType.FILESYSTEM:
            recommendations.append("Temporary directory fixture")

    # Remove duplicates
    return list(set(recommendations))
