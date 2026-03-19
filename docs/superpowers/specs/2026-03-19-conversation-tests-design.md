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

## Recommended Approach

Write API-level integration tests that:

1) Create workspace + workflow records in the test database (reuse existing fixture helper).
2) Patch `dingent.core.llms.service.get_llm_for_context` to return a Fake LLM that supports `bind_tools`.
3) Call `/api/v1/{ws.slug}/chat/agent/{workflow_name}/run` via `fastapi.testclient.TestClient`.
4) Parse the returned SSE payload as plain text and assert presence of key event fragments.
5) For multi-turn: re-run with the same `threadId` and validate persistence by calling `/connect` and reading its message snapshot.

Why patch `get_llm_for_context` (instead of overriding `get_copilot_sdk`):

- It exercises the real graph build path (GraphFactory -> create_swarm -> build_simple_react_agent -> handoff tools).
- It keeps test control strictly at the model boundary.
- It matches established patterns already used in this codebase.

## Fake LLM Behavior

We will use `FakeMessagesListChatModel` (LangChain) extended with `bind_tools` (already available as `tests/utils.py::FakeChatModelWithTools`).

For scenario C (handoff), the fake model for Agent A must emit an `AIMessage` with a tool call:

- tool name: `transfer_to_<normalized-destination>`
  - In the `single-cell` fixture, the destination assistant is `Analyst`.
  - `normalize_agent_name` does not change `Analyst`, so tool should be `transfer_to_Analyst`.

Agent B then emits a normal assistant message (final response), e.g. containing a distinctive marker string.

For scenario A (multi-turn), we can keep a single-agent workflow (fallback spec) OR reuse the same workflow but avoid handoff by returning plain assistant messages. To avoid DB setup complexity, we will reuse `mock_full_single_cell_data` but structure the Fake LLM responses so the first run produces an assistant answer without handoff; the second run produces a different assistant answer. (This keeps the API path consistent.)

Implementation detail: because `GraphFactory.build(...)` passes the same `llm` instance to all assistants by default, we will use a Fake model that can serve deterministic responses across multiple calls, and in the handoff test we will instead patch at a finer granularity if required:

- Option A (preferred): create a composite Fake model that returns responses based on the system prompt or current active agent name (if accessible in the prompt/messages).
- Option B (fallback): avoid needing per-assistant LLM instances by returning a response sequence that matches the expected call order (Agent A first, then Agent B).

We will start with Option B and only implement Option A if call-order proves nondeterministic.

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

1) Create workspace + workflow (`mock_full_single_cell_data`).
2) Patch `get_llm_for_context` to return Fake LLM with responses:
   - Run 1: `AIMessage(content="A1")`
   - Run 2: `AIMessage(content="A2")`
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

1) Create workspace + workflow (`mock_full_single_cell_data`).
2) Patch `get_llm_for_context` to return Fake LLM responses in this sequence:
   - First assistant call: `AIMessage(content="", tool_calls=[{"name": "transfer_to_Analyst", "args": {}, "id": "call_1"}])`
   - Second assistant call: `AIMessage(content="FINAL_FROM_ANALYST")`
3) POST `/run` with `threadId=T`, user message `"please analyze"`.
4) Verify SSE contains:
   - the tool name `transfer_to_Analyst` (handoff requested)
   - the tool result message `Transferred to Analyst` (from `create_handoff_tool`)
   - the final marker `FINAL_FROM_ANALYST`

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
  - Mitigation: introduce a routing Fake LLM keyed on prompt/system message or active agent name.
- Risk: tool name normalization mismatch (`transfer_to_Analyst` vs `transfer_to_analyst`).
  - Mitigation: derive expected tool name from the DB fixture (assistant name + `normalize_agent_name`) inside the test.
- Risk: tests become flaky if external plugin runtime is invoked.
  - Mitigation: for A/C, avoid invoking real plugin tools; only use handoff tool (pure in-process).

## Follow-up (Scenario B)

After A/C land, add B by patching `AssistantRuntime.load_tools` (like `scripts/performance.py`) to provide a deterministic tool that returns an artifact with `structured_content.display`, and assert that `DingMiddleware` produces `ActivityMessage` events that show up in SSE.
