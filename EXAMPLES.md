# Example Projects for End-to-End Verification

This document describes the example projects used for end-to-end testing and verification of `nit`.

## Repository Structure

Create a separate GitHub repository: `getnit-dev/examples` with the following structure:

```
examples/
├── README.md
├── nextjs-app/          # TypeScript + Vitest
├── python-api/          # Python + pytest
├── cpp-cmake/           # C++ + GTest + CMake
├── java-maven/          # Java + JUnit + Maven
├── go-project/          # Go + go test
└── rust-cargo/          # Rust + cargo test
```

## Setup Instructions

### Clone the Examples Repository

```bash
cd ~
git clone https://github.com/getnit-dev/examples.git
```

## Example Project Specifications

### 1. `nextjs-app/` — TypeScript + Vitest

**Purpose:** Verify nit works with a modern Next.js + TypeScript + Vitest stack.

**Structure:**
```
nextjs-app/
├── package.json          # Next.js 14, React, TypeScript, Vitest
├── vitest.config.ts
├── tsconfig.json
├── src/
│   ├── app/
│   │   └── page.tsx
│   ├── components/
│   │   ├── Button.tsx
│   │   └── Card.tsx
│   └── utils/
│       ├── formatting.ts    # 5-10 untested functions
│       ├── validation.ts    # 5-10 untested functions
│       └── math.ts          # 5-10 untested functions
└── tests/
    └── utils/
        └── math.test.ts     # 1-2 existing tests (to establish patterns)
```

**Requirements:**
- TypeScript strict mode enabled
- Mix of pure functions and React components
- Some existing tests to establish project patterns
- No tests for `formatting.ts` and `validation.ts` (for nit to generate)

**Verification Steps:**
```bash
cd ~/examples/nextjs-app
pip install getnit
nit init
nit scan
# Should detect: TypeScript, Vitest, Next.js

nit generate
# Should generate:
# - tests/utils/formatting.test.ts
# - tests/utils/validation.test.ts

nit run
# Should execute all tests (existing + generated) and report coverage
```

**Success Criteria:**
- ✅ nit detects TypeScript and Vitest
- ✅ nit generates tests matching the existing test style (describe/it, expect)
- ✅ Generated tests are syntactically valid
- ✅ Generated tests pass when run with `npx vitest run`
- ✅ Coverage increases from ~30% to 80%+

---

### 2. `python-api/` — Python + pytest

**Purpose:** Verify nit works with a Python FastAPI + pytest stack.

**Structure:**
```
python-api/
├── pyproject.toml        # FastAPI, pytest, pytest-cov
├── pytest.ini
├── src/
│   └── api/
│       ├── __init__.py
│       ├── main.py           # FastAPI app
│       ├── models/
│       │   ├── __init__.py
│       │   └── user.py       # Pydantic models
│       ├── services/
│       │   ├── __init__.py
│       │   ├── auth.py       # 5-10 untested functions
│       │   ├── database.py   # 5-10 untested functions
│       │   └── validators.py # 5-10 untested functions
│       └── utils/
│           ├── __init__.py
│           └── helpers.py    # 5-10 untested functions
└── tests/
    ├── conftest.py           # pytest fixtures
    └── services/
        └── test_auth.py      # 1-2 existing tests (to establish patterns)
```

**Requirements:**
- Python 3.11+
- Type hints throughout
- Mix of pure functions and FastAPI dependencies
- Some existing tests with pytest fixtures
- No tests for `database.py`, `validators.py`, `helpers.py` (for nit to generate)

**Verification Steps:**
```bash
cd ~/examples/python-api
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pip install getnit
nit init
nit scan
# Should detect: Python, pytest

nit generate
# Should generate:
# - tests/services/test_database.py
# - tests/services/test_validators.py
# - tests/utils/test_helpers.py

nit run
# Should execute all tests and report coverage
```

**Success Criteria:**
- ✅ nit detects Python and pytest
- ✅ nit generates tests matching existing style (function-based, assert statements, pytest.fixture)
- ✅ Generated tests are syntactically valid
- ✅ Generated tests pass when run with `pytest`
- ✅ Coverage increases from ~30% to 80%+

---

## Verification Script

Create a script to automate end-to-end verification:

```bash
#!/bin/bash
# verify-e2e.sh

set -e  # Exit on error

echo "=== End-to-End Verification for nit ==="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

failed=0

# Function to run verification for a project
verify_project() {
    local project_dir=$1
    local project_name=$2
    local expected_frameworks=$3

    echo ""
    echo "======================================"
    echo "Testing: $project_name"
    echo "======================================"
    cd "$project_dir"

    # Step 1: Init
    echo "[1/4] Running nit init..."
    if nit init --yes > /tmp/nit-init.log 2>&1; then
        echo -e "${GREEN}✓${NC} nit init succeeded"
    else
        echo -e "${RED}✗${NC} nit init failed"
        cat /tmp/nit-init.log
        ((failed++))
        return 1
    fi

    # Step 2: Scan
    echo "[2/4] Running nit scan..."
    if nit scan > /tmp/nit-scan.log 2>&1; then
        echo -e "${GREEN}✓${NC} nit scan succeeded"
        # Verify detection
        grep -q "$expected_frameworks" /tmp/nit-scan.log || echo "Warning: Expected frameworks not detected"
    else
        echo -e "${RED}✗${NC} nit scan failed"
        cat /tmp/nit-scan.log
        ((failed++))
        return 1
    fi

    # Step 3: Generate
    echo "[3/4] Running nit generate..."
    if OPENAI_API_KEY="${OPENAI_API_KEY}" nit generate --coverage-target 80 > /tmp/nit-generate.log 2>&1; then
        echo -e "${GREEN}✓${NC} nit generate succeeded"
    else
        echo -e "${RED}✗${NC} nit generate failed"
        cat /tmp/nit-generate.log
        ((failed++))
        return 1
    fi

    # Step 4: Run tests
    echo "[4/4] Running nit run..."
    if nit run > /tmp/nit-run.log 2>&1; then
        echo -e "${GREEN}✓${NC} nit run succeeded"
        echo "Coverage report:"
        tail -n 10 /tmp/nit-run.log
    else
        echo -e "${RED}✗${NC} nit run failed"
        cat /tmp/nit-run.log
        ((failed++))
        return 1
    fi

    echo -e "${GREEN}✓ All checks passed for $project_name${NC}"
}

# Verify OPENAI_API_KEY is set
if [ -z "$OPENAI_API_KEY" ]; then
    echo -e "${RED}Error: OPENAI_API_KEY environment variable not set${NC}"
    exit 1
fi

# Verify Next.js project
verify_project "$HOME/examples/nextjs-app" "Next.js + Vitest" "Vitest"

# Verify Python project
verify_project "$HOME/examples/python-api" "Python + pytest" "pytest"

# Summary
echo ""
echo "======================================"
echo "Verification Summary"
echo "======================================"
if [ $failed -eq 0 ]; then
    echo -e "${GREEN}✓ All projects verified successfully!${NC}"
    exit 0
else
    echo -e "${RED}✗ $failed project(s) failed verification${NC}"
    exit 1
fi
```

Make it executable:
```bash
chmod +x verify-e2e.sh
```

Run verification:
```bash
export OPENAI_API_KEY="your-key-here"
./verify-e2e.sh
```

## Future Example Projects

As nit supports more languages and frameworks, add:

### 3. `cpp-cmake/` — C++ + GTest + CMake (Phase 3)
### 4. `java-maven/` — Java + JUnit + Maven (Phase 3)
### 5. `go-project/` — Go + go test (Phase 3)
### 6. `rust-cargo/` — Rust + cargo test (Phase 3)

## Manual Verification Checklist

For each release, manually verify:

- [ ] `nit init` detects the correct stack
- [ ] `nit scan` identifies untested code
- [ ] `nit generate` creates valid, passing tests
- [ ] Generated tests match project conventions
- [ ] `nit run` executes tests and shows coverage
- [ ] Coverage improves from baseline to target
- [ ] No regressions (existing tests still pass)
- [ ] Memory system learns from existing tests
- [ ] Self-iteration fixes failing generated tests

## CI Integration

Add to `.github/workflows/ci.yml` (in the main nit repo):

```yaml
e2e-verification:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.14'

    - name: Install nit
      run: pip install .

    - name: Clone examples
      run: git clone https://github.com/getnit-dev/examples.git ~/examples

    - name: Run E2E verification
      env:
        OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      run: |
        chmod +x ~/examples/verify-e2e.sh
        ~/examples/verify-e2e.sh
```

## Notes

- Keep example projects minimal but realistic
- Include a mix of tested and untested code
- Ensure existing tests demonstrate project conventions clearly
- Update examples as nit's capabilities grow
- Document any edge cases discovered during verification
