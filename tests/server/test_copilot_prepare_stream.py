import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from ag_ui.core import EventType, RunAgentInput
from langchain_core.messages import AIMessage, HumanMessage

from dingent.server.copilot.agents import DingLangGraphAGUIAgent


def build_run_input(*, forwarded_props=None, messages=None) -> RunAgentInput:
    return RunAgentInput(
        threadId=str(uuid.uuid4()),
        runId="run_1",
        state={},
        messages=messages or [{"id": "user_1", "role": "user", "content": "hello"}],
        tools=[],
        context=[],
        forwardedProps=forwarded_props or {},
    )


@pytest.mark.asyncio
async def test_prepare_stream_delegates_to_regenerate_when_history_is_longer():
    graph = MagicMock()
    graph.astream_events = MagicMock()
    agent = DingLangGraphAGUIAgent(name="test", graph=graph)
    agent.active_run = {"id": "run_1", "mode": "start"}
    agent.get_schema_keys = MagicMock(return_value={"input": [], "output": [], "config": [], "context": []})
    agent.prepare_regenerate_stream = AsyncMock(return_value={"stream": "regen_stream", "state": "regen_state", "config": "regen_config"})

    agent_state = SimpleNamespace(
        values={
            "messages": [
                HumanMessage(id="existing_user", content="old request"),
                AIMessage(id="existing_ai", content="old answer"),
            ]
        },
        tasks=[],
    )
    input_data = build_run_input(messages=[{"id": "new_user", "role": "user", "content": "new request"}])
    config = {"configurable": {}}

    result = await agent.prepare_stream(input=input_data, agent_state=agent_state, config=config)

    assert result == {"stream": "regen_stream", "state": "regen_state", "config": "regen_config"}
    agent.prepare_regenerate_stream.assert_awaited_once()
    assert agent.prepare_regenerate_stream.await_args.kwargs["message_checkpoint"].id == "new_user"


@pytest.mark.asyncio
async def test_prepare_stream_returns_interrupt_events_without_starting_stream():
    graph = MagicMock()
    graph.astream_events = MagicMock()
    agent = DingLangGraphAGUIAgent(name="test", graph=graph)
    agent.active_run = {"id": "run_1", "mode": "start"}
    agent.get_schema_keys = MagicMock(return_value={"input": [], "output": [], "config": [], "context": []})

    interrupt = SimpleNamespace(value={"question": "Need confirmation"})
    agent_state = SimpleNamespace(values={"messages": []}, tasks=[SimpleNamespace(interrupts=[interrupt])])
    input_data = build_run_input()
    config = {"configurable": {}}

    result = await agent.prepare_stream(input=input_data, agent_state=agent_state, config=config)

    assert result["stream"] is None
    assert result["state"] is None
    assert result["config"] is None
    assert [event.type for event in result["events_to_dispatch"]] == [EventType.RUN_STARTED, EventType.CUSTOM, EventType.RUN_FINISHED]
    graph.astream_events.assert_not_called()
