"""Prompt template library for LLM-based test generation."""

from nit.llm.prompts.base import PromptSection, PromptTemplate, RenderedPrompt
from nit.llm.prompts.bug_analysis import (
    BugAnalysisContext,
    BugAnalysisPrompt,
    BugReproductionPrompt,
    RootCauseAnalysisPrompt,
)
from nit.llm.prompts.catch2_prompt import Catch2Template
from nit.llm.prompts.fix_generation import (
    FixGenerationContext,
    FixGenerationPrompt,
    MinimalFixPrompt,
    SafeFixPrompt,
)
from nit.llm.prompts.gtest_prompt import GTestTemplate
from nit.llm.prompts.pytest_prompt import PytestTemplate
from nit.llm.prompts.semantic_gap import SemanticGapContext, SemanticGapPrompt
from nit.llm.prompts.unit_test import UnitTestTemplate
from nit.llm.prompts.vitest import VitestTemplate

__all__ = [
    "BugAnalysisContext",
    "BugAnalysisPrompt",
    "BugReproductionPrompt",
    "Catch2Template",
    "FixGenerationContext",
    "FixGenerationPrompt",
    "GTestTemplate",
    "MinimalFixPrompt",
    "PromptSection",
    "PromptTemplate",
    "PytestTemplate",
    "RenderedPrompt",
    "RootCauseAnalysisPrompt",
    "SafeFixPrompt",
    "SemanticGapContext",
    "SemanticGapPrompt",
    "UnitTestTemplate",
    "VitestTemplate",
]
