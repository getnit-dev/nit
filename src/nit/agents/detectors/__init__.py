"""Detector agents for stack, framework, workspace, infra, dependency, and LLM usage."""

from nit.agents.detectors.dependency import DependencyDetector, DependencyProfile
from nit.agents.detectors.framework import FrameworkDetector
from nit.agents.detectors.infra import InfraDetector, InfraProfile
from nit.agents.detectors.llm_usage import (
    LLMUsageDetector,
    LLMUsageLocation,
    LLMUsageProfile,
)
from nit.agents.detectors.stack import LanguageProfile, StackDetector
from nit.agents.detectors.workspace import WorkspaceDetector, WorkspaceProfile

__all__ = [
    "DependencyDetector",
    "DependencyProfile",
    "FrameworkDetector",
    "InfraDetector",
    "InfraProfile",
    "LLMUsageDetector",
    "LLMUsageLocation",
    "LLMUsageProfile",
    "LanguageProfile",
    "StackDetector",
    "WorkspaceDetector",
    "WorkspaceProfile",
]
