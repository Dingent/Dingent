# Conversation Tests (Fake LLM) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add API-level integration tests for multi-turn conversation (A) and multi-agent handoff (C) using a routing Fake LLM with zero external MCP/plugin side effects.

**Architecture:** Use `fastapi.testclient.TestClient` against `/api/v1/{ws.slug}/chat/agent/{workflow_name}/run` and `/connect`. Patch `dingent.core.llms.service.get_llm_for_context` to return a routing Fake LLM. Insert a minimal no-plugin workflow into the test DB. Guard against external runtimes with fail-fast patches.

**Tech Stack:** Python 3.13, pytest, FastAPI TestClient, SQLModel, LangChain fake chat model, LangGraph/CopilotKit server endpoints.

---

## File Map (Create/Modify)

Create:

- `tests/server/test_conversation_multi_turn.py`
- `tests/server/test_conversation_handoff.py`
- `tests/server/conversation_fixtures.py` (shared helpers: minimal workflow DB insert, payload builders, SSE parsing, Fake LLM routing)
- `tests/server/__init__.py` (make `tests.server.*` imports unambiguous)

Modify (only if needed):

- `tests/server/conftest.py` (patch `paths.db_dir` per-test for isolated LangGraph checkpointer sqlite)

Reference:

- Spec: `docs/superpowers/specs/2026-03-19-conversation-tests-design.md`

---

### Task 1: Add Shared Test Helpers (Fixtures + Fake LLM)

**Files:**
- Create: `tests/server/__init__.py`
- Create: `tests/server/conversation_fixtures.py`
- Create: `tests/server/test_conversation_multi_turn.py`

- [ ] **Step 1: Write failing test for helpers contract**

Create a tiny “contract” test in `tests/server/test_conversation_multi_turn.py` that imports helper functions and asserts they return expected shapes (keeps failures localized when refactoring helpers):

```python
def test_conversation_helpers_contract():
    from tests.server.conversation_fixtures import build_run_payload, build_connect_payload

    payload = build_run_payload(thread_id="00000000-0000-0000-0000-000000000000", run_id="run-1", user_text="hi")
    assert payload["threadId"]
    assert payload["runId"] == "run-1"
    assert payload["messages"][0]["role"] == "user"

    connect_payload = build_connect_payload(thread_id=payload["threadId"], run_id="run-1")
    assert connect_payload["threadId"] == payload["threadId"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_conversation_multi_turn.py::test_conversation_helpers_contract -v`

Expected: FAIL with `ModuleNotFoundError` for `tests.server.conversation_fixtures`.

- [ ] **Step 3: Create `tests/server/__init__.py`**

Create: `tests/server/__init__.py` (empty)

- [ ] **Step 4: Create `tests/server/conversation_fixtures.py` with minimal payload + SSE helpers**

Create `tests/server/conversation_fixtures.py` implementing:

1) Payload builders:

```python
from __future__ import annotations

from typing import Any


def build_run_payload(*, thread_id: str, run_id: str, user_text: str) -> dict[str, Any]:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "parentRunId": None,
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": user_text}],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }


def build_connect_payload(*, thread_id: str, run_id: str) -> dict[str, Any]:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "parentRunId": None,
        "state": {},
        "messages": [],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
```

2) Minimal SSE text helpers:

```python
def sse_text(response) -> str:
    return response.content.decode("utf-8", errors="replace")
```

3) Routing Fake LLM:

- Implement `RoutingFakeChatModelWithTools` by extending `langchain_core.language_models.FakeMessagesListChatModel` and overriding `_generate` / `_agenerate` to return an `AIMessage` based on:
  - agent marker in system prompt (e.g., `SYSTEM_AGENT_A`, `SYSTEM_AGENT_B`)
  - or the *last* human message content (`hello`, `follow up`) (scenario A)

Keep the routing table explicit and tolerant:

- If no route matches, return `AIMessage(content="")`.

Minimal shape (copy into helper module):

```python
from __future__ import annotations

from typing import Any

from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class RoutingFakeChatModelWithTools(FakeMessagesListChatModel):
    def __init__(self, *, routes: list[tuple[str, AIMessage]], default: AIMessage | None = None):
        super().__init__(responses=[])
        self._routes = routes
        self._default = default or AIMessage(content="")

    def bind_tools(self, tools: Any, **kwargs: Any) -> "RoutingFakeChatModelWithTools":
        return self

    def _pick(self, messages: list[BaseMessage]) -> AIMessage:
        # We need two routing modes:
        # - Scenario A: route by *last* human message content.
        # - Scenario C: route by stable agent marker in system prompt (present anywhere in messages).
        last_human = next((m for m in reversed(messages) if getattr(m, "type", None) == "human"), None)
        last_human_text = str(getattr(last_human, "content", "")) if last_human is not None else ""
        all_text = "\n".join(str(getattr(m, "content", "")) for m in messages)

        for needle, msg in self._routes:
            if needle.startswith("SYSTEM_AGENT_"):
                if needle in all_text:
                    return msg
            else:
                if needle in last_human_text:
                    return msg

        return self._default

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any | None = None, **kwargs: Any) -> ChatResult:
        msg = self._pick(messages)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any | None = None, **kwargs: Any) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
```

4) DB insertion helpers:

- `create_workspace_row(*, session: Session, slug: str, allow_guest_access: bool) -> Workspace`
- `create_minimal_workflow(session, workspace_id, *, workflow_name="conv-test", agent_a_name="AgentA", agent_b_name="AgentB") -> tuple[Workflow, dict[str, Assistant]]`
- It should insert and return:
  - `Workspace` must set at least: `name`, `slug`, `allow_guest_access` (and can set `description=""` for consistency with existing tests)
  - `Assistant` rows with `instructions` containing `SYSTEM_AGENT_A` / `SYSTEM_AGENT_B`
  - `Workflow`, `WorkflowNode` (start node is AgentA), `WorkflowEdge` AgentA -> AgentB
  - No `AssistantPluginLink` rows

Return contract (make this exact in code):

- Return a 2-tuple `(workflow, assistants)` where:
  - `workflow` is the inserted `Workflow` row (refreshed)
  - `assistants` is a dict with exact keys: `{"agent_a": <Assistant>, "agent_b": <Assistant>}`

Important DB fields to set (minimum):

- `WorkflowNode.position` (required): e.g. `{"x": 0.0, "y": 0.0}`
- `WorkflowNode.measured`: e.g. `{}`

5) Isolation patches (helpers used inside tests):

- Provide a function that applies patches via `monkeypatch`:
   - patch `dingent.core.assistants.assistant.AssistantRuntime.create_runtime` to fail-fast if any plugins are present (no silent swallowing)
   - patch `dingent.core.assistants.assistant.AssistantRuntime.load_tools` to an `@asynccontextmanager` instance method yielding `[]` (signature must include `self`)

Make patches async-correct:

```python
async def _boom(*_args: Any, **_kwargs: Any):
    raise AssertionError("Plugin runtime should not be created in A/C tests")
```

Exact `create_runtime` fail-fast patch shape:

```python
from dingent.core.assistants.assistant import AssistantRuntime


_orig_create_runtime = AssistantRuntime.create_runtime


async def _create_runtime_failfast(cls, plugin_manager, assistant, log_method):
    if assistant.plugins:
        raise AssertionError("Plugin runtime should not be created in A/C tests")
    return await _orig_create_runtime(plugin_manager=plugin_manager, assistant=assistant, log_method=log_method)
```

Exact `load_tools` patch shape:

```python
from contextlib import asynccontextmanager


@asynccontextmanager
async def _load_tools_empty(self):
    yield []
```

Full helper implementations (copy into `tests/server/conversation_fixtures.py`):

```python
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from sqlmodel import Session

from dingent.core.assistants.assistant import AssistantRuntime
from dingent.core.db.models import Assistant, Workflow, WorkflowEdge, WorkflowNode, Workspace


def create_workspace_row(*, session: Session, slug: str, allow_guest_access: bool) -> Workspace:
    ws = Workspace(name="Test Workspace", slug=slug, description="", allow_guest_access=allow_guest_access)
    session.add(ws)
    session.commit()
    session.refresh(ws)
    return ws


def create_minimal_workflow(
    session: Session,
    workspace_id,
    *,
    workflow_name: str = "conv-test",
    agent_a_name: str = "AgentA",
    agent_b_name: str = "AgentB",
) -> tuple[Workflow, dict[str, Assistant]]:
    agent_a = Assistant(workspace_id=workspace_id, name=agent_a_name, description="", instructions="SYSTEM_AGENT_A")
    agent_b = Assistant(workspace_id=workspace_id, name=agent_b_name, description="", instructions="SYSTEM_AGENT_B")
    session.add(agent_a)
    session.add(agent_b)
    session.commit()
    session.refresh(agent_a)
    session.refresh(agent_b)

    wf = Workflow(workspace_id=workspace_id, name=workflow_name, description="")
    session.add(wf)
    session.commit()
    session.refresh(wf)

    node_a = WorkflowNode(workflow_id=wf.id, assistant_id=agent_a.id, is_start_node=True, position={"x": 0.0, "y": 0.0}, measured={})
    node_b = WorkflowNode(workflow_id=wf.id, assistant_id=agent_b.id, is_start_node=False, position={"x": 240.0, "y": 0.0}, measured={})
    session.add(node_a)
    session.add(node_b)
    session.commit()
    session.refresh(node_a)
    session.refresh(node_b)

    edge = WorkflowEdge(workflow_id=wf.id, source_node_id=node_a.id, target_node_id=node_b.id)
    session.add(edge)
    session.commit()

    return wf, {"agent_a": agent_a, "agent_b": agent_b}


def apply_isolation_patches(monkeypatch) -> None:
    # Fail-fast if ANY assistant tries to include plugins (prevents silent swallowing).
    _orig = AssistantRuntime.create_runtime

    async def _create_runtime_failfast(cls, plugin_manager, assistant, log_method):
        if assistant.plugins:
            raise AssertionError("Plugin runtime should not be created in A/C tests")
        return await _orig(plugin_manager=plugin_manager, assistant=assistant, log_method=log_method)

    monkeypatch.setattr(AssistantRuntime, "create_runtime", _create_runtime_failfast)

    @asynccontextmanager
    async def _load_tools_empty(self):
        yield []

    monkeypatch.setattr(AssistantRuntime, "load_tools", _load_tools_empty)
```

6) Routing LLM builders (used by Task 2/3 tests):

- `build_routing_llm_for_multi_turn() -> RoutingFakeChatModelWithTools`
  - Routes: `"hello" -> AIMessage(content="A1")`, `"follow up" -> AIMessage(content="A2")`
- `build_routing_llm_for_handoff(*, expected_handoff_tool: str) -> RoutingFakeChatModelWithTools`
  - Routes: `"SYSTEM_AGENT_A" -> AIMessage(content="", tool_calls=[{"name": expected_handoff_tool, "args": {}, "id": "call_1", "type": "tool_call"}])`
  - Routes: `"SYSTEM_AGENT_B" -> AIMessage(content="FINAL_FROM_AGENT_B")`

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/server/test_conversation_multi_turn.py::test_conversation_helpers_contract -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/server/__init__.py tests/server/conversation_fixtures.py tests/server/test_conversation_multi_turn.py
git commit -m "test: add conversation test fixtures and payload helpers"
```

### Task 2: Scenario A Test (Multi-turn + /connect snapshot)

**Files:**
- Modify: `tests/server/test_conversation_multi_turn.py`
- Test: `tests/server/test_conversation_multi_turn.py`

- [ ] **Step 1: Write failing test (A)**

```python
import uuid

import pytest
from sqlmodel import Session

from tests.server.conversation_fixtures import (
    apply_isolation_patches,
    build_connect_payload,
    build_routing_llm_for_multi_turn,
    build_run_payload,
    create_minimal_workflow,
    create_workspace_row,
    sse_text,
)


def test_run_multi_turn_persists_messages_and_connect_snapshots(client, session: Session, monkeypatch):
    ws = create_workspace_row(session=session, slug="ws-conv-a", allow_guest_access=True)
    wf, _assistants = create_minimal_workflow(session, ws.id, workflow_name="conv-a")

    visitor_id = str(uuid.uuid4())
    headers = {"Accept": "text/event-stream", "X-Visitor-ID": visitor_id}

    thread_id = str(uuid.uuid4())

    # Patch LLM: route by last user message
    routing_llm = build_routing_llm_for_multi_turn()

    from dingent.core.llms import service as llm_service

    monkeypatch.setattr(llm_service, "get_llm_for_context", lambda **_kwargs: routing_llm)
    apply_isolation_patches(monkeypatch)

    resp1 = client.post(f"/api/v1/{ws.slug}/chat/agent/{wf.name}/run", json=build_run_payload(thread_id=thread_id, run_id="run-1", user_text="hello"), headers=headers)
    assert resp1.status_code == 200
    assert "A1" in sse_text(resp1)

    resp2 = client.post(
        f"/api/v1/{ws.slug}/chat/agent/{wf.name}/run",
        json=build_run_payload(thread_id=thread_id, run_id="run-2", user_text="follow up"),
        headers=headers,
    )
    assert resp2.status_code == 200
    assert "A2" in sse_text(resp2)

    conn = client.post(
        f"/api/v1/{ws.slug}/chat/agent/{wf.name}/connect",
        json=build_connect_payload(thread_id=thread_id, run_id="run-3"),
        headers=headers,
    )
    assert conn.status_code == 200
    text = sse_text(conn)
    assert "hello" in text
    assert "follow up" in text
    assert "A1" in text
    assert "A2" in text
```

Expected failure reasons:

- chat API regression or missing DB fields in the minimal workflow fixture.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_conversation_multi_turn.py::test_run_multi_turn_persists_messages_and_connect_snapshots -v`

Expected: FAIL.

- [ ] **Step 3: Implement missing fixtures / helpers**

Fill in missing helper functions in `tests/server/conversation_fixtures.py` and update the test to use `create_workspace_row(...)` so the test can control `slug` and `allow_guest_access`.

- [ ] **Step 3.1: Add per-test checkpointer isolation (required)**

The app lifespan opens a LangGraph sqlite checkpointer at `paths.sqlite_path` (`src/dingent/server/app.py`). To avoid cross-test leakage, modify `tests/server/conftest.py` so the `client` fixture patches `paths.db_dir` before entering `TestClient(app)`.

Modify: `tests/server/conftest.py`

```python
from pathlib import Path

from dingent.core.paths import paths


@pytest.fixture(name="client")
def client_fixture(app, session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_dir = tmp_path / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "db_dir", db_dir)

    def get_session_override():
        return session

    app.dependency_overrides[get_db_session] = get_session_override

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
```

Routing logic for A:

- When last human message contains `"hello"` -> return `AIMessage(content="A1")`
- When last human message contains `"follow up"` -> return `AIMessage(content="A2")`

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/server/test_conversation_multi_turn.py::test_run_multi_turn_persists_messages_and_connect_snapshots -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/server/test_conversation_multi_turn.py tests/server/conversation_fixtures.py
git commit -m "test: cover multi-turn chat via run and connect"
```

### Task 3: Scenario C Test (Multi-agent handoff A -> B)

**Files:**
- Create: `tests/server/test_conversation_handoff.py`
- Test: `tests/server/test_conversation_handoff.py`

- [ ] **Step 1: Write failing test (C)**

```python
import uuid

from sqlmodel import Session

from dingent.core.utils import normalize_agent_name

from tests.server.conversation_fixtures import (
    apply_isolation_patches,
    build_routing_llm_for_handoff,
    build_run_payload,
    create_minimal_workflow,
    create_workspace_row,
    sse_text,
)


def test_run_handoff_transfers_to_second_agent_and_returns_final_answer(client, session: Session, monkeypatch):
    ws = create_workspace_row(session=session, slug="ws-conv-c", allow_guest_access=True)
    wf, assistants = create_minimal_workflow(session, ws.id, workflow_name="conv-c")

    visitor_id = str(uuid.uuid4())
    headers = {"Accept": "text/event-stream", "X-Visitor-ID": visitor_id}
    thread_id = str(uuid.uuid4())

    agent_b_name = assistants["agent_b"].name
    agent_b_id = normalize_agent_name(agent_b_name)
    expected_tool = f"transfer_to_{agent_b_id}"

    routing_llm = build_routing_llm_for_handoff(expected_handoff_tool=expected_tool)

    from dingent.core.llms import service as llm_service

    monkeypatch.setattr(llm_service, "get_llm_for_context", lambda **_kwargs: routing_llm)
    apply_isolation_patches(monkeypatch)

    resp = client.post(
        f"/api/v1/{ws.slug}/chat/agent/{wf.name}/run",
        json=build_run_payload(thread_id=thread_id, run_id="run-1", user_text="please analyze"),
        headers=headers,
    )
    assert resp.status_code == 200
    text = sse_text(resp)
    assert expected_tool in text
    assert f"Transferred to {agent_b_id}" in text
    assert "FINAL_FROM_AGENT_B" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_conversation_handoff.py::test_run_handoff_transfers_to_second_agent_and_returns_final_answer -v`

Expected: FAIL.

- [ ] **Step 3: Implement routing Fake LLM for C**

In `tests/server/conversation_fixtures.py`:

- Route AgentA marker (`SYSTEM_AGENT_A`) to:
  - `AIMessage(content="", tool_calls=[{"name": expected_handoff_tool, "args": {}, "id": "call_1", "type": "tool_call"}])`
- Route AgentB marker (`SYSTEM_AGENT_B`) to:
  - `AIMessage(content="FINAL_FROM_AGENT_B")`

Make sure the routing is tolerant to extra calls:

- If the system prompt marker cannot be found, fall back to last human message (or return empty AI message).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/server/test_conversation_handoff.py::test_run_handoff_transfers_to_second_agent_and_returns_final_answer -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/server/test_conversation_handoff.py tests/server/conversation_fixtures.py
git commit -m "test: cover agent handoff through chat run endpoint"
```

### Task 4: Stabilization + Repo Verification

**Files:**
- Modify: as needed based on failures

- [ ] **Step 1: Run the new tests as a small suite**

Run: `uv run pytest tests/server/test_conversation_multi_turn.py tests/server/test_conversation_handoff.py -v`

Expected: PASS.

- [ ] **Step 1.1: If startup fails in lifespan due to global plugin sync, patch it in tests**

Note: app startup runs `_setup_global_services()` which reloads plugins and syncs plugin rows into the *global* DB engine (`src/dingent/server/app.py`). If this fails in CI/local (e.g. missing plugin tables or unexpected DB URL), patch it in `tests/server/conftest.py` before creating the app:

```python
from dingent.server import app as server_app

monkeypatch.setattr(server_app, "_setup_global_services", lambda _app: None)
```

Keep this patch only if needed; prefer leaving the real startup path intact when it is stable.

- [ ] **Step 2: Run formatting and lint checks**

Run:

- `uv run ruff format --check .`
- `uv run ruff check .`

Expected: PASS with no changes.

- [ ] **Step 3: Run type check (if part of CI expectations)**

Run: `uv run basedpyright`

Expected: PASS.

- [ ] **Step 4: Run full test suite (optional but recommended before PR)**

Run: `uv run pytest`

Expected: PASS.

- [ ] **Step 5: Commit any final fixes**

```bash
git status
git add -A
git commit -m "test: stabilize conversation API integration tests"
```

---

## Notes / Implementation Details

- Use header `X-Visitor-ID` (matches router alias in `src/dingent/server/api/routers/frontend/threads.py`).
- Ensure all generated `threadId` values are UUID strings; the router validates them.
- Both `/run` and `/connect` rebuild agent context; apply the same isolation patches for both.
- Keep assertions substring-based; do not couple to exact `ag_ui` event formatting.
