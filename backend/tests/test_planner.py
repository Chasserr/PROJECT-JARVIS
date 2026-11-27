from __future__ import annotations

from jarvis.agent.planner import Planner

from .conftest import FakeLLM


async def test_planner_recovers_from_incomplete_json(container) -> None:
    llm = container.llm
    assert isinstance(llm, FakeLLM)
    llm.responses = [
        '{"summary": "incomplete plan"}',
        '{"summary": "still incomplete"}',
        '{"summary": "no tool needed", "steps": []}',
    ]

    plan = await Planner(llm, container.registry, container.settings).plan(
        "Respond with a simple greeting"
    )

    assert plan.summary == "no tool needed"
    assert plan.steps == []
    assert len(llm.calls) == 3
