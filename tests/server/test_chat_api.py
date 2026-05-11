import uuid

from ag_ui.core import EventType, MessagesSnapshotEvent, RunFinishedEvent
from ag_ui.core.events import RunStartedEvent
from ag_ui.encoder import EventEncoder
from ag_ui_langgraph.utils import AGUIAssistantMessage
from fastapi.testclient import TestClient
from sqlmodel import select

from dingent.core.db.models import Conversation, Workspace


def _create_workspace(*, session, slug: str, allow_guest_access: bool) -> Workspace:
    ws = Workspace(name="Test Workspace", slug=slug, description="", allow_guest_access=allow_guest_access)
    session.add(ws)
    session.commit()
    session.refresh(ws)
    return ws


def _create_conversation(*, session, workspace_id, title: str = "New Chat", user_id=None, visitor_id: str | None = None, conversation_id=None) -> Conversation:
    conv = Conversation(id=conversation_id, workspace_id=workspace_id, title=title, user_id=user_id, visitor_id=visitor_id)
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return conv


def test_list_threads_guest_without_visitor_id_returns_empty(client: TestClient, session):
    _create_workspace(session=session, slug="ws-guest-off", allow_guest_access=True)

    resp = client.get("/api/v1/ws-guest-off/chat/threads")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_threads_guest_with_invalid_visitor_id_returns_empty(client: TestClient, session):
    _create_workspace(session=session, slug="ws-guest-off", allow_guest_access=True)

    resp = client.get("/api/v1/ws-guest-off/chat/threads", headers={"X-Visitor-Id": "not-a-uuid"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_threads_guest_requires_workspace_allow_guest(client: TestClient, session):
    _create_workspace(session=session, slug="ws-guest-on", allow_guest_access=False)

    resp = client.get("/api/v1/ws-guest-on/chat/threads", headers={"X-Visitor-Id": str(uuid.uuid4())})
    assert resp.status_code == 403


def test_list_threads_guest_filters_by_visitor_and_workspace(client: TestClient, session):
    ws_a = _create_workspace(session=session, slug="ws-a", allow_guest_access=True)
    ws_b = _create_workspace(session=session, slug="ws-b", allow_guest_access=True)
    visitor_a = str(uuid.uuid4())
    visitor_b = str(uuid.uuid4())

    conv_a1 = _create_conversation(session=session, workspace_id=ws_a.id, title="A1", visitor_id=visitor_a)
    _create_conversation(session=session, workspace_id=ws_a.id, title="A2", visitor_id=visitor_b)
    _create_conversation(session=session, workspace_id=ws_b.id, title="B1", visitor_id=visitor_a)
    _create_conversation(session=session, workspace_id=ws_a.id, title="UserConv", user_id=uuid.uuid4(), visitor_id=visitor_a)

    resp = client.get(f"/api/v1/{ws_a.slug}/chat/threads", headers={"X-Visitor-Id": visitor_a})
    assert resp.status_code == 200
    data = resp.json()
    assert {t["id"] for t in data} == {str(conv_a1.id)}
    assert data[0]["title"] == "A1"


def test_delete_all_threads_guest_deletes_only_current_visitor(client: TestClient, session):
    ws = _create_workspace(session=session, slug="ws-delete", allow_guest_access=True)
    visitor_a = str(uuid.uuid4())
    visitor_b = str(uuid.uuid4())

    _create_conversation(session=session, workspace_id=ws.id, title="A1", visitor_id=visitor_a)
    _create_conversation(session=session, workspace_id=ws.id, title="A2", visitor_id=visitor_a)
    _create_conversation(session=session, workspace_id=ws.id, title="B1", visitor_id=visitor_b)

    resp = client.delete(f"/api/v1/{ws.slug}/chat/threads", headers={"X-Visitor-Id": visitor_a})
    assert resp.status_code == 200
    assert "Deleted all threads" in resp.json()["detail"]

    remaining = client.get(f"/api/v1/{ws.slug}/chat/threads", headers={"X-Visitor-Id": visitor_b}).json()
    assert {t["title"] for t in remaining} == {"B1"}


def test_delete_thread_guest_success_and_not_found(client: TestClient, session):
    ws = _create_workspace(session=session, slug="ws-delete-one", allow_guest_access=True)
    visitor_id = str(uuid.uuid4())
    conv = _create_conversation(session=session, workspace_id=ws.id, title="A1", visitor_id=visitor_id)

    resp = client.delete(f"/api/v1/{ws.slug}/chat/threads/{conv.id}", headers={"X-Visitor-Id": visitor_id})
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Thread deleted successfully"

    resp2 = client.delete(f"/api/v1/{ws.slug}/chat/threads/{conv.id}", headers={"X-Visitor-Id": visitor_id})
    assert resp2.status_code == 404


def test_run_guest_accepts_x_visitor_id_header(client: TestClient, session, monkeypatch):
    ws = _create_workspace(session=session, slug="ws-run", allow_guest_access=True)

    class _DummyAgent:
        async def run(self, _input):
            if False:  # pragma: no cover
                yield ""

    class _DummySDK:
        async def resolve_agent(self, _spec, _llm):
            return _DummyAgent()

    # Avoid external model resolution
    from dingent.core.llms import service as llm_service

    monkeypatch.setattr(llm_service, "get_llm_for_context", lambda **_kwargs: object())

    # Override sdk dependency used by the chat router
    from dingent.server.api.routers.frontend import threads as chat_threads

    client.app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda: _DummySDK()

    thread_id = str(uuid.uuid4())
    payload = {
        "threadId": thread_id,
        "runId": "run-1",
        "parentRunId": None,
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "Hello"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    resp = client.post(
        f"/api/v1/{ws.slug}/chat/agent/default/run",
        json=payload,
        headers={"Accept": "text/event-stream", "X-Visitor-Id": str(uuid.uuid4())},
    )
    assert resp.status_code == 200


def test_run_guest_requires_visitor_header_named_x_visitor_id(client: TestClient, session, monkeypatch):
    ws = _create_workspace(session=session, slug="ws-run-2", allow_guest_access=True)

    class _DummyAgent:
        async def run(self, _input):
            if False:  # pragma: no cover
                yield ""

    class _DummySDK:
        async def resolve_agent(self, _spec, _llm):
            return _DummyAgent()

    from dingent.core.llms import service as llm_service

    monkeypatch.setattr(llm_service, "get_llm_for_context", lambda **_kwargs: object())

    from dingent.server.api.routers.frontend import threads as chat_threads

    client.app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda: _DummySDK()

    thread_id = str(uuid.uuid4())
    payload = {
        "threadId": thread_id,
        "runId": "run-1",
        "parentRunId": None,
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "Hello"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    resp = client.post(
        f"/api/v1/{ws.slug}/chat/agent/default/run",
        json=payload,
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Authentication or X-Visitor-ID required"


def test_run_streams_agent_events_and_updates_conversation_title(client: TestClient, session, monkeypatch):
    ws = _create_workspace(session=session, slug="ws-stream-run", allow_guest_access=True)
    thread_id = str(uuid.uuid4())
    visitor_id = str(uuid.uuid4())

    events = [
        RunStartedEvent(type=EventType.RUN_STARTED, thread_id=thread_id, run_id="run-1"),
        RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id="run-1"),
    ]

    class _DummyAgent:
        async def run(self, _input):
            for event in events:
                yield event

    class _DummySDK:
        async def resolve_agent(self, _spec, _llm):
            return _DummyAgent()

    from dingent.core.llms import service as llm_service
    from dingent.server.api.routers.frontend import threads as chat_threads

    monkeypatch.setattr(llm_service, "get_llm_for_context", lambda **_kwargs: object())
    client.app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda: _DummySDK()

    payload = {
        "threadId": thread_id,
        "runId": "run-1",
        "parentRunId": None,
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "Streaming title"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    response = client.post(
        f"/api/v1/{ws.slug}/chat/agent/default/run",
        json=payload,
        headers={"Accept": "text/event-stream", "X-Visitor-ID": visitor_id},
    )

    assert response.status_code == 200
    encoder = EventEncoder(accept="text/event-stream")
    assert response.text == "".join(encoder.encode(event) for event in events)

    conversation = session.exec(select(Conversation).where(Conversation.id == uuid.UUID(thread_id))).one()
    assert conversation.title == "Streaming title"
    assert conversation.visitor_id == visitor_id


def test_connect_streams_thread_snapshot_events(client: TestClient, session, monkeypatch):
    ws = _create_workspace(session=session, slug="ws-connect", allow_guest_access=True)
    thread_id = str(uuid.uuid4())
    visitor_id = str(uuid.uuid4())
    _create_conversation(session=session, workspace_id=ws.id, title="Existing Chat", visitor_id=visitor_id, conversation_id=uuid.UUID(thread_id))

    messages_event = MessagesSnapshotEvent(
        type=EventType.MESSAGES_SNAPSHOT,
        messages=[AGUIAssistantMessage(id="a1", role="assistant", content="connected")],
    )

    class _DummyAgent:
        async def get_thread_messages(self, _thread_id, _run_id):
            yield messages_event

    class _DummySDK:
        async def resolve_agent(self, _spec, _llm):
            return _DummyAgent()

    from dingent.core.llms import service as llm_service
    from dingent.server.api.routers.frontend import threads as chat_threads

    monkeypatch.setattr(llm_service, "get_llm_for_context", lambda **_kwargs: object())
    client.app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda: _DummySDK()

    payload = {
        "threadId": thread_id,
        "runId": "run-connect-1",
        "parentRunId": None,
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "Hello"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    response = client.post(
        f"/api/v1/{ws.slug}/chat/agent/default/connect",
        json=payload,
        headers={"Accept": "text/event-stream", "X-Visitor-ID": visitor_id},
    )

    assert response.status_code == 200
    encoder = EventEncoder(accept="text/event-stream")
    assert response.text == encoder.encode(messages_event)


def test_run_returns_400_for_invalid_thread_id(client: TestClient, session, monkeypatch):
    ws = _create_workspace(session=session, slug="ws-invalid-thread", allow_guest_access=True)

    class _DummySDK:
        async def resolve_agent(self, _spec, _llm):
            raise AssertionError("resolve_agent should not be called")

    from dingent.core.llms import service as llm_service
    from dingent.server.api.routers.frontend import threads as chat_threads

    monkeypatch.setattr(llm_service, "get_llm_for_context", lambda **_kwargs: object())
    client.app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda: _DummySDK()

    payload = {
        "threadId": "not-a-uuid",
        "runId": "run-1",
        "parentRunId": None,
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "Hello"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    response = client.post(
        f"/api/v1/{ws.slug}/chat/agent/default/run",
        json=payload,
        headers={"Accept": "text/event-stream", "X-Visitor-ID": str(uuid.uuid4())},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid thread_id format"


def test_run_returns_404_for_unknown_workflow(client: TestClient, session, monkeypatch):
    ws = _create_workspace(session=session, slug="ws-missing-workflow", allow_guest_access=True)

    class _DummySDK:
        async def resolve_agent(self, _spec, _llm):
            raise AssertionError("resolve_agent should not be called")

    from dingent.core.llms import service as llm_service
    from dingent.server.api.routers.frontend import threads as chat_threads

    monkeypatch.setattr(llm_service, "get_llm_for_context", lambda **_kwargs: object())
    client.app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda: _DummySDK()

    payload = {
        "threadId": str(uuid.uuid4()),
        "runId": "run-1",
        "parentRunId": None,
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "Hello"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    response = client.post(
        f"/api/v1/{ws.slug}/chat/agent/missing-workflow/run",
        json=payload,
        headers={"Accept": "text/event-stream", "X-Visitor-ID": str(uuid.uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Workflow 'missing-workflow' not found"


def test_run_returns_403_for_guest_accessing_another_visitors_thread(client: TestClient, session, monkeypatch):
    ws = _create_workspace(session=session, slug="ws-visitor-forbidden", allow_guest_access=True)
    owner_visitor_id = str(uuid.uuid4())
    other_visitor_id = str(uuid.uuid4())
    conversation = _create_conversation(session=session, workspace_id=ws.id, visitor_id=owner_visitor_id)

    class _DummySDK:
        async def resolve_agent(self, _spec, _llm):
            raise AssertionError("resolve_agent should not be called")

    from dingent.core.llms import service as llm_service
    from dingent.server.api.routers.frontend import threads as chat_threads

    monkeypatch.setattr(llm_service, "get_llm_for_context", lambda **_kwargs: object())
    client.app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda: _DummySDK()

    payload = {
        "threadId": str(conversation.id),
        "runId": "run-1",
        "parentRunId": None,
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "Hello"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    response = client.post(
        f"/api/v1/{ws.slug}/chat/agent/default/run",
        json=payload,
        headers={"Accept": "text/event-stream", "X-Visitor-ID": other_visitor_id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have permission to access this conversation."


def test_run_returns_403_for_thread_from_different_workspace(client: TestClient, session, monkeypatch):
    ws_a = _create_workspace(session=session, slug="ws-a-forbidden", allow_guest_access=True)
    ws_b = _create_workspace(session=session, slug="ws-b-forbidden", allow_guest_access=True)
    visitor_id = str(uuid.uuid4())
    conversation = _create_conversation(session=session, workspace_id=ws_b.id, visitor_id=visitor_id)

    class _DummySDK:
        async def resolve_agent(self, _spec, _llm):
            raise AssertionError("resolve_agent should not be called")

    from dingent.core.llms import service as llm_service
    from dingent.server.api.routers.frontend import threads as chat_threads

    monkeypatch.setattr(llm_service, "get_llm_for_context", lambda **_kwargs: object())
    client.app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda: _DummySDK()

    payload = {
        "threadId": str(conversation.id),
        "runId": "run-1",
        "parentRunId": None,
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "Hello"}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }

    response = client.post(
        f"/api/v1/{ws_a.slug}/chat/agent/default/run",
        json=payload,
        headers={"Accept": "text/event-stream", "X-Visitor-ID": visitor_id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "This conversation belongs to a different workspace."
