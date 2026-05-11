import uuid

import pytest
from fastapi.testclient import TestClient

from dingent.core.db.models import Conversation, Workspace


def _create_workspace(*, session, slug: str, allow_guest_access: bool) -> Workspace:
    ws = Workspace(name="Test Workspace", slug=slug, description="", allow_guest_access=allow_guest_access)
    session.add(ws)
    session.commit()
    session.refresh(ws)
    return ws


def _create_conversation(*, session, workspace_id, title: str = "New Chat", user_id=None, visitor_id: str | None = None) -> Conversation:
    conv = Conversation(workspace_id=workspace_id, title=title, user_id=user_id, visitor_id=visitor_id)
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


@pytest.mark.xfail(reason="Known bug/ambiguity: header alias mismatch between X-Visitor-Id and X-Visitor-ID")
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

    client.app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda _request: _DummySDK()

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

    client.app.dependency_overrides[chat_threads.get_copilot_sdk] = lambda _request: _DummySDK()

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
    # Missing header currently fails at request validation layer (422),
    # because this endpoint declares `visitor_id` as a required Header parameter.
    assert resp.status_code == 422
