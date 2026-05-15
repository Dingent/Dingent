import uuid

import pytest
from ag_ui.core import EventType, RunAgentInput
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph_swarm import create_swarm

from dingent.engine.agents.simple_agent import build_simple_react_agent
from dingent.engine.agents.state import MainState
from dingent.engine.agents.tools import create_handoff_tool
from dingent.server.copilot.agents import DingLangGraphAGUIAgent, ding_langchain_messages_to_agui


class FakeMessagesListChatModelWithTools(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def build_ding_agui_agent(*, target_response: str = "I am Agent B, I have received the handoff.") -> DingLangGraphAGUIAgent:
    handoff_tool = create_handoff_tool("agent_b", "Agent B can help with math", lambda *args, **kwargs: None)
    llm_a = FakeMessagesListChatModelWithTools(responses=[AIMessage(content="", tool_calls=[{"name": "transfer_to_agent_b", "args": {}, "id": "call_123"}])])
    agent_a = build_simple_react_agent("agent_a", llm_a, tools=[handoff_tool], system_prompt="You are Agent A")

    @tool
    def dummy_tool() -> str:
        """Dummy tool."""
        return "ok"

    llm_b = FakeMessagesListChatModelWithTools(responses=[AIMessage(content=target_response)])
    agent_b = build_simple_react_agent("agent_b", llm_b, tools=[dummy_tool], system_prompt="You are Agent B")

    graph = create_swarm(
        agents=[agent_a, agent_b],
        state_schema=MainState,
        default_active_agent="agent_a",
        context_schema=dict,
    ).compile(checkpointer=InMemorySaver())
    return DingLangGraphAGUIAgent(name="test", graph=graph)


def build_run_input() -> RunAgentInput:
    return RunAgentInput(
        threadId=str(uuid.uuid4()),
        runId="run_1",
        state={},
        messages=[{"id": "user_1", "role": "user", "content": "Transfer to B"}],
        tools=[],
        context=[],
        forwardedProps={},
    )


@pytest.mark.asyncio
async def test_ding_langgraph_agui_agent_run_executes_tool_before_handoff_and_emits_final_reply():
    @tool
    def lookup_context(question: str) -> str:
        """Look up context for the user request."""
        return f"lookup result for: {question}"

    handoff_tool = create_handoff_tool("agent_b", "Agent B can finish the answer", lambda *args, **kwargs: None)
    llm_a = FakeMessagesListChatModelWithTools(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "lookup_context", "args": {"question": "Transfer to B"}, "id": "call_lookup"}]),
            AIMessage(content="", tool_calls=[{"name": "transfer_to_agent_b", "args": {}, "id": "call_handoff"}]),
        ]
    )
    agent_a = build_simple_react_agent("agent_a", llm_a, tools=[lookup_context, handoff_tool], system_prompt="You are Agent A")

    llm_b = FakeMessagesListChatModelWithTools(responses=[AIMessage(content="Agent B final answer using the tool result.")])
    agent_b = build_simple_react_agent("agent_b", llm_b, tools=[], system_prompt="You are Agent B")

    graph = create_swarm(
        agents=[agent_a, agent_b],
        state_schema=MainState,
        default_active_agent="agent_a",
        context_schema=dict,
    ).compile(checkpointer=InMemorySaver())
    agent = DingLangGraphAGUIAgent(name="test", graph=graph)

    events = []
    async for event in agent.run(build_run_input()):
        events.append(event)

    tool_results = [event for event in events if event.type == EventType.TOOL_CALL_RESULT]
    assert len(tool_results) == 2
    assert [event.content for event in tool_results] == ["lookup result for: Transfer to B", "Transferred to agent_b"]
    assert tool_results[0].tool_call_id == "call_lookup"
    assert tool_results[1].tool_call_id == "call_handoff"

    handoff_tool_events = [event for event in events if getattr(event, "tool_call_id", None) == "call_handoff"]
    assert [event.type for event in handoff_tool_events] == [EventType.TOOL_CALL_START, EventType.TOOL_CALL_ARGS, EventType.TOOL_CALL_END, EventType.TOOL_CALL_RESULT]

    started_steps = [event.step_name for event in events if event.type == EventType.STEP_STARTED]
    assert started_steps.count("tools") >= 2
    assert "agent_b" in started_steps
    assert "model" in started_steps

    snapshots = [event for event in events if event.type == EventType.MESSAGES_SNAPSHOT]
    snapshot = snapshots[-1]  # last snapshot has the full conversation
    assert [message.role for message in snapshot.messages] == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert snapshot.messages[1].tool_calls[0].id == "call_lookup"
    assert snapshot.messages[2].content == "lookup result for: Transfer to B"
    assert snapshot.messages[3].tool_calls[0].id == "call_handoff"
    assert snapshot.messages[4].content == "Transferred to agent_b"
    assert snapshot.messages[5].content.endswith("Agent B final answer using the tool result.")


@pytest.mark.asyncio
async def test_ding_langgraph_agui_agent_run_emits_handoff_and_final_snapshot():
    agent = build_ding_agui_agent()

    events = []
    async for event in agent.run(build_run_input()):
        events.append(event)

    tool_results = [event for event in events if event.type == EventType.TOOL_CALL_RESULT]
    assert len(tool_results) == 1
    assert tool_results[0].content == "Transferred to agent_b"

    started_steps = [event.step_name for event in events if event.type == EventType.STEP_STARTED]
    assert "tools" in started_steps
    assert "agent_b" in started_steps
    assert "model" in started_steps

    snapshots = [event for event in events if event.type == EventType.MESSAGES_SNAPSHOT]
    snapshot_messages = snapshots[-1].messages  # last snapshot has the full conversation
    assert [message.role for message in snapshot_messages] == ["user", "assistant", "tool", "assistant"]
    assert snapshot_messages[1].tool_calls[0].id == "call_123"
    assert snapshot_messages[2].content == "Transferred to agent_b"
    assert snapshot_messages[3].content.endswith("I am Agent B, I have received the handoff.")


@pytest.mark.asyncio
async def test_ding_langgraph_agui_agent_run_keeps_target_reply_in_snapshot_when_no_text_stream_is_emitted():
    agent = build_ding_agui_agent(target_response="Agent B final response")

    events = []
    async for event in agent.run(build_run_input()):
        events.append(event)

    text_events = [event for event in events if event.type in {EventType.TEXT_MESSAGE_START, EventType.TEXT_MESSAGE_CONTENT, EventType.TEXT_MESSAGE_END}]
    assert text_events == []

    snapshots = [event for event in events if event.type == EventType.MESSAGES_SNAPSHOT]
    assert snapshots[-1].messages[-1].content.endswith("Agent B final response")


def test_ding_langchain_messages_to_agui_preserves_handoff_messages():
    messages = [
        HumanMessage(id="user_1", content="Transfer to B"),
        ToolMessage(id="tool_1", content="Transferred to agent_b", tool_call_id="call_123", name="transfer_to_agent_b"),
        AIMessage(id="assistant_1", content="Agent B final response"),
    ]

    agui_messages = ding_langchain_messages_to_agui(messages)

    assert [message.role for message in agui_messages] == ["user", "tool", "assistant"]
    assert agui_messages[1].tool_call_id == "call_123"
    assert agui_messages[1].content == "Transferred to agent_b"
    assert agui_messages[2].content == "<thinking>\n</thinking>\nAgent B final response"
