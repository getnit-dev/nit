"""Prompt template library for LLM-based test generation."""

from nit.llm.prompts.base import PromptSection, PromptTemplate, RenderedPrompt
from nit.llm.prompts.catch2_prompt import Catch2Template
from nit.llm.prompts.gtest_prompt import GTestTemplate
from nit.llm.prompts.pytest_prompt import PytestTemplate
from nit.llm.prompts.unit_test import UnitTestTemplate
from nit.llm.prompts.vitest import VitestTemplate

__all__ = [
    "Catch2Template",
    "GTestTemplate",
    "PromptSection",
    "PromptTemplate",
    "PytestTemplate",
    "RenderedPrompt",
    "UnitTestTemplate",
    "VitestTemplate",
]
