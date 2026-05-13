import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlmodel import Session, select

from dingent.core.db.models import Assistant, Conversation, Workflow, WorkflowEdge, WorkflowNode, Workspace
from dingent.core.workflows.graph_factory import GraphFactory
from dingent.server.api.routers.frontend import threads as chat_threads
from dingent.server.services.copilotkit_service import CopilotKitSdk


class FakeMessagesListChatModelWithTools(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _create_workspace(*, session: Session, slug: str, allow_guest_access: bool) -> Workspace:
    ws = Workspace(name="Test Workspace", slug=slug, description="", allow_guest_access=allow_guest_access)
    session.add(ws)
    session.commit()
    session.refresh(ws)
    return ws


def _setup_workflow(session: Session, workspace_id: uuid.UUID, workflow_name: str) -> tuple[str, str]:
    """Create a 2-assistant workflow (DataGetter → Analyst) with no plugins. Returns (agent_a_name, agent_b_name)."""
    agent_a_name = "DataGetter"
    agent_b_name = "Analyst"

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
    session.add(assist_a)
    session.add(assist_b)
    session.commit()
    session.refresh(assist_a)
    session.refresh(assist_b)

    wf = Workflow(name=workflow_name, description=None, workspace_id=workspace_id)
    session.add(wf)
    session.commit()
    session.refresh(wf)

    node_a = WorkflowNode(workflow_id=wf.id, assistant_id=assist_a.id, is_start_node=True, type="assistant", position={})
    node_b = WorkflowNode(workflow_id=wf.id, assistant_id=assist_b.id, is_start_node=False, type="assistant", position={})
    session.add(node_a)
    session.add(node_b)
    session.commit()
    session.refresh(node_a)
    session.refresh(node_b)

    edge = WorkflowEdge(workflow_id=wf.id, source_node_id=node_a.id, target_node_id=node_b.id)
    session.add(edge)
    session.commit()

    return agent_a_name, agent_b_name


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in body.strip().split("\n\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.mark.asyncio
async def test_e2e_workflow_handoff_via_api(client: TestClient, session, app, monkeypatch):
    """
    Full E2E: TestClient → FastAPI → DB → GraphFactory → create_assistant_graphs
    → create_swarm → astream_events, with handoff between two assistants.

    Only LLM responses are mocked; everything else (API, DB, plugin manager,
    assistant factory, graph factory, swarm creation, event streaming) is real.
    """
    workflow_name = "e2e-test"
    ws = _create_workspace(session=session, slug="e2e-test", allow_guest_access=True)
    agent_a_name, agent_b_name = _setup_workflow(session, ws.id, workflow_name)

    # --- Mock LLM ---
    data_getter_turn = AIMessage(
        content="",
        tool_calls=[{"name": f"transfer_to_{agent_b_name}", "args": {}, "id": "call_handoff"}],
    )
    analyst_turn = AIMessage(content="Analysis complete. The data shows interesting patterns.")
    fake_llm = FakeMessagesListChatModelWithTools(responses=[data_getter_turn, analyst_turn])

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

    # Verify step-started events cover the workflow: handoff tools step (DataGetter) + Analyst step
    step_started = [e for e in events if e.get("type") == "STEP_STARTED"]
    step_names = {s.get("stepName") for s in step_started if "stepName" in s}
    assert "tools" in step_names, f"Missing tools step in {step_names}"
    assert agent_b_name in step_names, f"Missing {agent_b_name} step in {step_names}"

    # Verify a tool call result event exists for the handoff tool
    tool_call_events = [e for e in events if e.get("type") == "TOOL_CALL_RESULT"]
    assert len(tool_call_events) >= 1, f"No TOOL_CALL_RESULT events: {event_types}"
    handoff_event = next((e for e in tool_call_events if agent_b_name in str(e.get("content", ""))), None)
    assert handoff_event is not None, f"No handoff TOOL_CALL_RESULT mentioning {agent_b_name}"

    # Verify the final snapshot includes messages from Analyst
    snapshot_events = [e for e in events if e.get("type") == "MESSAGES_SNAPSHOT"]
    assert len(snapshot_events) >= 1, f"No MESSAGES_SNAPSHOT events: {event_types}"

    final_snapshot = snapshot_events[-1]
    snapshot_messages = [m.get("content", "") for m in final_snapshot.get("messages", [])]
    flattened_contents = " ".join(str(c) for c in snapshot_messages)
    assert agent_b_name.lower() in flattened_contents.lower(), f"Snapshot doesn't contain Analyst contribution: {flattened_contents[:300]}"

    # Verify conversation was created and title auto-set
    conv = session.exec(select(Conversation).where(Conversation.id == uuid.UUID(thread_id))).first()
    assert conv is not None, "No conversation record created"
    assert conv.title is not None and conv.title != "", "Conversation title was not set"
    assert conv.workspace_id == ws.id
