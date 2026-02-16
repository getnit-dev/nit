"""Memory system for nit.

Note: ``ConventionStore`` is intentionally **not** re-exported here.
Importing it eagerly would create a circular-import cycle::

    nit.memory -> conventions -> agents.analyzers.pattern
    -> agents.analyzers -> agents.builders -> adapters.registry
    -> nit.memory  (cycle)

Import ``ConventionStore`` directly from :mod:`nit.memory.conventions`
where needed.
"""

from nit.memory.analytics_collector import AnalyticsCollector
from nit.memory.analytics_history import AnalyticsHistory
from nit.memory.analytics_queries import AnalyticsQueries
from nit.memory.drift_baselines import DriftBaselinesManager
from nit.memory.global_memory import GlobalMemory
from nit.memory.package_memory import PackageMemory
from nit.memory.package_memory_manager import PackageMemoryManager
from nit.memory.prompt_analytics import PromptAnalytics
from nit.memory.prompt_store import PromptRecorder, get_prompt_recorder
from nit.memory.prompt_sync import PromptSyncer
from nit.memory.store import MemoryStore

__all__ = [
    "AnalyticsCollector",
    "AnalyticsHistory",
    "AnalyticsQueries",
    "DriftBaselinesManager",
    "GlobalMemory",
    "MemoryStore",
    "PackageMemory",
    "PackageMemoryManager",
    "PromptAnalytics",
    "PromptRecorder",
    "PromptSyncer",
    "get_prompt_recorder",
]
