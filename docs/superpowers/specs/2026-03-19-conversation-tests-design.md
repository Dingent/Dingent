---
title: Conversation Tests (Fake LLM) Design
date: 2026-03-19
status: draft
scope:
  - A: multi-turn, same thread
  - C: multi-agent handoff
  - B: tool-call + artifact (later)
---

# Conversation Tests (Fake LLM) Design

## Goal

Add high-signal automated tests that exercise a realistic end-user chat flow through the HTTP API (`/api/v1/{workspace}/chat/agent/{agent_id}/run`) while using a Fake LLM (no external network calls).

Primary scenarios (implemented in this order):

- A: multi-turn conversation on the same thread (multiple `/run` calls, verify persistence and accumulation)
- C: multi-agent handoff (Agent A transfers to Agent B via handoff tool, verify end-to-end behavior)

Deferred scenario:

- B: tool call -> ToolMessage/ActivityMessage w/ artifact/display in SSE stream (add after A/C land)

## Non-Goals

- End-to-end tests that require real model providers, real plugin MCP processes, or real network connectivity
- Full strict decoding/validation of every SSE event schema emitted by `ag_ui`
- Performance benchmarking (already covered by `scripts/performance.py` style tests)

## Current Context (Repo Observations)

- The chat API is implemented in `src/dingent/server/api/routers/frontend/threads.py`.
  - It resolves an LLM via `dingent.core.llms.service.get_llm_for_context(...)`.
  - It builds an agent via `CopilotKitSdk.resolve_agent(spec, llm)` which uses `GraphFactory.build(...)`.
  - It streams via `StreamingResponse` with `EventEncoder`.
- Existing engine tests already demonstrate Fake LLM + handoff at the graph layer:
  - `tests/engine/test_handoff_debug.py`
- Existing infra demonstrates patching `get_llm_for_context` to inject a replay/Fake model:
  - `scripts/performance.py` uses `tests/utils.py::create_replay_llm`.
- A ready-made 2-agent workflow fixture exists:
  - `tests/setup_data.py::mock_full_single_cell_data` creates a workflow `single-cell` with assistants `DataGetter -> Analyst`.

Important: the graph build path eagerly loads assistant tools.

- `CopilotKitSdk.resolve_agent(...)` -> `GraphFactory.build(...)` -> `create_assistant_graphs(...)` -> `AssistantFactory.create_runtime(...)` -> `AssistantRuntime.load_tools()`.
- Even if a test never invokes a tool, `load_tools()` can attempt MCP/client initialization. The test design must explicitly isolate this.

## Recommended Approach

Write API-level integration tests that:

1) Create minimum DB records in the test database.
   - Create `Workspace(slug=..., allow_guest_access=True)`.
   - Insert a workflow with 1-2 assistants as needed for A/C.
   - For A/C determinism and isolation, prefer assistants with no plugin links (no `AssistantPluginLink` rows), so graph build does not need any MCP/plugin runtime.
   - In guest-mode requests, use a single `visitor_id` (UUID string) and reuse it across all calls; send header key exactly as used by the router: `X-Visitor-ID`.
2) Patch `dingent.core.llms.service.get_llm_for_context` to return a Fake LLM that supports `bind_tools`.
3) Patch tool loading to avoid external MCP/plugin side effects.
   - For A/C, patch `dingent.core.assistants.assistant.AssistantRuntime.load_tools` to return an async context manager that yields an empty list (no external tools).
   - Additionally, add a guard patch so that if plugin runtime creation is accidentally triggered, the test fails fast (e.g., patch `dingent.core.plugins.plugin_manager.PluginManager.get_or_create_runtime` to raise in A/C tests).

Note on handoff tools: handoff tools are created from the workflow adjacency map (not from plugin tool loading) and are still present even if `AssistantRuntime.load_tools` yields `[]`.
4) Call `/api/v1/{ws.slug}/chat/agent/{workflow_name}/run` via `fastapi.testclient.TestClient`.
5) Parse the returned SSE payload as plain text and assert presence of key event fragments.
6) For multi-turn: re-run with the same `threadId` and validate persistence by calling `/connect` and reading its message snapshot.

Why patch `get_llm_for_context` (instead of overriding `get_copilot_sdk`):

- It exercises the real graph build path (GraphFactory -> create_swarm -> build_simple_react_agent -> handoff tools).
- It keeps test control strictly at the model boundary.
- It matches established patterns already used in this codebase.

## Fake LLM Behavior

We will use `FakeMessagesListChatModel` (LangChain) extended with `bind_tools` (already available as `tests/utils.py::FakeChatModelWithTools`).

For scenario C (handoff), the fake model for Agent A must emit an `AIMessage` with a tool call:

- tool name: `transfer_to_{normalize_agent_name(dest_name)}`

Agent B then emits a normal assistant message (final response), e.g. containing a distinctive marker string.

For scenario A (multi-turn), we will use the same minimal no-plugin workflow fixture described below (so that both `/run` and `/connect` are isolated from plugin/MCP side effects). The fake model responses will return distinct assistant messages per run.

Implementation detail: the engine supports resolving a distinct LLM per assistant when `create_assistant_graphs(...)` is called with a callable resolver.

Important constraint in the current build path:

- `create_assistant_graphs(...)` calls the resolver with an assistant id only if an `assistant_id_map` is provided.
- The current API path (`threads.py` -> `CopilotKitSdk.resolve_agent` -> `GraphFactory.build`) does not pass an `assistant_id_map`, so a resolver will be called as `resolver(None)` for every assistant.

Decision for A/C: do not plumb `assistant_id_map` yet. Use routing within a single Fake LLM instance as the primary determinism strategy.

If later we decide to plumb `assistant_id_map`, we can switch A/C to true per-assistant Fake LLM instances.

- Option A (recommended for A/C): a routing Fake LLM that selects responses by a stable marker in the prompt/messages (preferably the assistant system prompt text). It should also tolerate extra model calls by returning a safe default once expected replies are exhausted.
- Option B: per-assistant Fake LLM via resolver, but only after plumbing an `assistant_id_map` into the graph build path.
- Option C (fallback): a pre-seeded response sequence that matches the expected call order, over-provisioned to handle extra calls.

We will implement routing first for A/C; if it proves insufficient, fall back to over-provisioned sequences. Per-assistant resolution is a later enhancement if we decide to plumb `assistant_id_map`.

### Minimal Workflow Fixture (A/C)

To avoid any plugin/MCP side effects, A/C tests will create a minimal workflow in the DB with assistants that have no plugins.

Proposed helper (new test utility; exact location decided during implementation):

- Create 2 assistants `AgentA` and `AgentB` with:
  - `instructions` containing a unique marker per agent (e.g., `"SYSTEM_AGENT_A"`, `"SYSTEM_AGENT_B"`) so the routing Fake LLM can reliably select responses.
  - `plugin_links=[]` / `plugins=[]` (no `AssistantPluginLink` rows).
- Create a workflow with 2 nodes and an edge `AgentA -> AgentB` and `start_node=AgentA`.

Handoff tool naming: expected tool name is always derived from the destination assistant name:

- `transfer_to_{normalize_agent_name(dest_name)}`

Tests must compute this at runtime (do not hardcode a specific assistant name).

This replaces using `mock_full_single_cell_data` for A/C. The single-cell fixture remains useful for later scenario B (tool/artifact) where tool plumbing is intentionally exercised.

### Request Templates

Both `/run` and `/connect` accept a `RunAgentInput`-shaped body. Tests will send a consistent payload skeleton:

```json
{
  "threadId": "<uuid>",
  "runId": "run-1",
  "parentRunId": null,
  "state": {},
  "messages": [{"id": "m1", "role": "user", "content": "Hello"}],
  "tools": [],
  "context": [],
  "forwardedProps": {}
}
```

Headers:

- `Accept: text/event-stream`
- guest mode: `X-Visitor-ID: <uuid>`

`/connect` note: `/connect` also depends on `get_agent_context` (it rebuilds the agent), so the same isolation patches and headers apply as `/run`. Tests will send a minimal valid `RunAgentInput` body for `/connect` (same keys as above; `messages` can be an empty list).

## Test Layout

Add new tests under `tests/server/` to keep them close to the API integration surface.

Proposed files:

- `tests/server/test_conversation_multi_turn.py` (Scenario A)
- `tests/server/test_conversation_handoff.py` (Scenario C)

We will also add small shared helpers (either in the new test modules or `tests/utils.py` if broadly useful):

- `build_run_payload(thread_id, run_id, messages, forwarded_props=...)`
- `parse_sse_text(response_text)` minimal parser to split events (best-effort)

## Scenario A: Multi-turn on Same Thread

Test: `test_run_multi_turn_persists_messages_and_connect_snapshots`

Steps:

1) Create workspace + workflow records (minimal, no plugins).
2) Patch `get_llm_for_context` to return a routing Fake LLM:
   - If the latest user message contains `"hello"`, return `AIMessage(content="A1")`.
   - If the latest user message contains `"follow up"`, return `AIMessage(content="A2")`.
3) POST `/run` with `threadId=T`, message `"hello"`, verify HTTP 200 and SSE contains `A1`.
4) POST `/run` again with same `threadId=T`, new user message `"follow up"`, verify SSE contains `A2`.
5) POST `/connect` with same `threadId=T` and `runId=...`, verify snapshot contains both user messages and both assistant messages in order (at least as substrings).

Assertions (robust):

- `response.status_code == 200`
- `"A1" in response1_text` and `"A2" in response2_text`
- connect snapshot text contains `hello`, `follow up`, `A1`, `A2`

## Scenario C: Multi-agent Handoff

Test: `test_run_handoff_transfers_to_second_agent_and_returns_final_answer`

Steps:

1) Create workspace + workflow with two assistants connected by an edge (A -> B), with no plugins.
2) Patch `get_llm_for_context` to return a routing Fake LLM:
   - When the prompt/messages indicate Agent A (via the unique system prompt marker), return an `AIMessage` with a tool call to `<expected_handoff_tool>`.
   - When the prompt/messages indicate Agent B, return `AIMessage(content="FINAL_FROM_AGENT_B")`.
3) POST `/run` with `threadId=T`, user message `"please analyze"`.
4) Verify SSE contains (substring checks):
   - the tool name `<expected_handoff_tool>` (handoff requested)
   - the tool result message `Transferred to <dest_name>` (from `create_handoff_tool`)
   - the final marker `FINAL_FROM_AGENT_B`

Assertions (robust):

- status 200
- presence-based substring checks only (avoid strict event shape coupling)

## SSE Parsing Strategy

`TestClient` returns the streaming body in `response.content` (fully buffered). We will treat it as UTF-8 text and perform minimal parsing:

- Split on double newlines to get candidate SSE events.
- Keep plain substring assertions against the concatenated text.

This is intentionally tolerant to encoder changes while still catching regressions in core behavior.

## Risks and Mitigations

- Risk: the order of model calls differs between runs/versions, breaking response-sequence-based Fake model.
  - Mitigation: use routing keyed on stable markers (system prompt + latest user message); tolerate extra calls by returning a safe default.
- Risk: tool name normalization mismatch (`transfer_to_<DestName>` vs `transfer_to_<dest_name>`).
  - Mitigation: derive expected tool name from the DB fixture (assistant name + `normalize_agent_name`) inside the test.
- Risk: tests become flaky if external plugin runtime is invoked.
  - Mitigation: for A/C, avoid plugin-linked assistants entirely; additionally patch tool loading to yield an empty tool list; only handoff tool remains (pure in-process).
- Risk: checkpointer persistence can leak across tests.
  - Mitigation: ensure tests use isolated checkpoint DB (either per-test temporary `paths.sqlite_path` or a patched/in-memory checkpointer in app state), and never share `threadId` across tests.
- Risk: header alias mismatch (`X-Visitor-Id` vs `X-Visitor-ID`) introduces false failures.
  - Mitigation: always use `X-Visitor-ID` (matches router alias) and keep new tests consistent with existing xfail notes in `tests/server/test_chat_api.py`.

## Follow-up (Scenario B)

After A/C land, add B by patching `AssistantRuntime.load_tools` (like `scripts/performance.py`) to provide a deterministic tool that returns an artifact with `structured_content.display`, and assert that `DingMiddleware` produces `ActivityMessage` events that show up in SSE.

## Scope Gate (A/C First)

- The first implementation PR includes only A and C.
- B is explicitly out of scope until A/C are stable; no additional artifact/tool plumbing is introduced beyond what is necessary to keep A/C deterministic.
