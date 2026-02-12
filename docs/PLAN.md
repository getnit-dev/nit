# nit

### Open-Source AI Testing, Documentation & Quality Agent

---

## The Problem

Software testing is broken. Here's the reality in 2026:

- **85% of bugs still reach production** despite decades of testing tools
- **Playwright/Cypress require complex setup** — auth flows, environment config, and flaky selectors drain weeks of engineering time
- **Unit test coverage stagnates** because writing tests is tedious and always deprioritized
- **AI-generated code ("vibe coding") is creating a new category of technical debt** — only 29% of developers trust AI code accuracy
- **LLM-powered features drift silently** — model provider updates change your app's behavior and nobody notices
- **Documentation rots** — it's always the last thing updated and first thing abandoned

Existing solutions are either **expensive managed services** (QA Wolf at $4K+/month, Bug0 at $2.5K/month), **closed-source SaaS** (Tusk, Octomind), or **narrow open-source tools** that only cover one slice (Keploy for API replay, Shortest for natural-language E2E, Diffblue for Java unit tests).

**Nobody offers a self-hosted, open-source tool that does the full loop: detect your stack → generate tests at every level → run them → report bugs → auto-fix broken tests → track coverage → monitor LLM drift → keep docs current.**

nit does.

---

## What nit Is

nit is an **open-source, local-first AI quality agent** that:

1. **Auto-detects** your project's language, frameworks, and test infrastructure
2. **Generates tests** across all levels — unit, integration, E2E — using framework-native tooling
3. **Runs continuously** — on every PR, on schedule, or on-demand via CLI
4. **Self-heals** — when UI or API changes break tests, nit updates them
5. **Monitors LLM drift** — if your app uses AI features, nit detects when model outputs change
6. **Optimizes prompts** — analyzes prompt→output pairs and suggests improvements
7. **Generates documentation** — keeps API docs, component docs, and READMEs current with actual code
8. **Reports everything** — GitHub Issues with reproductions, PRs with new/fixed tests, coverage dashboards

### How It Runs

```
# Local CLI
nit init                    # Detect stack, create .nit.yml
nit scan                    # Analyze codebase, find untested code
nit generate                # Generate tests for uncovered code
nit run                     # Run full test suite
nit drift                   # Check LLM endpoints for drift
nit docs                    # Generate/update documentation

# GitHub Action
- uses: nit-ai/nit@v1  # Runs on PR, creates comments/issues/PRs

# Scheduled (cron via GitHub Actions or local)
nit watch --schedule "0 2 * * *"  # Nightly full regression + drift check
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        nit CLI                             │
│                    (Python — core orchestrator)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │   SCANNER    │  │  GENERATOR   │  │     RUNNER         │    │
│  │              │  │              │  │                    │    │
│  │ • Tree-sitter│  │ • LLM engine │  │ • Subprocess mgr  │    │
│  │   AST parse  │  │   (LiteLLM)  │  │ • Parallel exec   │    │
│  │ • Framework  │  │ • Template   │  │ • Result parser    │    │
│  │   detection  │  │   library    │  │ • Coverage merge   │    │
│  │ • Coverage   │  │ • Framework  │  │                    │    │
│  │   mapping    │  │   adapters   │  │                    │    │
│  └──────┬───────┘  └──────┬───────┘  └────────┬───────────┘    │
│         │                 │                    │                │
│  ┌──────┴─────────────────┴────────────────────┴───────────┐   │
│  │                    FRAMEWORK ADAPTERS                     │   │
│  │  (pluggable modules — community-contributed)              │   │
│  │                                                           │   │
│  │  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────────┐  │   │
│  │  │ Python  │ │   JS/TS │ │  C/C++   │ │    Java      │  │   │
│  │  │ pytest  │ │ vitest  │ │ GTest    │ │ JUnit        │  │   │
│  │  │ unittest│ │ jest    │ │ CTest    │ │ TestNG       │  │   │
│  │  └─────────┘ └─────────┘ └──────────┘ └──────────────┘  │   │
│  │  ┌─────────────────┐ ┌──────────────┐ ┌──────────────┐  │   │
│  │  │   E2E           │ │   Docs       │ │  LLM Drift   │  │   │
│  │  │ Playwright      │ │ Sphinx       │ │ Prompt test  │  │   │
│  │  │ Cypress         │ │ TypeDoc      │ │ Output diff  │  │   │
│  │  │ Selenium        │ │ Doxygen      │ │ Semantic cmp │  │   │
│  │  └─────────────────┘ │ JSDoc        │ └──────────────┘  │   │
│  │                      │ MkDocs       │                    │   │
│  │                      └──────────────┘                    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    REPORTER                               │   │
│  │  GitHub Issues • PRs • Comments • JSON • HTML Dashboard  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Technology Choices

| Component | Technology | Why |
|---|---|---|
| **Language** | Python 3.11+ | Fastest ecosystem for AI/LLM tooling, tree-sitter bindings, broad community |
| **AST Parsing** | tree-sitter + tree-sitter-language-pack | Multi-language, incremental, battle-tested (used by GitHub, Neovim) |
| **LLM Interface** | LiteLLM | Model-agnostic — supports OpenAI, Anthropic, Ollama, local models. Users bring their own key or run local |
| **E2E Engine** | Playwright (via subprocess) | Industry standard, headless, cross-browser, best auth handling |
| **Test Execution** | Native runners via subprocess | pytest, vitest, gtest, junit — nit generates code, native tools run it |
| **Coverage** | Istanbul (JS), coverage.py (Python), gcov/lcov (C/C++), JaCoCo (Java) | Native tools, merged into unified report |
| **Documentation** | Sphinx, TypeDoc, Doxygen, JSDoc, MkDocs | Generate with native tools, nit fills the content |
| **CI Integration** | GitHub Actions (primary), GitLab CI, Bitbucket Pipelines | GitHub Action published to Marketplace |
| **Config** | YAML (`.nit.yml`) | Simple, human-readable, version-controllable |
| **Distribution** | pip, pipx, Docker, GitHub Action | Multiple install paths for different workflows |

---

## Detection Engine — How nit Understands Your Project

When you run `nit init`, the Scanner module walks your project and builds a **Project Profile**:

### Step 1: Language Detection

Scan file extensions and parse representative files with tree-sitter to confirm languages:

```
.py → Python       .ts/.tsx → TypeScript    .cpp/.cc/.h → C/C++
.js/.jsx → JavaScript    .java → Java       .go → Go
.rs → Rust          .rb → Ruby              .cs → C#
```

### Step 2: Framework Detection

Check config files, imports, and directory structures:

```
package.json + "vitest" in devDeps          → Vitest
package.json + "jest" in devDeps            → Jest
package.json + "@playwright/test"           → Playwright
package.json + "cypress"                    → Cypress
pyproject.toml + [tool.pytest]              → pytest
requirements.txt + "pytest"                 → pytest
CMakeLists.txt + "enable_testing()"         → CTest/GTest
CMakeLists.txt + "gtest"                    → Google Test
build.gradle + "testImplementation junit"   → JUnit
pom.xml + "<artifactId>junit"              → JUnit
Makefile + "gtest"                          → Google Test
playwright.config.ts                        → Playwright
cypress.config.js                           → Cypress
vitest.config.ts                            → Vitest
jest.config.js                              → Jest
```

### Step 3: Documentation Framework Detection

```
docs/conf.py OR setup.cfg [build_sphinx]    → Sphinx
typedoc.json OR "typedoc" in package.json   → TypeDoc
Doxyfile OR Doxyfile.in                     → Doxygen
mkdocs.yml                                  → MkDocs
jsdoc.json OR "jsdoc" in package.json       → JSDoc
```

### Step 4: LLM Usage Detection

Scan imports and API calls for AI/LLM integration:

```
import openai / from openai               → OpenAI API usage
import anthropic / from anthropic          → Anthropic API usage
import litellm                             → LiteLLM usage
fetch("...api.openai.com...")              → REST-based LLM calls
fetch("...api.anthropic.com...")           → REST-based LLM calls
```

When LLM usage is detected, nit maps prompt→output flows for drift monitoring.

### Step 5: Coverage Mapping

Parse existing tests, map them to source files, identify:

- **Untested files** — source files with zero corresponding tests
- **Undertested functions** — public functions/methods with no test coverage
- **Dead zones** — complex code paths (high cyclomatic complexity) with no coverage
- **Stale tests** — tests referencing code that no longer exists

Output: `.nit/profile.json` — cached, re-scanned on changes.

---

## Test Generation — The Core Engine

### How Generation Works

For each untested or undertested source file:

1. **Parse** the file with tree-sitter → extract functions, classes, methods, dependencies, types
2. **Analyze** imports and call graph → understand what the code touches (DB, API, filesystem, etc.)
3. **Retrieve context** → pull related source files, existing test patterns, project conventions
4. **Prompt LLM** with structured context:
   - Source code being tested
   - Existing test examples from the project (for style matching)
   - Framework-specific test patterns (from adapter template library)
   - Dependency information (what to mock)
5. **Validate** generated test:
   - Parse with tree-sitter → must be syntactically valid
   - Run test → must pass or fail for expected reasons
   - Self-iterate → if test has errors, feed errors back to LLM (up to 3 retries)
6. **Output** verified test file in the project's test directory structure

### Unit Test Generation

**Input:** A source file with untested functions.

**Process:**
```
Source: src/utils/pricing.ts
├── tree-sitter parse → extract: calculateDiscount(price, tier), applyTax(amount, region)
├── Analyze → pure functions, no side effects, types from TS
├── Check existing tests → tests/utils/ exists, uses vitest, describe/it pattern
├── Generate → vitest test matching project conventions
├── Validate → run `npx vitest run tests/utils/pricing.test.ts`
└── Output → tests/utils/pricing.test.ts
```

**Supported test frameworks (Phase 1):**

| Language | Unit Test Framework | Integration Test | Notes |
|---|---|---|---|
| TypeScript/JavaScript | Vitest, Jest | Supertest, MSW | Auto-detect from config |
| Python | pytest, unittest | pytest + fixtures | Fixture generation included |
| C/C++ | Google Test, Catch2 | CTest | CMake integration |
| Java | JUnit 5, TestNG | Spring Boot Test | Gradle/Maven aware |

### Integration Test Generation

For code that touches databases, APIs, or external services:

1. **Detect dependencies** — tree-sitter import analysis + config file scanning
2. **Generate mocks/stubs** — framework-appropriate mocking (MSW for HTTP in JS, unittest.mock for Python, GMock for C++)
3. **Create fixture files** — test data factories based on types/schemas
4. **Wire up test harness** — DB setup/teardown, test containers config, API mock servers

### E2E Test Generation

For web applications with detected Playwright/Cypress:

1. **Route discovery** — parse router configs (Next.js pages/, React Router, Express routes, Django urls.py)
2. **Flow mapping** — identify critical user paths (auth → dashboard → CRUD → logout)
3. **Auth handling** — read `.nit.yml` for auth config:

```yaml
# .nit.yml
e2e:
  base_url: http://localhost:3000
  auth:
    strategy: form  # form | oauth | token | cookie | custom
    login_url: /login
    credentials:
      username_field: email
      password_field: password
      username: test@example.com
      password: ${nit_TEST_PASSWORD}  # env var reference
    wait_for: /dashboard  # URL to confirm auth success
  # or for OAuth:
  auth:
    strategy: oauth
    provider: auth0
    callback_url: /api/auth/callback
    test_token: ${nit_AUTH_TOKEN}
```

4. **Generate Playwright tests** — using page object pattern, with proper waits, data-testid selectors
5. **Self-heal on failure** — when selectors break, nit re-analyzes the DOM and updates

---

## LLM Drift Monitoring

For apps that integrate LLM APIs, nit monitors output quality over time.

### How It Works

1. **Define test cases** in `.nit/drift-tests.yml`:

```yaml
drift_tests:
  - name: "Product description generator"
    endpoint: "src/services/ai/generateDescription.ts"
    # or HTTP endpoint:
    # url: http://localhost:3000/api/generate-description
    inputs:
      - prompt: "Write a product description for a wireless mouse"
        expected_traits:
          - contains_keywords: ["wireless", "mouse", "ergonomic"]
          - max_length: 500
          - tone: "professional"
          - no_hallucination: true
      - prompt: "Describe a running shoe for marathons"
        expected_traits:
          - contains_keywords: ["marathon", "running", "cushion"]
          - sentiment: "positive"
    
  - name: "Customer support classifier"
    endpoint: "src/services/ai/classifyTicket.ts"
    inputs:
      - prompt: "My order hasn't arrived and it's been 2 weeks"
        expected_output: "shipping_issue"
        match: "exact"
      - prompt: "How do I reset my password?"
        expected_output: "account_access"
        match: "exact"
```

2. **nit runs these periodically** — compares current outputs against baseline
3. **Semantic comparison** — not just text diff, but meaning comparison using embeddings
4. **Alert on drift** — creates GitHub Issue with:
   - Which test case drifted
   - Old vs new output (side-by-side)
   - Semantic similarity score
   - Suggested prompt adjustments

### Prompt Optimization

When nit detects drift or poor test results on LLM features:

1. Analyze the prompt→output pairs
2. Identify patterns: token waste, ambiguous instructions, missing constraints
3. Suggest optimized prompts with:
   - Reduced token usage (removing redundant instructions)
   - Clearer output format specifications
   - Better few-shot examples
   - Temperature/parameter recommendations

---

## Documentation Auto-Generation

nit doesn't just generate tests — it keeps documentation synchronized with actual code.

### What It Generates

| Doc Type | Source | Output Framework |
|---|---|---|
| **API docs** | Route handlers + types/schemas | Sphinx (Python), TypeDoc (TS), Doxygen (C++) |
| **Component docs** | React/Vue/Svelte components | TypeDoc + Storybook-compatible MDX |
| **README updates** | Project structure changes | Markdown |
| **Changelog** | Git diff between versions | Markdown (Keep a Changelog format) |
| **Test documentation** | Generated/existing tests | Framework-native (pytest markers, JSDoc on tests) |

### How It Works

1. **Diff detection** — on each run, compare current code AST against last documented state
2. **Extract changes** — new functions, modified signatures, removed endpoints, new components
3. **Generate doc updates** — using LLM with code context + existing doc style
4. **Create PR** — with doc changes as a separate commit, easy to review

### Supported Documentation Frameworks (Phase 1)

- **Sphinx** — Python projects (RST/MyST generation)
- **TypeDoc** — TypeScript projects
- **Doxygen** — C/C++ projects
- **JSDoc** — JavaScript projects
- **MkDocs** — Markdown-based documentation sites (any language)

---

## Configuration

Everything is controlled through `.nit.yml` at project root:

```yaml
# .nit.yml — nit Configuration

# Project detection overrides (usually auto-detected)
project:
  languages: [typescript, python]
  test_frameworks:
    unit: vitest
    e2e: playwright
  doc_framework: typedoc

# LLM configuration
llm:
  # Mode 1: Built-in LiteLLM — user provides their own API key (default)
  mode: builtin
  provider: anthropic          # openai | anthropic | ollama | litellm
  model: claude-sonnet-4-20250514  # any model supported by LiteLLM
  api_key: ${ANTHROPIC_API_KEY}

  # Mode 2: Platform key — user gets a single key from getnit.dev
  # platform. LLM requests route through Hono Worker → AI Gateway,
  # which handles provider keys, caching, routing. D1 tracks usage/budgets.
  # mode: builtin
  # base_url: https://platform.getnit.dev/v1/llm-proxy  # platform AI Gateway endpoint
  # api_key: ${NIT_PLATFORM_API_KEY}                # virtual key issued by platform
  # model: claude-sonnet                             # model alias

  # Mode 3: CLI tool delegation (subprocess)
  # mode: cli
  # tool: claude               # claude | codex | aider | ollama | custom

  # Mode 4: Local models via Ollama
  # mode: ollama
  # model: codellama:13b
  # base_url: http://localhost:11434

# Test generation settings
generate:
  unit:
    enabled: true
    style: describe_it          # describe_it | test_function | class_based
    coverage_target: 80         # percentage
    mock_strategy: auto         # auto | minimal | comprehensive
    include:
      - "src/**/*.ts"
      - "src/**/*.py"
    exclude:
      - "src/**/*.d.ts"
      - "src/**/migrations/**"
  integration:
    enabled: true
    mock_externals: true        # auto-mock HTTP calls, DB, etc.
  e2e:
    enabled: true
    base_url: http://localhost:3000
    auth:
      strategy: form
      login_url: /login
      credentials:
        username: test@example.com
        password: ${nit_TEST_PASSWORD}
    flows:                      # critical paths to always test
      - name: "User signup"
        entry: /signup
      - name: "Checkout"
        entry: /cart

# LLM drift monitoring
drift:
  enabled: true
  schedule: "0 2 * * *"        # cron expression for scheduled checks
  tests: .nit/drift-tests.yml

# Documentation
docs:
  enabled: true
  framework: typedoc            # sphinx | typedoc | doxygen | jsdoc | mkdocs
  output: docs/
  auto_update: true             # update docs on every PR

# Reporting
report:
  github_issues: true           # create issues for bugs found
  github_prs: true              # create PRs with new/fixed tests
  github_comments: true         # comment on PRs with coverage delta
  dashboard: true               # generate HTML coverage dashboard
  slack_webhook: ${SLACK_WEBHOOK_URL}  # optional
```

---

## GitHub Action Integration

```yaml
# .github/workflows/nit.yml
name: nit QA
on:
  pull_request:
    types: [opened, synchronize]
  schedule:
    - cron: '0 2 * * *'        # Nightly full run

jobs:
  nit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: nit-ai/nit@v1
        with:
          mode: pr              # pr | full | drift | docs
          llm_provider: anthropic
          llm_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
        env:
          nit_TEST_PASSWORD: ${{ secrets.TEST_PASSWORD }}
      
      # nit automatically:
      # 1. Analyzes changed files in the PR
      # 2. Generates tests for new/modified code
      # 3. Runs existing + new tests
      # 4. Comments on PR with coverage report
      # 5. Creates separate PR with generated tests (if any)
      # 6. Checks LLM drift (if configured)
      # 7. Updates docs (if configured)
```

### PR Comment Output

When nit runs on a PR, it posts a comment like:

```
## 🛡️ nit QA Report

### Coverage
| File | Before | After | Delta |
|------|--------|-------|-------|
| src/services/pricing.ts | 45% | 82% | +37% ✅ |
| src/api/orders.ts | 0% | 68% | +68% ✅ |
| src/utils/auth.ts | 91% | 91% | — |

**Overall: 67% → 78%** (+11%)

### Generated Tests
- ✅ 4 unit tests for `pricing.ts` → [View PR #142](#)
- ✅ 2 integration tests for `orders.ts` → [View PR #142](#)
- ⚠️ 1 E2E test for checkout flow → needs auth config

### Issues Found
- 🐛 `calculateDiscount()` returns NaN for negative prices → [Issue #88](#)
- 🐛 `/api/orders` returns 500 when cart is empty → [Issue #89](#)

### LLM Drift
- ✅ All 6 prompt test cases passing
- ⚠️ `generateDescription` output length increased 23% since last baseline
```

---

## Implementation Roadmap

### Phase 1 — Foundation (Weeks 1–4)

**Goal: Working CLI that detects stack and generates unit tests for 2 languages.**

| Week | Deliverable |
|---|---|
| 1 | Project scaffolding (Python, Click CLI, project structure). Scanner module: language detection via file extensions + tree-sitter validation. Framework detection for JS/TS (vitest, jest, playwright) and Python (pytest). Output: `.nit/profile.json`. |
| 2 | Generator engine: LLM interface via LiteLLM. Template library for vitest and pytest patterns. AST-powered context extraction (functions, classes, imports, types). Test generation pipeline: parse → context → prompt → validate → output. |
| 3 | Test validation loop: run generated tests via subprocess, parse output, self-iterate on failures (up to 3 retries). Coverage integration: Istanbul for JS/TS, coverage.py for Python. Coverage mapping to identify untested code. |
| 4 | CLI polish: `nit init`, `nit scan`, `nit generate`, `nit run`. Config file support (`.nit.yml`). README, installation docs, first GitHub release. |

**Phase 1 Exit:** `pip install nit-ai && nit init && nit generate` works on a Next.js or Python project.

### Phase 2 — CI + E2E (Weeks 5–8)

| Week | Deliverable |
|---|---|
| 5 | GitHub Action wrapper. PR analysis mode (only test changed files). PR comment reporting with coverage delta. |
| 6 | E2E generation: route discovery for Next.js/Express. Playwright test generation with page object pattern. Auth flow support (form-based, token-based). |
| 7 | Self-healing: when tests fail due to selector/API changes, re-analyze and regenerate. Flaky test detection (run 3x, mark flaky). |
| 8 | Integration test generation: mock detection, fixture generation. Test PR creation (separate PR with generated tests for review). |

**Phase 2 Exit:** Full GitHub Action that generates unit + integration + E2E tests on PRs, comments with coverage, creates test PRs.

### Phase 3 — C/C++ & Java + LLM Drift (Weeks 9–14)

| Week | Deliverable |
|---|---|
| 9–10 | C/C++ adapter: GTest/Catch2 generation, CMake integration, gcov/lcov coverage. |
| 11–12 | Java adapter: JUnit 5 generation, Gradle/Maven integration, JaCoCo coverage. |
| 13 | LLM drift monitoring: drift test YAML spec, semantic comparison engine (embeddings-based), scheduled checking. |
| 14 | Prompt optimization module: token analysis, prompt compression suggestions, few-shot optimization. |

**Phase 3 Exit:** 4 language ecosystems supported. LLM drift monitoring working.

### Phase 4 — Documentation + Community (Weeks 15–20)

| Week | Deliverable |
|---|---|
| 15–16 | Documentation generator: TypeDoc, Sphinx, Doxygen adapters. Diff-based doc updates (only regenerate changed sections). Changelog generation from git history. |
| 17–18 | Plugin/adapter system formalization: clear API for community-contributed framework adapters. Adapter contribution guide + template. |
| 19 | HTML dashboard for coverage trends, drift history, test health. Slack/Discord webhook notifications. |
| 20 | Performance optimization, comprehensive test suite for nit itself, documentation site, launch prep. |

**Phase 4 Exit:** Full product with docs generation, plugin ecosystem, dashboard. Ready for public launch.

---

## Plugin / Adapter System

The community growth story depends on easy extensibility. Each framework adapter follows a standard interface:

```python
# nit/adapters/base.py

class TestFrameworkAdapter(ABC):
    """Base class for all test framework adapters."""
    
    @abstractmethod
    def detect(self, project_path: Path) -> bool:
        """Return True if this framework is present in the project."""
        pass
    
    @abstractmethod
    def get_test_pattern(self) -> str:
        """Return glob pattern for test files (e.g., '**/*.test.ts')."""
        pass
    
    @abstractmethod
    def get_prompt_template(self) -> str:
        """Return the LLM prompt template for generating tests."""
        pass
    
    @abstractmethod
    def run_tests(self, test_files: list[Path]) -> TestResult:
        """Execute tests and return structured results."""
        pass
    
    @abstractmethod
    def get_coverage(self, project_path: Path) -> CoverageReport:
        """Run coverage analysis and return unified report."""
        pass
    
    @abstractmethod
    def validate_test(self, test_code: str) -> ValidationResult:
        """Validate generated test is syntactically correct."""
        pass


class DocFrameworkAdapter(ABC):
    """Base class for documentation framework adapters."""
    
    @abstractmethod
    def detect(self, project_path: Path) -> bool:
        pass
    
    @abstractmethod
    def generate(self, sources: list[SourceFile], existing_docs: Path) -> list[DocFile]:
        pass
    
    @abstractmethod
    def build(self, project_path: Path) -> BuildResult:
        pass
```

### Contributing an Adapter

```
nit/adapters/
├── base.py                 # Abstract base classes
├── unit/
│   ├── vitest.py           # Vitest adapter (built-in)
│   ├── jest.py             # Jest adapter (built-in)
│   ├── pytest_adapter.py   # pytest adapter (built-in)
│   ├── gtest.py            # Google Test adapter (built-in)
│   ├── junit.py            # JUnit adapter (built-in)
│   └── ...                 # Community adapters
├── e2e/
│   ├── playwright.py       # Playwright adapter (built-in)
│   ├── cypress.py          # Cypress adapter (built-in)
│   └── ...
├── integration/
│   ├── supertest.py
│   ├── pytest_integration.py
│   └── ...
├── docs/
│   ├── typedoc.py
│   ├── sphinx.py
│   ├── doxygen.py
│   └── ...
└── drift/
    ├── openai_drift.py
    ├── anthropic_drift.py
    └── generic_http.py
```

Community contributors can add new adapters by implementing the base class and submitting a PR. nit auto-discovers adapters at runtime.

---

## Competitive Positioning

| Feature | nit | Tusk | QA Wolf | Bug0 | Keploy | Shortest |
|---|---|---|---|---|---|---|
| Open source | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Self-hosted | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Unit tests | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Integration tests | ✅ | ✅ | ❌ | ❌ | ✅ (API only) | ❌ |
| E2E tests | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ |
| Multi-language | ✅ (4+) | ✅ (6+) | JS only | Web only | Go/JS/Python/Java | JS only |
| C/C++ support | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| LLM drift monitoring | ✅ | ✅ (API drift) | ❌ | ❌ | ❌ | ❌ |
| Prompt optimization | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Doc generation | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| GitHub Action | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Auth handling | ✅ (config) | N/A | ✅ (human) | ✅ (human) | N/A | ❌ |
| Self-healing tests | ✅ | ✅ | ✅ (human) | ✅ | ❌ | ❌ |
| Price | Free | SaaS | $4K+/mo | $699+/mo | Free | Free |

**nit's unique position:** The only open-source tool that covers the full testing pyramid + LLM drift + documentation in a single, self-hosted CLI.

---

## Naming & Identity

**nit** — a guardian that watches over your codebase. Evokes vigilance, protection, and autonomy.

- `nit-ai` on PyPI and npm
- `nit-ai/nit` on GitHub
- CLI command: `nit`
- GitHub Action: `nit-ai/nit@v1`

Alternative names to check availability: **Vigil**, **Watchpost**, **Aegis**, **Overwatch**, **Bastion**

---

## Success Metrics

| Milestone | Target | Timeline |
|---|---|---|
| GitHub stars | 500 | Month 2 |
| GitHub stars | 5,000 | Month 6 |
| Framework adapters | 10+ (including community) | Month 6 |
| Weekly active users | 1,000 | Month 4 |
| Languages supported | 6+ | Month 6 |
| First external contributor | — | Month 1 |

---

## What Makes This Viral

1. **Instant gratification** — `pip install nit-ai && nit init && nit generate` gives you tests in minutes, not days
2. **The coverage badge** — projects display nit coverage badges, driving organic discovery
3. **"It found a bug" moments** — nit catches real bugs during generation (testing impossible states, null cases, edge conditions) — these get shared on social media
4. **Framework adapter contributions** — community members add their favorite frameworks, creating investment and advocacy
5. **The LLM drift angle** — unique feature nobody else offers as open-source, speaks directly to the "vibe coding" anxiety
6. **C/C++ support** — massively underserved by AI testing tools (most focus on web), taps into embedded/systems community (and your RoboTicks audience)



Rework:
# Project Plan: Open-Source AI Quality Agent

## Comprehensive Technical Specification & Implementation Blueprint

---

## 1. Naming

The name needs to be short, memorable, slightly aggressive/protective, dev-friendly, and not taken on npm/PyPI/GitHub.

### Top Picks

| Name | Vibe | Why It Works |
|---|---|---|
| **nit** | Slavic root for "forge/smith" | Short, unique, sounds like "cover" (coverage), easy to type, `.nit.yml` looks clean |
| **predar** | Bosnian/Serbian for "predator" | Aggressive, memorable, hunts bugs — speaks to your roots |
| **argus** | The hundred-eyed giant from Greek mythology | Watches everything, never sleeps — perfect for a testing guardian |
| **prober** | One who probes/investigates | Direct, action-oriented, `prober scan` feels natural |
| **sova** | Slavic for "owl" | Wise, sees in the dark, watches over your code at night |
| **vigil** | Keeping watch | `vigil run`, `vigil scan` — clean CLI feel, evokes 24/7 monitoring |
| **hound** | A tracker that never gives up | `hound sniff`, `hound chase` — fun CLI commands, aggressive energy |
| **recon** | Reconnaissance | Military precision, `recon scan`, `recon report` — implies thoroughness |
| **paladin** | Holy defender/guardian | RPG energy (fits your game dev background), protects the codebase |
| **bulwark** | A defensive wall | Strong protection metaphor, `bulwark check` feels solid |

### Recommendation: **nit**

- 4 letters, easy to type everywhere
- `nit init`, `nit scan`, `nit pick` — clean CLI ergonomics
- `.nit/` directory, `.nit.yml` config — looks professional
- Culturally meaningful to you (Slavic origin)
- Phonetically close to "cover" (coverage) — subconscious association
- Highly likely available on npm, PyPI, GitHub
- Works as a brand: "nit — forging quality into every commit"

> Throughout this document, we'll use **nit** as the project name. Replace with final choice.

---

## 2. Vision Statement

**nit is an open-source, local-first AI quality swarm that autonomously detects your stack, generates tests at every level, hunts bugs, fixes them, monitors LLM drift, and keeps documentation current — learning and improving with every run.**

It runs locally or in CI. It supports monorepos with mixed languages. It remembers what it learns. It gets smarter over time.

---

## 3. Supported Languages & Frameworks (Phase 1)

### Core Language Matrix

| Language | Unit Test Frameworks | Integration Test | E2E | Coverage Tool | Doc Framework |
|---|---|---|---|---|---|
| **JavaScript** | Jest, Vitest, Mocha+Chai | Supertest, MSW, Nock | Playwright, Cypress | Istanbul/c8 | JSDoc, TypeDoc |
| **TypeScript** | Vitest, Jest, ts-jest | Supertest, MSW | Playwright, Cypress | Istanbul/c8 | TypeDoc |
| **Python** | pytest, unittest, nose2 | pytest + fixtures, httpx | Playwright (Python), Selenium | coverage.py, pytest-cov | Sphinx, MkDocs |
| **Java** | JUnit 5, TestNG | Spring Boot Test, Mockito | Selenium, Playwright (Java) | JaCoCo | Javadoc, Dokka |
| **C/C++** | Google Test, Catch2 | CTest | N/A (API-level) | gcov, lcov, llvm-cov | Doxygen |
| **Go** | go test, Testify, Ginkgo | go test + httptest | N/A (API-level) | go tool cover | godoc, pkgsite |
| **Rust** | cargo test, #[test] | cargo test (integration) | N/A (API-level) | cargo-tarpaulin, llvm-cov | rustdoc, mdBook |
| **C#/.NET** | xUnit, NUnit, MSTest | TestServer, Moq | Playwright (.NET) | coverlet, dotCover | DocFX, xmldoc |
| **Kotlin** | JUnit 5, Kotest, Spek | Spring Boot Test, MockK | Playwright (Java) | JaCoCo, Kover | Dokka |
| **PHP** | PHPUnit, Pest | PHPUnit (integration) | Playwright, Cypress | Xdebug, PCOV | phpDocumentor |
| **Ruby** | RSpec, Minitest | RSpec (request specs) | Capybara, Playwright | SimpleCov | YARD, RDoc |
| **Swift** | XCTest, Quick+Nimble | XCTest (integration) | XCUITest | Xcode coverage | DocC, Jazzy |

### Phase 1 Priority (First 8 weeks)

**Tier 1 (Weeks 1–4):** JavaScript/TypeScript (Vitest, Jest, Playwright), Python (pytest)
**Tier 2 (Weeks 5–8):** C/C++ (GTest, Catch2), Go (go test, Testify), Java (JUnit 5)
**Tier 3 (Weeks 9–14):** Rust, C#/.NET, Kotlin
**Tier 4 (Community-contributed):** PHP, Ruby, Swift, Dart, Elixir, etc.

---

## 4. Monorepo & Multi-Repo Architecture

### The Problem

Real-world projects aren't single-language, single-framework repos. A typical monorepo might contain:

```
my-platform/
├── apps/
│   ├── web/              # Next.js (TypeScript, Vitest, Playwright)
│   ├── mobile/           # React Native (TypeScript, Jest)
│   └── api/              # Go (go test, Testify)
├── packages/
│   ├── shared-types/     # TypeScript (Vitest)
│   ├── auth-lib/         # Python (pytest)
│   └── core-engine/      # C++ (GTest)
├── services/
│   ├── ml-pipeline/      # Python (pytest)
│   └── data-ingestion/   # Rust (cargo test)
├── turbo.json / nx.json / pnpm-workspace.yaml
└── .nit.yml
```

### How nit Handles This

**Auto-discovery through workspace detection:**

```
Workspace Detectors (run in order):
1. Turborepo     → turbo.json → extract packages from pipeline config
2. Nx            → nx.json / project.json → extract project graph
3. pnpm          → pnpm-workspace.yaml → extract workspace globs
4. Yarn          → package.json workspaces field
5. npm           → package.json workspaces field
6. Cargo         → Cargo.toml [workspace] members
7. Go            → go.work → extract use directives
8. Gradle        → settings.gradle(.kts) → extract include()
9. Maven         → pom.xml → extract <modules>
10. Bazel        → WORKSPACE / BUILD files
11. CMake        → CMakeLists.txt → add_subdirectory() calls
12. Generic      → Walk directories, detect by config files per package
```

Each discovered package/project gets its own:
- **Detection profile** (language, frameworks, dependencies)
- **Memory file** (learning history — see §6)
- **Test plan** (what needs coverage, what exists)
- **Coverage report** (independent tracking)

### Configuration: Monorepo `.nit.yml`

```yaml
# .nit.yml (root)
version: 1

# Global settings inherited by all packages
global:
  llm:
    mode: builtin                        # builtin | cli | ollama | custom
    provider: anthropic                  # when mode=builtin: openai | anthropic | ollama
    model: claude-sonnet-4-20250514
    api_key: ${ANTHROPIC_API_KEY}
    # Or use platform key (replaces provider/api_key above):
    # base_url: https://platform.getnit.dev/v1/llm-proxy
    # api_key: ${NIT_PLATFORM_API_KEY}
  memory:
    enabled: true
    path: .nit/memory/        # Root memory directory
  report:
    github_issues: true
    github_prs: true

# Workspace auto-detection (or manual override)
workspace:
  auto_detect: true            # Auto-detect workspace tool
  # Manual override:
  # packages:
  #   - apps/*
  #   - packages/*
  #   - services/*

# Per-package overrides
packages:
  "apps/web":
    e2e:
      enabled: true
      base_url: http://localhost:3000
      auth:
        strategy: form
        login_url: /login
        credentials:
          username: test@example.com
          password: ${TEST_PASSWORD}
  
  "services/ml-pipeline":
    drift:
      enabled: true
      tests: .nit/drift/ml-pipeline.yml
  
  "packages/core-engine":
    generate:
      unit:
        framework: gtest          # Override auto-detection
        mock_strategy: comprehensive
    docs:
      framework: doxygen

# Packages to ignore
ignore:
  - "node_modules"
  - ".git"
  - "dist"
  - "build"
  - "vendor"
  - "**/*.generated.*"
```

### Split Repo Support

For organizations with separate repos, nit works identically — each repo is treated as a single-package workspace. No special config needed.

For cross-repo testing (e.g., testing API contracts between frontend and backend repos), nit supports a **federation mode** via shared drift test definitions:

```yaml
# In frontend repo .nit.yml
federation:
  contracts:
    - name: "user-api"
      source: "github.com/myorg/backend-api/.nit/contracts/user.yml"
      # Validates frontend's API client against backend's contract
```

---

## 5. Swarm Architecture — The Agent System

### Core Philosophy

nit doesn't run as a monolithic pipeline. It operates as a **swarm of specialized agents**, each with a clear responsibility, communicating through a shared work queue and memory system. Agents can run in parallel, hand off work to each other, and make autonomous decisions.

Think of it like a QA team where each person has a specialty:

```
                         ┌──────────────────┐
                         │   ORCHESTRATOR   │
                         │  (nit CLI/CI)   │
                         └────────┬─────────┘
                                  │ dispatches tasks
                    ┌─────────────┼─────────────┐
                    ▼             ▼               ▼
             ┌────────────┐ ┌──────────┐  ┌─────────────┐
             │ DETECTORS  │ │ ANALYZERS│  │  WATCHERS    │
             │            │ │          │  │              │
             │ • Stack    │ │ • Code   │  │ • Drift      │
             │ • Framework│ │ • Coverage│  │ • Schedule   │
             │ • Workspace│ │ • Dep    │  │ • Webhook    │
             │ • LLM usage│ │ • Risk   │  │              │
             └─────┬──────┘ └────┬─────┘  └──────┬───────┘
                   │             │                │
                   ▼             ▼                ▼
             ┌─────────────────────────────────────────┐
             │           WORK QUEUE (in-memory)         │
             │                                          │
             │  [analyze:src/api.ts] [generate:unit]    │
             │  [build:e2e-suite] [debug:pricing-bug]   │
             │  [doc:update-readme] [drift:check-gpt]   │
             └─────────────────┬───────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                     ▼
   ┌────────────┐     ┌──────────────┐      ┌────────────┐
   │  BUILDERS  │     │  DEBUGGERS   │      │  REPORTERS  │
   │            │     │              │      │             │
   │ • Unit     │     │ • Bug verify │      │ • GitHub PR │
   │ • Integr.  │     │ • Root cause │      │ • Issues    │
   │ • E2E      │     │ • Fix gen    │      │ • Dashboard │
   │ • Doc      │     │ • Fix verify │      │ • Comments  │
   │ • Infra    │     │              │      │ • Slack     │
   └─────┬──────┘     └──────┬───────┘      └──────┬──────┘
         │                   │                      │
         └───────────────────┼──────────────────────┘
                             ▼
                    ┌─────────────────┐
                    │     MEMORY      │
                    │  (per-package)  │
                    │                 │
                    │ • Patterns      │
                    │ • Failures      │
                    │ • Preferences   │
                    │ • History       │
                    └─────────────────┘
```

### Agent Definitions

#### 1. Detectors

**Purpose:** Understand what exists in the codebase. Run first, inform everything else.

| Detector | What It Does | Approach |
|---|---|---|
| **StackDetector** | Identifies languages in each package | File extension scan + tree-sitter validation + frequency analysis |
| **FrameworkDetector** | Identifies test/web/doc frameworks | Config file heuristics (package.json, pyproject.toml, CMakeLists.txt, go.mod, etc.) + import scanning via tree-sitter AST. Falls back to LLM classification for ambiguous cases |
| **WorkspaceDetector** | Maps monorepo structure | Detects workspace tools (Turbo, Nx, pnpm, Cargo workspace, Go workspace, Gradle multi-project, Maven multi-module, Bazel). Maps dependency graph between packages |
| **DependencyDetector** | Maps internal + external deps | Parse lock files + import graphs. Understands which packages depend on which |
| **LLMUsageDetector** | Finds AI/LLM integrations | Scans for OpenAI/Anthropic/Ollama SDK imports, HTTP calls to LLM endpoints, prompt templates |
| **InfraDetector** | Detects existing CI/CD, Docker, etc. | Scans `.github/workflows/`, `Dockerfile`, `docker-compose.yml`, Makefile, scripts/ |

**Output:** `ProjectProfile` — a complete structural understanding of the codebase stored in `.nit/profile.json`.

**Heuristics + AI fallback pattern:**
```
1. Try deterministic heuristics first (config file existence, known patterns)
2. If confidence < 80%, use tree-sitter AST to scan imports/patterns
3. If still ambiguous, ask LLM: "Given these files and imports, what framework is this?"
4. Cache result in memory — don't re-detect on next run unless files changed
```

#### 2. Analyzers

**Purpose:** Understand what needs work. Identify gaps, risks, and bugs.

| Analyzer | What It Does | Output |
|---|---|---|
| **CoverageAnalyzer** | Maps existing test coverage to source files | Gap report: which files/functions are untested |
| **CodeAnalyzer** | Parses source code via tree-sitter — extracts functions, classes, types, complexity | Structured code map per file |
| **RiskAnalyzer** | Identifies high-risk code (complex, recently changed, no tests, handles money/auth/PII) | Prioritized risk score per file/function |
| **DiffAnalyzer** | In PR mode: analyzes only changed files | Delta-focused work list |
| **PatternAnalyzer** | Examines existing tests to learn project conventions (naming, structure, assertion style, mocking patterns) | Convention profile stored in memory |
| **BugAnalyzer** | During test generation/execution: identifies actual bugs (not test bugs) | Bug reports with reproduction steps |

**Work distribution:** Analyzers create tasks for Builders and Debuggers:

```python
# Pseudocode: Analyzer decision tree
for file in changed_or_uncovered_files:
    analysis = code_analyzer.analyze(file)
    risk = risk_analyzer.score(file)
    
    if analysis.has_untested_functions:
        queue.add(BuildTask(
            type="unit",
            target=file,
            functions=analysis.untested_functions,
            priority=risk.score
        ))
    
    if analysis.has_untested_integrations:
        queue.add(BuildTask(
            type="integration",
            target=file,
            integrations=analysis.external_calls,
            priority=risk.score
        ))
    
    if analysis.has_user_facing_routes:
        queue.add(BuildTask(
            type="e2e",
            target=file,
            routes=analysis.routes,
            priority=risk.score
        ))
    
    if analysis.has_outdated_docs:
        queue.add(BuildTask(
            type="docs",
            target=file,
            changes=analysis.doc_delta
        ))
```

#### 3. Builders

**Purpose:** Create things — tests, documentation, infrastructure. The productive agents.

| Builder | What It Does | Integrates With |
|---|---|---|
| **UnitBuilder** | Generates unit tests using framework adapters | Jest, Vitest, pytest, GTest, Catch2, go test, Testify, JUnit, xUnit, cargo test, Kotest, PHPUnit, RSpec, XCTest |
| **IntegrationBuilder** | Generates integration tests with proper mocking | Supertest, MSW, pytest fixtures, httptest (Go), Spring Boot Test, Mockito |
| **E2EBuilder** | Generates end-to-end browser tests | Playwright (primary), Cypress |
| **DocBuilder** | Generates/updates documentation | TypeDoc, Sphinx, Doxygen, JSDoc, godoc, rustdoc, Javadoc, Dokka, DocFX, MkDocs |
| **InfraBuilder** | Sets up test infrastructure when none exists | Creates test config files, CI workflows, Docker test environments, installs dependencies |

**Builder pipeline (per test file):**

```
1. CONTEXT ASSEMBLY
   ├── Source code (tree-sitter parsed)
   ├── Existing test patterns from memory (PatternAnalyzer output)
   ├── Framework adapter templates
   ├── Import/dependency graph
   ├── Type information (if available)
   └── Related source files (call graph neighbors)

2. LLM GENERATION
   ├── Structured prompt with full context
   ├── Model selected per user config (Claude, GPT, Ollama, local)
   └── Or: CLI tool invocation (see §7: CLI Tool Integration)

3. VALIDATION
   ├── tree-sitter parse → must be syntactically valid
   ├── Run test → capture result
   │   ├── PASS → great, keep it
   │   ├── FAIL (test bug) → self-iterate (up to 3x)
   │   ├── FAIL (code bug) → hand off to BugAnalyzer → Debugger
   │   └── ERROR (missing dep) → hand off to InfraBuilder
   └── Coverage check → did this actually improve coverage?

4. OUTPUT
   ├── Write test file to correct location
   ├── Update memory with patterns used
   └── Create BuildReport for Reporter
```

**InfraBuilder — the "bootstrapper":**

When nit detects a project with NO existing test infrastructure, InfraBuilder can set it up:

```
Detected: TypeScript project with Next.js, no test framework installed

InfraBuilder actions:
1. Install vitest + @testing-library/react as devDependencies
2. Create vitest.config.ts with proper Next.js settings
3. Create test/setup.ts with common mocks
4. Install Playwright for E2E
5. Create playwright.config.ts with sensible defaults
6. Create .github/workflows/test.yml with CI pipeline
7. Create first example test to verify setup works
8. Add scripts to package.json: "test", "test:unit", "test:e2e"
```

This can run in Docker (isolated) or locally, per user preference:

```yaml
# .nit.yml
infra:
  execution: docker    # docker | local
  docker:
    image: node:20     # auto-selected based on detected stack
    volumes:
      - .:/workspace
```

#### 4. Debuggers

**Purpose:** When bugs are found (during analysis or test execution), Debuggers investigate and fix.

| Debugger | What It Does |
|---|---|
| **BugVerifier** | Takes a suspected bug from BugAnalyzer, creates a minimal reproduction, confirms it's real |
| **RootCauseAnalyzer** | Uses code analysis + LLM to trace the bug to its root cause |
| **FixGenerator** | Generates a potential fix for the bug |
| **FixVerifier** | Runs the fix through existing + new tests to verify it doesn't break anything |

**Debugger pipeline:**

```
BugAnalyzer detects: calculateDiscount() returns NaN for negative prices

1. BugVerifier
   ├── Generate minimal test case proving the bug
   ├── Run it → confirmed: NaN returned
   └── Output: VerifiedBug { file, function, input, expected, actual, test_case }

2. RootCauseAnalyzer
   ├── Parse function with tree-sitter
   ├── Trace data flow: price → Math.round(price * discount)
   ├── Identify: no guard for negative input, discount can be > 1.0
   └── Output: RootCause { location: line 42, issue: "no input validation" }

3. FixGenerator
   ├── Generate fix: add input validation, clamp discount range
   ├── Apply fix to a branch
   └── Output: ProposedFix { patch, explanation }

4. FixVerifier
   ├── Run existing tests → all pass
   ├── Run new regression test → passes
   ├── Run related tests → no regressions
   └── Output: VerifiedFix { patch, test_results, confidence_score }

5. Reporter creates:
   ├── GitHub Issue (bug report with reproduction)
   └── GitHub PR (fix + new test, linked to issue)
```

#### 5. Watchers

**Purpose:** Continuous monitoring — LLM drift, scheduled checks, webhook-triggered runs.

| Watcher | What It Does |
|---|---|
| **DriftWatcher** | Runs LLM drift tests on schedule, compares against baselines |
| **ScheduleWatcher** | Executes full test suite on cron schedule (nightly regression) |
| **WebhookWatcher** | Listens for GitHub webhook events to trigger runs |
| **CoverageWatcher** | Tracks coverage trends over time, alerts on drops |

#### 6. Reporters

**Purpose:** Communicate findings to humans. The output layer.

| Reporter | Output |
|---|---|
| **GitHubPRReporter** | Creates PRs with generated tests, descriptive commit messages, test explanations |
| **GitHubIssueReporter** | Creates issues for bugs with reproduction steps, screenshots, logs |
| **GitHubCommentReporter** | Comments on PRs with coverage delta, test results, drift status |
| **DashboardReporter** | Generates HTML dashboard with coverage trends, bug history, test health |
| **SlackReporter** | Sends webhook notifications for critical events |
| **CLIReporter** | Rich terminal output with colors, progress bars, summaries |

---

## 6. Memory System

### Core Concept

nit gets smarter the longer it runs on your project. Memory is stored as JSON files in `.nit/memory/` and is version-controlled alongside your code.

### Memory Architecture

```
.nit/
├── memory/
│   ├── global.json                    # Repo-wide patterns and preferences
│   ├── packages/
│   │   ├── apps--web.json             # Memory for apps/web
│   │   ├── apps--api.json             # Memory for apps/api
│   │   ├── packages--auth-lib.json    # Memory for packages/auth-lib
│   │   └── services--ml-pipeline.json # Memory for services/ml-pipeline
│   └── drift/
│       └── baselines.json             # LLM drift baselines
├── profile.json                       # Cached project detection profile
└── .nit.yml                          # Config (at repo root)
```

### What Memory Stores

#### Global Memory (`global.json`)

```json
{
  "version": 1,
  "created_at": "2026-02-10T00:00:00Z",
  "updated_at": "2026-02-15T00:00:00Z",
  
  "project_conventions": {
    "test_naming": "describe_it",
    "file_naming": "{name}.test.{ext}",
    "preferred_assertions": "expect",
    "mock_style": "vi.mock() with factory",
    "test_location": "colocated"
  },
  
  "known_patterns": {
    "auth_pattern": "JWT + refresh token, middleware at /api/*",
    "db_pattern": "Prisma ORM, PostgreSQL",
    "state_management": "Zustand stores in /stores"
  },
  
  "historical_bugs": [
    {
      "id": "bug-001",
      "date": "2026-02-12",
      "file": "src/utils/pricing.ts",
      "description": "NaN returned for negative prices",
      "root_cause": "Missing input validation",
      "fix_applied": true,
      "regression_test": "tests/utils/pricing.test.ts:42"
    }
  ],
  
  "generation_stats": {
    "total_tests_generated": 847,
    "tests_accepted": 823,
    "tests_rejected": 24,
    "bugs_found": 12,
    "bugs_fixed": 9,
    "coverage_improvement": "+34%"
  },
  
  "failed_patterns": [
    {
      "pattern": "Tried mocking Prisma with vi.mock('prisma') — doesn't work",
      "solution": "Must mock @prisma/client and provide type-safe mock",
      "learned_from": "apps/web",
      "occurrences": 3
    }
  ]
}
```

#### Package Memory (`packages/apps--web.json`)

```json
{
  "package": "apps/web",
  "language": "typescript",
  "frameworks": {
    "unit": "vitest",
    "e2e": "playwright",
    "web": "next.js"
  },
  
  "test_patterns": {
    "component_tests": {
      "template": "describe → render → assert",
      "imports": ["@testing-library/react", "vitest"],
      "setup": "Uses custom renderWithProviders wrapper",
      "example_file": "tests/components/Button.test.tsx"
    },
    "api_route_tests": {
      "template": "describe → mock request → call handler → assert response",
      "mocking": "MSW for external APIs, vi.mock for internal",
      "example_file": "tests/api/orders.test.ts"
    },
    "hook_tests": {
      "template": "renderHook → act → assert",
      "imports": ["@testing-library/react-hooks"],
      "example_file": "tests/hooks/useAuth.test.ts"
    }
  },
  
  "known_issues": {
    "flaky_selectors": [
      "[data-testid='modal-close'] sometimes takes 2s to render"
    ],
    "env_requirements": [
      "NEXT_PUBLIC_API_URL must be set for API tests"
    ]
  },
  
  "coverage_history": [
    { "date": "2026-02-10", "unit": 45, "integration": 22, "e2e": 10 },
    { "date": "2026-02-12", "unit": 68, "integration": 35, "e2e": 25 },
    { "date": "2026-02-15", "unit": 82, "integration": 48, "e2e": 40 }
  ],
  
  "llm_generation_feedback": {
    "good_prompts": [
      "Including the full type definitions dramatically improves test quality",
      "Showing 2 existing test examples yields better style matching"
    ],
    "bad_prompts": [
      "Asking for 'comprehensive tests' produces bloated, unfocused tests",
      "Not including mock patterns leads to tests that fail on dependency resolution"
    ]
  }
}
```

### How Memory Is Used

1. **Pattern Matching:** Before generating a test, Builders check memory for existing patterns in this package. If the project uses `renderWithProviders`, the generated test uses it too.

2. **Failure Avoidance:** If memory records that `vi.mock('prisma')` fails, the Builder uses the known working pattern instead.

3. **Prioritization:** RiskAnalyzer uses bug history to prioritize files that have had bugs before.

4. **Style Learning:** Each accepted/rejected test updates the convention profile, refining generation over time.

5. **Prompt Refinement:** LLM prompt templates are adjusted based on what works for this specific project (stored in `llm_generation_feedback`).

### Memory Lifecycle

```
First run:
  1. Detectors scan → create initial profile
  2. PatternAnalyzer examines existing tests → seed memory with conventions
  3. Builders generate tests → basic quality

Run 5:
  Memory contains patterns, 3 failed attempts learned from, 2 bug patterns
  → Builders generate better tests, avoid known pitfalls

Run 20:
  Memory is rich with project-specific knowledge
  → Generation quality approaches human-written test quality
  → Bug detection catches subtle patterns specific to this codebase

Run 100+:
  Memory understands the project deeply
  → Proactive suggestions: "This new feature looks like the auth module — 
     here's the test pattern that worked there"
```

---

## 7. CLI Tool Integration — Bring Your Own AI

### Core Concept

Users should be able to use ANY LLM tool they already have installed. nit doesn't force a specific AI backend.

### Supported Execution Modes

```yaml
# .nit.yml — LLM configuration
llm:
  # Mode 1: Built-in LiteLLM (default)
  mode: builtin
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
  
  # Mode 2: CLI tool delegation
  mode: cli
  tool: claude               # claude | codex | aider | ollama | cursor | custom
  
  # Mode 3: Custom command
  mode: custom
  command: "my-ai-tool generate --context {context_file} --output {output_file}"
  
  # Mode 4: Local model via Ollama
  mode: ollama
  model: codellama:34b
  base_url: http://localhost:11434
```

### CLI Tool Adapters

| Tool | Command Pattern | How nit Uses It |
|---|---|---|
| **Claude Code** | `claude --print --context file.md "Generate tests for..."` | nit assembles context, calls Claude Code with structured prompt, captures output |
| **OpenAI Codex CLI** | `codex --prompt "..." --file context.md` | Same pattern |
| **Aider** | `aider --message "Generate unit tests" --file src/utils.ts` | Aider modifies files in-place, nit captures the diff |
| **Ollama** | `ollama run codellama "Generate tests..."` | API call to local Ollama instance |
| **Custom** | User-defined command template | nit provides `{context_file}`, `{source_file}`, `{output_file}`, `{prompt}` placeholders |

### How It Works Internally

```python
# nit/llm/cli_adapter.py

class CLIToolAdapter:
    """Delegates test generation to user's preferred CLI tool."""
    
    def generate(self, context: GenerationContext) -> str:
        # 1. Write structured context to temp file
        context_file = self.write_context(context)
        
        # 2. Build prompt specific to the task
        prompt = self.build_prompt(context)
        
        # 3. Call the CLI tool
        if self.tool == "claude":
            result = subprocess.run([
                "claude", "--print",
                "--allowedTools", "none",
                "--systemPrompt", self.system_prompt_path,
                prompt
            ], capture_output=True, input=context_file.read_text())
        
        elif self.tool == "codex":
            result = subprocess.run([
                "codex", "--prompt", prompt,
                "--context", str(context_file)
            ], capture_output=True)
        
        elif self.tool == "custom":
            cmd = self.command_template.format(
                context_file=context_file,
                source_file=context.source_path,
                output_file=context.output_path,
                prompt=prompt
            )
            result = subprocess.run(cmd, shell=True, capture_output=True)
        
        # 4. Parse and validate output
        return self.parse_output(result.stdout)
```

### User Selects Model + Tool at Init

```bash
$ nit init

🔍 Detecting project structure...
✅ Found: TypeScript (Next.js), Python (FastAPI), C++ (CMake)
✅ Monorepo: Turborepo with 5 packages

🤖 How would you like to power AI generation?

  1. Built-in (API key) — Claude, GPT, Gemini, etc.
  2. Claude Code CLI — uses your installed `claude` command
  3. Codex CLI — uses OpenAI's `codex` command
  4. Ollama (local) — run models on your machine
  5. Custom command — specify your own tool

> 2

✅ Found claude CLI at /usr/local/bin/claude
✅ Configuration saved to .nit.yml
```

---

## 8. Complete Technology Stack

| Layer | Technology | Why |
|---|---|---|
| **Core CLI** | Python 3.11+ with Click | Rich ecosystem for AI/LLM, tree-sitter bindings, cross-platform |
| **AST Parsing** | tree-sitter + tree-sitter-language-pack | 30+ language support, incremental parsing, battle-tested |
| **LLM (built-in)** | LiteLLM | Model-agnostic, supports 100+ providers with unified API |
| **LLM (CLI)** | Subprocess adapters | Zero-dependency integration with any CLI tool |
| **Task Queue** | In-process asyncio queue | Simple, no external dependencies, parallel agent execution |
| **Memory Store** | JSON files (committed to git) | Version-controlled, diffable, no database needed |
| **Coverage Merge** | Custom unified format | Translates Istanbul, coverage.py, gcov, JaCoCo, go cover into common schema |
| **Test Execution** | Subprocess per framework | Native runners, no abstraction leaks |
| **CI Integration** | GitHub Actions (primary) | Composite action wrapping CLI, GitLab CI / Bitbucket Pipelines as adapters |
| **Dashboard** | Static HTML + Chart.js | Generated locally, no server needed. Can be hosted on GitHub Pages |
| **Landing Page** | React + Vite + Tailwind | Modern, animated, open-source showcase site on Cloudflare Workers |
| **Web Platform** (future) | Hono + React + D1 + KV + AI Gateway + Queues | Fully serverless on Cloudflare. AI Gateway for provider routing/caching/BYOK. D1 for virtual keys, usage logs, budgets. KV for rate limiting. LiteLLM SDK `CustomLogger` in CLI reports usage for both platform-key and BYOK users. No external PostgreSQL/Redis/containers. |
| **Package Distribution** | pip (PyPI), pipx, Docker, GH Action | Multiple entry points for different users |
| **Config** | YAML (`.nit.yml`) | Human-readable, comments supported, widely understood |

---

## 9. Detection Engine — Deep Technical Details

### Framework Detection Algorithm

```python
class FrameworkDetector:
    """Multi-signal framework detection with confidence scoring."""
    
    def detect(self, package_path: Path) -> list[DetectedFramework]:
        signals = []
        
        # Signal 1: Config file existence (weight: 0.9)
        signals += self.check_config_files(package_path)
        
        # Signal 2: Dependency declarations (weight: 0.8)
        signals += self.check_dependencies(package_path)
        
        # Signal 3: Import scanning via tree-sitter (weight: 0.7)
        signals += self.scan_imports(package_path)
        
        # Signal 4: File/directory naming conventions (weight: 0.5)
        signals += self.check_naming_conventions(package_path)
        
        # Signal 5: LLM classification for ambiguous cases (weight: 0.6)
        if max_confidence(signals) < 0.8:
            signals += self.llm_classify(package_path, signals)
        
        return self.resolve_conflicts(signals)
```

### Config File Heuristics (Comprehensive)

```python
FRAMEWORK_SIGNALS = {
    # JavaScript / TypeScript
    "vitest": [
        ConfigFile("vitest.config.ts"),
        ConfigFile("vitest.config.js"),
        ConfigFile("vitest.config.mts"),
        Dependency("vitest", "package.json", "devDependencies"),
    ],
    "jest": [
        ConfigFile("jest.config.ts"),
        ConfigFile("jest.config.js"),
        ConfigFile("jest.config.mjs"),
        Dependency("jest", "package.json", "devDependencies"),
        PackageJsonField("jest"),  # inline config
    ],
    "mocha": [
        ConfigFile(".mocharc.yml"),
        ConfigFile(".mocharc.json"),
        Dependency("mocha", "package.json", "devDependencies"),
    ],
    "playwright": [
        ConfigFile("playwright.config.ts"),
        ConfigFile("playwright.config.js"),
        Dependency("@playwright/test", "package.json", "devDependencies"),
    ],
    "cypress": [
        ConfigFile("cypress.config.ts"),
        ConfigFile("cypress.config.js"),
        DirectoryExists("cypress/"),
        Dependency("cypress", "package.json", "devDependencies"),
    ],
    
    # Python
    "pytest": [
        ConfigFile("pytest.ini"),
        ConfigFile("pyproject.toml", section="[tool.pytest"),
        ConfigFile("setup.cfg", section="[tool:pytest]"),
        ConfigFile("conftest.py"),
        Dependency("pytest", "requirements.txt"),
        Dependency("pytest", "pyproject.toml", group="dev"),
    ],
    "unittest": [
        ImportPattern("import unittest"),
        ImportPattern("from unittest"),
    ],
    
    # C/C++
    "gtest": [
        CMakePattern("find_package(GTest"),
        CMakePattern("gtest_discover_tests"),
        CMakePattern("target_link_libraries.*gtest"),
        ImportPattern("#include <gtest/gtest.h>"),
        ImportPattern("#include \"gtest/gtest.h\""),
    ],
    "catch2": [
        CMakePattern("find_package(Catch2"),
        ImportPattern("#include <catch2/catch"),
        ImportPattern("#include \"catch.hpp\""),
    ],
    
    # Go
    "go_test": [
        FilePattern("*_test.go"),  # Always present if Go tests exist
    ],
    "testify": [
        ImportPattern("github.com/stretchr/testify"),
        GoModDependency("github.com/stretchr/testify"),
    ],
    "ginkgo": [
        ImportPattern("github.com/onsi/ginkgo"),
        GoModDependency("github.com/onsi/ginkgo"),
    ],
    
    # Java / Kotlin
    "junit5": [
        GradleDependency("org.junit.jupiter"),
        MavenDependency("org.junit.jupiter", "junit-jupiter"),
        ImportPattern("import org.junit.jupiter"),
    ],
    "testng": [
        GradleDependency("org.testng"),
        MavenDependency("org.testng", "testng"),
        ImportPattern("import org.testng"),
    ],
    "kotest": [
        GradleDependency("io.kotest"),
        ImportPattern("import io.kotest"),
    ],
    
    # Rust
    "cargo_test": [
        FilePattern("**/tests/*.rs"),
        ContentPattern("#[test]", "**/*.rs"),
        ContentPattern("#[cfg(test)]", "**/*.rs"),
    ],
    
    # C# / .NET
    "xunit": [
        NuGetDependency("xunit"),
        ImportPattern("using Xunit"),
    ],
    "nunit": [
        NuGetDependency("NUnit"),
        ImportPattern("using NUnit"),
    ],
    
    # Documentation
    "sphinx": [
        ConfigFile("docs/conf.py"),
        ConfigFile("conf.py"),
        Dependency("sphinx", "requirements.txt"),
    ],
    "typedoc": [
        ConfigFile("typedoc.json"),
        Dependency("typedoc", "package.json"),
    ],
    "doxygen": [
        ConfigFile("Doxyfile"),
        ConfigFile("Doxyfile.in"),
        CMakePattern("find_package(Doxygen"),
    ],
    "mkdocs": [
        ConfigFile("mkdocs.yml"),
        ConfigFile("mkdocs.yaml"),
    ],
    "rustdoc": [
        ContentPattern("///", "src/**/*.rs"),  # Rust doc comments
    ],
    "godoc": [
        ContentPattern("// Package", "**/*.go"),  # Go doc comments
    ],
}
```

---

## 10. LLM Drift Monitoring — Technical Details

### Drift Test Specification

```yaml
# .nit/drift/ml-pipeline.yml
drift_tests:
  - name: "Summarization quality"
    type: semantic            # semantic | exact | regex | schema
    endpoint:
      type: function          # function | http | cli
      path: "src/services/summarizer.py"
      function: "summarize_article"
    
    inputs:
      - id: "news-article-1"
        args:
          text: "The Federal Reserve announced today..."
          max_length: 100
        expected:
          semantic_similarity: 0.85    # minimum cosine similarity to baseline
          max_tokens: 150
          must_contain: ["Federal Reserve", "interest"]
          must_not_contain: ["I think", "As an AI"]
          tone: "neutral"
    
    baseline:
      created: "2026-02-01"
      output: "The Federal Reserve has decided to maintain current interest rates..."
      embedding: [0.123, -0.456, ...]   # cached embedding for fast comparison

  - name: "Classification accuracy"
    type: exact
    endpoint:
      type: http
      url: "http://localhost:8000/api/classify"
      method: POST
    
    inputs:
      - id: "support-ticket-1"
        body: { "text": "My order hasn't arrived" }
        expected:
          output: { "category": "shipping" }
          match: "json_subset"
      
      - id: "support-ticket-2"
        body: { "text": "How do I change my password?" }
        expected:
          output: { "category": "account" }
          match: "json_subset"

  - name: "Prompt template regression"
    type: schema
    endpoint:
      type: function
      path: "src/prompts/product_description.py"
      function: "generate_description"
    
    inputs:
      - id: "product-1"
        args:
          product: { "name": "Wireless Mouse", "features": ["ergonomic", "bluetooth"] }
        expected:
          json_schema:
            type: object
            required: ["title", "description", "keywords"]
          max_tokens: 300
          readability_score: "> 60"     # Flesch-Kincaid
```

### Semantic Comparison Engine

```python
class DriftComparator:
    """Multi-strategy drift comparison."""
    
    def compare(self, baseline: str, current: str, strategy: str) -> DriftResult:
        if strategy == "exact":
            return self.exact_match(baseline, current)
        
        elif strategy == "semantic":
            # Use sentence-transformers for local embedding comparison
            # Falls back to LLM-based comparison if embeddings unavailable
            baseline_emb = self.embed(baseline)
            current_emb = self.embed(current)
            similarity = cosine_similarity(baseline_emb, current_emb)
            return DriftResult(
                drifted=similarity < self.threshold,
                similarity=similarity,
                details=self.explain_drift(baseline, current) if similarity < self.threshold else None
            )
        
        elif strategy == "schema":
            return self.validate_schema(current, self.expected_schema)
        
        elif strategy == "regex":
            return self.regex_match(current, self.expected_pattern)
```

### Prompt Optimization (when drift detected)

```
Drift detected: summarize_article output quality dropped 12%

Prompt Optimizer analysis:
1. Token waste: System prompt contains 340 tokens of boilerplate → suggest trimming to 180
2. Ambiguous instruction: "Write a good summary" → suggest "Write a neutral, factual 
   summary under 100 words containing the key entities and outcomes"
3. Missing constraints: No format specification → suggest "Output JSON with fields: 
   summary, key_entities, sentiment"
4. Temperature recommendation: Currently 0.9 → suggest 0.3 for factual summarization

Estimated improvement: 15-25% consistency, 45% token savings
```

---

## 11. Documentation Generation — Technical Details

### What Gets Generated/Updated

| Doc Type | Trigger | Source | Output |
|---|---|---|---|
| **Function/method docs** | New or modified function with no/outdated docs | tree-sitter AST + function body | Inline docstrings/comments in target format |
| **API endpoint docs** | New or modified route handler | Route definition + handler code + types | OpenAPI spec update or Sphinx/TypeDoc page |
| **Component docs** | New or modified React/Vue/Svelte component | Component props, state, usage | TypeDoc page or Storybook MDX |
| **README** | Structural changes to project | package.json, exports, directory structure | Updated sections in README.md |
| **Changelog** | New release or tag | Git diff, commit messages, PR descriptions | CHANGELOG.md in Keep a Changelog format |
| **Test documentation** | Tests generated by nit | Test file + tested code | Inline comments explaining test cases |

### Doc Generation Pipeline

```
1. DIFF DETECTION
   Compare current code AST against last documented state (stored in memory)
   → Changed functions, new exports, modified APIs, removed components

2. EXTRACT
   For each changed item:
   ├── Function signature + types (tree-sitter)
   ├── Implementation summary (LLM-assisted)
   ├── Usage examples (from test files + existing usage)
   ├── Dependencies and side effects
   └── Error conditions and edge cases

3. GENERATE
   Use detected doc framework adapter:
   ├── TypeDoc → TSDoc comments in source files
   ├── Sphinx → RST or MyST files in docs/
   ├── Doxygen → Doxygen-format comments in headers
   ├── JSDoc → JSDoc comments in source files
   ├── godoc → Go doc comments
   ├── rustdoc → /// doc comments
   └── MkDocs → Markdown pages

4. VALIDATE
   ├── Build docs with native tool → must succeed
   ├── Check for broken links
   └── Verify examples compile/run

5. OUTPUT
   ├── Doc files created/updated
   └── PR created with changes
```

---

## 12. Landing Page & Dashboard

### Landing Page

**Tech:** Next.js 14+ / App Router, Tailwind CSS, Framer Motion, deployed on Vercel.

**Design Direction:** Dark theme, terminal-aesthetic with neon accents. Hero shows a live terminal animation of nit running. Think: Vercel's website meets a hacker terminal.

**Sections:**

```
1. HERO
   ├── Animated terminal showing: nit init → nit pick
   ├── Tagline: "Forge quality into every commit"
   ├── Subline: "Open-source AI testing swarm. Unit · Integration · E2E · Drift · Docs"
   ├── CTA: "Get Started" | "Star on GitHub"
   └── GitHub stars counter (live)

2. THE PROBLEM
   ├── "85% of bugs still reach production"
   ├── Statistics with animated counters
   └── Pain points developers feel

3. HOW IT WORKS
   ├── 4-step visual pipeline: Detect → Analyze → Build → Report
   ├── Interactive demo (embedded Asciinema or custom player)
   └── Monorepo visualization showing multi-package detection

4. LANGUAGES & FRAMEWORKS
   ├── Logo grid of supported languages/frameworks
   ├── Interactive: click a language → see supported test frameworks
   └── "Community contributed" badge for newer adapters

5. THE SWARM
   ├── Animated swarm visualization (agents working in parallel)
   ├── Agent cards: Detectors, Analyzers, Builders, Debuggers, Watchers
   └── Live demo of agent communication

6. MEMORY
   ├── "Gets smarter with every run" visualization
   ├── Before/after comparison: Run 1 vs Run 50
   └── Memory growth animation

7. COMPARISON TABLE
   ├── nit vs Tusk vs QA Wolf vs Bug0 vs Keploy
   └── Feature-by-feature with checkmarks

8. QUICKSTART
   ├── Code block: pip install nit && nit init && nit pick
   ├── GitHub Action YAML snippet
   └── 30-second GIF showing first run

9. COMMUNITY
   ├── "Build an adapter" CTA
   ├── GitHub contributors grid
   ├── Discord/Slack join button
   └── "nit is open source and always will be"

10. FOOTER
    ├── Docs, GitHub, Discord, Twitter/X
    ├── License (MIT)
    └── "Made by [your name] — forging better software"
```

### User Dashboard + LLM Gateway (Phase 5 — Future)

**Tech:** 100% Cloudflare — Workers (Hono) + D1 + KV + R2 + AI Gateway + Queues + Workflows + Better Auth. No external infrastructure (no PostgreSQL, no Redis, no Docker containers).

**Purpose:** Optional hosted platform for teams wanting cross-repo visibility **and** managed LLM access. The CLI generates local dashboards for free; the platform adds team features and a managed LLM gateway.

**Key design decisions:**

- **No LiteLLM Proxy on the platform.** LiteLLM Proxy requires PostgreSQL + Redis — external dependencies we don't want. Instead, we build the gateway layer ourselves using Cloudflare-native primitives.
- **LiteLLM SDK stays in the CLI.** The Python library handles the unified provider API, local cost calculation, and `CustomLogger` callbacks. It doesn't care what the backend platform uses.
- **Usage tracking works for ALL users.** Whether they use a platform key (routed through AI Gateway) or their own key (BYOK, direct to provider), the CLI's `CustomLogger` callback captures tokens + cost (calculated locally from LiteLLM's bundled pricing data) and reports to the platform.

**LLM Gateway Architecture — Platform Key (user doesn't manage provider accounts):**

```
nit CLI → LiteLLM SDK (base_url = platform proxy endpoint)
                │
                └── POST https://platform.getnit.dev/v1/llm-proxy
                          │
                          ├── Hono Worker middleware:
                          │     1. Validate virtual key (D1 virtual_keys table)
                          │     2. Check budget (D1: spend_total < max_budget)
                          │     3. Check rate limit (KV: incr counter, check < rpm_limit)
                          │
                          ├── Cloudflare AI Gateway:
                          │     ├── BYOK: injects platform's real provider key (Secrets Store)
                          │     ├── Caching: serves cached responses from edge (free)
                          │     ├── Routes to: Anthropic / OpenAI / Bedrock
                          │     └── Custom metadata: user_id, project_id for analytics
                          │
                          └── Response flows back
                                ├── Hono Worker: calculate margin, update spend_total in D1
                                ├── Enqueue usage event to Cloudflare Queue
                                └── Queue consumer: batch-insert into D1 usage_events
```

**LLM Gateway Architecture — BYOK (user uses their own API key):**

```
nit CLI → LiteLLM SDK → Provider directly (user's own key)
                │
                └── CustomLogger callback fires automatically:
                      ├── Captures: model, tokens, cost (local calculation), duration
                      ├── Buffers in memory
                      └── Batch POST to platform /api/v1/usage/ingest
                            └── Hono Worker → Queue → D1 usage_events
```

**What replaces LiteLLM Proxy features:**

| LiteLLM Proxy feature | Cloudflare-native replacement |
|---|---|
| PostgreSQL (virtual keys, spend logs) | D1 — virtual_keys, usage_events, usage_daily tables |
| Redis (rate limiting, caching) | KV — rate limit counters with TTL, budget cache |
| Provider routing + fallbacks | AI Gateway — routing, fallback chains, edge caching |
| Provider key storage | AI Gateway BYOK / Secrets Store |
| Virtual key management API | Hono Worker routes — key CRUD against D1 |
| Per-user cost tracking | D1 usage_events (from Queue consumer), populated by both platform proxy and CLI CustomLogger callback |
| Margin/markup | Hono Worker — margin multiplier applied in proxy response, stored in D1 |
| Admin dashboard | Our React SPA — reads from D1 via Hono API |

```
Dashboard Features:
├── Multi-repo overview (coverage trends across all repos)
├── Team activity feed (who merged what tests, which bugs were found)
├── Coverage heatmaps (visual grid of tested vs untested code)
├── Drift monitoring timeline (LLM output quality over time)
├── Bug discovery history (bugs found by nit over time)
├── Memory insights (what nit has learned about your codebase)
├── LLM usage & costs (per-user token usage, cost by model/provider, spend vs budget)
│   └── Works for BOTH platform-key and BYOK users (CLI reports usage either way)
├── LLM key management (create/revoke/rotate virtual keys, set budgets, model restrictions)
├── Alert configuration (Slack/email for coverage drops, drift events, budget thresholds)
└── Test quality scoring (are generated tests actually catching bugs?)

Monetization (optional, never required):
├── Free tier: 1 repo, local dashboard, bring your own API key (usage still tracked)
├── Team tier: Unlimited repos, hosted dashboard, team features
├── Pro tier: Platform LLM key with margin (no need to manage provider accounts)
└── Enterprise: SSO, audit logs, dedicated AI Gateway instance
```

---

## 13. Implementation Roadmap (Expanded)

### Phase 1 — Foundation (Weeks 1–4)

**Goal:** Working CLI that detects stack and generates unit tests for JS/TS + Python.

| Week | Deliverables | Technical Details |
|---|---|---|
| **1** | Project scaffolding. Scanner/Detector agents. | Python project with Click CLI, async agent system, tree-sitter integration. StackDetector + FrameworkDetector for JS/TS/Python. WorkspaceDetector for Turbo/pnpm/npm. Output: `.nit/profile.json` |
| **2** | Builder engine: UnitBuilder for Vitest + pytest. Memory system v1. | LLM interface via LiteLLM. Template library for vitest and pytest. Context assembly pipeline: tree-sitter parse → dependency graph → prompt construction. PatternAnalyzer seeds memory from existing tests. |
| **3** | Validation loop + coverage integration. | Run generated tests via subprocess, parse results, self-iterate on failures. Istanbul/c8 for JS coverage, coverage.py for Python. CoverageAnalyzer maps gaps. |
| **4** | CLI polish, config system, first release. | `nit init`, `nit scan`, `nit generate`, `nit run`. `.nit.yml` config support. Memory file I/O. README, install docs, PyPI publish. |

### Phase 2 — CI + E2E + Monorepo (Weeks 5–8)

| Week | Deliverables |
|---|---|
| **5** | GitHub Action wrapper. DiffAnalyzer for PR-only mode. GitHubCommentReporter with coverage delta. |
| **6** | E2EBuilder: Playwright test generation. Route discovery for Next.js/Express. Auth config system (form, token, OAuth). |
| **7** | Full monorepo support: per-package detection, memory, and generation. Turbo/pnpm/npm workspace support. Parallel agent execution across packages. |
| **8** | InfraBuilder: bootstrap test infrastructure for projects with none. Self-healing: when tests break on UI changes, re-analyze + regenerate. GitHubPRReporter: create PRs with generated tests. |

### Phase 3 — Systems Languages + Debuggers (Weeks 9–14)

| Week | Deliverables |
|---|---|
| **9–10** | C/C++ adapter: GTest + Catch2 generation, CMake integration, gcov/lcov coverage. Go adapter: go test + Testify generation, go cover integration. |
| **11–12** | Java adapter: JUnit 5 generation, Gradle/Maven integration, JaCoCo coverage. Kotlin adapter via JUnit 5 + Kotest. CLI tool integration: Claude Code, Codex, Ollama, custom command adapters. |
| **13** | Debugger agents: BugVerifier, RootCauseAnalyzer, FixGenerator, FixVerifier. Full bug detection → fix → PR pipeline. GitHubIssueReporter for bug reports. |
| **14** | DriftWatcher: LLM drift monitoring system. Drift test YAML spec. Semantic comparison engine (sentence-transformers). Prompt optimization module. |

### Phase 4 — Docs + Dashboard + More Languages (Weeks 15–20)

| Week | Deliverables |
|---|---|
| **15–16** | DocBuilder: TypeDoc, Sphinx, Doxygen adapters. Diff-based doc generation. README auto-update. Changelog generation. |
| **17** | Rust adapter (cargo test, tarpaulin). C#/.NET adapter (xUnit, coverlet). Plugin system formalization with clear adapter API. |
| **18** | Landing page: Next.js + Tailwind, terminal animation hero, interactive demo, comparison table. |
| **19** | Local HTML dashboard: coverage trends, bug history, memory insights, drift timeline. Chart.js visualizations. |
| **20** | Cargo workspace + Go workspace + Gradle multi-project detection. Performance optimization. Comprehensive test suite for nit itself. Public launch. |

### Phase 5 — Web Platform + LLM Gateway (Post-launch)

- Web platform: 100% Cloudflare — Workers (Hono) + D1 + KV + R2 + AI Gateway + Queues + Workflows + Better Auth. No external infrastructure.
- Repository split: `~/web` contains only marketing/landing code; `~/platform` contains only dashboard + API + gateway code.
- LLM gateway: AI Gateway for provider routing/caching/BYOK + Hono Worker for virtual key management, budget enforcement, rate limiting (D1 + KV). No LiteLLM Proxy, no PostgreSQL, no Redis.
- CLI usage tracking: LiteLLM SDK `CustomLogger` callback in nit CLI captures tokens + cost for every LLM call (calculated locally), batch-POSTs to platform — works for both platform-key and BYOK users.
- CLI ↔ platform integration: `nit config set platform.api_key` — platform-key mode routes through AI Gateway; BYOK mode calls providers directly but still reports usage.
- PHP, Ruby, Swift adapters (community-contributed)
- VS Code extension
- MCP server for IDE integration
- Bazel/Buck2 workspace support
- Cross-repo contract testing (federation mode)
- GitHub App (richer integration than Action)

---

## 14. Project File Structure

```
nit/
├── pyproject.toml                    # Python project config (PEP 621)
├── README.md
├── LICENSE                           # MIT
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                    # nit's own CI
│   │   └── release.yml               # PyPI publishing
│   └── action.yml                    # GitHub Action definition
│
├── src/
│   └── nit/
│       ├── __init__.py
│       ├── cli.py                    # Click CLI entrypoint
│       ├── config.py                 # .nit.yml parsing
│       ├── orchestrator.py           # Swarm orchestrator + task queue
│       │
│       ├── agents/
│       │   ├── base.py               # BaseAgent abstract class
│       │   │
│       │   ├── detectors/
│       │   │   ├── stack.py           # StackDetector
│       │   │   ├── framework.py       # FrameworkDetector
│       │   │   ├── workspace.py       # WorkspaceDetector
│       │   │   ├── dependency.py      # DependencyDetector
│       │   │   ├── llm_usage.py       # LLMUsageDetector
│       │   │   ├── infra.py           # InfraDetector
│       │   │   └── signals.py         # Detection signal definitions
│       │   │
│       │   ├── analyzers/
│       │   │   ├── coverage.py        # CoverageAnalyzer
│       │   │   ├── code.py            # CodeAnalyzer (tree-sitter)
│       │   │   ├── risk.py            # RiskAnalyzer
│       │   │   ├── diff.py            # DiffAnalyzer (PR mode)
│       │   │   ├── pattern.py         # PatternAnalyzer
│       │   │   └── bug.py             # BugAnalyzer
│       │   │
│       │   ├── builders/
│       │   │   ├── unit.py            # UnitBuilder
│       │   │   ├── integration.py     # IntegrationBuilder
│       │   │   ├── e2e.py             # E2EBuilder
│       │   │   ├── docs.py            # DocBuilder
│       │   │   └── infra.py           # InfraBuilder
│       │   │
│       │   ├── debuggers/
│       │   │   ├── verifier.py        # BugVerifier
│       │   │   ├── root_cause.py      # RootCauseAnalyzer
│       │   │   ├── fix_gen.py         # FixGenerator
│       │   │   └── fix_verify.py      # FixVerifier
│       │   │
│       │   ├── watchers/
│       │   │   ├── drift.py           # DriftWatcher
│       │   │   ├── schedule.py        # ScheduleWatcher
│       │   │   └── coverage.py        # CoverageWatcher
│       │   │
│       │   └── reporters/
│       │       ├── github_pr.py
│       │       ├── github_issue.py
│       │       ├── github_comment.py
│       │       ├── dashboard.py
│       │       ├── slack.py
│       │       └── terminal.py
│       │
│       ├── adapters/                  # Framework-specific adapters
│       │   ├── base.py                # TestAdapter + DocAdapter ABCs
│       │   ├── registry.py            # Auto-discovery + registration
│       │   │
│       │   ├── unit/
│       │   │   ├── vitest.py
│       │   │   ├── jest.py
│       │   │   ├── pytest_adapter.py
│       │   │   ├── gtest.py
│       │   │   ├── catch2.py
│       │   │   ├── go_test.py
│       │   │   ├── testify.py
│       │   │   ├── junit5.py
│       │   │   ├── cargo_test.py
│       │   │   ├── xunit.py
│       │   │   └── kotest.py
│       │   │
│       │   ├── e2e/
│       │   │   ├── playwright.py
│       │   │   └── cypress.py
│       │   │
│       │   ├── coverage/
│       │   │   ├── istanbul.py
│       │   │   ├── coverage_py.py
│       │   │   ├── gcov.py
│       │   │   ├── jacoco.py
│       │   │   ├── go_cover.py
│       │   │   ├── tarpaulin.py
│       │   │   └── coverlet.py
│       │   │
│       │   └── docs/
│       │       ├── typedoc.py
│       │       ├── sphinx.py
│       │       ├── doxygen.py
│       │       ├── jsdoc.py
│       │       ├── godoc_adapter.py
│       │       ├── rustdoc.py
│       │       └── mkdocs.py
│       │
│       ├── llm/                       # LLM integration layer
│       │   ├── engine.py              # LLM call abstraction
│       │   ├── builtin.py             # LiteLLM built-in adapter
│       │   ├── cli_adapter.py         # CLI tool delegation
│       │   ├── ollama.py              # Ollama local model adapter
│       │   ├── prompts/               # Prompt templates
│       │   │   ├── unit_test.py
│       │   │   ├── integration_test.py
│       │   │   ├── e2e_test.py
│       │   │   ├── bug_analysis.py
│       │   │   ├── fix_generation.py
│       │   │   ├── doc_generation.py
│       │   │   └── drift_analysis.py
│       │   └── context.py             # Context assembly engine
│       │
│       ├── memory/
│       │   ├── store.py               # Memory read/write
│       │   ├── global_memory.py       # Repo-wide memory
│       │   ├── package_memory.py      # Per-package memory
│       │   └── drift_baselines.py     # Drift baseline management
│       │
│       ├── parsing/
│       │   ├── treesitter.py          # tree-sitter wrapper
│       │   ├── languages.py           # Language-specific AST queries
│       │   └── coverage_parser.py     # Unified coverage format
│       │
│       └── utils/
│           ├── git.py                 # Git operations
│           ├── subprocess_runner.py   # Safe subprocess execution
│           ├── file_watcher.py        # File change detection
│           └── templates.py           # Template engine for test stubs
│
├── tests/                             # nit's own tests
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── website/                           # Landing page
│   ├── package.json
│   ├── app/
│   └── components/
│
└── docker/
    ├── Dockerfile                     # For running nit in Docker
    └── Dockerfile.test                # For isolated test execution
```

---

## 15. CLI Commands

```bash
# Setup
nit init                              # Detect project, create .nit.yml
nit init --interactive                # Interactive setup wizard

# Detection
nit scan                              # Full project analysis
nit scan --package apps/web           # Scan specific package
nit scan --diff                       # Only scan changed files (git diff)

# Test Generation
nit generate                          # Generate tests for all uncovered code
nit generate --type unit              # Only unit tests
nit generate --type integration       # Only integration tests
nit generate --type e2e               # Only E2E tests
nit generate --file src/utils.ts      # Generate tests for specific file
nit generate --package apps/api       # Generate for specific package
nit generate --coverage-target 80     # Generate until 80% coverage reached

# Running
nit run                               # Run full test suite
nit run --only-generated              # Run only nit-generated tests
nit run --package services/ml         # Run tests for specific package

# Bug Hunting
nit pick                              # Full pipeline: scan → analyze → generate → run → report
nit pick --fix                        # Also generate fixes for found bugs
nit pick --pr                         # Create PRs with tests and fixes

# LLM Drift
nit drift                             # Run drift tests
nit drift --baseline                  # Update baselines to current outputs
nit drift --watch                     # Continuous drift monitoring

# Documentation
nit docs                              # Generate/update documentation
nit docs --check                      # Check for outdated docs (no changes)
nit docs --changelog v1.2.0           # Generate changelog since tag

# Memory
nit memory show                       # Display memory contents
nit memory show --package apps/web    # Package-specific memory
nit memory reset                      # Reset all memory (start fresh)
nit memory export                     # Export memory as readable report

# Dashboard
nit dashboard                         # Generate HTML dashboard in .nit/dashboard/
nit dashboard --serve                 # Serve dashboard on localhost:4040

# Configuration
nit config show                       # Display resolved config
nit config validate                   # Validate .nit.yml
nit config set llm.model gpt-4o       # Update config value
```

---

## 16. Competitive Edge Summary

| Capability | Only nit | Why It Matters |
|---|---|---|
| Full testing pyramid in one tool | ✅ | Unit + Integration + E2E + Drift + Docs — no stitching tools together |
| Open source + self-hosted | ✅ | No sensitive code leaves your infrastructure |
| Monorepo-native with mixed languages | ✅ | Real-world projects aren't single-language |
| Memory that improves over time | ✅ | Gets smarter, not just repetitive |
| C/C++, Go, Rust, Kotlin support | ✅ | Systems languages are completely ignored by competitors |
| Bring your own AI tool | ✅ | Claude Code, Codex, Ollama — users keep their workflow |
| Bug detection + auto-fix pipeline | ✅ | Not just tests — actually finds and proposes fixes for bugs |
| Swarm architecture | ✅ | Agents work in parallel, hand off work, make autonomous decisions |
| Prompt optimization + drift | ✅ | Unique for LLM-integrated applications |
| Free forever | ✅ | MIT license, no hidden tiers for core features |

---

## 17. What Makes This Go Viral

1. **The `nit pick` moment** — single command runs the full swarm, finds bugs, creates PRs. The output is dramatic and shareable.

2. **"nit found 3 bugs in 2 minutes"** — these stories get tweeted, posted on HN, shared in Discord servers.

3. **Monorepo support is undersold** — every startup with a Turborepo has this pain. nit solving multi-language testing in monorepos is an immediate draw.

4. **C/C++ and Go coverage** — these communities are starved for AI testing tools. Instant credibility and a passionate user base.

5. **Memory visualization** — showing how nit learned your codebase over time is fascinating and shareable content.

6. **Framework adapter contributions** — community members adding support for their framework creates investment and evangelism.

7. **The landing page** — terminal-aesthetic, animated, impressive. Makes people want to try it just based on how it looks.

8. **"Bring your own AI" model** — no API key lock-in means anyone can try it immediately with Ollama locally, zero cost.


Next rework:
# Project Plan Update: Naming & Cloudflare-Native Infrastructure

> This document updates and replaces §1 (Naming) and §12 (Landing Page & Dashboard) from the previous plan. All other sections remain valid.

---

## 1. Naming — Revised

The name "jrdev.ai" has the right energy (junior dev → AI does the grunt work) but risks being read as dismissive of junior developers. Let's keep that "AI does the boring work" spirit while finding something that stands on its own.

### Naming Criteria

- 3–6 characters ideal (CLI ergonomics)
- Must not be taken on npm, PyPI, or GitHub (or at least not actively used)
- Should feel like a dev tool, not a product (think: git, vim, tmux, curl, grep, lint)
- Should imply action, intelligence, or protection
- Must work as: CLI command, config file prefix, GitHub org, domain
- Avoid: overused mythology (Athena, Apollo, Zeus), generic AI names (CoverAI, TestBot)

### Top Picks — Round 2

| # | Name | Vibe | CLI Feel | Config | Domain Options | Why |
|---|---|---|---|---|---|---|
| 1 | **tusk** | A weapon/tool — elephants never forget (memory!) | `tusk hunt`, `tusk scan` | `.tusk.yml` | tusk.dev, usetusk.dev | Short, punchy, memorable. Elephants = memory = your memory system. Aggressive (a tusk is a weapon). Already dev-associated (Tusk exists but is closed SaaS — open-source version would be a statement) |
| 2 | **pry** | To investigate, to pry open | `pry run`, `pry into src/` | `.pry.yml` | pry.dev, getpry.dev | 3 letters. Implies deep investigation. `pry open your codebase`. Ruby has a `pry` debugger (good association) but no testing tool |
| 3 | **vex** | To test/examine (Latin: vexare) + to challenge | `vex check`, `vex hunt` | `.vex.yml` | vex.dev, getvex.dev | 3 letters. Latin root meaning "to test/agitate." Sounds like a dev tool. `.vex.yml` looks great |
| 4 | **grip** | To hold tight, to grasp/control quality | `grip test`, `grip scan` | `.grip.yml` | grip.dev, getgrip.dev | "Get a grip on your tests." Implies control, reliability. 4 letters, easy to type |
| 5 | **raze** | To tear down (bugs), to stress-test | `raze run`, `raze hunt` | `.raze.yml` | raze.dev, getraze.dev | Aggressive. "Raze your bugs to the ground." Edgy but memorable. Gamers will love it |
| 6 | **sift** | To examine carefully, filter out bugs | `sift scan`, `sift run` | `.sift.yml` | sift.dev, usesift.dev | Clean, professional, implies thoroughness. "Sift through your code." 4 letters |
| 7 | **nit** | As in "nitpick" — finding every small issue | `nit check`, `nit pick` | `.nit.yml` | nit.dev, getnit.dev | 3 letters! Self-deprecating humor. Developers already say "that's a nit." `nit pick src/` is hilarious and memorable |
| 8 | **flux** | Constant change/testing | `flux test`, `flux scan` | `.flux.yml` | flux.dev, useflux.dev | Modern, dynamic feel. Implies continuous quality. 4 letters |
| 9 | **vet** | To examine/verify carefully | `vet check`, `vet scan` | `.vet.yml` | vet.dev, getvet.dev | 3 letters. "Vet your code before shipping." Professional, clear intent. Everyone knows what vetting means |
| 10 | **prowl** | To move stealthily, hunting | `prowl hunt`, `prowl scan` | `.prowl.yml` | prowl.dev, getprowl.dev | Predatory, implies the swarm agents quietly hunting through your code. 5 letters, distinctive |
| 11 | **forge** | To create/build (tests), to strengthen | `forge test`, `forge build` | `.forge.yml` | forge.dev, useforge.dev | Double meaning: forging tests + forging quality. Implies craftsmanship |
| 12 | **qabot** | QA + bot — instantly clear | `qabot run`, `qabot hunt` | `.qabot.yml` | qabot.dev | Zero ambiguity about what it does. Not cute, but searchable. Google-friendly |
| 13 | **tack** | To take a different approach/strategy | `tack test`, `tack scan` | `.tack.yml` | tack.dev, gettack.dev | Short, sharp. "Tack on tests to your codebase." Nautical — changing direction |
| 14 | **comb** | To comb through code | `comb scan`, `comb run` | `.comb.yml` | comb.dev, getcomb.dev | "Comb through your code for bugs." Visual metaphor, thorough |
| 15 | **jarvis** | The AI assistant (Marvel) | `jarvis test`, `jarvis scan` | `.jarvis.yml` | jarvis.dev | Instantly recognized as AI assistant. May have trademark concerns though |

### Shortlist & Recommendation

**Tier 1 (My top 3):**

1. **`nit`** — 3 letters, hilarious, memorable, self-aware dev humor. `nit pick src/` as a command is unforgettable. "Nit found 3 bugs" is tweetable. The `.nit/` directory is tiny and clean. "Nit — the open-source AI that nitpicks your code so reviewers don't have to."

2. **`pry`** — 3 letters, investigative energy, works across cultures. "Pry open your codebase." Clean and professional. `pry into src/utils.ts` is a natural command.

3. **`vex`** — 3 letters, Latin root for testing/challenging. Edgy but professional. "Vex your code before production does." `.vex.yml` looks fantastic.

**Tier 2 (Strong alternatives):**

4. **`sift`** — More professional/enterprise-friendly. "Sift through your codebase for quality gaps."
5. **`grip`** — Solid, implies control. "Get a grip on your test coverage."
6. **`prowl`** — Best fit for the swarm/agent metaphor. Agents prowling through code.

### Name Validation Checklist

For whichever name you pick, verify:
- [ ] GitHub org available (`github.com/{name}-ai` or `github.com/get{name}`)
- [ ] npm package available or claimable
- [ ] PyPI package available
- [ ] `.dev` domain available (or `.sh`, `.run`, `.tools`)
- [ ] No major trademark conflicts
- [ ] Not an offensive word in any major language

---

## 2. Cloudflare-Native Infrastructure Stack

### Previous Stack (Removed)
- ~~Supabase (auth + database)~~
- ~~Vercel (hosting)~~
- ~~Next.js for landing page~~

### New Stack: 100% Cloudflare

Everything runs on Cloudflare's edge platform. Zero external dependencies for hosting.

| Layer | Technology | Cloudflare Service | Why |
|---|---|---|---|
| **Web Framework** | **Hono** | Cloudflare Workers | Ultrafast, <14KB, native CF Workers support, built-in middleware, TypeScript-first. Cloudflare themselves use Hono internally for D1 and Workers Logs APIs |
| **Frontend** | **React + Vite** (SPA) | Workers Static Assets | Official CF template: `cloudflare/templates/vite-react-template`. SPA routes are free (served from static assets, don't invoke Worker) |
| **Database** | **Drizzle ORM + D1** | Cloudflare D1 | Serverless SQLite at the edge. No cold starts. Free tier: 5M reads/day, 100K writes/day. Drizzle provides type-safe queries + migrations |
| **Authentication** | **Better Auth** | Workers + D1 | Best CF-native auth library. Supports email/password, OAuth (GitHub, Google), magic links. Uses D1 via Kysely/Drizzle adapter. `better-auth-cloudflare` package handles all CF-specific quirks |
| **Session Storage** | **Better Auth + KV** | Cloudflare KV | Low-latency session reads. Better Auth has native KV adapter for session caching |
| **File Storage** | **R2** | Cloudflare R2 | S3-compatible. Store coverage reports, dashboard snapshots, generated test archives. Free egress |
| **Cron/Scheduling** | **Workers Cron Triggers** | Cloudflare Workers | Native cron scheduling for drift monitoring dashboard updates. No external scheduler needed |
| **Email** | **Resend** (or CF Email Workers) | Workers + external API | Transactional emails for alerts, invites. Resend has generous free tier |
| **Analytics** | **Workers Analytics Engine** | Cloudflare Analytics | Track CLI usage, test generation stats (opt-in, privacy-first) |
| **DNS/CDN** | **Cloudflare** | Cloudflare CDN | Obviously — global CDN, DDoS protection, SSL |
| **CI/CD** | **Workers Builds** | Cloudflare Builds | Deploy on push. 6 concurrent builds on paid plan |
| **Realtime** (future) | **Durable Objects** | Cloudflare Durable Objects | For future live dashboard with WebSocket updates |

### Architecture Diagram

```
                    ┌──────────────────────────────────────┐
                    │        Cloudflare Edge Network         │
                    │                                        │
                    │  ┌──────────────────────────────────┐  │
                    │  │     Workers Static Assets         │  │
                    │  │     (React + Vite SPA)            │  │
                    │  │                                    │  │
                    │  │  • Dashboard SPA (/dashboard)      │  │
                    │  │  • Docs (/docs)                    │  │
                    │  │  FREE — no Worker invocation       │  │
                    │  └──────────────────────────────────┘  │
                    │                 │                        │
                    │       API calls (fetch /api/*)          │
                    │                 ▼                        │
                    │  ┌──────────────────────────────────┐  │
                    │  │     Hono API (Cloudflare Worker)   │  │
                    │  │                                    │  │
                    │  │  /api/auth/*     → Better Auth     │  │
                    │  │  /api/projects/* → Project CRUD    │  │
                    │  │  /api/reports/*  → Coverage data   │  │
                    │  │  /api/drift/*    → Drift results   │  │
                    │  │  /api/webhook    → GitHub webhook  │  │
                    │  │  /api/upload     → Report upload   │  │
                    │  │                                    │  │
                    │  └─────┬──────┬──────┬──────┬────────┘  │
                    │        │      │      │      │            │
                    │        ▼      ▼      ▼      ▼            │
                    │   ┌──────┐ ┌────┐ ┌────┐ ┌─────┐        │
                    │   │  D1  │ │ KV │ │ R2 │ │Cron │        │
                    │   │(SQLite)│ │    │ │    │ │Trigger│     │
                    │   │      │ │    │ │    │ │     │         │
                    │   │Users │ │Sess│ │Rpts│ │Drift│         │
                    │   │Projct│ │ions│ │Arch│ │Schd │         │
                    │   │Report│ │Cach│ │ive │ │     │         │
                    │   │Config│ │    │ │    │ │     │         │
                    │   └──────┘ └────┘ └────┘ └─────┘        │
                    └──────────────────────────────────────┘
                                      ▲
                                      │ CLI uploads results
                                      │
                    ┌──────────────────────────────────────┐
                    │         User's Machine / CI           │
                    │                                       │
                    │   $ nit pick --report                 │
                    │                                       │
                    │   1. Swarm runs locally (or in CI)    │
                    │   2. Generates tests, finds bugs      │
                    │   3. Uploads report to dashboard API  │
                    │   4. Creates GitHub PRs/Issues        │
                    └──────────────────────────────────────┘
```

### Key Architectural Decisions

**1. CLI-first, dashboard-optional**

The CLI tool (Python, runs locally/CI) is the core product. The Cloudflare dashboard is an optional add-on for teams who want:
- Cross-repo coverage visibility
- Historical trend tracking
- Team activity feeds
- Drift monitoring timeline
- Alert configuration

The CLI works perfectly without the dashboard. The dashboard is powered by the CLI uploading JSON reports to the API.

**2. SPA + API Worker pattern**

Using the official Cloudflare pattern: React SPA served from Workers Static Assets (free, no Worker invocations) + Hono API Worker for dynamic data. This means the landing page, docs, and dashboard UI are all served for free from the edge CDN. Only API calls invoke the Worker (and are fast because Hono).

**3. D1 for everything relational**

D1 is serverless SQLite on Cloudflare. Schema managed by Drizzle ORM with type-safe queries and automatic migrations.

### D1 Database Schema

```sql
-- Users (managed by Better Auth, extended)
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT UNIQUE NOT NULL,
    email_verified INTEGER DEFAULT 0,
    image TEXT,
    github_username TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Better Auth tables (auto-generated by Better Auth)
-- accounts, sessions, verification_tokens

-- Projects
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,                    -- e.g., "my-monorepo"
    repo_url TEXT,                         -- GitHub URL
    repo_provider TEXT DEFAULT 'github',   -- github | gitlab | bitbucket
    default_branch TEXT DEFAULT 'main',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Packages (within a project / monorepo)
CREATE TABLE packages (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    path TEXT NOT NULL,                    -- e.g., "apps/web", "packages/auth-lib"
    language TEXT,                         -- typescript, python, cpp, go, java, rust, etc.
    test_framework TEXT,                   -- vitest, pytest, gtest, go_test, junit5, etc.
    doc_framework TEXT,                    -- typedoc, sphinx, doxygen, etc.
    created_at TEXT DEFAULT (datetime('now'))
);

-- Coverage Reports
CREATE TABLE coverage_reports (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    package_id TEXT REFERENCES packages(id),  -- NULL = whole project
    run_id TEXT NOT NULL,                     -- Unique run identifier
    run_mode TEXT NOT NULL,                   -- pr | full | pick | drift | docs
    branch TEXT,
    commit_sha TEXT,
    
    -- Coverage numbers
    unit_coverage REAL,                    -- 0.0 - 100.0
    integration_coverage REAL,
    e2e_coverage REAL,
    overall_coverage REAL,
    
    -- Generation stats
    tests_generated INTEGER DEFAULT 0,
    tests_passed INTEGER DEFAULT 0,
    tests_failed INTEGER DEFAULT 0,
    bugs_found INTEGER DEFAULT 0,
    bugs_fixed INTEGER DEFAULT 0,
    
    -- Full report stored in R2
    report_r2_key TEXT,                    -- R2 object key for full JSON report
    
    created_at TEXT DEFAULT (datetime('now'))
);

-- Drift Results
CREATE TABLE drift_results (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    test_name TEXT NOT NULL,
    status TEXT NOT NULL,                  -- passed | drifted | error
    similarity_score REAL,                 -- 0.0 - 1.0
    baseline_output TEXT,
    current_output TEXT,
    details TEXT,                          -- JSON: explanation, suggestions
    created_at TEXT DEFAULT (datetime('now'))
);

-- Bug Reports
CREATE TABLE bugs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    package_id TEXT REFERENCES packages(id),
    file_path TEXT NOT NULL,
    function_name TEXT,
    description TEXT NOT NULL,
    root_cause TEXT,
    severity TEXT DEFAULT 'medium',        -- low | medium | high | critical
    status TEXT DEFAULT 'open',            -- open | fixed | wont_fix | false_positive
    github_issue_url TEXT,
    github_pr_url TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT
);

-- API Keys (for CLI auth to dashboard)
CREATE TABLE api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    project_id TEXT REFERENCES projects(id),  -- NULL = all projects
    key_hash TEXT NOT NULL UNIQUE,             -- bcrypt hash of the API key
    name TEXT,                                 -- e.g., "CI key", "local dev"
    last_used_at TEXT,
    expires_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX idx_coverage_project ON coverage_reports(project_id, created_at);
CREATE INDEX idx_coverage_package ON coverage_reports(package_id, created_at);
CREATE INDEX idx_drift_project ON drift_results(project_id, created_at);
CREATE INDEX idx_bugs_project ON bugs(project_id, status);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);
```

### Hono API Routes

```typescript
// src/worker/index.ts
import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { auth } from './lib/auth';         // Better Auth instance
import { authMiddleware } from './middleware/auth';
import { projectRoutes } from './routes/projects';
import { reportRoutes } from './routes/reports';
import { driftRoutes } from './routes/drift';
import { bugRoutes } from './routes/bugs';
import { webhookRoutes } from './routes/webhooks';
import { uploadRoutes } from './routes/upload';
import { apiKeyMiddleware } from './middleware/api-key';

type Bindings = {
  DB: D1Database;
  KV: KVNamespace;
  R2: R2Bucket;
  BETTER_AUTH_SECRET: string;
  BETTER_AUTH_URL: string;
  GITHUB_CLIENT_ID: string;
  GITHUB_CLIENT_SECRET: string;
};

const app = new Hono<{ Bindings: Bindings }>();

// CORS for SPA
app.use('/api/*', cors({
  origin: ['https://nit.dev', 'http://localhost:5173'],
  credentials: true,
}));

// Better Auth routes (login, register, OAuth callbacks)
app.on(['GET', 'POST'], '/api/auth/**', (c) => {
  return auth(c.env).handler(c.req.raw);
});

// Dashboard API routes (session-based auth)
app.route('/api/projects', authMiddleware, projectRoutes);
app.route('/api/drift', authMiddleware, driftRoutes);
app.route('/api/bugs', authMiddleware, bugRoutes);

// CLI upload routes (API key auth)
app.route('/api/v1/reports', apiKeyMiddleware, reportRoutes);
app.route('/api/v1/upload', apiKeyMiddleware, uploadRoutes);

// GitHub webhook (signature verification)
app.route('/api/webhooks', webhookRoutes);

export default app;
```

### Better Auth Configuration

```typescript
// src/worker/lib/auth.ts
import { betterAuth } from 'better-auth';
import { withCloudflare } from 'better-auth-cloudflare';
import { drizzleAdapter } from 'better-auth/adapters/drizzle';
import { drizzle } from 'drizzle-orm/d1';
import * as schema from '../db/schema';

export function auth(env: Bindings) {
  const db = drizzle(env.DB, { schema });
  
  return betterAuth({
    ...withCloudflare({
      autoDetectIpAddress: true,
      geolocationTracking: true,
    }),
    database: drizzleAdapter(db, {
      provider: 'sqlite',
    }),
    secret: env.BETTER_AUTH_SECRET,
    baseURL: env.BETTER_AUTH_URL,
    
    // Auth methods
    emailAndPassword: {
      enabled: true,
    },
    socialProviders: {
      github: {
        clientId: env.GITHUB_CLIENT_ID,
        clientSecret: env.GITHUB_CLIENT_SECRET,
      },
    },
    
    // Session config
    session: {
      expiresIn: 60 * 60 * 24 * 7,  // 7 days
      updateAge: 60 * 60 * 24,       // 1 day
    },
  });
}
```

### CLI ↔ Dashboard Integration

The CLI authenticates with the dashboard via API keys:

```bash
# User generates API key in dashboard UI
# Then configures CLI:
$ nit config set dashboard.url https://nit.dev
$ nit config set dashboard.api_key nit_key_abc123...

# Now runs upload results automatically:
$ nit pick --report
# ... runs swarm locally ...
# ✅ Results uploaded to https://nit.dev/dashboard/my-project

# Or in CI:
- uses: nit-ai/nit@v1
  with:
    mode: pick
    dashboard_url: https://nit.dev
    dashboard_api_key: ${{ secrets.NIT_API_KEY }}
```

Report upload flow:
```
CLI finishes run
  → Compresses full report to JSON
  → POST /api/v1/reports with API key header
  → Worker validates key, stores summary in D1, full report in R2
  → Dashboard UI reads from D1 for charts, R2 for drill-down
```

### Wrangler Configuration

```jsonc
// wrangler.jsonc
{
  "name": "nit-dashboard",
  "main": "src/worker/index.ts",
  "compatibility_date": "2025-12-01",
  "compatibility_flags": ["nodejs_compat"],
  
  "assets": {
    "directory": "./dist",
    "binding": "ASSETS",
    "not_found_handling": "single-page-application"
  },
  
  "d1_databases": [
    {
      "binding": "DB",
      "database_name": "nit-db",
      "database_id": "xxxx-xxxx-xxxx"
    }
  ],
  
  "kv_namespaces": [
    {
      "binding": "KV",
      "id": "xxxx"
    }
  ],
  
  "r2_buckets": [
    {
      "binding": "R2",
      "bucket_name": "nit-reports"
    }
  ],
  
  "triggers": {
    "crons": [
      "0 2 * * *"   // Nightly drift check aggregation
    ]
  },
  
  "placement": {
    "mode": "smart"  // Run Worker close to D1 for lower latency
  }
}
```

---

## 3. Landing Page — Cloudflare-Native

### Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Framework | **React + Vite** | Official CF template, SPA served free from Workers Static Assets |
| Styling | **Tailwind CSS v4** | Utility-first, fast iteration |
| Animations | **Framer Motion** | Smooth scroll animations, terminal effects |
| Icons | **Lucide React** | Clean, consistent icon set |
| Syntax Highlighting | **Shiki** | Terminal code block rendering |
| Deployment | **Cloudflare Workers** (`~/web` repository) | Separate deployment from platform Worker in `~/platform` |

### Design Direction

**Theme:** Dark mode, terminal-aesthetic with accent color (electric blue or acid green). Think: Warp terminal meets Linear's marketing site.

**Hero concept:** Split screen — left side shows a terminal with `nit pick` running (animated typewriter effect showing agents detecting, analyzing, building, finding bugs), right side shows the output: a GitHub PR with generated tests and a bug fix.

### Page Structure (Single SPA, route-based)

```
/ (landing)
├── Hero — animated terminal + tagline
├── Problem — "Your tests are lying to you" / stats
├── How It Works — 4-step flow: Detect → Analyze → Build → Report  
├── The Swarm — agent visualization (interactive)
├── Languages — logo grid with hover details
├── Memory — "Gets smarter every run" visualization
├── Comparison — feature table vs competitors
├── Quickstart — code blocks + 30s demo GIF
├── Community — contributors, Discord, "Build an adapter"
└── Footer

/dashboard (authenticated)
├── Projects overview
├── Per-project detail (coverage trends, bugs, drift)
├── Settings (API keys, alerts, team)
└── Docs integration

/docs (static, generated from repo)
├── Getting started
├── Configuration reference
├── Framework adapters
├── Plugin development guide
└── API reference
```

### Dashboard UI Features

```
PROJECTS OVERVIEW
├── Cards per project showing:
│   ├── Current coverage (unit / integration / e2e gauge charts)
│   ├── Trend sparkline (last 30 days)
│   ├── Open bugs count
│   ├── Last run status + time
│   └── Drift status indicator
│
PROJECT DETAIL
├── Coverage tab
│   ├── Coverage over time (line chart per package)
│   ├── Per-package breakdown table
│   ├── File-level heatmap (green=covered, red=uncovered)
│   └── Test generation history
├── Bugs tab
│   ├── Open bugs list with severity badges
│   ├── Bug discovery timeline
│   ├── Fix rate metrics
│   └── Links to GitHub issues/PRs
├── Drift tab
│   ├── Drift test results timeline
│   ├── Similarity score trends
│   ├── Alert history
│   └── Baseline management
├── Memory tab
│   ├── What the tool has learned (human-readable)
│   ├── Pattern library extracted from project
│   ├── Failed approaches log
│   └── Memory size over time
└── Settings tab
    ├── API key management (create, revoke, rotate)
    ├── Alert configuration (Slack webhook, email thresholds)
    ├── Team members (invite by email)
    └── Danger zone (delete project, reset memory)
```

---

## 4. Cloudflare Cost Analysis

### Free Tier Coverage (Generous)

| Service | Free Tier | Our Usage (small project) | Covered? |
|---|---|---|---|
| **Workers** | 100K requests/day | ~1K requests/day (API calls + LLM proxy) | ✅ |
| **Workers Static Assets** | Unlimited static serves | Landing + dashboard SPA | ✅ |
| **D1** | 5M reads/day, 100K writes/day, 5GB storage | ~10K reads, ~1K writes/day (incl. usage events) | ✅ |
| **KV** | 100K reads/day, 1K writes/day | ~5K reads (sessions + rate limit checks) | ✅ |
| **R2** | 10M Class A ops, 10M Class B ops, 10GB storage | ~100 uploads/day, ~1K reads | ✅ |
| **AI Gateway** | Free (analytics, caching, rate limiting) | LLM proxy routing + caching | ✅ |
| **Queues** | 10K operations/day (free), 1M/month (paid $5) | Usage event batching | ✅ |
| **Cron Triggers** | Included | Nightly aggregation + budget resets | ✅ |
| **Workers Builds** | 3K minutes/month | ~100 minutes/month | ✅ |

**Bottom line:** The entire platform — dashboard, LLM gateway, usage tracking — runs on Cloudflare with **no external infrastructure**. No PostgreSQL, no Redis, no Docker containers. Small-to-medium projects run entirely free. Larger teams need the Workers Paid plan ($5/month).

### Scaling Path

| Growth Stage | Monthly Cost | What You Get |
|---|---|---|
| Solo developer | **$0** | Full CLI + dashboard + LLM usage tracking, 1 project |
| Small team (5 people) | **$0** | Still within free tier |
| Growing startup (20 people, 10 repos) | **$5** | Workers Paid plan, extended D1/KV/R2/Queues, AI Gateway paid features |
| Enterprise (100+ repos) | **$25-50** | Higher D1 storage, more R2, dedicated AI Gateway instance |

---

## 5. Updated Technology Stack Summary

### CLI (Core Product)

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| CLI Framework | Click |
| AST Parsing | tree-sitter |
| LLM Interface | LiteLLM SDK (built-in) or CLI tool delegation |
| LLM Usage Tracking | LiteLLM `CustomLogger` callback — captures tokens + cost (local calculation) for every call, batch-POSTs to platform. Works with any provider key (BYOK or platform). |
| Task Queue | asyncio |
| Memory | JSON files in `.{name}/memory/` |
| Config | YAML (`.{name}.yml`) |
| Distribution | pip, pipx, Docker, GitHub Action |

### Web Platform (Dashboard + Landing Page)

| Component | Technology | Cloudflare Service |
|---|---|---|
| API Framework | Hono (TypeScript) | Workers |
| Frontend | React + Vite | Workers Static Assets |
| Database | Drizzle ORM | D1 (SQLite) |
| Auth | Better Auth | Workers + D1 + KV |
| Sessions | Better Auth + KV | KV |
| File Storage | R2 SDK | R2 |
| Scheduling | Cron Triggers | Workers |
| ORM | Drizzle | N/A |
| Styling | Tailwind CSS v4 | N/A |
| Charts | Recharts | N/A |
| Deployment | Wrangler | Workers Builds |

### LLM Gateway (Fully Serverless on Cloudflare)

| Component | Technology | Cloudflare Service |
|---|---|---|
| Provider Routing | AI Gateway | AI Gateway (free core features) |
| Edge Caching | AI Gateway caching | AI Gateway |
| Provider Key Storage | AI Gateway BYOK | Secrets Store |
| Virtual Keys | Custom — Hono Worker + D1 | Workers + D1 |
| Rate Limiting | Custom — KV counters with TTL | KV |
| Budget Enforcement | Custom — Hono middleware + D1 | Workers + D1 |
| Margin/Markup | Custom — multiplier in Hono proxy response | Workers |
| Usage Event Batching | Cloudflare Queues | Queues |
| Usage Storage | D1 tables (usage_events, usage_daily) | D1 |
| Nightly Aggregation | Cron Trigger + Workflows | Workers |
| CLI Usage Reporting | LiteLLM SDK `CustomLogger` callback | N/A (runs in CLI) |

**Architecture:** No external infrastructure. Platform-key users: CLI → Hono Worker (validate key, check budget/rate limit) → AI Gateway (BYOK, caching, routing) → providers. BYOK users: CLI → providers directly, `CustomLogger` callback batch-POSTs usage events to platform. Both paths write to D1 via Queues. Dashboard reads from D1.

### Repo Structure (Updated)

```
nit/                              # CLI repository
├── pyproject.toml
├── src/nit/
├── tests/
└── action/

web/                              # marketing repository (landing/docs only)
├── wrangler.jsonc
├── package.json
├── vite.config.ts
└── src/

platform/                         # platform repository (dashboard + API + gateway)
├── wrangler.jsonc
├── package.json
├── drizzle/
├── src/
│   ├── worker/
│   │   ├── index.ts
│   │   ├── lib/
│   │   │   ├── auth.ts
│   │   │   └── db.ts
│   │   ├── middleware/
│   │   │   ├── auth.ts
│   │   │   └── api-key.ts
│   │   ├── routes/
│   │   ├── queues/
│   │   └── db/
│   └── react-app/
└── tests/
```

---

## 6. Migration from Previous Plan

The following sections from the previous plan are **unchanged** and carry forward:

- §3: Supported Languages & Frameworks (all 12 languages + frameworks)
- §4: Monorepo & Multi-Repo Architecture
- §5: Swarm Architecture — The Agent System (all 6 agent types)
- §6: Memory System (per-package + global)
- §7: CLI Tool Integration (bring your own AI)
- §9: Detection Engine
- §10: LLM Drift Monitoring
- §11: Documentation Generation
- §13: Implementation Roadmap (adjusted: landing page/dashboard phases use Cloudflare stack)
- §14: Project File Structure (updated above for split `web/` + `platform/` repositories)
- §15: CLI Commands
- §16: Competitive Edge
- §17: Viral Growth Mechanisms

The **only changes** are:
1. **Naming** — new options replacing "nit"
2. **Web infrastructure** — Cloudflare-native replacing Supabase/Vercel/Next.js
3. **Dashboard tech** — Hono + D1 + Better Auth + R2 + React SPA replacing Next.js + Supabase
4. **Landing page** — Same design concept, built with React + Vite on Workers instead of Next.js on Vercel
5. **LLM gateway** — Fully serverless on Cloudflare (no LiteLLM Proxy, no PostgreSQL, no Redis). AI Gateway for provider routing/caching/BYOK. D1 for virtual keys + usage logs + budgets. KV for rate limiting. LiteLLM SDK `CustomLogger` callback in CLI reports usage for both platform-key and BYOK users. Margin applied in Hono Worker. Usage events batched via Cloudflare Queues.

---

*Pick your name, and we build.*


# Nit: Package Naming & Distribution Strategy

## 1. The Name Problem

**Brand name:** `nit` — domain: `getnit.dev`
**CLI command:** `nit` (this is what users type)

Now we need package names that are available AND install cleanly so the `nit` command just works.

### Current Registry Status

| Registry | `nit` | Status |
|---|---|---|
| **PyPI** | `nit` | ⚠️ TAKEN — a placeholder/squatted package (Guatemala tax ID validator related namespace) |
| **npm** | `nit` | ⚠️ TAKEN — abandoned text file issue tracker (v0.0.5, 14 years old, 2 dependents) |
| **Homebrew** | `nit` | ✅ Likely available (no known formula) |
| **GitHub** | `nit` | ⚠️ TAKEN as username — but `getnit` or `nit-dev` likely available |

### Recommended Package Names

The key insight: **the package name doesn't have to match the CLI command.** Many popular tools do this:

| Tool | Package Name (pip/npm) | CLI Command |
|---|---|---|
| Black | `black` | `black` |
| Claude Code | `@anthropic-ai/claude-code` | `claude` |
| Codex CLI | `@openai/codex` | `codex` |
| Prettier | `prettier` | `prettier` |
| Create React App | `create-react-app` | `npx create-react-app` |

**Strategy: Use `getnit` as the package name everywhere.** It matches the domain, it's memorable, and it's almost certainly available across all registries.

| Registry | Package Name | Install Command | CLI Command |
|---|---|---|---|
| **PyPI** | `getnit` | `pip install getnit` | `nit` |
| **pipx** | `getnit` | `pipx install getnit` | `nit` |
| **npm** | `getnit` | `npm install -g getnit` | `nit` |
| **npx** | `getnit` | `npx getnit@latest init` | `npx getnit` |
| **Homebrew** | `nit` (in custom tap) | `brew install getnit/tap/nit` | `nit` |
| **Docker** | `ghcr.io/getnit/nit` | `docker run ghcr.io/getnit/nit` | `nit` |
| **GitHub Action** | `getnit/nit@v1` | `uses: getnit/nit@v1` | N/A |
| **curl** | standalone binary | `curl -fsSL getnit.dev/install | sh` | `nit` |

**Alternative if `getnit` is somehow taken:** `nitpick-ai`, `nit-ai`, `@nit-dev/cli`

### GitHub Organization

**Primary:** `github.com/getnit`
- `getnit/nit` — main CLI repo
- `getnit/dashboard` — web dashboard (or monorepo)
- `getnit/adapters` — community framework adapters
- `getnit/homebrew-tap` — Homebrew formula

---

## 2. Multi-Platform Distribution Architecture

### The Problem

Our CLI is Python-based, but we're targeting developers across ALL ecosystems. A Go developer shouldn't need to know what `pip` is. A JS developer shouldn't install Python. The install experience must be:

```
One command. Under 30 seconds. Works everywhere.
```

### Distribution Channels (Priority Order)

#### Channel 1: npm / npx (HIGHEST PRIORITY — largest dev audience)

**Why npm first:** Every JS/TS developer (our largest initial audience) already has Node.js installed. `npx` requires zero permanent installation.

**How it works:** The npm package is a thin Node.js wrapper that:
1. Downloads the correct platform-specific Python binary (bundled with PyInstaller/Nuitka)
2. Extracts it to `~/.nit/bin/`
3. Proxies all commands to the binary

```
npm package: getnit
├── package.json
├── bin/
│   └── nit                    # Shell script / JS entry point
├── scripts/
│   ├── postinstall.js         # Downloads platform binary on install
│   └── proxy.js               # Proxies commands to binary
└── README.md
```

**package.json:**
```json
{
  "name": "getnit",
  "version": "0.1.0",
  "description": "AI testing swarm — unit, integration, E2E, drift, docs",
  "bin": {
    "nit": "./bin/nit"
  },
  "scripts": {
    "postinstall": "node scripts/postinstall.js"
  },
  "os": ["darwin", "linux", "win32"],
  "cpu": ["x64", "arm64"],
  "keywords": ["testing", "ai", "coverage", "e2e", "unit-test", "playwright", "pytest", "jest", "vitest"],
  "homepage": "https://getnit.dev",
  "repository": "github:getnit/nit"
}
```

**postinstall.js** (downloads correct binary):
```javascript
const os = require('os');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');

const PLATFORM_MAP = {
  'darwin-x64': 'nit-macos-x64',
  'darwin-arm64': 'nit-macos-arm64',
  'linux-x64': 'nit-linux-x64',
  'linux-arm64': 'nit-linux-arm64',
  'win32-x64': 'nit-windows-x64.exe',
};

const key = `${os.platform()}-${os.arch()}`;
const binary = PLATFORM_MAP[key];

if (!binary) {
  console.log(`⚠️  No pre-built binary for ${key}. Falling back to pip install.`);
  console.log('   Run: pip install getnit');
  process.exit(0);
}

const version = require('../package.json').version;
const url = `https://github.com/getnit/nit/releases/download/v${version}/${binary}`;
const dest = path.join(__dirname, '..', 'bin', os.platform() === 'win32' ? 'nit.exe' : 'nit-bin');

// Download binary from GitHub Releases
download(url, dest).then(() => {
  fs.chmodSync(dest, 0o755);
  console.log('✅ nit installed successfully');
});
```

**bin/nit** (shell wrapper):
```bash
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
BINARY="$DIR/nit-bin"

if [ -f "$BINARY" ]; then
  exec "$BINARY" "$@"
else
  echo "❌ nit binary not found. Try reinstalling: npm install -g getnit"
  exit 1
fi
```

**User experience:**
```bash
# Install globally
$ npm install -g getnit
# ✅ nit installed successfully

$ nit --version
# nit 0.1.0

# Or use without installing (npx)
$ npx getnit@latest init
# 🔍 Detecting project structure...
```

#### Channel 2: pip / pipx (Python developers)

**PyPI package name:** `getnit`

**pyproject.toml:**
```toml
[project]
name = "getnit"
version = "0.1.0"
description = "AI testing swarm — unit, integration, E2E, drift, docs"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
keywords = ["testing", "ai", "coverage", "e2e", "playwright", "pytest"]

[project.urls]
Homepage = "https://getnit.dev"
Repository = "https://github.com/getnit/nit"
Documentation = "https://getnit.dev/docs"

[project.scripts]
nit = "nit.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/nit"]
```

**User experience:**
```bash
# With pipx (recommended — isolated install)
$ pipx install getnit
# ✅ installed package getnit, installed using Python 3.12
#   These apps are now globally available: nit

$ nit --version
# nit 0.1.0

# With pip
$ pip install getnit
$ nit init
```

#### Channel 3: Homebrew (macOS / Linux power users)

**Homebrew tap:** `getnit/homebrew-tap`

**Formula (auto-generated from PyPI using homebrew-pypi-poet):**
```ruby
class Nit < Formula
  include Language::Python::Virtualenv

  desc "AI testing swarm — unit, integration, E2E, drift, docs"
  homepage "https://getnit.dev"
  url "https://files.pythonhosted.org/packages/.../getnit-0.1.0.tar.gz"
  sha256 "abc123..."
  license "MIT"

  depends_on "python@3.12"
  depends_on "tree-sitter"

  # ... resource blocks for dependencies (auto-generated by poet)

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "nit", shell_output("#{bin}/nit --version")
  end
end
```

**User experience:**
```bash
# Add tap (one-time)
$ brew tap getnit/tap

# Install
$ brew install nit
# ✅ nit 0.1.0 installed

$ nit --version
# nit 0.1.0

# Or one-liner:
$ brew install getnit/tap/nit
```

#### Channel 4: Standalone Binary (curl | sh)

**For users who don't have npm, pip, or brew.** Also the recommended install method in CI environments.

**Binary built with:** PyInstaller or Nuitka (compiles Python to standalone binary, ~50MB).

**Platforms built in CI (GitHub Actions matrix):**
- `nit-linux-x64`
- `nit-linux-arm64`
- `nit-macos-x64`
- `nit-macos-arm64`
- `nit-windows-x64.exe`

**Install script hosted at `getnit.dev/install`:**
```bash
#!/bin/sh
set -e

# Detect platform
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

case "$OS-$ARCH" in
  linux-x86_64)   BINARY="nit-linux-x64" ;;
  linux-aarch64)   BINARY="nit-linux-arm64" ;;
  darwin-x86_64)   BINARY="nit-macos-x64" ;;
  darwin-arm64)    BINARY="nit-macos-arm64" ;;
  *)
    echo "❌ Unsupported platform: $OS-$ARCH"
    echo "   Try: pip install getnit"
    exit 1
    ;;
esac

VERSION=$(curl -s https://api.github.com/repos/getnit/nit/releases/latest | grep tag_name | cut -d '"' -f 4)
URL="https://github.com/getnit/nit/releases/download/${VERSION}/${BINARY}"

echo "📦 Downloading nit ${VERSION} for ${OS}/${ARCH}..."

INSTALL_DIR="${HOME}/.nit/bin"
mkdir -p "$INSTALL_DIR"
curl -fsSL "$URL" -o "${INSTALL_DIR}/nit"
chmod +x "${INSTALL_DIR}/nit"

# Add to PATH
if ! echo "$PATH" | grep -q "$INSTALL_DIR"; then
  SHELL_NAME=$(basename "$SHELL")
  RC_FILE="${HOME}/.${SHELL_NAME}rc"
  echo "export PATH=\"${INSTALL_DIR}:\$PATH\"" >> "$RC_FILE"
  echo "✅ Added ${INSTALL_DIR} to PATH in ${RC_FILE}"
  echo "   Run: source ${RC_FILE}"
fi

echo "✅ nit ${VERSION} installed to ${INSTALL_DIR}/nit"
echo "   Run: nit --version"
```

**User experience:**
```bash
$ curl -fsSL getnit.dev/install | sh
# 📦 Downloading nit v0.1.0 for darwin/arm64...
# ✅ nit v0.1.0 installed to ~/.nit/bin/nit

$ nit --version
# nit 0.1.0
```

**Windows (PowerShell):**
```powershell
irm getnit.dev/install.ps1 | iex
```

#### Channel 5: Docker

```bash
# Run directly
$ docker run --rm -v $(pwd):/workspace ghcr.io/getnit/nit:latest pick

# Or use as base image in CI
FROM ghcr.io/getnit/nit:latest
COPY . /workspace
RUN nit scan
```

**Dockerfile:**
```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir getnit
WORKDIR /workspace
ENTRYPOINT ["nit"]
```

#### Channel 6: GitHub Action

```yaml
# .github/workflows/nit.yml
name: Nit Quality Check
on: [pull_request]

jobs:
  nit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: getnit/nit@v1
        with:
          mode: pick        # pick | scan | generate | drift | docs
          llm_provider: anthropic
          llm_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          dashboard_url: https://getnit.dev    # optional
          dashboard_key: ${{ secrets.NIT_API_KEY }}  # optional
```

**action.yml:**
```yaml
name: 'Nit — AI Testing Swarm'
description: 'Generate tests, find bugs, monitor drift, update docs'
branding:
  icon: 'shield'
  color: 'green'

inputs:
  mode:
    description: 'Run mode: pick | scan | generate | drift | docs'
    required: false
    default: 'pick'
  llm_provider:
    description: 'LLM provider: anthropic | openai | ollama'
    required: false
    default: 'anthropic'
  llm_api_key:
    description: 'API key for LLM provider'
    required: true
  dashboard_url:
    description: 'Dashboard URL for report upload'
    required: false
  dashboard_key:
    description: 'Dashboard API key'
    required: false

runs:
  using: 'composite'
  steps:
    - name: Install nit
      shell: bash
      run: pip install getnit
    - name: Run nit
      shell: bash
      env:
        NIT_LLM_PROVIDER: ${{ inputs.llm_provider }}
        NIT_LLM_API_KEY: ${{ inputs.llm_api_key }}
        NIT_DASHBOARD_URL: ${{ inputs.dashboard_url }}
        NIT_DASHBOARD_KEY: ${{ inputs.dashboard_key }}
      run: nit ${{ inputs.mode }} --ci
```

---

## 3. Install Experience Summary

### The "30-Second Install" Promise

| User Profile | Install Command | Time |
|---|---|---|
| **JS/TS developer** | `npm install -g getnit` | ~15s |
| **Quick try (no install)** | `npx getnit@latest init` | ~10s |
| **Python developer** | `pipx install getnit` | ~10s |
| **macOS power user** | `brew install getnit/tap/nit` | ~20s |
| **Any developer** | `curl -fsSL getnit.dev/install \| sh` | ~10s |
| **CI/CD** | `uses: getnit/nit@v1` | ~15s |
| **Docker user** | `docker run ghcr.io/getnit/nit` | ~30s (first pull) |

### The Quickstart (what appears on the landing page)

```bash
# Install (pick your weapon)
npm install -g getnit     # JS/TS devs
pipx install getnit       # Python devs
brew install getnit/tap/nit  # Homebrew
curl -fsSL getnit.dev/install | sh  # Universal

# Run
cd your-project
nit init                  # Detect stack, create .nit.yml
nit pick                  # Full swarm: detect → analyze → build → report
```

---

## 4. Binary Build Pipeline (GitHub Actions)

```yaml
# .github/workflows/release.yml
name: Release
on:
  push:
    tags: ['v*']

jobs:
  build-binaries:
    strategy:
      matrix:
        include:
          - os: ubuntu-latest
            target: linux-x64
            artifact: nit-linux-x64
          - os: ubuntu-latest
            target: linux-arm64
            artifact: nit-linux-arm64
          - os: macos-latest
            target: macos-x64
            artifact: nit-macos-x64
          - os: macos-14       # M1 runner
            target: macos-arm64
            artifact: nit-macos-arm64
          - os: windows-latest
            target: windows-x64
            artifact: nit-windows-x64.exe
    
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install pyinstaller
      - run: pip install -e ./cli
      - name: Build binary
        run: |
          pyinstaller --onefile --name ${{ matrix.artifact }} \
            --hidden-import nit \
            cli/src/nit/cli.py
      - uses: actions/upload-artifact@v4
        with:
          name: ${{ matrix.artifact }}
          path: dist/${{ matrix.artifact }}

  publish-pypi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install build twine
      - run: cd cli && python -m build
      - run: twine upload cli/dist/*
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}

  publish-npm:
    needs: build-binaries
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: cd npm && npm publish
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}

  create-release:
    needs: build-binaries
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
      - uses: softprops/action-gh-release@v2
        with:
          files: |
            nit-linux-x64/nit-linux-x64
            nit-linux-arm64/nit-linux-arm64
            nit-macos-x64/nit-macos-x64
            nit-macos-arm64/nit-macos-arm64
            nit-windows-x64.exe/nit-windows-x64.exe

  update-homebrew:
    needs: publish-pypi
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: getnit/homebrew-tap
          token: ${{ secrets.TAP_TOKEN }}
      - run: |
          # Auto-update formula with new version/sha
          pip install homebrew-pypi-poet
          poet -f getnit > Formula/nit.rb
          git add . && git commit -m "Update nit to ${{ github.ref_name }}"
          git push
```

---

## 5. Naming Cross-Reference

| Context | Name | Notes |
|---|---|---|
| **Brand** | Nit | Capitalized in prose |
| **CLI command** | `nit` | Lowercase, what users type |
| **PyPI** | `getnit` | `pip install getnit` → installs `nit` command |
| **npm** | `getnit` | `npm i -g getnit` → installs `nit` command |
| **Homebrew** | `nit` | In tap `getnit/tap` |
| **Docker** | `ghcr.io/getnit/nit` | GitHub Container Registry |
| **GitHub org** | `getnit` | `github.com/getnit` |
| **GitHub repo** | `getnit/nit` | Main repo |
| **GitHub Action** | `getnit/nit@v1` | Action reference |
| **Domain** | `getnit.dev` | Landing + dashboard + docs |
| **Config file** | `.nit.yml` | In project root |
| **Config dir** | `.nit/` | Memory, profile, drift tests |
| **Dashboard** | `getnit.dev/dashboard` | Cloudflare-hosted |
| **Docs** | `getnit.dev/docs` | Cloudflare-hosted |
| **Tagline** | "The AI that nitpicks your code so reviewers don't have to" | Marketing |

---

## 6. Naming Alternatives (Backup)

If `getnit` is taken anywhere:

| Alternative | PyPI | npm | GitHub |
|---|---|---|---|
| `nit-dev` | `nit-dev` | `nit-dev` | `nit-dev` |
| `nitpick-ai` | `nitpick-ai` | `nitpick-ai` | `nitpick-ai` |
| `@nit-dev/cli` | N/A | `@nit-dev/cli` | `nit-dev` |
| `runnit` | `runnit` | `runnit` | `runnit` |
| `nitr` | `nitr` | `nitr` | `nitr` |
