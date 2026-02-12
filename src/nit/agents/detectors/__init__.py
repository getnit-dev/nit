"""Detector agents for stack, framework, workspace, and LLM usage detection."""

from nit.agents.detectors.framework import FrameworkDetector
from nit.agents.detectors.llm_usage import (
    LLMUsageDetector,
    LLMUsageLocation,
    LLMUsageProfile,
)
from nit.agents.detectors.stack import LanguageProfile, StackDetector
from nit.agents.detectors.workspace import WorkspaceDetector, WorkspaceProfile

__all__ = [
    "FrameworkDetector",
    "LLMUsageDetector",
    "LLMUsageLocation",
    "LLMUsageProfile",
    "LanguageProfile",
    "StackDetector",
    "WorkspaceDetector",
    "WorkspaceProfile",
]
