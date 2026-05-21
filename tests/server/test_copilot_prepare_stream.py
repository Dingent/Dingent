import uuid
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from ag_ui.core import EventType, RunAgentInput
from ag_ui_langgraph.agent import ToolCallResultEvent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

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
async def test_prepare_stream_filters_activity_messages_from_state():
    from dingent.engine.agents.messages import ActivityMessage

    graph = MagicMock()
    graph.astream_events = MagicMock()
    agent = DingLangGraphAGUIAgent(name="test", graph=graph)
    agent.active_run = {"id": "run_1", "mode": "start"}
    agent.get_schema_keys = MagicMock(return_value={"input": [], "output": [], "config": [], "context": []})

    activity_msg = ActivityMessage(content=[{"type": "a2ui-surface"}])

    agent_state = SimpleNamespace(
        values={
            "messages": [
                HumanMessage(id="user_1", content="hello"),
                activity_msg,
                AIMessage(id="ai_1", content="reply"),
            ]
        },
        tasks=[],
    )
    input_data = build_run_input(messages=[{"id": "user_1", "role": "user", "content": "hello"}])
    config = {"configurable": {}}

    await agent.prepare_stream(input=input_data, agent_state=agent_state, config=config)

    assert activity_msg not in agent_state.values["messages"]
    assert len(agent_state.values["messages"]) == 2


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


@pytest.mark.asyncio
async def test_handle_single_event_emits_activity_from_current_state():
    from dingent.engine.agents.messages import ActivityMessage

    graph = MagicMock()
    agent = DingLangGraphAGUIAgent(name="test", graph=graph)
    agent.active_run = {
        "id": "run_1",
        "mode": "start",
        "has_function_streaming": False,
        "model_made_tool_call": False,
        "state_reliable": True,
    }

    tool_message = ToolMessage(id="tool_1", content="tool result", tool_call_id="call_1", name="tool")
    activity_message = ActivityMessage(id="activity_1", content=[{"type": "markdown", "content": "### Live result"}])
    event = {
        "event": "on_tool_end",
        "name": "tool",
        "data": {
            "input": {},
            "output": tool_message,
        },
    }
    state = {"messages": [HumanMessage(id="user_1", content="hello"), tool_message, activity_message]}

    events = cast(list[Any], [event async for event in agent._handle_single_event(event, state)])

    assert any(isinstance(event, ToolCallResultEvent) for event in events)
    activity_events = [event for event in events if event.type == EventType.ACTIVITY_SNAPSHOT]
    assert len(activity_events) == 1
    assert activity_events[0].message_id == "activity_1"
    assert activity_events[0].content == {"type": "markdown", "content": "### Live result"}
