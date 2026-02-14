"""E2E test framework adapters."""

from nit.adapters.e2e.cypress_adapter import CypressAdapter
from nit.adapters.e2e.playwright_adapter import PlaywrightAdapter

__all__ = [
    "CypressAdapter",
    "PlaywrightAdapter",
]
