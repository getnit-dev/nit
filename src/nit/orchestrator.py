"""Async orchestrator for dispatching and running agent tasks."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class WorkItem:
    """A queued work item binding a task to an agent."""

    agent: BaseAgent
    task: TaskInput
    future: asyncio.Future[TaskOutput] = field(init=False)

    def __post_init__(self) -> None:
        loop = asyncio.get_event_loop()
        self.future = loop.create_future()


class Orchestrator:
    """Async orchestrator with in-memory work queue and parallel execution."""

    def __init__(self, max_concurrency: int = 4) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._queue: asyncio.Queue[WorkItem] = asyncio.Queue()
        self._max_concurrency = max_concurrency
        self._running = False

    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent for task dispatch."""
        self._agents[agent.name] = agent
        logger.info("Registered agent: %s", agent.name)

    def get_agent(self, name: str) -> BaseAgent | None:
        """Look up a registered agent by name."""
        return self._agents.get(name)

    async def submit(self, agent: BaseAgent, task: TaskInput) -> TaskOutput:
        """Submit a task to an agent and wait for the result."""
        item = WorkItem(agent=agent, task=task)
        await self._queue.put(item)
        return await item.future

    async def _worker(self) -> None:
        """Worker coroutine that pulls tasks from the queue and executes them."""
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except TimeoutError:
                continue

            try:
                logger.info(
                    "Running agent %s on task %s",
                    item.agent.name,
                    item.task.task_type,
                )
                result = await item.agent.run(item.task)
                item.future.set_result(result)
            except Exception as exc:
                error_output = TaskOutput(
                    status=TaskStatus.FAILED,
                    errors=[str(exc)],
                )
                item.future.set_result(error_output)
                logger.exception("Agent %s failed", item.agent.name)
            finally:
                self._queue.task_done()

    async def start(self) -> list[asyncio.Task[None]]:
        """Start worker tasks. Returns the list of worker asyncio tasks."""
        self._running = True
        workers = [asyncio.create_task(self._worker()) for _ in range(self._max_concurrency)]
        logger.info("Orchestrator started with %d workers", self._max_concurrency)
        return workers

    async def stop(self, workers: list[asyncio.Task[None]]) -> None:
        """Drain the queue and stop all workers."""
        await self._queue.join()
        self._running = False
        await asyncio.gather(*workers, return_exceptions=True)
        logger.info("Orchestrator stopped")

    async def run_all(self, tasks: list[tuple[BaseAgent, TaskInput]]) -> list[TaskOutput]:
        """Submit a batch of tasks and wait for all results.

        Convenience method that starts workers, submits all tasks,
        waits for results, and shuts down.
        """
        workers = await self.start()
        futures = [asyncio.ensure_future(self.submit(agent, task)) for agent, task in tasks]
        results = await asyncio.gather(*futures)
        await self.stop(workers)
        return list(results)
