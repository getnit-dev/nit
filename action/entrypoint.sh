#!/bin/bash
# GitHub Action entrypoint for nit
# This script is provided for reference but the composite action in action.yml
# handles execution directly without needing this separate script.

set -e

# Parse inputs (passed as environment variables from GitHub Actions)
MODE="${INPUT_MODE:-hunt}"
LLM_PROVIDER="${INPUT_LLM_PROVIDER:-}"
LLM_MODEL="${INPUT_LLM_MODEL:-}"
LLM_API_KEY="${INPUT_LLM_API_KEY:-}"
PLATFORM_URL="${INPUT_PLATFORM_URL:-}"
PLATFORM_API_KEY="${INPUT_PLATFORM_API_KEY:-}"
DASHBOARD_URL="${INPUT_DASHBOARD_URL:-}"
DASHBOARD_KEY="${INPUT_DASHBOARD_KEY:-}"
PATH_ARG="${INPUT_PATH:-.}"
COVERAGE_TARGET="${INPUT_COVERAGE_TARGET:-}"
TEST_TYPE="${INPUT_TEST_TYPE:-all}"

echo "==> Running nit in CI mode"
echo "    Mode: $MODE"
echo "    Path: $PATH_ARG"
echo "    Test type: $TEST_TYPE"

# Set up LLM/platform configuration if provided
if [ -n "$LLM_PROVIDER" ] || [ -n "$LLM_MODEL" ] || [ -n "$LLM_API_KEY" ] || [ -n "$PLATFORM_URL" ] || [ -n "$PLATFORM_API_KEY" ]; then
    echo "==> Configuring nit runtime values"
    mkdir -p .nit
    cat > .nit.yml <<EOF
llm:
  provider: $LLM_PROVIDER
  model: $LLM_MODEL
  api_key: $LLM_API_KEY
EOF

    if [ -n "$PLATFORM_URL" ] || [ -n "$PLATFORM_API_KEY" ]; then
        PLATFORM_MODE="platform"
        if [ -n "$LLM_API_KEY" ]; then
            PLATFORM_MODE="byok"
        fi
        cat >> .nit.yml <<EOF
platform:
  url: $PLATFORM_URL
  api_key: $PLATFORM_API_KEY
  mode: $PLATFORM_MODE
EOF
    fi
fi

# Export environment variables
export NIT_LLM_API_KEY="$LLM_API_KEY"
export NIT_PLATFORM_URL="$PLATFORM_URL"
export NIT_PLATFORM_API_KEY="$PLATFORM_API_KEY"
export NIT_DASHBOARD_URL="$DASHBOARD_URL"
export NIT_DASHBOARD_KEY="$DASHBOARD_KEY"

# Build command
CMD="nit $MODE --ci --path $PATH_ARG"

# Add mode-specific flags
if [ "$MODE" = "generate" ] || [ "$MODE" = "hunt" ]; then
    CMD="$CMD --type $TEST_TYPE"
    if [ -n "$COVERAGE_TARGET" ]; then
        CMD="$CMD --coverage-target $COVERAGE_TARGET"
    fi
fi

# Execute
echo "==> Executing: $CMD"
$CMD
EXIT_CODE=$?

# Report result
if [ $EXIT_CODE -eq 0 ]; then
    echo "==> nit completed successfully"
else
    echo "==> nit failed with exit code $EXIT_CODE"
fi

exit $EXIT_CODE
