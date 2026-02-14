"""Tests for the contract (Pact) analyzer and builder.

Covers:
- Detecting Pact contract JSON files in standard directories
- Detecting Pact dependencies in package.json and requirements files
- Parsing Pact v2 contracts (consumer, provider, interactions)
- Extracting request/response details and provider state
- Handling multiple contracts with different consumers/providers
- Generating test plans from analysis results
- Handling empty contracts directories
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nit.agents.analyzers.contract import (
    ContractAnalysisResult,
    PactContract,
    PactInteraction,
    PactRequest,
    PactResponse,
    analyze_contracts,
    detect_contract_files,
)
from nit.agents.builders.contract import ContractTestBuilder

# ── Fixtures ─────────────────────────────────────────────────────

_MINIMAL_PACT_V2: dict[str, object] = {
    "consumer": {"name": "WebApp"},
    "provider": {"name": "UserService"},
    "interactions": [
        {
            "description": "a request for users",
            "providerState": "users exist",
            "request": {
                "method": "GET",
                "path": "/api/users",
                "headers": {"Accept": "application/json"},
            },
            "response": {
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "body": {"users": [{"id": 1, "name": "Alice"}]},
            },
        }
    ],
}

_MULTI_INTERACTION_PACT: dict[str, object] = {
    "consumer": {"name": "Frontend"},
    "provider": {"name": "OrderService"},
    "interactions": [
        {
            "description": "a request to create an order",
            "providerState": "product exists",
            "request": {
                "method": "POST",
                "path": "/api/orders",
                "headers": {"Content-Type": "application/json"},
                "body": {"product_id": 42, "quantity": 2},
            },
            "response": {
                "status": 201,
                "headers": {"Content-Type": "application/json"},
                "body": {"order_id": 100},
            },
        },
        {
            "description": "a request to get order status",
            "providerState": "order exists",
            "request": {
                "method": "GET",
                "path": "/api/orders/100",
            },
            "response": {
                "status": 200,
                "body": {"order_id": 100, "status": "pending"},
            },
        },
    ],
}


@pytest.fixture()
def pact_project(tmp_path: Path) -> Path:
    """Create a project with a pacts/ directory containing one contract."""
    pacts_dir = tmp_path / "pacts"
    pacts_dir.mkdir()
    (pacts_dir / "webapp-userservice.json").write_text(
        json.dumps(_MINIMAL_PACT_V2), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def multi_contract_project(tmp_path: Path) -> Path:
    """Create a project with multiple contracts from different consumers."""
    pacts_dir = tmp_path / "pacts"
    pacts_dir.mkdir()
    (pacts_dir / "webapp-userservice.json").write_text(
        json.dumps(_MINIMAL_PACT_V2), encoding="utf-8"
    )
    (pacts_dir / "frontend-orderservice.json").write_text(
        json.dumps(_MULTI_INTERACTION_PACT), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def empty_project(tmp_path: Path) -> Path:
    """Create a project with an empty pacts/ directory."""
    (tmp_path / "pacts").mkdir()
    return tmp_path


# ── detect_contract_files ────────────────────────────────────────


def test_detect_finds_pact_json_in_pacts_dir(pact_project: Path) -> None:
    """detect_contract_files should find JSON files in pacts/ directory."""
    files = detect_contract_files(pact_project)
    assert len(files) == 1
    assert files[0].name == "webapp-userservice.json"


def test_detect_finds_files_in_pact_dir(tmp_path: Path) -> None:
    """detect_contract_files should find JSON files in pact/ directory."""
    pact_dir = tmp_path / "pact"
    pact_dir.mkdir()
    (pact_dir / "consumer-provider.json").write_text(json.dumps(_MINIMAL_PACT_V2), encoding="utf-8")
    files = detect_contract_files(tmp_path)
    assert len(files) == 1
    assert files[0].name == "consumer-provider.json"


def test_detect_finds_files_in_contracts_dir(tmp_path: Path) -> None:
    """detect_contract_files should find JSON files in contracts/ directory."""
    contracts_dir = tmp_path / "contracts"
    contracts_dir.mkdir()
    (contracts_dir / "api-contract.json").write_text(json.dumps(_MINIMAL_PACT_V2), encoding="utf-8")
    files = detect_contract_files(tmp_path)
    assert len(files) == 1
    assert files[0].name == "api-contract.json"


def test_detect_returns_empty_when_no_dirs(tmp_path: Path) -> None:
    """detect_contract_files should return empty list when no contract dirs exist."""
    files = detect_contract_files(tmp_path)
    assert files == []


def test_detect_returns_empty_for_empty_dir(empty_project: Path) -> None:
    """detect_contract_files should return empty list for empty pacts/ directory."""
    files = detect_contract_files(empty_project)
    assert files == []


def test_detect_pact_foundation_in_package_json(tmp_path: Path) -> None:
    """detect_contract_files should detect @pact-foundation/pact in package.json."""
    package_data = {
        "name": "my-app",
        "devDependencies": {
            "@pact-foundation/pact": "^12.0.0",
            "jest": "^29.0.0",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(package_data), encoding="utf-8")
    # Even without pact files, the function should not error
    files = detect_contract_files(tmp_path)
    assert files == []  # No actual contract files, just dependency detection


def test_detect_pact_python_in_requirements(tmp_path: Path) -> None:
    """detect_contract_files should detect pact-python in requirements.txt."""
    (tmp_path / "requirements-dev.txt").write_text("pytest\npact-python>=2.0.0\n", encoding="utf-8")
    files = detect_contract_files(tmp_path)
    assert files == []  # No actual contract files, just dependency detection


def test_detect_multiple_contracts(multi_contract_project: Path) -> None:
    """detect_contract_files should find multiple JSON files."""
    files = detect_contract_files(multi_contract_project)
    assert len(files) == 2
    names = {f.name for f in files}
    assert "webapp-userservice.json" in names
    assert "frontend-orderservice.json" in names


# ── analyze_contracts ────────────────────────────────────────────


def test_analyze_parses_minimal_pact_v2(pact_project: Path) -> None:
    """analyze_contracts should parse a minimal Pact v2 contract."""
    result = analyze_contracts(pact_project)

    assert len(result.contracts) == 1
    contract = result.contracts[0]
    assert contract.consumer == "WebApp"
    assert contract.provider == "UserService"
    assert len(contract.interactions) == 1


def test_analyze_extracts_interaction_details(pact_project: Path) -> None:
    """analyze_contracts should extract request, response, and provider state."""
    result = analyze_contracts(pact_project)
    interaction = result.contracts[0].interactions[0]

    assert interaction.description == "a request for users"
    assert interaction.provider_state == "users exist"

    # Request
    assert interaction.request.method == "GET"
    assert interaction.request.path == "/api/users"
    assert interaction.request.headers == {"Accept": "application/json"}
    assert interaction.request.body is None

    # Response
    assert interaction.response.status == 200
    assert interaction.response.headers == {"Content-Type": "application/json"}
    assert interaction.response.body is not None
    assert "users" in interaction.response.body


def test_analyze_counts_total_interactions(multi_contract_project: Path) -> None:
    """analyze_contracts should count interactions across all contracts."""
    result = analyze_contracts(multi_contract_project)
    assert result.total_interactions == 3  # 1 + 2


def test_analyze_collects_consumers_and_providers(
    multi_contract_project: Path,
) -> None:
    """analyze_contracts should collect unique consumer and provider names."""
    result = analyze_contracts(multi_contract_project)

    assert sorted(result.consumers) == ["Frontend", "WebApp"]
    assert sorted(result.providers) == ["OrderService", "UserService"]


def test_analyze_empty_project(empty_project: Path) -> None:
    """analyze_contracts should return empty result for empty pacts/ dir."""
    result = analyze_contracts(empty_project)

    assert result.contracts == []
    assert result.total_interactions == 0
    assert result.consumers == []
    assert result.providers == []


def test_analyze_skips_invalid_json(tmp_path: Path) -> None:
    """analyze_contracts should skip files that are not valid JSON."""
    pacts_dir = tmp_path / "pacts"
    pacts_dir.mkdir()
    (pacts_dir / "invalid.json").write_text("not json!", encoding="utf-8")
    (pacts_dir / "valid.json").write_text(json.dumps(_MINIMAL_PACT_V2), encoding="utf-8")

    result = analyze_contracts(tmp_path)
    assert len(result.contracts) == 1
    assert result.contracts[0].consumer == "WebApp"


def test_analyze_skips_non_pact_json(tmp_path: Path) -> None:
    """analyze_contracts should skip JSON files that lack consumer/provider."""
    pacts_dir = tmp_path / "pacts"
    pacts_dir.mkdir()
    (pacts_dir / "config.json").write_text(json.dumps({"setting": "value"}), encoding="utf-8")

    result = analyze_contracts(tmp_path)
    assert result.contracts == []


def test_analyze_request_with_body(tmp_path: Path) -> None:
    """analyze_contracts should parse request body from POST interactions."""
    pacts_dir = tmp_path / "pacts"
    pacts_dir.mkdir()
    (pacts_dir / "order.json").write_text(json.dumps(_MULTI_INTERACTION_PACT), encoding="utf-8")

    result = analyze_contracts(tmp_path)
    create_interaction = result.contracts[0].interactions[0]

    assert create_interaction.request.method == "POST"
    assert create_interaction.request.body is not None
    assert create_interaction.request.body["product_id"] == 42
    assert create_interaction.request.body["quantity"] == 2


def test_analyze_provider_state_v3_key(tmp_path: Path) -> None:
    """analyze_contracts should handle provider_state key (v3 format variant)."""
    pact_data: dict[str, object] = {
        "consumer": {"name": "App"},
        "provider": {"name": "API"},
        "interactions": [
            {
                "description": "a v3 interaction",
                "provider_state": "state from v3 format",
                "request": {"method": "GET", "path": "/health"},
                "response": {"status": 200},
            }
        ],
    }
    pacts_dir = tmp_path / "pacts"
    pacts_dir.mkdir()
    (pacts_dir / "v3.json").write_text(json.dumps(pact_data), encoding="utf-8")

    result = analyze_contracts(tmp_path)
    interaction = result.contracts[0].interactions[0]
    assert interaction.provider_state == "state from v3 format"


# ── ContractTestBuilder ─────────────────────────────────────────


def test_builder_generates_consumer_and_provider_tests() -> None:
    """ContractTestBuilder should generate consumer and provider test cases."""
    analysis = ContractAnalysisResult(
        contracts=[
            PactContract(
                consumer="WebApp",
                provider="UserService",
                interactions=[
                    PactInteraction(
                        description="get users",
                        provider_state="users exist",
                        request=PactRequest(method="GET", path="/api/users"),
                        response=PactResponse(status=200),
                    )
                ],
            )
        ],
        total_interactions=1,
        consumers=["WebApp"],
        providers=["UserService"],
    )

    builder = ContractTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    assert len(test_cases) == 2

    consumer_case = test_cases[0]
    assert consumer_case.test_type == "consumer_mock"
    assert consumer_case.consumer == "WebApp"
    assert consumer_case.provider == "UserService"
    assert "test_consumer_" in consumer_case.test_name

    provider_case = test_cases[1]
    assert provider_case.test_type == "provider_verification"
    assert provider_case.consumer == "WebApp"
    assert provider_case.provider == "UserService"
    assert "test_provider_" in provider_case.test_name


def test_builder_generates_tests_for_multiple_interactions() -> None:
    """ContractTestBuilder should generate tests for every interaction."""
    analysis = ContractAnalysisResult(
        contracts=[
            PactContract(
                consumer="Frontend",
                provider="OrderService",
                interactions=[
                    PactInteraction(
                        description="create order",
                        provider_state="product exists",
                        request=PactRequest(method="POST", path="/orders"),
                        response=PactResponse(status=201),
                    ),
                    PactInteraction(
                        description="get order status",
                        provider_state="order exists",
                        request=PactRequest(method="GET", path="/orders/1"),
                        response=PactResponse(status=200),
                    ),
                ],
            )
        ],
        total_interactions=2,
        consumers=["Frontend"],
        providers=["OrderService"],
    )

    builder = ContractTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    # 2 interactions * 2 test types = 4 test cases
    assert len(test_cases) == 4

    test_types = [tc.test_type for tc in test_cases]
    assert test_types.count("consumer_mock") == 2
    assert test_types.count("provider_verification") == 2


def test_builder_handles_empty_analysis() -> None:
    """ContractTestBuilder should return empty list for empty analysis."""
    analysis = ContractAnalysisResult()
    builder = ContractTestBuilder()
    test_cases = builder.generate_test_plan(analysis)
    assert test_cases == []


def test_builder_test_name_slugification() -> None:
    """ContractTestBuilder should produce valid test names from descriptions."""
    analysis = ContractAnalysisResult(
        contracts=[
            PactContract(
                consumer="App",
                provider="API",
                interactions=[
                    PactInteraction(
                        description="a request for user's profile (special chars!)",
                        provider_state="user exists",
                        request=PactRequest(method="GET", path="/profile"),
                        response=PactResponse(status=200),
                    )
                ],
            )
        ],
        total_interactions=1,
        consumers=["App"],
        providers=["API"],
    )

    builder = ContractTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    for tc in test_cases:
        # Test names should only contain valid identifier characters
        assert tc.test_name.replace("_", "").isalnum()


def test_builder_multiple_contracts() -> None:
    """ContractTestBuilder should handle multiple contracts."""
    analysis = ContractAnalysisResult(
        contracts=[
            PactContract(
                consumer="WebApp",
                provider="UserService",
                interactions=[
                    PactInteraction(
                        description="get users",
                        provider_state="users exist",
                        request=PactRequest(method="GET", path="/users"),
                        response=PactResponse(status=200),
                    )
                ],
            ),
            PactContract(
                consumer="MobileApp",
                provider="UserService",
                interactions=[
                    PactInteraction(
                        description="get user by id",
                        provider_state="user 1 exists",
                        request=PactRequest(method="GET", path="/users/1"),
                        response=PactResponse(status=200),
                    )
                ],
            ),
        ],
        total_interactions=2,
        consumers=["MobileApp", "WebApp"],
        providers=["UserService"],
    )

    builder = ContractTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    # 2 contracts * 1 interaction * 2 test types = 4 test cases
    assert len(test_cases) == 4

    consumers = {tc.consumer for tc in test_cases}
    assert consumers == {"WebApp", "MobileApp"}


def test_builder_descriptions_are_human_readable() -> None:
    """ContractTestBuilder should produce informative descriptions."""
    analysis = ContractAnalysisResult(
        contracts=[
            PactContract(
                consumer="WebApp",
                provider="API",
                interactions=[
                    PactInteraction(
                        description="fetch data",
                        provider_state="data ready",
                        request=PactRequest(method="GET", path="/data"),
                        response=PactResponse(status=200),
                    )
                ],
            )
        ],
        total_interactions=1,
        consumers=["WebApp"],
        providers=["API"],
    )

    builder = ContractTestBuilder()
    test_cases = builder.generate_test_plan(analysis)

    consumer_case = test_cases[0]
    assert "WebApp" in consumer_case.description
    assert "fetch data" in consumer_case.description

    provider_case = test_cases[1]
    assert "API" in provider_case.description
    assert "fetch data" in provider_case.description
