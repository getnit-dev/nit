"""Tests for the base agent interface and orchestrator."""

from typing import cast

from nit.agents.base import BaseAgent, TaskInput, TaskOutput, TaskStatus
from nit.orchestrator import Orchestrator


class EchoAgent(BaseAgent):
    """Test agent that echoes its input."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes input back"

    async def run(self, task: TaskInput) -> TaskOutput:
        return TaskOutput(
            status=TaskStatus.COMPLETED,
            result={"echoed": task.target},
        )


class FailAgent(BaseAgent):
    """Test agent that always fails."""

    @property
    def name(self) -> str:
        return "fail"

    @property
    def description(self) -> str:
        return "Always fails"

    async def run(self, task: TaskInput) -> TaskOutput:
        raise RuntimeError("intentional failure")


def test_agent_interface() -> None:
    agent = EchoAgent()
    assert agent.name == "echo"
    assert agent.description == "Echoes input back"


async def test_orchestrator_single_task() -> None:
    orchestrator = Orchestrator(max_concurrency=2)
    agent = EchoAgent()
    orchestrator.register_agent(agent)

    task = TaskInput(task_type="test", target="hello")
    results = await orchestrator.run_all([(agent, task)])

    assert len(results) == 1
    assert results[0].status == TaskStatus.COMPLETED
    assert results[0].result == {"echoed": "hello"}


async def test_orchestrator_parallel_tasks() -> None:
    orchestrator = Orchestrator(max_concurrency=4)
    agent = EchoAgent()
    orchestrator.register_agent(agent)

    tasks = [(agent, TaskInput(task_type="test", target=f"item-{i}")) for i in range(5)]
    results = await orchestrator.run_all(cast("list[tuple[BaseAgent, TaskInput]]", tasks))

    assert len(results) == 5
    assert all(r.status == TaskStatus.COMPLETED for r in results)


async def test_orchestrator_handles_failure() -> None:
    orchestrator = Orchestrator(max_concurrency=2)
    agent = FailAgent()
    orchestrator.register_agent(agent)

    task = TaskInput(task_type="test", target="will-fail")
    results = await orchestrator.run_all([(agent, task)])

    assert len(results) == 1
    assert results[0].status == TaskStatus.FAILED
    assert "intentional failure" in results[0].errors[0]


def test_orchestrator_register_and_get() -> None:
    orchestrator = Orchestrator()
    agent = EchoAgent()
    orchestrator.register_agent(agent)
    assert orchestrator.get_agent("echo") is agent
    assert orchestrator.get_agent("nonexistent") is None
