"""Prompt template library for LLM-based test generation."""

from nit.llm.prompts.accessibility_test_prompt import (
    AccessibilityTestTemplate,
    JestAxeTemplate,
    PlaywrightAxeTemplate,
)
from nit.llm.prompts.api_test_prompt import APITestTemplate
from nit.llm.prompts.base import PromptSection, PromptTemplate, RenderedPrompt
from nit.llm.prompts.bug_analysis import (
    BugAnalysisContext,
    BugAnalysisPrompt,
    BugReproductionPrompt,
    RootCauseAnalysisPrompt,
)
from nit.llm.prompts.catch2_prompt import Catch2Template
from nit.llm.prompts.contract_test_prompt import (
    ContractTestTemplate,
    JestPactTemplate,
    PytestPactTemplate,
    VitestPactTemplate,
)
from nit.llm.prompts.cypress_prompt import CypressTemplate
from nit.llm.prompts.fix_generation import (
    FixGenerationContext,
    FixGenerationPrompt,
    MinimalFixPrompt,
    SafeFixPrompt,
)
from nit.llm.prompts.graphql_test_prompt import GraphQLTestTemplate
from nit.llm.prompts.gtest_prompt import GTestTemplate
from nit.llm.prompts.jest_prompt import JestTemplate
from nit.llm.prompts.migration_test_prompt import (
    AlembicMigrationTemplate,
    DjangoMigrationTemplate,
    MigrationTestTemplate,
)
from nit.llm.prompts.mocha_prompt import MochaTemplate
from nit.llm.prompts.mutation_test_prompt import (
    MutationTestPromptContext,
    build_mutation_test_messages,
)
from nit.llm.prompts.pytest_prompt import PytestTemplate
from nit.llm.prompts.semantic_gap import SemanticGapContext, SemanticGapPrompt
from nit.llm.prompts.snapshot_test_prompt import (
    JestSnapshotTemplate,
    PytestSyrupyTemplate,
    SnapshotTestTemplate,
)
from nit.llm.prompts.unit_test import UnitTestTemplate
from nit.llm.prompts.vitest import VitestTemplate

__all__ = [
    "APITestTemplate",
    "AccessibilityTestTemplate",
    "AlembicMigrationTemplate",
    "BugAnalysisContext",
    "BugAnalysisPrompt",
    "BugReproductionPrompt",
    "Catch2Template",
    "ContractTestTemplate",
    "CypressTemplate",
    "DjangoMigrationTemplate",
    "FixGenerationContext",
    "FixGenerationPrompt",
    "GTestTemplate",
    "GraphQLTestTemplate",
    "JestAxeTemplate",
    "JestPactTemplate",
    "JestSnapshotTemplate",
    "JestTemplate",
    "MigrationTestTemplate",
    "MinimalFixPrompt",
    "MochaTemplate",
    "MutationTestPromptContext",
    "PlaywrightAxeTemplate",
    "PromptSection",
    "PromptTemplate",
    "PytestPactTemplate",
    "PytestSyrupyTemplate",
    "PytestTemplate",
    "RenderedPrompt",
    "RootCauseAnalysisPrompt",
    "SafeFixPrompt",
    "SemanticGapContext",
    "SemanticGapPrompt",
    "SnapshotTestTemplate",
    "UnitTestTemplate",
    "VitestPactTemplate",
    "VitestTemplate",
    "build_mutation_test_messages",
]
