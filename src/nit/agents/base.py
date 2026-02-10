"""Base agent interface for all nit agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskInput:
    """Input for an agent task."""

    task_type: str
    target: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskOutput:
    """Output from an agent task."""

    status: TaskStatus
    result: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class BaseAgent(ABC):
    """Abstract base class for all nit agents."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name identifying this agent."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this agent does."""

    @abstractmethod
    async def run(self, task: TaskInput) -> TaskOutput:
        """Execute the agent's task asynchronously.

        Args:
            task: The input task to process.

        Returns:
            The result of the task execution.
        """
