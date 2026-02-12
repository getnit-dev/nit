"""Self-healing test engine for E2E tests.

This module provides the capability to automatically detect and fix E2E test
failures caused by UI/selector changes, and to identify flaky tests through
repeated execution.
"""

from __future__ import annotations

import importlib
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from nit.llm.engine import GenerationRequest, LLMMessage

if TYPE_CHECKING:
    from pathlib import Path

    from nit.adapters.base import RunResult, TestFrameworkAdapter
    from nit.llm.engine import LLMEngine

logger = logging.getLogger(__name__)


class FailureType(Enum):
    """Classification of test failure types."""

    SELECTOR_NOT_FOUND = "selector_not_found"
    """Element selector could not be found in the DOM."""

    TIMEOUT = "timeout"
    """Test timed out waiting for an element or action."""

    SELECTOR_MISMATCH = "selector_mismatch"
    """Selector exists but doesn't match expected state."""

    FLAKY = "flaky"
    """Test passes/fails intermittently (non-deterministic)."""

    UNKNOWN = "unknown"
    """Failure type could not be classified."""


@dataclass
class FailureClassification:
    """Classification result for a test failure."""

    failure_type: FailureType
    """The type of failure detected."""

    confidence: float
    """Confidence score (0.0-1.0) in this classification."""

    selector: str = ""
    """The problematic selector, if identified."""

    error_message: str = ""
    """The original error message from the test."""

    suggested_fix: str = ""
    """Suggested fix for the failure, if available."""


@dataclass
class DOMSnapshot:
    """Snapshot of DOM state for re-analysis."""

    selectors: list[str] = field(default_factory=list)
    """Available selectors in the DOM."""

    test_ids: list[str] = field(default_factory=list)
    """Available data-testid attributes."""

    roles: list[str] = field(default_factory=list)
    """Available ARIA roles."""

    text_content: list[str] = field(default_factory=list)
    """Available text content for text-based selectors."""


@dataclass
class HealingResult:
    """Result of a self-healing attempt."""

    healed: bool
    """Whether the test was successfully healed."""

    original_code: str
    """The original failing test code."""

    healed_code: str = ""
    """The healed test code, if healing was successful."""

    failure_classification: FailureClassification | None = None
    """Classification of the original failure."""

    attempts: int = 0
    """Number of healing attempts made."""

    is_flaky: bool = False
    """Whether the test was identified as flaky."""

    messages: list[str] = field(default_factory=list)
    """Log messages from the healing process."""


# ── Failure Detection Patterns ────────────────────────────────────────


_SELECTOR_PATTERNS = [
    # Playwright
    re.compile(r"(?:locator|element).*?not found", re.IGNORECASE),
    re.compile(r"element.*?not visible", re.IGNORECASE),
    re.compile(r"selector.*?not found", re.IGNORECASE),
    re.compile(r"waiting for selector.*?failed", re.IGNORECASE),
    # Generic patterns
    re.compile(r"unable to locate element", re.IGNORECASE),
    re.compile(r"no such element", re.IGNORECASE),
    re.compile(r"element.*?does not exist", re.IGNORECASE),
]

_TIMEOUT_PATTERNS = [
    re.compile(r"timeout.*?exceeded", re.IGNORECASE),
    re.compile(r"timed out", re.IGNORECASE),
    re.compile(r"waitFor.*?timeout", re.IGNORECASE),
]

_SELECTOR_EXTRACTION = re.compile(
    r"""
    (?:locator|getBy|page\.get|element|selector|find)
    .*?
    ['"](.*?)['"]
    """,
    re.VERBOSE | re.IGNORECASE,
)


# ── Self-Healing Engine ────────────────────────────────────────────────


class SelfHealingEngine:
    """Engine for automatically healing failing E2E tests.

    The engine can:
    1. Detect test failures caused by UI/selector changes
    2. Re-analyze the DOM to find updated selectors
    3. Regenerate test code with corrected selectors
    4. Detect flaky tests through repeated execution
    """

    def __init__(
        self,
        llm_engine: LLMEngine,
        adapter: TestFrameworkAdapter,
        *,
        flaky_test_retries: int = 3,
        max_healing_attempts: int = 2,
    ) -> None:
        """Initialize the self-healing engine.

        Args:
            llm_engine: LLM engine for test regeneration.
            adapter: Test framework adapter for running tests.
            flaky_test_retries: Number of retries for flaky test detection.
            max_healing_attempts: Maximum healing attempts per test.
        """
        self._llm = llm_engine
        self._adapter = adapter
        self._flaky_retries = flaky_test_retries
        self._max_attempts = max_healing_attempts

    async def heal_test(
        self,
        test_code: str,
        run_result: RunResult,
        original_request: GenerationRequest,
        project_path: Path,
        test_file: Path | None = None,
    ) -> HealingResult:
        """Attempt to heal a failing test.

        Args:
            test_code: The failing test code.
            run_result: The test run result containing failure information.
            original_request: The original LLM request used to generate the test.
            project_path: Project root path for running tests.
            test_file: Optional path to the test file for targeted execution.

        Returns:
            HealingResult with healing outcome and updated code if successful.
        """
        logger.info("Starting self-healing analysis for failing test")

        result = HealingResult(
            healed=False,
            original_code=test_code,
        )

        # Extract error messages from run result
        error_messages = self._extract_error_messages(run_result)
        if not error_messages:
            result.messages.append("No error messages found in test output")
            return result

        # Classify the failure
        classification = self._classify_failure(error_messages)
        result.failure_classification = classification
        result.messages.append(
            f"Classified failure as: {classification.failure_type.value} "
            f"(confidence: {classification.confidence:.2f})"
        )

        # Check for flaky tests first
        if classification.failure_type in (FailureType.TIMEOUT, FailureType.UNKNOWN):
            is_flaky = await self._check_if_flaky(test_code, project_path, test_file)
            result.is_flaky = is_flaky

            if is_flaky:
                result.messages.append(
                    f"Test identified as FLAKY after {self._flaky_retries} retries"
                )
                # Don't attempt healing for flaky tests
                return result

        # Attempt healing for selector-related failures
        if classification.failure_type in (
            FailureType.SELECTOR_NOT_FOUND,
            FailureType.SELECTOR_MISMATCH,
        ):
            healed_code = await self._attempt_selector_healing(
                test_code,
                classification,
                original_request,
                project_path,
                test_file,
            )

            if healed_code and healed_code != test_code:
                result.healed = True
                result.healed_code = healed_code
                result.messages.append("Successfully healed test with updated selectors")
            else:
                result.messages.append("Healing attempt did not produce valid fixes")

        return result

    def _extract_error_messages(self, run_result: RunResult) -> list[str]:
        """Extract error messages from test run result."""
        # Collect from test cases
        errors = [
            test_case.failure_message
            for test_case in run_result.test_cases
            if test_case.failure_message
        ]

        # Also check raw output if no structured errors
        if not errors and run_result.raw_output:
            errors.append(run_result.raw_output)

        return errors

    def _classify_failure(self, error_messages: list[str]) -> FailureClassification:
        """Classify the type of test failure based on error messages.

        Implements task 2.9.1: Detect test failures caused by UI/selector changes.
        """
        combined_errors = "\n".join(error_messages)

        # Check for selector not found
        for pattern in _SELECTOR_PATTERNS:
            if pattern.search(combined_errors):
                selector = self._extract_selector(combined_errors)
                return FailureClassification(
                    failure_type=FailureType.SELECTOR_NOT_FOUND,
                    confidence=0.9,
                    selector=selector,
                    error_message=combined_errors,
                    suggested_fix=(
                        (
                            f"The selector '{selector}' could not be found. "
                            "The DOM structure may have changed."
                        )
                        if selector
                        else "A selector could not be found in the DOM."
                    ),
                )

        # Check for timeout
        for pattern in _TIMEOUT_PATTERNS:
            if pattern.search(combined_errors):
                selector = self._extract_selector(combined_errors)
                return FailureClassification(
                    failure_type=FailureType.TIMEOUT,
                    confidence=0.85,
                    selector=selector,
                    error_message=combined_errors,
                    suggested_fix=(
                        "Test timed out. This could be a flaky test or the "
                        "element may have a different selector."
                    ),
                )

        # Default to unknown
        return FailureClassification(
            failure_type=FailureType.UNKNOWN,
            confidence=0.5,
            error_message=combined_errors,
        )

    def _extract_selector(self, error_text: str) -> str:
        """Extract selector from error message."""
        match = _SELECTOR_EXTRACTION.search(error_text)
        if match:
            return match.group(1)
        return ""

    async def _check_if_flaky(
        self,
        _test_code: str,
        project_path: Path,
        test_file: Path | None,
    ) -> bool:
        """Check if test is flaky by running it multiple times.

        Implements task 2.9.4: Run failing test 3x, if intermittent → mark as flaky.
        """
        logger.info(
            "Checking for flaky behavior with %d retries",
            self._flaky_retries,
        )

        results = []

        for attempt in range(self._flaky_retries):
            try:
                run_result = await self._adapter.run_tests(
                    project_path,
                    test_files=[test_file] if test_file else None,
                    timeout=60.0,
                )
                results.append(run_result.success)
                logger.debug("Flaky check attempt %d: %s", attempt + 1, run_result.success)
            except Exception as e:
                logger.warning("Flaky check attempt %d failed: %s", attempt + 1, e)
                results.append(False)

        # If results are inconsistent, it's flaky
        if len(set(results)) > 1:
            passed_count = sum(results)
            logger.info(
                "Test is FLAKY: passed %d/%d times",
                passed_count,
                self._flaky_retries,
            )
            return True

        return False

    async def _attempt_selector_healing(
        self,
        test_code: str,
        classification: FailureClassification,
        original_request: GenerationRequest,
        project_path: Path,
        _test_file: Path | None,
    ) -> str:
        """Attempt to heal selector-related failures.

        Implements tasks 2.9.2 and 2.9.3:
        - Re-scan the target page/component DOM to find updated selector
        - Feed original test + error + updated DOM context back to LLM for fix
        """
        logger.info("Attempting selector healing for: %s", classification.selector)

        # In a real implementation, we would:
        # 1. Launch a headless browser with Playwright
        # 2. Navigate to the page being tested
        # 3. Extract available selectors from the DOM
        # 4. Feed this information back to the LLM
        #
        # For now, we'll simulate DOM re-analysis and provide the error
        # feedback to the LLM for regeneration.

        # Simulate DOM snapshot (in production, this would be real DOM analysis)
        dom_snapshot = await self._analyze_dom(project_path, test_code)

        # Build healing prompt
        healing_prompt = self._build_healing_prompt(
            classification,
            dom_snapshot,
        )

        # Request LLM to regenerate with fixes
        messages = [
            *original_request.messages,
            LLMMessage(role="assistant", content=test_code),
            LLMMessage(role="user", content=healing_prompt),
        ]

        request = GenerationRequest(messages=messages)

        try:
            response = await self._llm.generate(request)
            healed_code = response.text.strip()

            # Clean up markdown code blocks if present
            healed_code = self._clean_code_blocks(healed_code)

            logger.info(
                "Generated healed test code (%d characters)",
                len(healed_code),
            )

            return healed_code

        except Exception as e:
            logger.exception("Healing attempt failed: %s", e)
            return ""

    async def _analyze_dom(
        self,
        _project_path: Path,
        test_code: str,
    ) -> DOMSnapshot:
        """Analyze DOM to find available selectors.

        Attempts to launch a headless Playwright browser and navigate to
        the page under test to extract live selector information.  Falls
        back to static extraction from the test source when Playwright
        is not installed or the target URL is unreachable.

        Args:
            _project_path: Project root path.
            test_code: The test source code (used to extract the target URL).

        Returns:
            DOMSnapshot with available selectors, test IDs, roles, and text.
        """
        target_url = self._extract_url_from_test(test_code)
        if target_url:
            snapshot = await self._live_dom_snapshot(target_url)
            if snapshot is not None:
                return snapshot

        # Fallback: extract selectors statically from test source
        return self._static_dom_snapshot(test_code)

    async def _live_dom_snapshot(self, url: str) -> DOMSnapshot | None:
        """Launch a headless browser and extract DOM information.

        Returns ``None`` when Playwright is not installed or the page
        cannot be loaded, allowing the caller to fall back gracefully.
        """
        try:
            pw_api = importlib.import_module("playwright.async_api")
        except ImportError:
            logger.debug("playwright package not installed — skipping live DOM analysis")
            return None

        try:
            async with pw_api.async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=15_000)

                    # Extract selectors, data-testid values, ARIA roles and text
                    dom_data: dict[str, list[str]] = await page.evaluate("""() => {
                        const MAX = 200;
                        const selectors = [];
                        const testIds = [];
                        const roles = new Set();
                        const texts = [];

                        for (const el of document.querySelectorAll('*')) {
                            if (selectors.length >= MAX) break;

                            // CSS id selector
                            if (el.id) selectors.push('#' + el.id);

                            // data-testid
                            const tid = el.getAttribute('data-testid')
                                      || el.getAttribute('data-test-id');
                            if (tid) testIds.push(tid);

                            // ARIA role
                            const role = el.getAttribute('role')
                                      || el.tagName.toLowerCase();
                            if (role) roles.add(role);

                            // Visible text (trimmed, non-empty, short)
                            const txt = (el.textContent || '').trim();
                            if (txt && txt.length < 100 && !el.children.length) {
                                texts.push(txt);
                            }
                        }

                        return {
                            selectors: [...new Set(selectors)].slice(0, MAX),
                            testIds:   [...new Set(testIds)].slice(0, MAX),
                            roles:     [...roles].slice(0, MAX),
                            texts:     [...new Set(texts)].slice(0, MAX),
                        };
                    }""")

                    return DOMSnapshot(
                        selectors=dom_data.get("selectors", []),
                        test_ids=dom_data.get("testIds", []),
                        roles=dom_data.get("roles", []),
                        text_content=dom_data.get("texts", []),
                    )
                finally:
                    await browser.close()

        except Exception as exc:
            logger.warning("Live DOM analysis failed for %s: %s", url, exc)
            return None

    # ── Static helpers ────────────────────────────────────────────────

    _URL_PATTERN = re.compile(
        r"""page\.goto\(\s*['"`](https?://[^'"`]+)['"`]""",
        re.IGNORECASE,
    )

    def _extract_url_from_test(self, test_code: str) -> str:
        """Extract the first ``page.goto(...)`` URL from test source."""
        match = self._URL_PATTERN.search(test_code)
        return match.group(1) if match else ""

    _STATIC_SELECTOR_RE = re.compile(
        r"""(?:locator|getBy\w+|querySelector|page\.\$)\(\s*['"`]([^'"`]+)['"`]""",
    )

    def _static_dom_snapshot(self, test_code: str) -> DOMSnapshot:
        """Build a best-effort DOMSnapshot from selectors found in test code."""
        raw_selectors = self._STATIC_SELECTOR_RE.findall(test_code)

        selectors: list[str] = []
        test_ids: list[str] = []
        roles: list[str] = []
        texts: list[str] = []

        seen: set[str] = set()
        for sel in raw_selectors:
            if sel in seen:
                continue
            seen.add(sel)

            if sel.startswith(("#", ".", "[")):
                selectors.append(sel)
            elif sel.startswith("role="):
                roles.append(sel.split("=", 1)[1])
            elif sel.startswith("data-testid="):
                test_ids.append(sel.split("=", 1)[1])
            else:
                texts.append(sel)

        return DOMSnapshot(
            selectors=selectors,
            test_ids=test_ids,
            roles=roles,
            text_content=texts,
        )

    def _build_healing_prompt(
        self,
        classification: FailureClassification,
        dom_snapshot: DOMSnapshot,
    ) -> str:
        """Build prompt for LLM to heal the test."""
        prompt = (
            "The generated E2E test has failed with a selector-related error:\n\n"
            f"Error: {classification.error_message}\n\n"
        )

        if classification.selector:
            prompt += f"Problematic selector: '{classification.selector}'\n\n"

        prompt += "Available selectors in the current DOM:\n"
        if dom_snapshot.test_ids:
            prompt += f"- data-testid: {', '.join(dom_snapshot.test_ids)}\n"
        if dom_snapshot.roles:
            prompt += f"- ARIA roles: {', '.join(dom_snapshot.roles)}\n"
        if dom_snapshot.text_content:
            prompt += f"- Text content: {', '.join(dom_snapshot.text_content[:5])}\n"

        prompt += (
            "\nPlease update the test code to use the correct selectors. "
            "Prefer data-testid attributes over CSS selectors when available. "
            "Return only the corrected test code without explanations."
        )

        return prompt

    def _clean_code_blocks(self, code: str) -> str:
        """Remove markdown code blocks if the LLM wrapped the output."""
        lines = code.strip().splitlines()

        # Check if wrapped in code fence
        if lines and lines[0].startswith("```"):
            # Remove first line (opening fence)
            lines = lines[1:]

            # Remove last line if it's a closing fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

        return "\n".join(lines).strip()
