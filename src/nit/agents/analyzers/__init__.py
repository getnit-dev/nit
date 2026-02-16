"""Analyzer agents for nit."""

from nit.agents.analyzers.accessibility import (
    AccessibilityAnalysisResult,
    AccessibilityReport,
    AccessibilityViolation,
    analyze_accessibility,
    detect_frontend_project,
)
from nit.agents.analyzers.bug import (
    BugAnalysisTask,
    BugAnalyzer,
    BugLocation,
    BugReport,
    BugSeverity,
    BugType,
)
from nit.agents.analyzers.code import (
    CodeAnalysisTask,
    CodeAnalyzer,
    CodeMap,
    ComplexityMetrics,
    FunctionCall,
    SideEffect,
    SideEffectType,
)
from nit.agents.analyzers.contract import (
    ContractAnalysisResult,
    PactContract,
    PactInteraction,
    analyze_contracts,
    detect_contract_files,
)
from nit.agents.analyzers.coverage import (
    CoverageAnalysisTask,
    CoverageAnalyzer,
    CoverageGapReport,
    FunctionGap,
    GapPriority,
    StaleTest,
)
from nit.agents.analyzers.database import (
    Migration,
    MigrationAnalysisResult,
    analyze_migrations,
    detect_migration_framework,
    discover_migrations,
)
from nit.agents.analyzers.diff import (
    ChangeType,
    DiffAnalysisResult,
    DiffAnalysisTask,
    DiffAnalyzer,
    FileChange,
    FileMapping,
)
from nit.agents.analyzers.flow_mapping import FlowMapper, FlowMappingResult, UserFlow
from nit.agents.analyzers.graphql import (
    GraphQLField,
    GraphQLOperation,
    GraphQLSchemaAnalysis,
    GraphQLTypeInfo,
    analyze_graphql_schema,
    detect_graphql_schemas,
)
from nit.agents.analyzers.integration_deps import (
    DetectedDependency,
    IntegrationDependencyReport,
    detect_integration_dependencies,
)
from nit.agents.analyzers.mutation import MutationAnalysisResult, MutationTestAnalyzer
from nit.agents.analyzers.openapi import (
    OpenAPIAnalysisResult,
    OpenAPIEndpoint,
    OpenAPIParameter,
    analyze_openapi_spec,
    detect_openapi_specs,
)
from nit.agents.analyzers.pattern import (
    ConventionProfile,
    PatternAnalysisTask,
    PatternAnalyzer,
)
from nit.agents.analyzers.risk import RiskAnalysisTask, RiskAnalyzer, RiskReport
from nit.agents.analyzers.route_discovery import RouteDiscoveryAgent, discover_routes
from nit.agents.analyzers.semantic_gap import (
    GapCategory,
    SemanticGap,
    SemanticGapDetector,
    SemanticGapTask,
)
from nit.agents.analyzers.snapshot import (
    SnapshotAnalysisResult,
    SnapshotFile,
    analyze_snapshots,
    detect_snapshot_framework,
    discover_snapshots,
)
from nit.agents.analyzers.test_mapper import TestMapper, TestMapping

__all__ = [
    "AccessibilityAnalysisResult",
    "AccessibilityReport",
    "AccessibilityViolation",
    "BugAnalysisTask",
    "BugAnalyzer",
    "BugLocation",
    "BugReport",
    "BugSeverity",
    "BugType",
    "ChangeType",
    "CodeAnalysisTask",
    "CodeAnalyzer",
    "CodeMap",
    "ComplexityMetrics",
    "ContractAnalysisResult",
    "ConventionProfile",
    "CoverageAnalysisTask",
    "CoverageAnalyzer",
    "CoverageGapReport",
    "DetectedDependency",
    "DiffAnalysisResult",
    "DiffAnalysisTask",
    "DiffAnalyzer",
    "FileChange",
    "FileMapping",
    "FlowMapper",
    "FlowMappingResult",
    "FunctionCall",
    "FunctionGap",
    "GapCategory",
    "GapPriority",
    "GraphQLField",
    "GraphQLOperation",
    "GraphQLSchemaAnalysis",
    "GraphQLTypeInfo",
    "IntegrationDependencyReport",
    "Migration",
    "MigrationAnalysisResult",
    "MutationAnalysisResult",
    "MutationTestAnalyzer",
    "OpenAPIAnalysisResult",
    "OpenAPIEndpoint",
    "OpenAPIParameter",
    "PactContract",
    "PactInteraction",
    "PatternAnalysisTask",
    "PatternAnalyzer",
    "RiskAnalysisTask",
    "RiskAnalyzer",
    "RiskReport",
    "RouteDiscoveryAgent",
    "SemanticGap",
    "SemanticGapDetector",
    "SemanticGapTask",
    "SideEffect",
    "SideEffectType",
    "SnapshotAnalysisResult",
    "SnapshotFile",
    "StaleTest",
    "TestMapper",
    "TestMapping",
    "UserFlow",
    "analyze_accessibility",
    "analyze_contracts",
    "analyze_graphql_schema",
    "analyze_migrations",
    "analyze_openapi_spec",
    "analyze_snapshots",
    "detect_contract_files",
    "detect_frontend_project",
    "detect_graphql_schemas",
    "detect_integration_dependencies",
    "detect_migration_framework",
    "detect_openapi_specs",
    "detect_snapshot_framework",
    "discover_migrations",
    "discover_routes",
    "discover_snapshots",
]
