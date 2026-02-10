# Nit — Master Task List

> Derived from [testing.md](testing.md). Every phase and sub-phase broken into granular, parallelizable tasks.
> Tasks marked with `[P]` can be worked on in parallel within their sub-phase.

---

## Phase 1 — Foundation (Weeks 1–4)

### 1.1 Project Scaffolding (Week 1)

- [x] **1.1.1** Initialize Python project with `pyproject.toml` (PEP 621, hatchling build system, `getnit` as package name, `nit` CLI entry point)
- [x] **1.1.2** Set up directory structure: `cli/src/nit/` with sub-packages (`agents/`, `adapters/`, `llm/`, `memory/`, `parsing/`, `utils/`)
- [x] **1.1.3** Configure development tooling: ruff (linting), mypy (type checking), pytest (testing), pre-commit hooks
- [x] **1.1.4** Set up Click CLI entrypoint (`cli.py`) with top-level command group and `--version` flag
- [x] **1.1.5** Create `BaseAgent` abstract class (`agents/base.py`) defining the agent interface (async `run()`, `name`, `description`, task input/output types)
- [x] **1.1.6** Implement async orchestrator (`orchestrator.py`) with in-memory asyncio work queue, agent dispatch, and parallel execution support
- [x] **1.1.7** Write initial `README.md` with project description, install instructions, and quickstart placeholder

### 1.2 Tree-sitter Integration (Week 1) `[P with 1.1]`

- [x] **1.2.1** Add `tree-sitter` + `tree-sitter-language-pack` as dependencies; verify bindings work for Python, JS/TS, C/C++, Java, Go, Rust
- [x] **1.2.2** Build tree-sitter wrapper (`parsing/treesitter.py`): parse file → return AST, extract functions/classes/methods/imports per language
- [x] **1.2.3** Implement language-specific AST query modules (`parsing/languages/`): extract function signatures, class definitions, import statements, type annotations for each supported language (refactored into per-language files)
- [x] **1.2.4** Write unit tests for tree-sitter parsing across Python, JS/TS, C/C++, Java, Go sample files (73 tests)

### 1.3 Stack Detector (Week 1) `[P with 1.2]`

- [x] **1.3.1** Implement `StackDetector` (`agents/detectors/stack.py`): scan file extensions in a directory, count by language, rank by frequency
- [x] **1.3.2** Add tree-sitter validation pass: for ambiguous extensions (`.h` → C or C++), parse a sample file to confirm language
- [x] **1.3.3** Output `LanguageProfile` dataclass with detected languages, confidence scores, and file counts
- [x] **1.3.4** Write tests for StackDetector using fixture directories with mixed-language projects

### 1.4 Framework Detector (Week 1) `[P with 1.3]`

- [x] **1.4.1** Define detection signal types: `ConfigFile`, `Dependency`, `ImportPattern`, `FilePattern`, `CMakePattern`, `PackageJsonField`, etc. (`agents/detectors/signals.py`)
- [x] **1.4.2** Implement `FrameworkDetector` (`agents/detectors/framework.py`) with multi-signal confidence scoring (config files=0.9, deps=0.8, imports=0.7, naming=0.5)
- [x] **1.4.3** Add JS/TS detection rules: Vitest, Jest, Mocha, Playwright, Cypress (check `package.json` devDeps, config files, import patterns)
- [x] **1.4.4** Add Python detection rules: pytest, unittest (check `pyproject.toml`, `requirements.txt`, `conftest.py`, import patterns)
- [x] **1.4.5** Implement conflict resolution: when multiple frameworks detected for same purpose, pick highest confidence
- [x] **1.4.6** Add LLM fallback classification for ambiguous cases (confidence < 0.8): prompt LLM with file samples to identify framework
- [x] **1.4.7** Write tests for FrameworkDetector with fixture projects for each supported framework (67 tests)

### 1.5 Workspace Detector (Week 1) `[P with 1.4]`

- [x] **1.5.1** Implement `WorkspaceDetector` (`agents/detectors/workspace.py`) with ordered detection: Turborepo → Nx → pnpm → Yarn → npm → Cargo → Go → Gradle → Maven → Bazel → CMake → Generic
- [x] **1.5.2** Parse each workspace tool's config to extract package paths (e.g., `turbo.json` pipeline, `pnpm-workspace.yaml` globs, `go.work` use directives)
- [x] **1.5.3** Build dependency graph between detected packages (internal deps based on import/config references)
- [x] **1.5.4** Support single-repo projects (no workspace detected → treat root as single package)
- [x] **1.5.5** Write tests for WorkspaceDetector with monorepo fixture directories (50 tests)

### 1.6 Profile Output (Week 1)

- [x] **1.6.1** Define `ProjectProfile` data model: languages, frameworks (unit, e2e, integration, docs), packages, dependencies, workspace tool
- [x] **1.6.2** Implement profile serialization to `.nit/profile.json` with caching (re-scan only when source files change, using file modification times or git status)
- [x] **1.6.3** Implement `nit init` CLI command: run all detectors → present results to user → write `.nit.yml` config + `.nit/profile.json`
- [x] **1.6.4** Implement `nit scan` CLI command: re-run detectors, update profile, display results in terminal

### 1.7 LLM Interface (Week 2)

- [x] **1.7.1** Add LiteLLM as dependency; implement `LLMEngine` abstraction (`llm/engine.py`) with `generate(prompt, context) → str` interface
- [x] **1.7.2** Implement built-in LiteLLM adapter (`llm/builtin.py`): supports OpenAI, Anthropic, Ollama, any LiteLLM-supported provider via unified API
- [x] **1.7.3** Implement rate limiting, retry logic (exponential backoff), and token counting in the LLM engine
- [x] **1.7.4** Add LLM configuration parsing from `.nit.yml` (`llm.provider`, `llm.model`, `llm.api_key`, `llm.base_url`)
- [x] **1.7.5** Write integration tests for LLM engine with mock responses (don't call real APIs in tests)

### 1.8 Context Assembly Engine (Week 2) `[P with 1.7]`

- [x] **1.8.1** Implement `ContextAssembler` (`llm/context.py`): given a source file, collect source code, tree-sitter AST extract, import/dependency graph, related files
- [x] **1.8.2** Implement "existing test pattern" extraction: find existing test files in the project, extract naming conventions, assertion styles, mocking patterns
- [x] **1.8.3** Implement context windowing: truncate/prioritize context to fit within model's context window (configurable max tokens)
- [x] **1.8.4** Write tests for context assembly with sample projects

### 1.9 Prompt Template Library (Week 2) `[P with 1.8]`

- [x] **1.9.1** Create unit test prompt template (`llm/prompts/unit_test.py`): structured prompt with source code, existing patterns, framework conventions, dependency info
- [x] **1.9.2** Create Vitest-specific prompt template: `describe/it` pattern, `vi.mock()` usage, `expect()` assertions, proper imports
- [x] **1.9.3** Create pytest-specific prompt template: function-based tests, `@pytest.fixture` usage, `assert` statements, conftest patterns
- [x] **1.9.4** Implement prompt template system: base template class with variable substitution, framework-specific overrides
- [x] **1.9.5** Write tests verifying prompt templates produce valid, well-structured prompts (46 tests)

### 1.10 UnitBuilder — Vitest Adapter (Week 2)

- [x] **1.10.1** Implement `VitestAdapter` (`adapters/unit/vitest.py`): detection (`vitest.config.*` + devDep), test file pattern (`**/*.test.{ts,tsx}`), test execution (`npx vitest run`)
- [x] **1.10.2** Implement `VitestAdapter.get_prompt_template()`: returns Vitest-specific test generation prompt
- [x] **1.10.3** Implement `VitestAdapter.run_tests()`: execute Vitest via subprocess, parse JSON reporter output into `TestResult`
- [x] **1.10.4** Implement `VitestAdapter.validate_test()`: parse generated test with tree-sitter TypeScript parser, check for syntax errors
- [x] **1.10.5** Write integration tests for VitestAdapter with a real sample TS project

### 1.11 UnitBuilder — pytest Adapter (Week 2) `[P with 1.10]`

- [x] **1.11.1** Implement `PytestAdapter` (`adapters/unit/pytest_adapter.py`): detection (`conftest.py`, `pyproject.toml [tool.pytest]`), test file pattern (`**/test_*.py`), test execution (`pytest --json-report`)
- [x] **1.11.2** Implement `PytestAdapter.get_prompt_template()`: returns pytest-specific generation prompt with fixture patterns
- [x] **1.11.3** Implement `PytestAdapter.run_tests()`: execute pytest via subprocess, parse JSON report into `TestResult`
- [x] **1.11.4** Implement `PytestAdapter.validate_test()`: parse generated test with tree-sitter Python parser, check syntax
- [x] **1.11.5** Write integration tests for PytestAdapter with a real sample Python project

### 1.12 Adapter Registry (Week 2) `[P with 1.10, 1.11]`

- [x] **1.12.1** Implement `AdapterRegistry` (`adapters/registry.py`): auto-discover adapters via entry points or module scanning at runtime
- [x] **1.12.2** Implement adapter selection: given a `ProjectProfile`, return the correct adapter(s) for each package
- [x] **1.12.3** Define `TestFrameworkAdapter` and `DocFrameworkAdapter` abstract base classes (`adapters/base.py`) with all required methods
- [x] **1.12.4** Write tests for adapter registry with mock adapters

### 1.13 UnitBuilder Agent (Week 2)

- [x] **1.13.1** Implement `UnitBuilder` agent (`agents/builders/unit.py`): receives a `BuildTask`, assembles context, calls LLM via adapter prompt, captures generated test code
- [x] **1.13.2** Implement the full generation pipeline in UnitBuilder: parse source → extract functions → assemble context → prompt LLM → receive generated test
- [x] **1.13.3** Wire UnitBuilder into orchestrator: CoverageAnalyzer produces `BuildTask`s → queue → UnitBuilder picks up and generates
- [x] **1.13.4** Write tests for UnitBuilder with mocked LLM responses

### 1.14 PatternAnalyzer (Week 2) `[P with 1.13]`

- [x] **1.14.1** Implement `PatternAnalyzer` (`agents/analyzers/pattern.py`): scan existing test files, extract naming conventions (describe/it vs test_function vs class-based)
- [x] **1.14.2** Extract assertion style patterns (expect/assert/should), mocking patterns (vi.mock/unittest.mock/pytest.fixture), import conventions
- [x] **1.14.3** Store extracted conventions in memory as a "convention profile"
- [x] **1.14.4** Write tests for PatternAnalyzer with sample test files in different styles

### 1.15 Memory System v1 (Week 2)

- [x] **1.15.1** Implement `MemoryStore` (`memory/store.py`): read/write JSON files in `.nit/memory/` directory
- [x] **1.15.2** Implement `GlobalMemory` (`memory/global_memory.py`): project-wide conventions, known patterns, failed patterns, generation stats
- [x] **1.15.3** Implement `PackageMemory` (`memory/package_memory.py`): per-package test patterns, known issues, coverage history, LLM feedback
- [x] **1.15.4** Implement memory seeding: on first run, PatternAnalyzer populates memory from existing tests
- [x] **1.15.5** Implement memory usage in UnitBuilder: before generating, check memory for existing patterns and failed approaches
- [x] **1.15.6** Write tests for memory read/write/update operations

### 1.16 Test Validation Loop (Week 3)

- [x] **1.16.1** Implement subprocess-based test runner (`utils/subprocess_runner.py`): safe execution with timeout, output capture, error handling, working directory management
- [x] **1.16.2** Implement validation pipeline in UnitBuilder: after LLM generates test → parse with tree-sitter (syntax check) → run test via adapter → capture result
- [x] **1.16.3** Implement self-iteration loop: on test failure, extract error message → feed back to LLM with original context + error → regenerate (up to 3 retries)
- [x] **1.16.4** Implement failure classification: distinguish "test bug" (generation error) vs "code bug" (actual bug found) vs "missing dep" (infrastructure issue)
- [x] **1.16.5** Update memory on generation outcomes: record what worked, what failed, and why
- [x] **1.16.6** Write tests for validation loop using fixture test files that intentionally fail

### 1.17 Coverage Integration — JS/TS (Week 3) `[P with 1.16]`

- [x] **1.17.1** Implement `IstanbulAdapter` (`adapters/coverage/istanbul.py`): run Istanbul/c8 via Vitest's built-in coverage, parse JSON coverage report
- [x] **1.17.2** Define unified `CoverageReport` data model: per-file line coverage, function coverage, branch coverage, overall percentages
- [x] **1.17.3** Implement coverage data parsing: translate Istanbul's JSON format into unified `CoverageReport`
- [x] **1.17.4** Write tests for Istanbul coverage parsing with sample coverage output

### 1.18 Coverage Integration — Python (Week 3) `[P with 1.17]`

- [x] **1.18.1** Implement `CoveragePyAdapter` (`adapters/coverage/coverage_py_adapter.py`): run `coverage.py` via pytest-cov, parse JSON coverage report
- [x] **1.18.2** Translate `coverage.py` JSON into unified `CoverageReport` format
- [x] **1.18.3** Write tests for coverage.py parsing with sample coverage output

### 1.19 CoverageAnalyzer (Week 3) `[P with 1.17, 1.18]`

- [x] **1.19.1** Implement `CoverageAnalyzer` (`agents/analyzers/coverage.py`): run coverage tool → parse report → map coverage to source files
- [x] **1.19.2** Identify untested files (zero coverage), undertested functions (public functions with no test), dead zones (high cyclomatic complexity + no coverage)
- [x] **1.19.3** Identify stale tests: tests referencing code that no longer exists (compare test imports against current source)
- [x] **1.19.4** Generate gap report: prioritized list of files/functions needing tests, sorted by risk (complexity, recency, criticality)
- [x] **1.19.5** Create `BuildTask` entries for each gap, ready for UnitBuilder to pick up
- [x] **1.19.6** Write tests for CoverageAnalyzer with sample coverage data

### 1.20 CodeAnalyzer (Week 3) `[P with 1.19]`

- [x] **1.20.1** Implement `CodeAnalyzer` (`agents/analyzers/code.py`): parse source file with tree-sitter → extract structured code map (functions, classes, methods, imports, types, complexity)
- [x] **1.20.2** Calculate cyclomatic complexity per function (count decision points: if/else, loops, try/catch, ternaries)
- [x] **1.20.3** Build call graph: which functions call which other functions (via tree-sitter import/call analysis)
- [x] **1.20.4** Detect side effects: functions that touch DB, filesystem, HTTP, or external services (via import/call patterns)
- [x] **1.20.5** Write tests for CodeAnalyzer with sample source files

### 1.21 RiskAnalyzer (Week 3) `[P with 1.20]`

- [x] **1.21.1** Implement `RiskAnalyzer` (`agents/analyzers/risk.py`): composite risk score per file/function based on complexity, coverage, recency, criticality domain
- [x] **1.21.2** Domain criticality detection: identify auth, payment, PII, encryption code (via keyword/import heuristics)
- [x] **1.21.3** Recency scoring: weight recently changed files higher (via git log)
- [x] **1.21.4** Output prioritized risk report consumed by orchestrator for task ordering
- [x] **1.21.5** Write tests for RiskAnalyzer with sample project data

### 1.22 CLI Polish & Config (Week 4)

- [x] **1.22.1** Implement `nit init` interactive wizard: detect stack → present findings → ask LLM config (provider, model, API key) → write `.nit.yml` (basic version done, interactive LLM config pending)
- [x] **1.22.2** Implement `.nit.yml` config parser (`config.py`): parse YAML with env var substitution (`${VAR_NAME}`), validation, defaults, per-package overrides
- [x] **1.22.3** Implement `nit scan` command: run detectors → display results → update profile
- [x] **1.22.4** Implement `nit generate` command: run analyzers → create build tasks → run UnitBuilder → write test files → report summary (skeleton done, full implementation pending)
- [x] **1.22.5** Implement `nit generate --type unit` filter and `nit generate --file <path>` targeting
- [x] **1.22.6** Implement `nit generate --coverage-target <n>` mode: keep generating until target percentage reached
- [x] **1.22.7** Implement `nit run` command: run full test suite via detected adapter(s), display results with coverage (skeleton donx§e, full implementation pending)
- [x] **1.22.8** Implement `CLIReporter` (`agents/reporters/terminal.py`): rich terminal output with colors, progress bars, test summaries, coverage tables
- [x] **1.22.9** Add `nit hunt` command: alias for generate with full pipeline (scan → analyze → generate → run → debug → report)
- [x] **1.22.10** Add `nit pick` command: alias for scan

### 1.23 First Release (Week 4) `[P with 1.22]`

- [x] **1.23.1** Finalize `pyproject.toml` with all dependencies, metadata, classifiers, URLs
- [x] **1.23.2** Write comprehensive README: project description, features, installation, quickstart, configuration reference, contributing guide
- [x] **1.23.3** Set up GitHub Actions CI: lint, type check, run tests on every push/PR
- [x] **1.23.4** Set up GitHub Actions release workflow: build, publish to PyPI on tag push
- [x] **1.23.5** Register `getnit` package on PyPI and do first `v0.1.0` release (documented in RELEASE.md)
- [x] **1.23.6** Verify end-to-end: `pip install getnit && nit init && nit generate` works on a sample Next.js project - using a new repository getnit-dev/examples which is checked out at ~/examples/ (documented in EXAMPLES.md)
- [x] **1.23.7** Verify end-to-end: `pip install getnit && nit init && nit generate` works on a sample Python/pytest project - using a new repository getnit-dev/examples which is checked out at ~/examples/ (documented in EXAMPLES.md)
---

## Phase 2 — CI + E2E + Monorepo (Weeks 5–8)

### 2.1 GitHub Action (Week 5)

- [x] **2.1.1** Create GitHub Action definition (`action/action.yml`): composite action with inputs for mode, LLM provider, API key, dashboard URL
- [x] **2.1.2** Implement `--ci` flag in CLI: machine-readable JSON output, non-interactive mode, exit codes for pass/fail
- [x] **2.1.3** Implement Action entrypoint script (`action/entrypoint.sh`): install getnit, run specified mode, handle env vars
- [x] **2.1.4** Write example workflow YAML (`.github/workflows/nit.yml`) for documentation
- [x] **2.1.5** Test GitHub Action in a real repo with a PR trigger

### 2.2 DiffAnalyzer — PR Mode (Week 5) `[P with 2.1]`

- [x] **2.2.1** Implement `DiffAnalyzer` (`agents/analyzers/diff.py`): in PR mode, use `git diff` to identify changed files only
- [x] **2.2.2** Map changed source files to their corresponding test files (and vice versa)
- [x] **2.2.3** Generate delta-focused work list: only analyze/generate for changed code
- [x] **2.2.4** Implement `nit scan --diff` command that uses DiffAnalyzer
- [x] **2.2.5** Write tests for DiffAnalyzer with sample git diffs

### 2.3 GitHubCommentReporter (Week 5) `[P with 2.2]`

- [x] **2.3.1** Implement `GitHubCommentReporter` (`agents/reporters/github_comment.py`): post PR comment with coverage delta table, generated tests summary, issues found, drift status
- [x] **2.3.2** Implement GitHub API integration (`utils/git.py`): authenticate with `GITHUB_TOKEN`, create/update PR comments (upsert to avoid duplicates)
- [x] **2.3.3** Format coverage delta as markdown table: file-by-file before/after/delta with color indicators
- [x] **2.3.4** Test GitHubCommentReporter with mocked GitHub API

### 2.4 E2E — Route Discovery (Week 6)

- [x] **2.4.1** Implement route discovery for Next.js: parse `pages/` directory and `app/` directory (App Router) to extract routes
- [x] **2.4.2** Implement route discovery for Express/Fastify: parse `app.get()`, `router.post()` etc. calls via tree-sitter AST
- [x] **2.4.3** Implement route discovery for Django: parse `urls.py` `urlpatterns` to extract routes
- [x] **2.4.4** Map routes to handlers: link each route to its handler function/component for context assembly
- [x] **2.4.5** Write tests for route discovery with sample app structures
- [x] **2.4.6** **BONUS:** Added Flask, FastAPI, Gin, Echo, Chi, and Gorilla Mux route discovery support

### 2.5 E2E — Auth Config System (Week 6) `[P with 2.4]`

- [x] **2.5.1** Design auth config schema in `.nit.yml`: support `form`, `oauth`, `token`, `cookie`, `custom` strategies
- [x] **2.5.2** Implement form-based auth: navigate to login URL, fill credentials, wait for redirect/success indicator
- [x] **2.5.3** Implement token-based auth: inject bearer token from env var into browser context
- [x] **2.5.4** Implement OAuth placeholder: support pre-authenticated test tokens (skip OAuth flow, inject session)
- [x] **2.5.5** Write tests for auth config parsing and strategy selection

### 2.6 E2EBuilder — Playwright Generation (Week 6)

- [x] **2.6.1** Implement `PlaywrightAdapter` (`adapters/e2e/playwright_adapter.py`): detection (`playwright.config.*`, `@playwright/test` dep), test execution (`npx playwright test`)
- [x] **2.6.2** Implement `E2EBuilder` agent (`agents/builders/e2e.py`): receives route + flow info, assembles context, generates Playwright test via LLM
- [x] **2.6.3** Create E2E prompt template (`llm/prompts/e2e_test.py`): page object pattern, proper `await`/`waitFor` usage, `data-testid` selectors, auth setup
- [x] **2.6.4** Implement flow mapping: identify critical user paths (auth → dashboard → CRUD → logout) from route graph (`agents/analyzers/flow_mapping.py`)
- [x] **2.6.5** Implement `nit generate --type e2e` command (CLI already supports --type e2e, full pipeline integration pending)
- [x] **2.6.6** Write tests for E2EBuilder with sample web app structures (`tests/test_playwright_adapter.py`, 25 tests passing)

### 2.7 Monorepo Support (Week 7)

- [x] **2.7.1** Implement per-package detection: run StackDetector + FrameworkDetector independently for each discovered package
- [x] **2.7.2** Implement per-package memory: separate memory files per package in `.nit/memory/packages/`
- [x] **2.7.3** Implement per-package generation: UnitBuilder respects package boundaries, uses correct adapter per package
- [x] **2.7.4** Implement parallel agent execution across packages: orchestrator dispatches build tasks for multiple packages concurrently
- [x] **2.7.5** Implement monorepo config: `workspace` section in `.nit.yml` with `auto_detect` and per-package overrides
- [x] **2.7.6** Implement `nit generate --package <path>` and `nit run --package <path>` commands
- [x] **2.7.7** Test full monorepo flow with Turborepo/pnpm fixture containing JS + Python packages

### 2.8 InfraBuilder (Week 8)

- [x] **2.8.1** Implement `InfraBuilder` agent (`agents/builders/infra.py`): when no test infrastructure exists, bootstrap it (install deps, create configs, add scripts)
- [x] **2.8.2** Implement Vitest bootstrap: install vitest + @testing-library/react, create `vitest.config.ts`, add test scripts to `package.json`
- [x] **2.8.3** Implement pytest bootstrap: create `conftest.py`, add pytest to dev dependencies, create test directory
- [x] **2.8.4** Implement Playwright bootstrap: install @playwright/test, create `playwright.config.ts`, create example test
- [x] **2.8.5** Implement Docker execution mode: run InfraBuilder actions in Docker container for isolation (`infra.execution: docker` config)
- [x] **2.8.6** Write tests for InfraBuilder bootstrapping scenarios

### 2.9 Self-Healing Tests (Week 8) `[P with 2.8]`

- [x] **2.9.1** Detect test failures caused by UI/selector changes (compare error message patterns: "element not found", "timeout", selector mismatch)
- [x] **2.9.2** Implement re-analysis: on selector failure, re-scan the target page/component DOM to find updated selector
- [x] **2.9.3** Implement test regeneration: feed original test + error + updated DOM context back to LLM for fix
- [x] **2.9.4** Implement flaky test detection: run failing test 3x, if intermittent → mark as flaky instead of failing
- [x] **2.9.5** Write tests for self-healing logic with simulated selector changes

### 2.10 GitHubPRReporter (Week 8) `[P with 2.9]`

- [x] **2.10.1** Implement `GitHubPRReporter` (`agents/reporters/github_pr.py`): create PRs with generated/fixed tests on a new branch
- [x] **2.10.2** Implement branch creation and commit workflow: create `nit/generated-tests-<hash>` branch, commit test files, push, open PR
- [x] **2.10.3** Generate descriptive PR body: list generated tests, coverage improvement, bugs found, link to relevant source files
- [x] **2.10.4** Implement `nit hunt --pr` command: full pipeline ending with PR creation
- [x] **2.10.5** Test GitHubPRReporter with mocked GitHub API

### 2.11 Integration Test Generation (Week 8) `[P with 2.10]`

- [x] **2.11.1** Implement `IntegrationBuilder` agent (`agents/builders/integration.py`): generates integration tests for code touching DBs, APIs, external services
- [x] **2.11.2** Implement dependency detection for integration targets: DB calls, HTTP clients, filesystem, message queues (via import/call analysis)
- [x] **2.11.3** Implement mock generation: MSW for HTTP in JS, `unittest.mock` for Python, framework-appropriate mocking per adapter
- [x] **2.11.4** Implement fixture/test data factory generation: create test data based on types/schemas detected in source
- [x] **2.11.5** Create integration test prompt template (`llm/prompts/integration_test.py`)
- [x] **2.11.6** Implement `nit generate --type integration` command
- [x] **2.11.7** Write tests for IntegrationBuilder with sample code containing external dependencies

---

## Phase 3 — Systems Languages + Debuggers (Weeks 9–14)

### 3.1 C/C++ — GTest Adapter (Weeks 9–10)

- [x] **3.1.1** Implement `GTestAdapter` (`adapters/unit/gtest_adapter.py`): detection (CMake patterns: `find_package(GTest)`, `gtest_discover_tests`, `#include <gtest/gtest.h>`)
- [x] **3.1.2** Implement GTest test file pattern and naming conventions (`*_test.cpp`, `*_test.cc`)
- [x] **3.1.3** Implement GTest prompt template: `TEST()` / `TEST_F()` macros, `EXPECT_*` / `ASSERT_*` assertions, proper includes
- [x] **3.1.4** Implement GTest test execution via CMake/CTest subprocess: `cmake --build . --target test` or direct gtest binary execution
- [x] **3.1.5** Implement GTest result parsing: parse XML/JSON test output into `RunResult`/`TestCaseResult`
- [x] **3.1.6** Write tests for GTestAdapter with sample C++ project

### 3.2 C/C++ — Catch2 Adapter (Weeks 9–10) `[P with 3.1]`

- [x] **3.2.1** Implement `Catch2Adapter` (`adapters/unit/catch2_adapter.py`): detection (`find_package(Catch2)`, `#include <catch2/catch`)
- [x] **3.2.2** Implement Catch2 prompt template: `TEST_CASE` / `SECTION` macros, `REQUIRE` / `CHECK` assertions
- [x] **3.2.3** Implement Catch2 test execution and result parsing
- [x] **3.2.4** Write tests for Catch2Adapter

### 3.3 C/C++ — CMake Integration (Weeks 9–10) `[P with 3.1, 3.2]`

- [ ] **3.3.1** Implement CMakeLists.txt parsing: detect existing test targets, include directories, linked libraries
- [ ] **3.3.2** Implement automatic CMakeLists.txt modification: add new test targets for generated test files (add_executable + target_link_libraries + gtest_discover_tests)
- [ ] **3.3.3** Write tests for CMake integration

### 3.4 C/C++ — Coverage (Weeks 9–10) `[P with 3.3]`

- [ ] **3.4.1** Implement `GcovAdapter` (`adapters/coverage/gcov.py`): run gcov/lcov, parse coverage data into unified `CoverageReport`
- [ ] **3.4.2** Support both gcov and llvm-cov output formats
- [ ] **3.4.3** Write tests for gcov coverage parsing

### 3.5 Go Adapter (Weeks 9–10) `[P with 3.1]`

- [ ] **3.5.1** Implement `GoTestAdapter` (`adapters/unit/go_test.py`): detection (`*_test.go` files, `go.mod`), test execution (`go test ./...`)
- [ ] **3.5.2** Implement Go test prompt template: table-driven tests, `t.Run()` subtests, `testify` assertions (if detected)
- [ ] **3.5.3** Implement `TestifyAdapter` (`adapters/unit/testify.py`): detection (`github.com/stretchr/testify` in go.mod), suite-based and assert-based patterns
- [ ] **3.5.4** Implement `GoCovertAdapter` (`adapters/coverage/go_cover.py`): run `go test -cover -coverprofile`, parse into unified report
- [ ] **3.5.5** Write tests for Go adapters with sample Go project

### 3.6 Java Adapter (Weeks 11–12)

- [ ] **3.6.1** Implement `JUnit5Adapter` (`adapters/unit/junit5.py`): detection (Gradle/Maven deps for `org.junit.jupiter`), test execution (`./gradlew test` or `mvn test`)
- [ ] **3.6.2** Implement JUnit 5 prompt template: `@Test`, `@BeforeEach`, `@DisplayName`, `Assertions.*` patterns
- [ ] **3.6.3** Implement Gradle integration: parse `build.gradle(.kts)` for test dependencies, source sets
- [ ] **3.6.4** Implement Maven integration: parse `pom.xml` for test dependencies, surefire plugin config
- [ ] **3.6.5** Implement `JaCoCoAdapter` (`adapters/coverage/jacoco.py`): parse JaCoCo XML report into unified format
- [ ] **3.6.6** Write tests for Java adapters with sample Gradle and Maven projects

### 3.7 Kotlin Adapter (Weeks 11–12) `[P with 3.6]`

- [ ] **3.7.1** Implement `KotestAdapter` (`adapters/unit/kotest.py`): detection (`io.kotest` deps), prompt template with Kotest DSL patterns
- [ ] **3.7.2** Support Kotlin running on JUnit 5 via `junit5.py` adapter (Kotlin compiles to JVM, same execution path)
- [ ] **3.7.3** Write tests for Kotlin adapter

### 3.8 CLI Tool Integration (Weeks 11–12) `[P with 3.6]`

- [x] **3.8.1** Implement `CLIToolAdapter` (`llm/cli_adapter.py`): abstract interface for delegating generation to external CLI tools
- [x] **3.8.2** Implement Claude Code adapter: call `claude --print` with structured prompt, capture output, parse token usage and errors
- [x] **3.8.3** Implement OpenAI Codex CLI adapter: call `codex --prompt` with context file, capture JSON output
- [x] **3.8.4** Ollama adapter: already supported via builtin LiteLLM mode
- [x] **3.8.5** Implement custom command adapter: user-defined command template with `{context_file}`, `{source_file}`, `{output_file}`, `{prompt}` placeholders
- [x] **3.8.6** Add `llm.mode` config option: `builtin` | `cli` | `custom` | `ollama` (added cli_command, cli_timeout, cli_extra_args to LLMConfig)
- [x] **3.8.7** Update `nit init` wizard to offer LLM tool selection (built-in API key, Claude Code, Codex, Ollama, custom)
- [x] **3.8.8** Write tests for CLI tool adapters with mocked subprocess calls (17 comprehensive tests, all passing)

### 3.9 Debugger Agents (Week 13)

- [ ] **3.9.1** Implement `BugAnalyzer` (`agents/analyzers/bug.py`): during test generation/execution, detect actual code bugs (not test bugs) — e.g., NaN returns, null dereference, uncaught exceptions
- [ ] **3.9.2** Implement `BugVerifier` (`agents/debuggers/verifier.py`): take suspected bug → create minimal reproduction test case → confirm it's real by running
- [ ] **3.9.3** Implement `RootCauseAnalyzer` (`agents/debuggers/root_cause.py`): use tree-sitter code analysis + LLM to trace bug to root cause (data flow analysis, missing validation, etc.)
- [ ] **3.9.4** Create bug analysis prompt template (`llm/prompts/bug_analysis.py`)
- [ ] **3.9.5** Implement `FixGenerator` (`agents/debuggers/fix_gen.py`): generate a code fix for the confirmed bug, output as a patch
- [ ] **3.9.6** Create fix generation prompt template (`llm/prompts/fix_generation.py`)
- [ ] **3.9.7** Implement `FixVerifier` (`agents/debuggers/fix_verify.py`): apply fix → run existing tests + new regression test → confirm no regressions
- [ ] **3.9.8** Wire debugger pipeline: BugAnalyzer → BugVerifier → RootCauseAnalyzer → FixGenerator → FixVerifier → Reporter
- [ ] **3.9.9** Implement `nit hunt` command: full pipeline (scan → analyze → generate → run → debug → report)
- [ ] **3.9.10** Implement `nit hunt --fix` flag: also generate and apply fixes for found bugs
- [ ] **3.9.11** Write tests for each debugger agent with sample buggy code

### 3.10 GitHubIssueReporter (Week 13) `[P with 3.9]`

- [ ] **3.10.1** Implement `GitHubIssueReporter` (`agents/reporters/github_issue.py`): create GitHub Issues for confirmed bugs
- [ ] **3.10.2** Format issue body: bug description, reproduction steps, minimal test case, root cause analysis, suggested fix, affected file/function
- [ ] **3.10.3** Link issues to PRs when fix is generated
- [ ] **3.10.4** Test GitHubIssueReporter with mocked GitHub API

### 3.11 DriftWatcher (Week 14)

- [ ] **3.11.1** Implement `DriftWatcher` (`agents/watchers/drift.py`): load drift test definitions from `.nit/drift-tests.yml`, execute tests, compare against baselines
- [ ] **3.11.2** Implement drift test YAML spec parser: support `semantic`, `exact`, `regex`, `schema` comparison types
- [ ] **3.11.3** Implement test endpoint execution: `function` type (import and call Python/JS function), `http` type (send HTTP request), `cli` type (run command)
- [ ] **3.11.4** Implement `DriftComparator` semantic comparison: use sentence-transformers for embedding-based cosine similarity (local, no API needed)
- [ ] **3.11.5** Implement exact match, regex match, and JSON schema validation comparison strategies
- [ ] **3.11.6** Implement baseline management (`memory/drift_baselines.py`): store/update baseline outputs and embeddings
- [ ] **3.11.7** Implement `nit drift` command: run all drift tests, report results
- [ ] **3.11.8** Implement `nit drift --baseline` command: update baselines to current outputs
- [ ] **3.11.9** Implement `nit drift --watch` command: continuous monitoring on schedule
- [ ] **3.11.10** Write tests for DriftWatcher with mock LLM endpoints

### 3.12 Prompt Optimization (Week 14) `[P with 3.11]`

- [ ] **3.12.1** Implement prompt analysis module: token counting, redundancy detection, instruction clarity scoring
- [ ] **3.12.2** Implement optimization suggestions: reduced token usage, clearer output format specs, better few-shot examples, temperature/parameter recommendations
- [ ] **3.12.3** Create drift analysis prompt template (`llm/prompts/drift_analysis.py`)
- [ ] **3.12.4** Integrate prompt optimization into drift alert output: when drift detected, include optimization suggestions in the report
- [ ] **3.12.5** Write tests for prompt optimization module

### 3.13 LLM Usage Detector (Week 14) `[P with 3.11]`

- [ ] **3.13.1** Implement `LLMUsageDetector` (`agents/detectors/llm_usage.py`): scan for OpenAI/Anthropic/Ollama SDK imports, HTTP calls to LLM endpoints, prompt template files
- [ ] **3.13.2** Map detected LLM usage to drift test candidates: suggest which endpoints/functions should have drift tests
- [ ] **3.13.3** Auto-generate drift test skeleton from detected LLM integrations
- [ ] **3.13.4** Write tests for LLMUsageDetector

---

## Phase 4 — Documentation + Dashboard + More Languages (Weeks 15–20)

### 4.1 DocBuilder — Core (Weeks 15–16)

- [ ] **4.1.1** Implement `DocBuilder` agent (`agents/builders/docs.py`): receives changed files → detects doc framework → generates/updates documentation
- [ ] **4.1.2** Implement diff-based doc detection: compare current code AST against last documented state (stored in memory), identify new functions, modified signatures, removed endpoints
- [ ] **4.1.3** Create doc generation prompt template (`llm/prompts/doc_generation.py`): generate docstrings/comments in target framework format
- [ ] **4.1.4** Implement `nit docs` command: run DocBuilder for all packages
- [ ] **4.1.5** Implement `nit docs --check` command: report outdated docs without making changes

### 4.2 TypeDoc Adapter (Weeks 15–16) `[P with 4.1]`

- [ ] **4.2.1** Implement `TypeDocAdapter` (`adapters/docs/typedoc.py`): detection (`typedoc.json`, `typedoc` dep), doc generation (TSDoc comments in source), doc build (`npx typedoc`)
- [ ] **4.2.2** Generate TSDoc comments for undocumented exported functions/classes/interfaces
- [ ] **4.2.3** Write tests for TypeDocAdapter

### 4.3 Sphinx Adapter (Weeks 15–16) `[P with 4.2]`

- [ ] **4.3.1** Implement `SphinxAdapter` (`adapters/docs/sphinx.py`): detection (`docs/conf.py`, sphinx dep), doc generation (RST/MyST files), doc build (`sphinx-build`)
- [ ] **4.3.2** Generate Python docstrings (Google/NumPy style) for undocumented functions/classes
- [ ] **4.3.3** Generate RST pages for new modules
- [ ] **4.3.4** Write tests for SphinxAdapter

### 4.4 Doxygen Adapter (Weeks 15–16) `[P with 4.3]`

- [ ] **4.4.1** Implement `DoxygenAdapter` (`adapters/docs/doxygen.py`): detection (`Doxyfile`, CMake `find_package(Doxygen)`), doc generation (Doxygen comments in headers), doc build (`doxygen`)
- [ ] **4.4.2** Generate Doxygen-format comments (`/** ... */` with `@param`, `@return`, `@brief`) for undocumented C/C++ functions/classes
- [ ] **4.4.3** Write tests for DoxygenAdapter

### 4.5 Additional Doc Adapters (Weeks 15–16) `[P with 4.4]`

- [ ] **4.5.1** Implement `JSDocAdapter` (`adapters/docs/jsdoc.py`): JSDoc comments for JavaScript projects
- [ ] **4.5.2** Implement `GoDocAdapter` (`adapters/docs/godoc_adapter.py`): Go doc comments (`// Package ...`, `// FunctionName ...`)
- [ ] **4.5.3** Implement `RustDocAdapter` (`adapters/docs/rustdoc.py`): Rust doc comments (`///` with markdown)
- [ ] **4.5.4** Implement `MkDocsAdapter` (`adapters/docs/mkdocs.py`): markdown page generation for MkDocs sites

### 4.6 README Auto-Update (Weeks 15–16) `[P with 4.5]`

- [ ] **4.6.1** Implement README update detection: monitor project structure changes (new packages, changed exports, new CLI commands)
- [ ] **4.6.2** Generate README section updates via LLM: installation instructions, API overview, project structure
- [ ] **4.6.3** Write tests for README auto-update

### 4.7 Changelog Generation (Weeks 15–16) `[P with 4.6]`

- [ ] **4.7.1** Implement changelog generation from git history: parse commits between tags, group by type (feat, fix, refactor, etc.)
- [ ] **4.7.2** Use LLM to generate human-readable changelog entries from commit messages + diffs
- [ ] **4.7.3** Output in Keep a Changelog format (`CHANGELOG.md`)
- [ ] **4.7.4** Implement `nit docs --changelog <tag>` command
- [ ] **4.7.5** Write tests for changelog generation

### 4.8 Rust Adapter (Week 17)

- [ ] **4.8.1** Implement `CargoTestAdapter` (`adapters/unit/cargo_test.py`): detection (`Cargo.toml`, `#[test]` attributes), test execution (`cargo test`), result parsing
- [ ] **4.8.2** Implement Rust test prompt template: `#[test]` functions, `assert_eq!`/`assert!` macros, module-level `#[cfg(test)]` blocks
- [ ] **4.8.3** Implement `TarpaulinAdapter` (`adapters/coverage/tarpaulin.py`): run `cargo tarpaulin`, parse coverage output
- [ ] **4.8.4** Write tests for Rust adapters

### 4.9 C#/.NET Adapter (Week 17) `[P with 4.8]`

- [ ] **4.9.1** Implement `XUnitAdapter` (`adapters/unit/xunit.py`): detection (NuGet `xunit` dep, `using Xunit`), test execution (`dotnet test`), result parsing (TRX format)
- [ ] **4.9.2** Implement xUnit prompt template: `[Fact]`, `[Theory]`, `[InlineData]`, `Assert.*` patterns
- [ ] **4.9.3** Implement `CoverletAdapter` (`adapters/coverage/coverlet.py`): parse Coverlet JSON/Cobertura XML into unified format
- [ ] **4.9.4** Write tests for C#/.NET adapters

### 4.10 Plugin System Formalization (Week 17) `[P with 4.9]`

- [ ] **4.10.1** Formalize adapter plugin API: document all abstract methods, input/output types, lifecycle hooks
- [ ] **4.10.2** Implement adapter auto-discovery via Python entry points: community adapters install as separate pip packages, register via `[project.entry-points]`
- [ ] **4.10.3** Create adapter contribution guide: template adapter with boilerplate, step-by-step instructions, testing requirements
- [ ] **4.10.4** Create adapter template repository on GitHub (cookiecutter/copier template)
- [ ] **4.10.5** Write tests for plugin loading and registration

### 4.11 Landing Page (Week 18)

- [x] **4.11.1** Set up separate `~/web` repository for marketing landing page with React + Vite + Tailwind CSS v4 (using official Cloudflare `vite-react-template`)
- [x] **4.11.2** Configure Wrangler for SPA deployment: Workers Static Assets with `not_found_handling: "single-page-application"`
- [x] **4.11.3** Build Hero section: animated terminal showing `nit hunt` running (typewriter effect), tagline, CTA buttons, GitHub stars counter
- [x] **4.11.4** Build Problem section: animated statistics counters, pain points
- [x] **4.11.5** Build How It Works section: 4-step visual pipeline (Detect → Analyze → Build → Report), interactive demo area
- [x] **4.11.6** Build Languages & Frameworks section: logo grid with hover details, "community contributed" badges
- [x] **4.11.7** Build The Swarm section: animated agent visualization (agents working in parallel), agent cards
- [x] **4.11.8** Build Memory section: "gets smarter every run" visualization, before/after comparison
- [x] **4.11.9** Build Comparison Table section: feature matrix vs competitors (Tusk, QA Wolf, Bug0, Keploy, Shortest)
- [x] **4.11.10** Build Quickstart section: install command code blocks, GitHub Action YAML snippet, demo GIF
- [x] **4.11.11** Build Community section: contributor grid, Discord/Slack join, "Build an adapter" CTA
- [x] **4.11.12** Build Footer: docs, GitHub, Discord, Twitter/X links, MIT license
- [x] **4.11.13** Implement dark theme with terminal-aesthetic design, electric blue/acid green accent color
- [x] **4.11.14** Add Framer Motion scroll animations throughout all sections
- [x] **4.11.15** Implement responsive design for mobile/tablet

### 4.12 Local HTML Dashboard (Week 19)

- [ ] **4.12.1** Implement `DashboardReporter` (`agents/reporters/dashboard.py`): generate static HTML dashboard in `.nit/dashboard/`
- [ ] **4.12.2** Build coverage trends chart: line chart per package over time (using Chart.js or embedded inline SVG)
- [ ] **4.12.3** Build bug discovery history: timeline of bugs found, fixed, and open
- [ ] **4.12.4** Build memory insights view: human-readable display of what nit has learned
- [ ] **4.12.5** Build drift timeline: drift test results over time with similarity scores
- [ ] **4.12.6** Build test health overview: total tests, pass rate, generation stats, flaky tests
- [ ] **4.12.7** Implement `nit dashboard` command: generate HTML files
- [ ] **4.12.8** Implement `nit dashboard --serve` command: serve dashboard on localhost:4040
- [ ] **4.12.9** Write tests for dashboard generation

### 4.13 Additional Workspace Support (Week 20) `[P with 4.12]`

- [ ] **4.13.1** Implement Cargo workspace detection: parse `Cargo.toml` `[workspace]` members
- [ ] **4.13.2** Implement Go workspace detection: parse `go.work` use directives
- [ ] **4.13.3** Implement Gradle multi-project detection: parse `settings.gradle(.kts)` include statements
- [ ] **4.13.4** Implement Maven multi-module detection: parse parent `pom.xml` `<modules>` section
- [ ] **4.13.5** Implement Bazel workspace detection: parse `WORKSPACE` / `BUILD` files
- [ ] **4.13.6** Write tests for each workspace detector

### 4.14 Notification Integrations (Week 19–20) `[P with 4.12]`

- [ ] **4.14.1** Implement `SlackReporter` (`agents/reporters/slack.py`): send webhook notifications for critical events (bugs found, coverage drops, drift alerts)
- [ ] **4.14.2** Format Slack messages with blocks: bug details, coverage delta, action links
- [ ] **4.14.3** Add `report.slack_webhook` config option in `.nit.yml`
- [ ] **4.14.4** Write tests for SlackReporter

### 4.15 Watcher Agents (Week 19–20) `[P with 4.14]`

- [ ] **4.15.1** Implement `ScheduleWatcher` (`agents/watchers/schedule.py`): execute full test suite on cron schedule (used with `nit watch --schedule "0 2 * * *"`)
- [ ] **4.15.2** Implement `CoverageWatcher` (`agents/watchers/coverage.py`): track coverage trends over time, alert on drops below threshold
- [ ] **4.15.3** Write tests for watcher agents

### 4.16 Performance & Quality (Week 20)

- [ ] **4.16.1** Profile and optimize: identify bottlenecks in tree-sitter parsing, LLM calls, subprocess execution
- [ ] **4.16.2** Implement caching: cache tree-sitter ASTs, profile data, and LLM responses for unchanged files
- [ ] **4.16.3** Implement parallel test execution: run independent test suites concurrently
- [ ] **4.16.4** Write comprehensive test suite for nit itself: unit tests for all agents, integration tests for full pipelines, fixture-based end-to-end tests
- [ ] **4.16.5** Ensure all CLI commands have `--help` documentation and consistent output formatting
- [ ] **4.16.6** Final README polish: complete feature list, screenshots/GIFs, badges (PyPI version, test status, coverage)

### 4.17 Public Launch (Week 20)

- [ ] **4.17.1** Final end-to-end testing on real-world projects: Next.js, Python/FastAPI, C++ with CMake, Go, Java/Gradle, monorepo
- [ ] **4.17.2** Deploy landing page to Cloudflare Workers
- [ ] **4.17.3** Publish `getnit` v1.0.0 to PyPI
- [ ] **4.17.4** Publish GitHub Action `getnit/nit@v1`
- [ ] **4.17.5** Create GitHub Releases with platform binaries (linux-x64, linux-arm64, macos-x64, macos-arm64, windows-x64)
- [ ] **4.17.6** Write launch blog post / announcement

---

## Phase 5 — Web Platform (Cloudflare Dashboard)

> **Architecture decision:** No external infrastructure (no LiteLLM Proxy, no PostgreSQL, no Redis).
> Everything runs on Cloudflare: Workers + D1 + KV + R2 + AI Gateway + Queues + Workflows.
> LiteLLM SDK stays in the CLI — its `CustomLogger` callback reports usage to the platform
> regardless of whether the user uses a platform key or their own (BYOK).
> Repository split: `~/web` contains only marketing site code; `~/platform` contains only platform API/dashboard code.

### 5.1 Hono API Worker

- [ ] **5.1.1** Set up Hono project in `src/worker/` (within `~/platform`): TypeScript, Cloudflare Worker bindings (D1, KV, R2, Queues, AI Gateway)
- [ ] **5.1.2** Configure `wrangler.jsonc`: D1 database, KV namespace, R2 bucket, Queue producer/consumer, AI Gateway binding, Cron Triggers, Workers Static Assets
- [ ] **5.1.3** Implement CORS middleware for SPA (`/api/*` routes, allow `getnit.dev` + `localhost:5173`)
- [ ] **5.1.4** Implement session auth middleware (`middleware/auth.ts`): validate Better Auth session for dashboard routes
- [ ] **5.1.5** Implement virtual key middleware (`middleware/api-key.ts`): validate platform virtual key against D1 `virtual_keys` table, resolve user/project, check budget + rate limits (KV)

### 5.2 Database Schema (D1 + Drizzle) `[P with 5.1]`

- [x] **5.2.1** Define Drizzle schema (`src/worker/db/schema.ts` in `~/platform`): users, accounts, sessions (Better Auth), projects, packages, coverage_reports, drift_results, bugs tables
- [x] **5.2.2** Add LLM gateway tables: `virtual_keys` (key_hash, user_id, project_id, models_allowed, max_budget, budget_duration, rpm_limit, tpm_limit, spend_total, created_at, expires_at, revoked), `usage_events` (user_id, project_id, key_hash, model, provider, prompt_tokens, completion_tokens, cost_usd, margin_usd, cache_hit, source [platform|byok], timestamp), `usage_daily` (user_id, project_id, model, date, total_requests, total_tokens, total_cost_usd)
- [x] **5.2.3** Create D1 migration files for initial schema
- [x] **5.2.4** Add database indexes: `idx_coverage_project`, `idx_coverage_package`, `idx_drift_project`, `idx_bugs_project`, `idx_virtual_keys_hash`, `idx_usage_events_user_ts`, `idx_usage_daily_user_date`
- [x] **5.2.5** Implement Drizzle DB client helper (`src/worker/lib/db.ts` in `~/platform`)

### 5.3 Better Auth Integration `[P with 5.2]`

- [x] **5.3.1** Configure Better Auth (`src/worker/lib/auth.ts` in `~/platform`): email/password auth, GitHub OAuth, D1 adapter via Drizzle, KV session caching
- [x] **5.3.2** Mount Better Auth routes on `/api/auth/**`
- [x] **5.3.3** Configure session settings: 7-day expiry, 1-day update age
- [x] **5.3.4** Implement auth client for React SPA (`src/react-app/src/lib/auth-client.ts` in `~/platform`)

### 5.4 AI Gateway + LLM Proxy Layer `[P with 5.1]`

- [ ] **5.4.1** Configure Cloudflare AI Gateway: create gateway instance, enable caching, configure provider routing with fallback chains (Anthropic → Bedrock fallback, OpenAI primary + secondary)
- [ ] **5.4.2** Store platform's provider API keys in AI Gateway BYOK (Secrets Store): Anthropic, OpenAI, Bedrock keys — never exposed to users
- [x] **5.4.3** Implement LLM proxy route (`src/worker/routes/llm-proxy.ts` in `~/platform`): validate virtual key (D1), check budget (D1: `spend_total < max_budget`), check rate limit (KV: `incr` counter with TTL), if all pass → forward request to AI Gateway with BYOK alias header
- [x] **5.4.4** Implement margin calculation in proxy response: read cost from AI Gateway response headers, apply per-provider margin multiplier (configurable in D1 or KV), include in usage event
- [x] **5.4.5** Implement rate limiting via KV: `rate_limit:{key_hash}:rpm` and `:tpm` keys with sliding window counters (TTL-based reset)
- [x] **5.4.6** Implement budget enforcement: on each request, increment `spend_total` in D1 `virtual_keys`; reject requests when budget exceeded; support `budget_duration` for auto-reset via Cron Trigger
- [x] **5.4.7** Configure AI Gateway custom metadata: tag every request with `user_id`, `project_id`, `key_hash` for AI Gateway analytics dashboard

### 5.5 Usage Ingestion Pipeline `[P with 5.4]`

- [x] **5.5.1** Implement usage event Queue producer: after each proxied LLM request (platform key) or received CLI usage report (BYOK), enqueue usage event to Cloudflare Queue
- [x] **5.5.2** Implement Queue consumer Worker: batch-process usage events from Queue, insert into D1 `usage_events` table
- [x] **5.5.3** Implement usage ingestion API (`src/worker/routes/usage-ingest.ts` in `~/platform`): `POST /api/v1/usage/ingest` — accepts batched usage events from nit CLI's `CustomLogger` callback (for BYOK users who use their own keys), validates platform token, enqueues to Queue
- [x] **5.5.4** Implement Cron Trigger Workflow: nightly aggregation of `usage_events` → `usage_daily` table, budget period resets, stale data cleanup

### 5.6 API Routes

- [x] **5.6.1** Implement project CRUD routes (`src/worker/routes/projects.ts` in `~/platform`): list, create, update, delete projects
- [x] **5.6.2** Implement report routes (`src/worker/routes/reports.ts` in `~/platform`): upload coverage report (store summary in D1, full report in R2), list reports, get report detail
- [x] **5.6.3** Implement drift routes (`src/worker/routes/drift.ts` in `~/platform`): upload drift results, list results, get timeline
- [x] **5.6.4** Implement bug routes (`src/worker/routes/bugs.ts` in `~/platform`): list bugs, update status, link to GitHub issues/PRs
- [x] **5.6.5** Implement upload routes (`src/worker/routes/upload.ts` in `~/platform`): handle R2 file uploads for full JSON reports
- [x] **5.6.6** Implement webhook routes (`src/worker/routes/webhooks.ts` in `~/platform`): GitHub webhook receiver with signature verification
- [x] **5.6.7** Implement virtual key management routes (`src/worker/routes/llm-keys.ts` in `~/platform`): generate key (hash + store in D1), list keys, revoke (set `revoked=true`), rotate (revoke old + generate new), update budget/limits
- [x] **5.6.8** Implement LLM usage routes (`src/worker/routes/llm-usage.ts` in `~/platform`): query D1 `usage_events` + `usage_daily` for per-user token usage, cost breakdown by model/provider, daily activity, spend vs budget
- [x] **5.6.9** Implement cron handler: nightly drift check aggregation, usage aggregation, budget resets, stale data cleanup

### 5.7 React SPA — Dashboard `[P with 5.6]`

- [x] **5.7.1** Set up React SPA in `src/react-app/` (within `~/platform`): Vite config, React Router, Tailwind CSS v4 (`src/react-app/vite.config.ts`, `src/react-app/src/main.tsx`, `src/react-app/src/styles.css`)
- [x] **5.7.2** Implement API client (`lib/api.ts`): typed fetch wrapper for all API routes (`src/react-app/src/lib/api.ts`)
- [x] **5.7.3** Build authentication pages: login, register, GitHub OAuth callback (`src/react-app/src/pages/LoginPage.tsx`, `src/react-app/src/pages/RegisterPage.tsx`, `src/react-app/src/pages/GithubCallbackPage.tsx`)
- [x] **5.7.4** Build projects overview page: cards per project with coverage gauges, trend sparklines, open bug counts, last run status (`src/react-app/src/pages/ProjectsOverviewPage.tsx`)
- [x] **5.7.5** Build project detail — Coverage tab: coverage over time line chart (Recharts), per-package breakdown table, file-level heatmap (`src/react-app/src/pages/ProjectCoveragePage.tsx`)
- [x] **5.7.6** Build project detail — Bugs tab: open bugs list with severity badges, bug discovery timeline, fix rate metrics, GitHub links (`src/react-app/src/pages/ProjectBugsPage.tsx`)
- [x] **5.7.7** Build project detail — Drift tab: drift test results timeline, similarity score trends, alert history, baseline management (`src/react-app/src/pages/ProjectDriftPage.tsx`)
- [x] **5.7.8** Build project detail — Memory tab: human-readable learned patterns, failed approaches log, memory growth chart (`src/react-app/src/pages/ProjectMemoryPage.tsx`)
- [x] **5.7.9** Build project detail — LLM Usage tab: token usage over time (by model/provider), cost breakdown chart, spend vs budget gauge, per-key activity log — works for both platform-key and BYOK users (`src/react-app/src/pages/ProjectUsagePage.tsx`)
- [x] **5.7.10** Build settings page: virtual key management (create/revoke/rotate keys, set per-key budgets and model restrictions), alert config (Slack webhook, email thresholds, budget alerts), team members, danger zone (delete project) (`src/react-app/src/pages/ProjectSettingsPage.tsx`)
- [x] **5.7.11** Build docs section (`/docs`): getting started, config reference, framework adapters, plugin dev guide, API reference (`src/react-app/src/pages/DocsPage.tsx`)

### 5.8 CLI Usage Tracking (LiteLLM SDK CustomLogger) `[P with 5.5]`

- [x] **5.8.1** Implement `NitUsageCallback` (`llm/usage_callback.py`): subclass LiteLLM `CustomLogger`, override `log_success_event` and `async_log_success_event` to capture model, tokens, cost (calculated locally by LiteLLM from bundled pricing data), duration, cache_hit
- [x] **5.8.2** Implement batched HTTP reporter in `NitUsageCallback`: buffer usage events in memory, flush to platform `POST /api/v1/usage/ingest` every N events or every M seconds (configurable), with retry on failure
- [x] **5.8.3** Register `NitUsageCallback` in `LLMEngine` startup: `litellm.callbacks = [NitUsageCallback(...)]` — fires automatically for every `litellm.completion()` and `litellm.acompletion()` call, works with any provider key (BYOK or platform)
- [x] **5.8.4** Pass nit-specific metadata in LLM calls: `metadata={"nit_user_id": ..., "nit_project_id": ..., "nit_session_id": ...}` — available in callback via `kwargs["litellm_params"]["metadata"]`
- [x] **5.8.5** Implement graceful shutdown: flush remaining buffered events on CLI exit via `atexit` handler
- [x] **5.8.6** Write tests for `NitUsageCallback` with mocked LiteLLM responses and mocked HTTP endpoint
- [x] **5.8.7** Add parsing to CLI outputs (calls to claude or codex) and ingest that data in the same manner LiteLLM data is ingested
- [x] **5.8.8** Make sure to notify backend about the type of the usage (API, BYOK or CLI), and model/provider configurations for each event.

### 5.9 CLI ↔ Platform Integration `[P with 5.7]`

- [x] **5.9.1** Implement `nit config set platform.url <url>` and `nit config set platform.api_key <key>` commands
- [x] **5.9.2** When platform API key is configured with platform key mode: CLI sets LiteLLM `base_url` to platform's AI Gateway proxy endpoint (`https://api.getnit.dev/v1/llm-proxy`), all LLM requests route through platform Worker → AI Gateway → providers
- [x] **5.9.3** When platform API key is configured with BYOK mode: CLI uses user's own provider key directly, but `NitUsageCallback` reports usage events to platform `POST /api/v1/usage/ingest` — dashboard shows costs either way
- [x] **5.9.4** Implement report upload in CLI: after `nit hunt --report`, compress results to JSON, POST to `/api/v1/reports`
- [x] **5.9.5** Add `platform_url` and `platform_api_key` inputs to GitHub Action
- [x] **5.9.6** Write tests for CLI → platform integration (both platform-key and BYOK paths)

---

## Phase 6 — Distribution & Packaging

### 6.1 npm Package `[P with 6.2, 6.3]`

- [ ] **6.1.1** Create npm package structure: `npm/package.json` with `bin.nit`, `postinstall.js` for binary download, shell wrapper `bin/nit`
- [ ] **6.1.2** Implement `postinstall.js`: detect OS/arch, download correct platform binary from GitHub Releases, extract to package bin directory
- [ ] **6.1.3** Implement shell wrapper (`bin/nit`): proxy all commands to downloaded binary
- [ ] **6.1.4** Implement Windows batch wrapper (`bin/nit.cmd`)
- [ ] **6.1.5** Register `getnit` on npm, publish first version
- [ ] **6.1.6** Test: `npm install -g getnit && nit --version` on macOS, Linux, Windows
- [ ] **6.1.7** Test: `npx getnit@latest init` works without global install

### 6.2 Homebrew Tap `[P with 6.1]`

- [ ] **6.2.1** Create `getnit/homebrew-tap` repository
- [ ] **6.2.2** Write Homebrew formula (`Formula/nit.rb`): Python virtualenv install from PyPI, tree-sitter dependency
- [ ] **6.2.3** Test: `brew install getnit/tap/nit && nit --version` on macOS
- [ ] **6.2.4** Automate formula update on new releases (via `homebrew-pypi-poet` in CI)

### 6.3 Standalone Binary `[P with 6.1, 6.2]`

- [ ] **6.3.1** Set up PyInstaller build: `--onefile` mode, `--hidden-import nit`, include tree-sitter grammars
- [ ] **6.3.2** Create GitHub Actions build matrix: linux-x64, linux-arm64, macos-x64, macos-arm64, windows-x64
- [ ] **6.3.3** Implement install script (`getnit.dev/install`): detect platform, download binary from GitHub Releases, add to PATH
- [ ] **6.3.4** Implement PowerShell install script (`getnit.dev/install.ps1`) for Windows
- [ ] **6.3.5** Test standalone binary on all 5 platforms
- [ ] **6.3.6** Host install scripts on Cloudflare Workers (served from landing page domain)

### 6.4 Docker `[P with 6.3]`

- [ ] **6.4.1** Create `Dockerfile`: Python 3.12-slim base, `pip install getnit`, workspace volume mount, `ENTRYPOINT ["nit"]`
- [ ] **6.4.2** Create `Dockerfile.test`: includes Node.js + Python + Java for multi-language test execution
- [ ] **6.4.3** Set up GitHub Actions to build and push Docker images to `ghcr.io/getnit/nit` on release
- [ ] **6.4.4** Test: `docker run --rm -v $(pwd):/workspace ghcr.io/getnit/nit:latest hunt`

### 6.5 Release Pipeline

- [ ] **6.5.1** Create `release.yml` GitHub Actions workflow: triggered on tag push `v*`
- [ ] **6.5.2** Build binaries job: matrix build for all 5 platforms
- [ ] **6.5.3** Publish PyPI job: `python -m build && twine upload`
- [ ] **6.5.4** Publish npm job: `npm publish` in npm package directory
- [ ] **6.5.5** Create GitHub Release job: upload all platform binaries as release assets
- [ ] **6.5.6** Update Homebrew tap job: auto-update formula with new version/sha
- [ ] **6.5.7** Build and push Docker images job
- [ ] **6.5.8** Test full release pipeline with a dry run

---

## Phase 7 — Growth (Post-Launch)

### 7.1 VS Code Extension

- [ ] **7.1.1** Create VS Code extension: sidebar panel showing coverage, inline test generation, one-click `nit hunt`
- [ ] **7.1.2** Implement CodeLens for untested functions: "Generate test" link above each untested function
- [ ] **7.1.3** Implement coverage gutter highlighting: green/red indicators per line
- [ ] **7.1.4** Publish to VS Code Marketplace

### 7.2 MCP Server

- [ ] **7.2.1** Implement MCP (Model Context Protocol) server for nit: expose tools for scan, generate, run, drift via MCP
- [ ] **7.2.2** Enable IDE AI assistants (Copilot, Cursor, Claude) to invoke nit tools directly
- [ ] **7.2.3** Write MCP server documentation

### 7.3 Community Adapters

- [ ] **7.3.1** PHP adapter: PHPUnit / Pest, Xdebug/PCOV coverage, phpDocumentor
- [ ] **7.3.2** Ruby adapter: RSpec / Minitest, SimpleCov coverage, YARD/RDoc
- [ ] **7.3.3** Swift adapter: XCTest / Quick+Nimble, Xcode coverage, DocC/Jazzy
- [ ] **7.3.4** Dart/Flutter adapter
- [ ] **7.3.5** Elixir adapter: ExUnit

### 7.4 Advanced Features

- [ ] **7.4.1** Cross-repo contract testing (federation mode): shared drift test definitions across repos
- [ ] **7.4.2** GitHub App (richer integration than Action): installation-level permissions, automatic repo setup
- [ ] **7.4.3** Bazel/Buck2 workspace support
- [ ] **7.4.4** GitLab CI adapter
- [ ] **7.4.5** Bitbucket Pipelines adapter

### 7.5 Infra Detector

- [ ] **7.5.1** Implement `InfraDetector` (`agents/detectors/infra.py`): detect existing CI/CD (`.github/workflows/`, Jenkinsfile), Docker (`Dockerfile`, `docker-compose.yml`), Makefile, scripts/
- [ ] **7.5.2** Use detected infra context to generate CI-compatible test commands and configurations
- [ ] **7.5.3** Write tests for InfraDetector

### 7.6 Dependency Detector

- [ ] **7.6.1** Implement `DependencyDetector` (`agents/detectors/dependency.py`): parse lock files (package-lock.json, yarn.lock, poetry.lock, go.sum, Cargo.lock) + import graphs
- [ ] **7.6.2** Map internal dependencies (which packages depend on which) for monorepo-aware testing
- [ ] **7.6.3** Write tests for DependencyDetector

---

## Utility / Config Tasks (Parallel throughout all phases)

### U.1 Configuration System

- [ ] **U.1.1** Full `.nit.yml` schema documentation with all supported keys, types, defaults, and examples
- [ ] **U.1.2** Implement `nit config show` command: display resolved config with env var values masked
- [ ] **U.1.3** Implement `nit config validate` command: validate `.nit.yml` against schema, report errors
- [ ] **U.1.4** Implement `nit config set <key> <value>` command: update config values programmatically

### U.2 Memory Commands

- [ ] **U.2.1** Implement `nit memory show` command: display memory contents in human-readable format
- [ ] **U.2.2** Implement `nit memory show --package <path>` command: package-specific memory
- [ ] **U.2.3** Implement `nit memory reset` command: clear all memory (start fresh)
- [ ] **U.2.4** Implement `nit memory export` command: export memory as readable markdown report

### U.3 Git Utilities

- [ ] **U.3.1** Implement git operations helper (`utils/git.py`): branch creation, commit, push, diff, log, status
- [ ] **U.3.2** Implement GitHub API client: create issues, PRs, comments; authenticate with `GITHUB_TOKEN`
- [ ] **U.3.3** Write tests for git utilities

### U.4 Template Engine

- [ ] **U.4.1** Implement template engine (`utils/templates.py`): render test stubs, config files, CI workflows from templates with variable substitution
- [ ] **U.4.2** Write tests for template engine
