import json
import uuid
from collections.abc import AsyncGenerator
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

import ag_ui_langgraph
import ag_ui_langgraph.utils
from ag_ui.core import (
    ActivityMessage,
    ActivitySnapshotEvent,
    EventType,
    MessagesSnapshotEvent,
    RunAgentInput,
    StateSnapshotEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ThinkingTextMessageContentEvent,
    ThinkingTextMessageEndEvent,
    ThinkingTextMessageStartEvent,
)
from ag_ui.core.events import RunStartedEvent
from ag_ui_langgraph.agent import Command, normalize_tool_content
from ag_ui_langgraph.types import LangGraphReasoning
from ag_ui_langgraph.utils import (
    AGUIAssistantMessage,
    AGUIFunctionCall,
    AGUIMessage,
    AGUISystemMessage,
    AGUIToolCall,
    AGUIToolMessage,
    AGUIUserMessage,
    convert_agui_multimodal_to_langchain,
    convert_langchain_multimodal_to_agui,
    resolve_message_content,
    stringify_if_needed,
)
from copilotkit import LangGraphAGUIAgent
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from loguru import logger

from dingent.engine.agents import messages as DingMessages
from dingent.engine.agents.simple_agent import mcp_artifact_to_agui_display


class DingRunAgentInput(RunAgentInput):
    owner_id: uuid.UUID


def ding_resolve_reasoning_content(chunk: AIMessageChunk | AIMessage) -> LangGraphReasoning | None:
    # -----------------------------------------------------------
    # 1. 优先检查 additional_kwargs
    # (Gemini, DeepSeek, OpenAI o1/o3 通常在这里)
    # -----------------------------------------------------------
    if hasattr(chunk, "additional_kwargs"):
        kwargs = chunk.additional_kwargs

        # 定义可能的推理字段名列表
        # 'reasoning_content': DeepSeek R1, 这里的 Gemini 适配器通常也用这个
        # 'reasoning': 某些版本的 OpenAI 适配器
        # 'thinking': 某些自定义适配器
        possible_keys = ["reasoning_content", "reasoning", "thinking"]

        for key in possible_keys:
            val = kwargs.get(key)
            if val:
                # OpenAI 有时会嵌套在字典里: {"summary": [{"text": "..."}]}
                if isinstance(val, dict):
                    summary = val.get("summary", [])
                    if summary and isinstance(summary, list):
                        data = summary[0]
                        if data and data.get("text"):
                            return LangGraphReasoning(type="text", text=data["text"], index=data.get("index", 0))
                # Gemini / DeepSeek 通常直接就是字符串
                elif isinstance(val, str) and val.strip():
                    return LangGraphReasoning(
                        type="text",
                        text=val,
                        index=0,  # 流式通常没有 index，默认为 0
                    )

    content = chunk.content
    # Anthropic reasoning response
    if isinstance(content, list) and content and content[0]:
        if not content[0].get("thinking"):
            return None
        return LangGraphReasoning(text=content[0]["thinking"], type="text", index=content[0].get("index", 0))

    # OpenAI reasoning response
    if hasattr(chunk, "additional_kwargs"):
        reasoning = chunk.additional_kwargs.get("reasoning", {})
        summary = reasoning.get("summary", [])
        if summary:
            data = summary[0]
            if not data or not data.get("text"):
                return None
            return LangGraphReasoning(type="text", text=data["text"], index=data.get("index", 0))

    return None


def ding_strip_reasoning_metadata(chunk: AIMessageChunk | AIMessage) -> AIMessageChunk | AIMessage:
    reasoning_keys = {"reasoning_content", "reasoning", "thinking"}
    additional_kwargs = getattr(chunk, "additional_kwargs", None)
    if not isinstance(additional_kwargs, dict) or not any(key in additional_kwargs for key in reasoning_keys):
        return chunk

    return chunk.model_copy(update={"additional_kwargs": {key: value for key, value in additional_kwargs.items() if key not in reasoning_keys}})


def ding_strip_event_reasoning_metadata(event: Any) -> Any:
    chunk = event.get("data", {}).get("chunk")
    if not isinstance(chunk, AIMessageChunk | AIMessage):
        return event

    stripped_chunk = ding_strip_reasoning_metadata(chunk)
    if stripped_chunk is chunk:
        return event

    return {**event, "data": {**event.get("data", {}), "chunk": stripped_chunk}}


def ding_langchain_messages_to_agui(messages: list[BaseMessage]):
    agui_messages: list[AGUIMessage] = []
    thinking_content = ""
    for message in messages:
        if isinstance(message, ToolMessage):
            agui_messages.append(
                AGUIToolMessage(
                    id=str(message.id),
                    role="tool",
                    content=stringify_if_needed(resolve_message_content(message.content)),
                    tool_call_id=message.tool_call_id,
                )
            )
        elif message.type == "activity":
            try:
                agui_messages.append(
                    ActivityMessage(
                        activity_type="a2ui-surface",
                        id=str(message.id or uuid.uuid4()),
                        content=message.content[0],
                    )
                )
            except Exception as e:
                print(f"Error processing artifact in ToolMessage: {e}")
        elif isinstance(message, HumanMessage):
            # Handle multimodal content
            if isinstance(message.content, list):
                content = convert_langchain_multimodal_to_agui(message.content)
            else:
                content = stringify_if_needed(resolve_message_content(message.content))

            agui_messages.append(
                AGUIUserMessage(
                    id=str(message.id),
                    role="user",
                    content=content,
                    name=message.name,
                )
            )
        elif isinstance(message, AIMessage):
            reasoning = ding_resolve_reasoning_content(message)
            tool_calls = None
            if message.tool_calls:
                tool_calls = [
                    AGUIToolCall(
                        id=str(tc["id"]),
                        type="function",
                        function=AGUIFunctionCall(
                            name=tc["name"],
                            arguments=json.dumps(tc.get("args", {})),
                        ),
                    )
                    for tc in message.tool_calls
                ]

            thinking_content_chunk = reasoning.get("text", "") if reasoning else ""
            thinking_content += f"\n{thinking_content_chunk}"
            message_content = stringify_if_needed(resolve_message_content(message.content))

            if message_content:
                message_content = f"<thinking>{thinking_content}</thinking>\n{message_content}"
                thinking_content = ""

            agui_messages.append(
                AGUIAssistantMessage(
                    id=str(message.id),
                    role="assistant",
                    content=message_content,
                    tool_calls=tool_calls,
                    name=message.name,
                )
            )
        elif isinstance(message, SystemMessage):
            agui_messages.append(
                AGUISystemMessage(
                    id=str(message.id),
                    role="system",
                    content=stringify_if_needed(resolve_message_content(message.content)),
                    name=message.name,
                )
            )
        else:
            raise TypeError(f"Unsupported message type: {type(message)}")
    return agui_messages


def ding_agui_messages_to_langchain(messages: list[AGUIMessage]) -> list[BaseMessage]:
    langchain_messages = []
    for message in messages:
        role = message.role
        if role == "user":
            # Handle multimodal content
            if isinstance(message.content, str):
                content = message.content
            elif isinstance(message.content, list):
                content = convert_agui_multimodal_to_langchain(message.content)
            else:
                content = str(message.content)

            langchain_messages.append(
                HumanMessage(
                    id=message.id,
                    content=content,
                    name=message.name,
                )
            )
        elif role == "assistant":
            tool_calls = []
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tc in message.tool_calls:
                    tool_calls.append(
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "args": json.loads(tc.function.arguments) if hasattr(tc, "function") and tc.function.arguments else {},
                            "type": "tool_call",
                        }
                    )
            langchain_messages.append(
                AIMessage(
                    id=message.id,
                    content=message.content or "",
                    tool_calls=tool_calls,
                    name=message.name,
                )
            )
        elif role == "system":
            langchain_messages.append(
                SystemMessage(
                    id=message.id,
                    content=message.content,
                    name=message.name,
                )
            )
        elif role == "tool":
            langchain_messages.append(
                ToolMessage(
                    id=message.id,
                    content=message.content,
                    tool_call_id=message.tool_call_id,
                )
            )
        elif role == "activity":
            langchain_messages.append(
                DingMessages.ActivityMessage(
                    id=message.id,
                    content=message.content,
                    name=message.name,
                )
            )
        else:
            raise ValueError(f"Unsupported message role: {role}")
    return langchain_messages


def ding_make_json_safe(value: Any, _seen: set[int] | None = None) -> Any:
    """
    Convert `value` into something that `json.dumps` can always handle.
    Includes a blacklist to prevent traversing into dangerous LangGraph internal objects.
    """
    if _seen is None:
        _seen = set()

    obj_id = id(value)
    if obj_id in _seen:
        return "<recursive>"

    # --- 0. Blocklist for dangerous keys ---------------------------------------
    # 这些 key 通常包含不可序列化的运行时对象（如数据库连接、回调管理器）
    # 在遍历字典时，如果遇到这些 key，直接跳过其内容的递归
    UNSAFE_KEYS = {"runtime", "config", "configurable", "callbacks", "__pregel_runtime", "__pregel_task_id", "stream_writer", "store"}

    # --- 1. Primitives -----------------------------------------------------
    if isinstance(value, str | int | float | bool) or value is None:
        return value

    # --- 2. Enum → use underlying value -----------------------------------
    if isinstance(value, Enum):
        return ding_make_json_safe(value.value, _seen)

    # --- 3. Dicts (CRITICAL FIX HERE) --------------------------------------
    if isinstance(value, dict):
        _seen.add(obj_id)
        safe_dict = {}
        for k, v in value.items():
            # 检查 key 是否在黑名单中，或者是内部私有属性（以 __pregel 开头）
            str_k = str(k)
            if str_k in UNSAFE_KEYS or str_k.startswith("__pregel_"):
                # 仅保留占位符，不再递归进入 v
                safe_dict[ding_make_json_safe(k, _seen)] = f"<Filtered: {str_k}>"
            else:
                safe_dict[ding_make_json_safe(k, _seen)] = ding_make_json_safe(v, _seen)
        return safe_dict

    # --- 4. Iterable containers -------------------------------------------
    if isinstance(value, list | tuple | set | frozenset):
        _seen.add(obj_id)
        return [ding_make_json_safe(v, _seen) for v in value]

    # --- 5. Dataclasses ----------------------------------------------------
    if is_dataclass(value):
        _seen.add(obj_id)
        return ding_make_json_safe(asdict(value), _seen)

    # --- 6. Pydantic-like models (v2: model_dump) -------------------------
    if hasattr(value, "model_dump") and callable(value.model_dump):
        _seen.add(obj_id)
        try:
            # model_dump 返回字典，递归调用会进入上方的第 3 步 (Dicts)，从而触发过滤逻辑
            return ding_make_json_safe(value.model_dump(), _seen)
        except Exception:
            pass

    # --- 7. Pydantic v1-style / other libs with .dict() -------------------
    if hasattr(value, "dict") and callable(value.dict):
        _seen.add(obj_id)
        try:
            return ding_make_json_safe(value.dict(), _seen)
        except Exception:
            pass

    # --- 8. Generic "to_dict" pattern -------------------------------------
    if hasattr(value, "to_dict") and callable(value.to_dict):
        _seen.add(obj_id)
        try:
            return ding_make_json_safe(value.to_dict(), _seen)
        except Exception:
            pass

    # --- 9. Generic Python objects with __dict__ --------------------------
    if hasattr(value, "__dict__"):
        _seen.add(obj_id)
        try:
            return ding_make_json_safe(vars(value), _seen)
        except Exception:
            pass

    # --- 10. Last resort ---------------------------------------------------
    try:
        return repr(value)
    except Exception:
        return "<Unrepresentable Object>"


ag_ui_langgraph.agent.langchain_messages_to_agui = ding_langchain_messages_to_agui
ag_ui_langgraph.utils.agui_messages_to_langchain = ding_agui_messages_to_langchain
ag_ui_langgraph.utils.make_json_safe = ding_make_json_safe


class DingLangGraphAGUIAgent(LangGraphAGUIAgent):
    """
    自定义 Agent 类
    """

    async def run(self, input: RunAgentInput, extra_config: dict | None = None) -> AsyncGenerator[str]:
        previous_config = self.config
        streamed_message_content: dict[str, str] = {}

        current_config = previous_config.copy() if previous_config else {}

        if extra_config:
            current_config.update(extra_config)

        self.config = current_config
        logger.info(
            "AG-UI agent run started: agent={}, thread_id={}, run_id={}, input_messages={}, extra_config_keys={}",
            self.name,
            input.thread_id,
            input.run_id,
            len(input.messages or []),
            sorted(extra_config or {}),
        )
        event_counts: dict[str, int] = {}

        try:
            async for event_str in super().run(input):
                event_type = getattr(event_str, "type", None)
                event_counts[str(event_type)] = event_counts.get(str(event_type), 0) + 1
                if event_type == EventType.TEXT_MESSAGE_CONTENT:
                    message_id = getattr(event_str, "message_id", None)
                    delta = getattr(event_str, "delta", None)
                    if message_id and delta:
                        streamed_message_content[message_id] = streamed_message_content.get(message_id, "") + delta
                elif event_type == EventType.MESSAGES_SNAPSHOT:
                    for message in getattr(event_str, "messages", []) or []:
                        if getattr(message, "role", None) != "assistant":
                            continue

                        message_id = getattr(message, "id", None)
                        content = getattr(message, "content", None)
                        if message_id in streamed_message_content and not content:
                            message.content = streamed_message_content[message_id]

                yield event_str
            logger.info("AG-UI agent run completed: agent={}, thread_id={}, run_id={}, event_counts={}", self.name, input.thread_id, input.run_id, event_counts)
        except Exception:
            logger.exception("AG-UI agent run failed: agent={}, thread_id={}, run_id={}, event_counts={}", self.name, input.thread_id, input.run_id, event_counts)
            raise
        finally:
            self.config = previous_config

    async def get_thread_messages(self, thread_id: str, run_id: str):
        """
        返回格式已转换为前端友好的 AG-UI 格式。
        """

        config = self.graph.config or {}
        config["configurable"] = config.get("configurable", {})
        config["configurable"]["thread_id"] = thread_id
        logger.info("Loading thread messages: agent={}, thread_id={}, run_id={}", self.name, thread_id, run_id)

        state = await self.graph.aget_state(config)

        # 提取 messages
        messages = state.values.get("messages", [])
        logger.info("Thread messages loaded: agent={}, thread_id={}, run_id={}, message_count={}", self.name, thread_id, run_id, len(messages))

        yield self._dispatch_event(
            RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=thread_id,
                run_id=run_id,
            )
        )
        yield self._dispatch_event(
            MessagesSnapshotEvent(type=EventType.MESSAGES_SNAPSHOT, messages=ding_langchain_messages_to_agui(messages)),
        )

    async def get_state_and_messages_snapshots(self, config) -> AsyncGenerator[Any]:
        state = await self.graph.aget_state(config)
        state_values = state.values or {}
        yield self._dispatch_event(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=self.get_state_snapshot(state_values)))

        snapshot_messages = self._filter_orphan_tool_messages(state_values.get("messages", []))
        yield self._dispatch_event(
            MessagesSnapshotEvent(
                type=EventType.MESSAGES_SNAPSHOT,
                messages=ding_langchain_messages_to_agui(snapshot_messages),
            )
        )

    async def prepare_stream(self, input: RunAgentInput, agent_state, config):
        previous_count = len(agent_state.values.get("messages", []))
        agent_state.values["messages"] = [msg for msg in agent_state.values.get("messages", []) if msg.type != "activity"]
        logger.info(
            "Preparing AG-UI stream: agent={}, thread_id={}, run_id={}, previous_messages={}, retained_messages={}",
            self.name,
            input.thread_id,
            input.run_id,
            previous_count,
            len(agent_state.values["messages"]),
        )

        return await super().prepare_stream(input, agent_state, config)

    async def _handle_command_tool_end_event(self, event: Any) -> AsyncGenerator[str]:
        if event.get("event") == ag_ui_langgraph.LangGraphEventTypes.OnToolEnd:
            tool_call_output = event.get("data", {}).get("output")
            if isinstance(tool_call_output, Command):
                messages = tool_call_output.update.get("messages", [])
                tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
                activity_messages = [message for message in messages if getattr(message, "type", None) == "activity"]

                # History-preserving Commands (such as handoff) may include prior tool messages.
                # Only the newly appended tool result belongs to the current OnToolEnd event.
                if tool_messages:
                    tool_messages = [tool_messages[-1]]

                for tool_msg in tool_messages:
                    if not self.active_run["has_function_streaming"]:
                        yield self._dispatch_event(
                            ag_ui_langgraph.agent.ToolCallStartEvent(
                                type=EventType.TOOL_CALL_START,
                                tool_call_id=tool_msg.tool_call_id,
                                tool_call_name=tool_msg.name or event.get("name") or "tool",
                                parent_message_id=tool_msg.id,
                                raw_event=event,
                            )
                        )
                        yield self._dispatch_event(
                            ag_ui_langgraph.agent.ToolCallArgsEvent(
                                type=EventType.TOOL_CALL_ARGS,
                                tool_call_id=tool_msg.tool_call_id,
                                delta=json.dumps(event.get("data", {}).get("input", {})),
                                raw_event=event,
                            )
                        )
                        yield self._dispatch_event(
                            ag_ui_langgraph.agent.ToolCallEndEvent(
                                type=EventType.TOOL_CALL_END,
                                tool_call_id=tool_msg.tool_call_id,
                                raw_event=event,
                            )
                        )

                    yield self._dispatch_event(
                        ag_ui_langgraph.agent.ToolCallResultEvent(
                            type=EventType.TOOL_CALL_RESULT,
                            tool_call_id=tool_msg.tool_call_id,
                            message_id=str(uuid.uuid4()),
                            content=normalize_tool_content(tool_msg.content),
                            role="tool",
                        )
                    )

                for activity_msg in activity_messages:
                    for snapshot_event in self._emit_activity_snapshot_events(activity_msg, event):
                        yield snapshot_event
                return

    def _emit_activity_snapshot_events(self, activity_msg: BaseMessage, raw_event: Any) -> list[Any]:
        if self.active_run is None:
            return []

        emitted_ids = self.active_run.setdefault("emitted_activity_message_ids", set())
        contents = activity_msg.content if isinstance(activity_msg.content, list) else [activity_msg.content]
        message_id = str(activity_msg.id or uuid.uuid4())
        events = []
        for index, content in enumerate(contents):
            if not isinstance(content, dict):
                continue

            content_message_id = message_id if len(contents) == 1 else f"{message_id}:{index}"
            if content_message_id in emitted_ids:
                continue

            emitted_ids.add(content_message_id)
            events.append(
                self._dispatch_event(
                    ActivitySnapshotEvent(
                        type=EventType.ACTIVITY_SNAPSHOT,
                        message_id=content_message_id,
                        activity_type="a2ui-surface",
                        content=content,
                        raw_event=raw_event,
                    )
                )
            )

        return events

    def _emit_state_activity_snapshot_events(self, state: Any, raw_event: Any) -> list[Any]:
        if not isinstance(state, dict):
            return []

        messages = state.get("messages", [])
        return [event for message in messages if getattr(message, "type", None) == "activity" for event in self._emit_activity_snapshot_events(message, raw_event)]

    def _emit_tool_output_activity_snapshot_events(self, event: Any) -> list[Any]:
        if event.get("event") != ag_ui_langgraph.LangGraphEventTypes.OnToolEnd:
            return []

        tool_output = event.get("data", {}).get("output")
        if isinstance(tool_output, ToolMessage):
            artifact = tool_output.artifact
            tool_call_id = tool_output.tool_call_id
        elif isinstance(tool_output, dict):
            artifact = tool_output.get("artifact")
            tool_call_id = tool_output.get("tool_call_id")
        else:
            return []

        if not isinstance(artifact, dict) or not tool_call_id:
            return []

        structured_content = artifact.get("structured_content")
        if isinstance(structured_content, str) and structured_content.strip():
            try:
                structured_content = json.loads(structured_content)
            except json.JSONDecodeError:
                return []

        if not isinstance(structured_content, dict):
            return []

        display = structured_content.get("display")
        if not display:
            return []

        content = mcp_artifact_to_agui_display(
            tool_name=str(event.get("name") or "tool"),
            query_args=event.get("data", {}).get("input", {}),
            surface_base_id=str(tool_call_id),
            artifact=display,
        )
        activity_message = DingMessages.ActivityMessage(id=f"{tool_call_id}:activity", content=content)
        return self._emit_activity_snapshot_events(activity_message, event)

    def _emit_thinking_events(self, reasoning_data: LangGraphReasoning):
        if not reasoning_data or "type" not in reasoning_data or "text" not in reasoning_data:
            return

        thinking_step_index = reasoning_data.get("index", 0)

        if (
            self.active_run.get("thinking_process")
            and self.active_run["thinking_process"].get("index") is not None
            and self.active_run["thinking_process"]["index"] != thinking_step_index
        ):
            thinking_message_id = self.active_run["thinking_process"]["message_id"]
            if self.active_run["thinking_process"].get("type"):
                yield self._dispatch_event(ThinkingTextMessageEndEvent(type=EventType.THINKING_TEXT_MESSAGE_END, message_id=thinking_message_id))
            yield self._dispatch_event(ThinkingEndEvent(type=EventType.THINKING_END, message_id=thinking_message_id))
            self.active_run["thinking_process"] = None

        if not self.active_run.get("thinking_process"):
            message_id = str(uuid.uuid4())
            yield self._dispatch_event(ThinkingStartEvent(type=EventType.THINKING_START, message_id=message_id))
            self.active_run["thinking_process"] = {"index": thinking_step_index, "message_id": message_id}

        if self.active_run["thinking_process"].get("type") != reasoning_data["type"]:
            yield self._dispatch_event(
                ThinkingTextMessageStartEvent(
                    type=EventType.THINKING_TEXT_MESSAGE_START,
                    message_id=self.active_run["thinking_process"]["message_id"],
                )
            )
            self.active_run["thinking_process"]["type"] = reasoning_data["type"]

        if self.active_run["thinking_process"].get("type"):
            yield self._dispatch_event(
                ThinkingTextMessageContentEvent(
                    type=EventType.THINKING_TEXT_MESSAGE_CONTENT,
                    message_id=self.active_run["thinking_process"]["message_id"],
                    delta=reasoning_data["text"],
                )
            )

    async def _handle_single_event(self, event: Any, state) -> AsyncGenerator[str]:
        event_type = event.get("event")
        chunk = event.get("data", {}).get("chunk")

        reasoning_data = None
        if event_type == ag_ui_langgraph.LangGraphEventTypes.OnChatModelStream and chunk:
            reasoning_data = ding_resolve_reasoning_content(chunk)

        if reasoning_data:
            for evt in self._emit_thinking_events(reasoning_data):
                yield evt

        command_tool_events = [evt async for evt in self._handle_command_tool_end_event(event)]
        if command_tool_events:
            for evt in command_tool_events:
                yield evt
            return

        event_for_text_stream = ding_strip_event_reasoning_metadata(event) if reasoning_data else event
        async for evt in super()._handle_single_event(event_for_text_stream, state):
            yield evt

        for evt in self._emit_tool_output_activity_snapshot_events(event):
            yield evt

        for evt in self._emit_state_activity_snapshot_events(state, event):
            yield evt
