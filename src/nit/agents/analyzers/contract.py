"""Contract testing (Pact) analyzer -- detects and parses Pact contract files.

This analyzer:
1. Discovers Pact contract JSON files in common locations
2. Detects Pact dependencies in package.json and requirements files
3. Parses Pact v2/v3 contract format (consumer, provider, interactions)
4. Produces a ContractAnalysisResult summarizing all contracts
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── Data models ──────────────────────────────────────────────────


@dataclass
class PactRequest:
    """HTTP request within a Pact interaction."""

    method: str
    """HTTP method (GET, POST, etc.)."""

    path: str
    """Request path."""

    headers: dict[str, str] = field(default_factory=dict)
    """Request headers."""

    body: dict[str, Any] | None = None
    """Optional request body."""


@dataclass
class PactResponse:
    """HTTP response within a Pact interaction."""

    status: int
    """HTTP status code."""

    headers: dict[str, str] = field(default_factory=dict)
    """Response headers."""

    body: dict[str, Any] | None = None
    """Optional response body."""


@dataclass
class PactInteraction:
    """A single consumer-provider interaction in a Pact contract."""

    description: str
    """Human-readable description of the interaction."""

    provider_state: str
    """The provider state required for this interaction."""

    request: PactRequest
    """The expected request."""

    response: PactResponse
    """The expected response."""


@dataclass
class PactContract:
    """A complete Pact contract between a consumer and provider."""

    consumer: str
    """Name of the consumer service."""

    provider: str
    """Name of the provider service."""

    interactions: list[PactInteraction] = field(default_factory=list)
    """List of interactions defined in this contract."""


@dataclass
class ContractAnalysisResult:
    """Aggregated result of contract analysis across all discovered files."""

    contracts: list[PactContract] = field(default_factory=list)
    """All parsed Pact contracts."""

    total_interactions: int = 0
    """Total number of interactions across all contracts."""

    consumers: list[str] = field(default_factory=list)
    """Unique consumer names found."""

    providers: list[str] = field(default_factory=list)
    """Unique provider names found."""


# ── Detection ────────────────────────────────────────────────────


def detect_contract_files(project_root: Path) -> list[Path]:
    """Find Pact contract JSON files in common locations.

    Searches the following directories for ``*.json`` files:
    - ``pacts/``
    - ``pact/``
    - ``contracts/``

    Also checks ``package.json`` for the ``@pact-foundation/pact`` dependency
    and ``requirements*.txt`` for ``pact-python``.

    Args:
        project_root: Root directory of the project.

    Returns:
        Sorted list of discovered contract file paths.
    """
    contract_dirs = ["pacts", "pact", "contracts"]
    found: list[Path] = []

    for dir_name in contract_dirs:
        contract_dir = project_root / dir_name
        if contract_dir.is_dir():
            found.extend(sorted(contract_dir.glob("*.json")))

    # Check package.json for Pact JS dependency
    package_json = project_root / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            all_deps: dict[str, str] = {}
            for key in ("dependencies", "devDependencies"):
                deps = data.get(key)
                if isinstance(deps, dict):
                    all_deps.update(deps)
            if "@pact-foundation/pact" in all_deps:
                logger.info("Detected @pact-foundation/pact in package.json")
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Could not parse package.json: %s", exc)

    # Check requirements*.txt for pact-python
    for req_file in project_root.glob("requirements*.txt"):
        try:
            content = req_file.read_text(encoding="utf-8")
            if "pact-python" in content:
                logger.info("Detected pact-python in %s", req_file.name)
        except OSError as exc:
            logger.debug("Could not read %s: %s", req_file.name, exc)

    return found


# ── Parsing ──────────────────────────────────────────────────────


def _parse_request(raw: dict[str, Any]) -> PactRequest:
    """Parse a Pact request object from JSON.

    Args:
        raw: Raw request dictionary from the Pact JSON file.

    Returns:
        Parsed PactRequest.
    """
    headers = raw.get("headers") or {}
    body = raw.get("body")
    if isinstance(body, dict):
        body_dict: dict[str, Any] | None = body
    else:
        body_dict = None
    return PactRequest(
        method=str(raw.get("method", "GET")),
        path=str(raw.get("path", "/")),
        headers={str(k): str(v) for k, v in headers.items()},
        body=body_dict,
    )


def _parse_response(raw: dict[str, Any]) -> PactResponse:
    """Parse a Pact response object from JSON.

    Args:
        raw: Raw response dictionary from the Pact JSON file.

    Returns:
        Parsed PactResponse.
    """
    headers = raw.get("headers") or {}
    body = raw.get("body")
    if isinstance(body, dict):
        body_dict: dict[str, Any] | None = body
    else:
        body_dict = None
    return PactResponse(
        status=int(raw.get("status", 200)),
        headers={str(k): str(v) for k, v in headers.items()},
        body=body_dict,
    )


def _parse_interaction(raw: dict[str, Any]) -> PactInteraction:
    """Parse a single Pact interaction from JSON.

    Args:
        raw: Raw interaction dictionary from the Pact JSON file.

    Returns:
        Parsed PactInteraction.
    """
    return PactInteraction(
        description=str(raw.get("description", "")),
        provider_state=str(raw.get("providerState", raw.get("provider_state", ""))),
        request=_parse_request(raw.get("request") or {}),
        response=_parse_response(raw.get("response") or {}),
    )


def _parse_contract_file(file_path: Path) -> PactContract | None:
    """Parse a single Pact JSON contract file.

    Supports both Pact v2 and v3 formats. Returns ``None`` if the file
    cannot be parsed or does not look like a Pact contract.

    Args:
        file_path: Path to the Pact JSON file.

    Returns:
        Parsed PactContract, or None if parsing fails.
    """
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not parse contract file %s: %s", file_path, exc)
        return None

    if not isinstance(data, dict):
        return None

    # Extract consumer and provider names
    consumer_obj = data.get("consumer") or {}
    provider_obj = data.get("provider") or {}
    consumer = str(consumer_obj.get("name", "")) if isinstance(consumer_obj, dict) else ""
    provider = str(provider_obj.get("name", "")) if isinstance(provider_obj, dict) else ""

    if not consumer and not provider:
        logger.debug("File %s does not appear to be a Pact contract", file_path)
        return None

    # Parse interactions
    raw_interactions = data.get("interactions") or []
    interactions = [_parse_interaction(item) for item in raw_interactions if isinstance(item, dict)]

    return PactContract(
        consumer=consumer,
        provider=provider,
        interactions=interactions,
    )


# ── Analysis ─────────────────────────────────────────────────────


def analyze_contracts(project_root: Path) -> ContractAnalysisResult:
    """Analyze all Pact contract files found in the project.

    Discovers contract JSON files, parses them, and produces an aggregated
    analysis result including all contracts, total interaction count, and
    unique consumer/provider names.

    Args:
        project_root: Root directory of the project.

    Returns:
        ContractAnalysisResult summarizing all discovered contracts.
    """
    contract_files = detect_contract_files(project_root)
    contracts: list[PactContract] = []

    for file_path in contract_files:
        contract = _parse_contract_file(file_path)
        if contract is not None:
            contracts.append(contract)

    total_interactions = sum(len(c.interactions) for c in contracts)
    consumers = sorted({c.consumer for c in contracts if c.consumer})
    providers = sorted({c.provider for c in contracts if c.provider})

    logger.info(
        "Contract analysis: %d contracts, %d interactions, %d consumers, %d providers",
        len(contracts),
        total_interactions,
        len(consumers),
        len(providers),
    )

    return ContractAnalysisResult(
        contracts=contracts,
        total_interactions=total_interactions,
        consumers=consumers,
        providers=providers,
    )
