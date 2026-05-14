import json
import os
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field
from sqlmodel import Session, select

from dingent.core.db.models import Assistant, Conversation, Workflow, WorkflowEdge, WorkflowNode, Workspace
from dingent.core.workflows.graph_factory import GraphFactory
from dingent.server.api.routers.frontend import threads as chat_threads
from dingent.server.services.copilotkit_service import CopilotKitSdk


class FakeMessagesListChatModelWithTools(FakeMessagesListChatModel):
    received_messages: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tool_names: list[list[str]] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound_tool_names.append([getattr(tool, "name", "") for tool in tools])
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs):
        self.received_messages.append(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _create_workspace(*, session: Session, slug: str, allow_guest_access: bool) -> Workspace:
    ws = Workspace(name="Test Workspace", slug=slug, description="", allow_guest_access=allow_guest_access)
    session.add(ws)
    session.commit()
    session.refresh(ws)
    return ws


def _setup_workflow(session: Session, workspace_id: uuid.UUID, workflow_name: str) -> tuple[str, str, str]:
    """Create a 3-assistant workflow (DataGetter → Analyst → Reviewer) with no plugins."""
    agent_a_name = "DataGetter"
    agent_b_name = "Analyst"
    agent_c_name = "Reviewer"

    assist_a = Assistant(
        name=agent_a_name,
        description="Data getting assistant",
        instructions="You get data and hand off to the analyst.",
        enabled=True,
        workspace_id=workspace_id,
    )
    assist_b = Assistant(
        name=agent_b_name,
        description="Analysis assistant",
        instructions="You analyze data and respond.",
        enabled=True,
        workspace_id=workspace_id,
    )
    assist_c = Assistant(
        name=agent_c_name,
        description="Review assistant",
        instructions="You review the analysis and provide the final answer.",
        enabled=True,
        workspace_id=workspace_id,
    )
    session.add(assist_a)
    session.add(assist_b)
    session.add(assist_c)
    session.commit()
    session.refresh(assist_a)
    session.refresh(assist_b)
    session.refresh(assist_c)

    wf = Workflow(name=workflow_name, description=None, workspace_id=workspace_id)
    session.add(wf)
    session.commit()
    session.refresh(wf)

    node_a = WorkflowNode(workflow_id=wf.id, assistant_id=assist_a.id, is_start_node=True, type="assistant", position={})
    node_b = WorkflowNode(workflow_id=wf.id, assistant_id=assist_b.id, is_start_node=False, type="assistant", position={})
    node_c = WorkflowNode(workflow_id=wf.id, assistant_id=assist_c.id, is_start_node=False, type="assistant", position={})
    session.add(node_a)
    session.add(node_b)
    session.add(node_c)
    session.commit()
    session.refresh(node_a)
    session.refresh(node_b)
    session.refresh(node_c)

    edge_ab = WorkflowEdge(workflow_id=wf.id, source_node_id=node_a.id, target_node_id=node_b.id)
    edge_bc = WorkflowEdge(workflow_id=wf.id, source_node_id=node_b.id, target_node_id=node_c.id)
    session.add(edge_ab)
    session.add(edge_bc)
    session.commit()

    return agent_a_name, agent_b_name, agent_c_name


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in body.strip().split("\n\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _message_contents(messages: list[BaseMessage]) -> str:
    return "\n".join(str(message.content) for message in messages)


def _tool_call_names(message: AIMessage) -> list[str]:
    return [tool_call["name"] for tool_call in message.tool_calls]


def _message_debug_payload(message: BaseMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": message.type,
        "class": type(message).__name__,
        "content": message.content,
    }
    if isinstance(message, AIMessage):
        payload["tool_calls"] = message.tool_calls
    if isinstance(message, ToolMessage):
        payload["tool_call_id"] = message.tool_call_id
        payload["name"] = message.name
    return payload


def _print_e2e_debug_trace(*, events: list[dict[str, Any]], received_messages: list[list[BaseMessage]], bound_tool_names: list[list[str]]) -> None:
    if os.getenv("DINGENT_E2E_DEBUG") != "1":
        return

    interesting_events = [
        event for event in events if event.get("type") in {"RUN_STARTED", "STEP_STARTED", "TOOL_CALL_START", "TOOL_CALL_RESULT", "MESSAGES_SNAPSHOT", "RUN_FINISHED"}
    ]
    print("\n=== Dingent E2E API events ===")
    print(json.dumps(interesting_events, ensure_ascii=False, indent=2, default=str))

    print("\n=== Dingent E2E bound tools per LLM ===")
    print(json.dumps(bound_tool_names, ensure_ascii=False, indent=2, default=str))

    print("\n=== Dingent E2E LLM input messages ===")
    for idx, messages in enumerate(received_messages, start=1):
        print(f"--- LLM call #{idx} ---")
        print(json.dumps([_message_debug_payload(message) for message in messages], ensure_ascii=False, indent=2, default=str))


def _assert_single_human_request(messages: list[BaseMessage], content: str) -> None:
    human_messages = [message for message in messages if isinstance(message, HumanMessage)]
    assert len(human_messages) == 1
    assert human_messages[0].content == content


def _assert_system_prompt_contract(messages: list[BaseMessage], *, includes: str, excludes: list[str]) -> None:
    system_messages = [message for message in messages if isinstance(message, SystemMessage)]
    assert len(system_messages) == 1
    system_content = str(system_messages[0].content)
    assert includes in system_content
    for excluded in excludes:
        assert excluded not in system_content


def _assert_tool_binding_contract(bound_tool_names: list[list[str]], agent_b_name: str, agent_c_name: str) -> None:
    assert len(bound_tool_names) == 3

    data_getter_tools, analyst_tools, reviewer_tools = bound_tool_names
    assert f"transfer_to_{agent_b_name}" in data_getter_tools
    assert f"transfer_to_{agent_c_name}" not in data_getter_tools

    assert f"transfer_to_{agent_b_name}" not in analyst_tools
    assert f"transfer_to_{agent_c_name}" in analyst_tools

    assert f"transfer_to_{agent_b_name}" not in reviewer_tools
    assert f"transfer_to_{agent_c_name}" not in reviewer_tools


def _assert_handoff_input_contract(messages: list[BaseMessage], *, source_agent_name: str, target_agent_name: str, tool_call_id: str, include_prior_handoff: bool = False) -> None:
    transfer_tool_name = f"transfer_to_{target_agent_name}"
    transfer_ai_indexes = [idx for idx, message in enumerate(messages) if isinstance(message, AIMessage) and transfer_tool_name in _tool_call_names(message)]
    transfer_tool_indexes = [
        idx
        for idx, message in enumerate(messages)
        if isinstance(message, ToolMessage) and message.tool_call_id == tool_call_id and message.content == f"Transferred to {target_agent_name}"
    ]

    assert len(transfer_ai_indexes) == 1, f"Expected exactly one {source_agent_name} -> {target_agent_name} AI handoff call"
    assert len(transfer_tool_indexes) == 1, f"Expected exactly one {source_agent_name} -> {target_agent_name} tool result"
    assert transfer_ai_indexes[0] < transfer_tool_indexes[0]

    if not include_prior_handoff:
        prior_tool_messages = [message for message in messages if isinstance(message, ToolMessage) and message.tool_call_id != tool_call_id]
        assert prior_tool_messages == []


@pytest.mark.asyncio
async def test_e2e_workflow_handoff_via_api(client: TestClient, session, app, monkeypatch):
    """
    Full E2E: TestClient → FastAPI → DB → GraphFactory → create_assistant_graphs
    → create_swarm → astream_events, with handoff across a 3-assistant graph.

    Only LLM responses are mocked; everything else (API, DB, plugin manager,
    assistant factory, graph factory, swarm creation, event streaming) is real.
    The mock also records every LLM input so this test covers both API output
    and the messages/tools sent into the AI side.
    """
    workflow_name = "e2e-test"
    ws = _create_workspace(session=session, slug="e2e-test", allow_guest_access=True)
    agent_a_name, agent_b_name, agent_c_name = _setup_workflow(session, ws.id, workflow_name)

    # --- Mock LLM ---
    data_getter_turn = AIMessage(
        content="",
        tool_calls=[{"name": f"transfer_to_{agent_b_name}", "args": {}, "id": "call_handoff"}],
    )
    analyst_turn = AIMessage(
        content="",
        tool_calls=[{"name": f"transfer_to_{agent_c_name}", "args": {}, "id": "call_review"}],
    )
    reviewer_turn = AIMessage(content="Reviewer final answer: Analysis complete. The data shows interesting patterns.")
    fake_llm = FakeMessagesListChatModelWithTools(responses=[data_getter_turn, analyst_turn, reviewer_turn])

    from dingent.core.llms import service as llm_service

    monkeypatch.setattr(llm_service, "get_llm_for_context", lambda **_kwargs: fake_llm)

    # --- Replace CopilotKitSdk with InMemorySaver variant ---
    graph_factory = GraphFactory(app.state.assistant_factory)
    sdk = CopilotKitSdk(graph_factory=graph_factory, checkpointer=InMemorySaver())
    app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda: sdk

    # --- API request ---
    thread_id = str(uuid.uuid4())
    visitor_id = str(uuid.uuid4())
    payload = {
        "threadId": thread_id,
        "runId": "run-1",
        "parentRunId": None,
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "Get data and analyze it"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    response = client.post(
        f"/api/v1/{ws.slug}/chat/agent/{workflow_name}/run",
        json=payload,
        headers={"Accept": "text/event-stream", "X-Visitor-Id": visitor_id},
    )

    # --- Assertions ---
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:500]}"

    events = _parse_sse_events(response.text)

    event_types = [e.get("type") for e in events]
    assert "RUN_STARTED" in event_types, f"No RUN_STARTED event in {event_types}"
    assert "RUN_FINISHED" in event_types, f"No RUN_FINISHED event in {event_types}"

    # Verify step-started events cover the workflow: both handoff tool steps + downstream assistants
    step_started = [e for e in events if e.get("type") == "STEP_STARTED"]
    step_names = {s.get("stepName") for s in step_started if "stepName" in s}
    assert "tools" in step_names, f"Missing tools step in {step_names}"
    assert agent_b_name in step_names, f"Missing {agent_b_name} step in {step_names}"
    assert agent_c_name in step_names, f"Missing {agent_c_name} step in {step_names}"

    # Verify a tool call result event exists for the handoff tool
    tool_call_events = [e for e in events if e.get("type") == "TOOL_CALL_RESULT"]
    assert len(tool_call_events) >= 2, f"Expected both handoff TOOL_CALL_RESULT events: {event_types}"
    handoff_event = next((e for e in tool_call_events if agent_b_name in str(e.get("content", ""))), None)
    assert handoff_event is not None, f"No handoff TOOL_CALL_RESULT mentioning {agent_b_name}"
    review_handoff_event = next((e for e in tool_call_events if agent_c_name in str(e.get("content", ""))), None)
    assert review_handoff_event is not None, f"No handoff TOOL_CALL_RESULT mentioning {agent_c_name}"

    # Verify the final snapshot includes the terminal Reviewer answer.
    snapshot_events = [e for e in events if e.get("type") == "MESSAGES_SNAPSHOT"]
    assert len(snapshot_events) >= 1, f"No MESSAGES_SNAPSHOT events: {event_types}"

    final_snapshot = snapshot_events[-1]
    snapshot_messages = [m.get("content", "") for m in final_snapshot.get("messages", [])]
    flattened_contents = " ".join(str(c) for c in snapshot_messages)
    assert "Reviewer final answer" in flattened_contents, f"Snapshot doesn't contain Reviewer contribution: {flattened_contents[:300]}"

    _print_e2e_debug_trace(events=events, received_messages=fake_llm.received_messages, bound_tool_names=fake_llm.bound_tool_names)

    # Verify the AI-side inputs, not only the API-side stream.
    assert len(fake_llm.received_messages) == 3

    data_getter_messages, analyst_messages, reviewer_messages = fake_llm.received_messages
    _assert_tool_binding_contract(fake_llm.bound_tool_names, agent_b_name, agent_c_name)

    _assert_system_prompt_contract(
        data_getter_messages,
        includes="You get data and hand off to the analyst.",
        excludes=["You analyze data and respond.", "You review the analysis and provide the final answer."],
    )
    _assert_single_human_request(data_getter_messages, "Get data and analyze it")
    assert not any(isinstance(message, ToolMessage) for message in data_getter_messages)
    assert not any(isinstance(message, AIMessage) and message.tool_calls for message in data_getter_messages)

    _assert_system_prompt_contract(
        analyst_messages,
        includes="You analyze data and respond.",
        excludes=["You get data and hand off to the analyst.", "You review the analysis and provide the final answer."],
    )
    _assert_single_human_request(analyst_messages, "Get data and analyze it")
    _assert_handoff_input_contract(
        analyst_messages,
        source_agent_name=agent_a_name,
        target_agent_name=agent_b_name,
        tool_call_id="call_handoff",
    )
    assert not any(isinstance(message, AIMessage) and f"transfer_to_{agent_c_name}" in _tool_call_names(message) for message in analyst_messages)
    assert "Reviewer final answer" not in _message_contents(analyst_messages)

    _assert_system_prompt_contract(
        reviewer_messages,
        includes="You review the analysis and provide the final answer.",
        excludes=["You get data and hand off to the analyst.", "You analyze data and respond."],
    )
    _assert_single_human_request(reviewer_messages, "Get data and analyze it")
    _assert_handoff_input_contract(
        reviewer_messages,
        source_agent_name=agent_a_name,
        target_agent_name=agent_b_name,
        tool_call_id="call_handoff",
        include_prior_handoff=True,
    )
    _assert_handoff_input_contract(
        reviewer_messages,
        source_agent_name=agent_b_name,
        target_agent_name=agent_c_name,
        tool_call_id="call_review",
        include_prior_handoff=True,
    )
    assert "Reviewer final answer" not in _message_contents(reviewer_messages)

    # Verify conversation was created and title auto-set
    conv = session.exec(select(Conversation).where(Conversation.id == uuid.UUID(thread_id))).first()
    assert conv is not None, "No conversation record created"
    assert conv.title is not None and conv.title != "", "Conversation title was not set"
    assert conv.workspace_id == ws.id
