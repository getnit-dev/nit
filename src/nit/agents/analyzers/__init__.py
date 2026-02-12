"""Analyzer agents for nit."""

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
from nit.agents.analyzers.coverage import (
    CoverageAnalysisTask,
    CoverageAnalyzer,
    CoverageGapReport,
    FunctionGap,
    GapPriority,
    StaleTest,
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
from nit.agents.analyzers.integration_deps import (
    DetectedDependency,
    IntegrationDependencyReport,
    detect_integration_dependencies,
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

__all__ = [
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
    "IntegrationDependencyReport",
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
    "StaleTest",
    "UserFlow",
    "detect_integration_dependencies",
    "discover_routes",
]
