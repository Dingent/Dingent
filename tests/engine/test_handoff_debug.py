from typing import Any, cast

import pytest
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph_swarm import create_swarm

from dingent.engine.agents.simple_agent import build_simple_react_agent
from dingent.engine.agents.state import MainState
from dingent.engine.agents.tools import create_handoff_tool


class FakeMessagesListChatModelWithTools(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def build_handoff_swarm():
    handoff_tool = create_handoff_tool("agent_b", "Agent B can help with math", lambda *args, **kwargs: None)
    llm_a = FakeMessagesListChatModelWithTools(responses=[AIMessage(content="", tool_calls=[{"name": "transfer_to_agent_b", "args": {}, "id": "call_123"}])])
    agent_a = build_simple_react_agent("agent_a", llm_a, tools=[handoff_tool], system_prompt="You are Agent A")

    @tool
    def dummy_tool() -> str:
        """Dummy tool."""
        return "ok"

    llm_b = FakeMessagesListChatModelWithTools(responses=[AIMessage(content="I am Agent B, I have received the handoff.")])
    agent_b = build_simple_react_agent("agent_b", llm_b, tools=[dummy_tool], system_prompt="You are Agent B")

    return create_swarm(
        agents=[agent_a, agent_b],
        state_schema=MainState,
        default_active_agent="agent_a",
        context_schema=dict,
    ).compile()


@pytest.mark.asyncio
async def test_handoff_behavior_invokes_target_agent():
    compiled_swarm = build_handoff_swarm()

    result = await compiled_swarm.ainvoke({"messages": [HumanMessage(content="Transfer to B")]})

    assert [type(message).__name__ for message in result["messages"]] == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    assert result["messages"][1].tool_calls[0]["id"] == "call_123"
    assert result["messages"][2].content == "Transferred to agent_b"
    assert result["messages"][2].tool_call_id == "call_123"
    assert result["messages"][3].content == "I am Agent B, I have received the handoff."


@pytest.mark.asyncio
async def test_handoff_behavior_stream_events_reach_target_agent():
    compiled_swarm = build_handoff_swarm()

    events = []
    async for event in compiled_swarm.astream_events({"messages": [HumanMessage(content="Transfer to B")]}, version="v2"):
        events.append(event)

    tool_events = [event for event in events if event.get("event") == "on_tool_end"]
    assert any(event.get("name") == "transfer_to_agent_b" for event in tool_events)

    target_agent_events = [event for event in events if event.get("event") == "on_chain_end" and event.get("metadata", {}).get("langgraph_node") == "agent_b"]
    assert target_agent_events

    final_messages = target_agent_events[-1]["data"]["output"]["messages"]
    assert final_messages[-2].tool_call_id == "call_123"
    assert final_messages[-1].content == "I am Agent B, I have received the handoff."


@pytest.mark.asyncio
async def test_handoff_behavior_completes_sibling_tool_calls_before_transfer():
    handoff_tool = create_handoff_tool("agent_b", "Agent B can help with math", lambda *args, **kwargs: None)

    @tool
    def list_tables() -> str:
        """List tables."""
        return '["breed"]'

    @tool
    def dummy_tool() -> str:
        """Dummy tool."""
        return "ok"

    llm_a = FakeMessagesListChatModelWithTools(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "list_tables", "args": {}, "id": "call_list"},
                    {"name": "transfer_to_agent_b", "args": {}, "id": "call_transfer"},
                ],
            )
        ]
    )
    agent_a = build_simple_react_agent("agent_a", llm_a, tools=[handoff_tool, list_tables], system_prompt="You are Agent A")
    llm_b = FakeMessagesListChatModelWithTools(responses=[AIMessage(content="I am Agent B, I have received the handoff.")])
    agent_b = build_simple_react_agent("agent_b", llm_b, tools=[dummy_tool], system_prompt="You are Agent B")
    compiled_swarm = create_swarm(
        agents=[agent_a, agent_b],
        state_schema=MainState,
        default_active_agent="agent_a",
        context_schema=dict,
    ).compile()

    result = await compiled_swarm.ainvoke({"messages": [HumanMessage(content="List tables, then transfer to B")]})

    assert [type(message).__name__ for message in result["messages"]] == ["HumanMessage", "AIMessage", "ToolMessage", "ToolMessage", "AIMessage"]
    assert result["messages"][2].tool_call_id == "call_list"
    assert result["messages"][2].content == "Tool call 'list_tables' result is unavailable after handoff to agent_b."
    assert result["messages"][3].tool_call_id == "call_transfer"
    assert result["messages"][3].content == "Transferred to agent_b"
    assert result["messages"][4].content == "I am Agent B, I have received the handoff."


@pytest.mark.asyncio
async def test_handoff_behavior_does_not_duplicate_existing_sibling_tool_messages():
    handoff_tool = create_handoff_tool("agent_b", "Agent B can help with math", lambda *args, **kwargs: None)
    prior_message = AIMessage(
        content="",
        tool_calls=[
            {"name": "list_tables", "args": {}, "id": "call_list"},
            {"name": "transfer_to_agent_b", "args": {}, "id": "call_transfer"},
        ],
    )
    existing_tool_message = ToolMessage(content='["breed"]', tool_call_id="call_list", name="list_tables")

    result = await cast(Any, handoff_tool).coroutine(state={"messages": [prior_message, existing_tool_message]}, tool_call_id="call_transfer")

    messages = result.update["messages"]
    assert [message.tool_call_id for message in messages if isinstance(message, ToolMessage)] == ["call_list", "call_transfer"]
    assert messages[1] is existing_tool_message
    assert messages[2].content == "Transferred to agent_b"
