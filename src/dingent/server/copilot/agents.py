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
    CustomEvent,
    EventType,
    MessagesSnapshotEvent,
    RunAgentInput,
    RunFinishedEvent,
)
from ag_ui.core.events import RunStartedEvent
from ag_ui_langgraph.agent import Command, dump_json_safe, get_stream_payload_input, normalize_tool_content
from ag_ui_langgraph.types import LangGraphReasoning
from ag_ui_langgraph.utils import (
    AGUIAssistantMessage,
    AGUIFunctionCall,
    AGUIMessage,
    AGUISystemMessage,
    AGUIToolCall,
    AGUIToolMessage,
    AGUIUserMessage,
    agui_messages_to_langchain,
    convert_agui_multimodal_to_langchain,
    convert_langchain_multimodal_to_agui,
    resolve_message_content,
    stringify_if_needed,
)
from copilotkit import LangGraphAGUIAgent
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from dingent.engine.agents import messages as DingMessages


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
                        id=str(uuid.uuid4()),
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
ag_ui_langgraph.agent.resolve_reasoning_content = ding_resolve_reasoning_content


async def graph_aget_state(self, config, *, subgraphs: bool = False):
    """
    替换原有的 graph.get_state 方法，去掉ActivityMessage
    """
    state = await self._original_aget_state(config, subgraphs=subgraphs)
    state.values["messages"] = [msg for msg in state.values.get("messages", []) if not msg.type == "activity"]
    return state


class DingLangGraphAGUIAgent(LangGraphAGUIAgent):
    """
    自定义 Agent 类
    """

    async def run(self, input: RunAgentInput, extra_config: dict | None = None) -> AsyncGenerator[str]:
        previous_config = self.config

        current_config = previous_config.copy() if previous_config else {}

        if extra_config:
            current_config.update(extra_config)

        self.config = current_config

        try:
            async for event_str in super().run(input):
                yield event_str
        finally:
            self.config = previous_config

    async def get_thread_messages(self, thread_id: str, run_id: str):
        """
        返回格式已转换为前端友好的 AG-UI 格式。
        """

        config = self.graph.config or {}
        config["configurable"] = config.get("configurable", {})
        config["configurable"]["thread_id"] = thread_id

        state = await self.graph.aget_state(config)

        # 提取 messages
        messages = state.values.get("messages", [])

        yield self._dispatch_event(
            RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=thread_id,
                run_id=run_id,
            )
        )
        yield self._dispatch_event(
            MessagesSnapshotEvent(type=EventType.MESSAGES_SNAPSHOT, messages=ag_ui_langgraph.agent.langchain_messages_to_agui(messages)),
        )

    async def prepare_stream(self, input: RunAgentInput, agent_state, config):
        state_input = input.state or {}
        messages = input.messages or []
        forwarded_props = input.forwarded_props or {}
        thread_id = input.thread_id

        state_input["messages"] = agent_state.values.get("messages", [])
        self.active_run["current_graph_state"] = agent_state.values.copy()
        langchain_messages = agui_messages_to_langchain(messages)
        state = self.langgraph_default_merge_state(state_input, langchain_messages, input)
        self.active_run["current_graph_state"].update(state)
        config["configurable"]["thread_id"] = thread_id
        interrupts = agent_state.tasks[0].interrupts if agent_state.tasks and len(agent_state.tasks) > 0 else []
        has_active_interrupts = len(interrupts) > 0
        resume_input = forwarded_props.get("command", {}).get("resume", None)

        self.active_run["schema_keys"] = self.get_schema_keys(config)

        non_system_messages = [msg for msg in langchain_messages if not isinstance(msg, SystemMessage)]
        messages_without_activities = [msg for msg in agent_state.values.get("messages", []) if not msg.type == "activity"]
        if len(messages_without_activities) > len(non_system_messages):
            # Find the last user message by working backwards from the last message
            last_user_message = None
            for i in range(len(langchain_messages) - 1, -1, -1):
                if isinstance(langchain_messages[i], HumanMessage):
                    last_user_message = langchain_messages[i]
                    break

            if last_user_message:
                return await self.prepare_regenerate_stream(input=input, message_checkpoint=last_user_message, config=config)

        events_to_dispatch = []
        if has_active_interrupts and not resume_input:
            events_to_dispatch.append(RunStartedEvent(type=EventType.RUN_STARTED, thread_id=thread_id, run_id=self.active_run["id"]))

            for interrupt in interrupts:
                events_to_dispatch.append(
                    CustomEvent(
                        type=EventType.CUSTOM,
                        name=ag_ui_langgraph.LangGraphEventTypes.OnInterrupt.value,
                        value=dump_json_safe(interrupt.value),
                        raw_event=interrupt,
                    )
                )

            events_to_dispatch.append(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=self.active_run["id"]))
            return {
                "stream": None,
                "state": None,
                "config": None,
                "events_to_dispatch": events_to_dispatch,
            }

        if self.active_run["mode"] == "continue":
            await self.graph.aupdate_state(config, state, as_node=self.active_run.get("node_name"))

        if resume_input:
            stream_input = Command(resume=resume_input)
        else:
            payload_input = get_stream_payload_input(
                mode=self.active_run["mode"],
                state=state,
                schema_keys=self.active_run["schema_keys"],
            )
            stream_input = {**forwarded_props, **payload_input} if payload_input else None

        subgraphs_stream_enabled = input.forwarded_props.get("stream_subgraphs") if input.forwarded_props else False

        kwargs = self.get_stream_kwargs(
            input=stream_input,
            config=config,
            subgraphs=bool(subgraphs_stream_enabled),
            version="v2",
        )

        stream = self.graph.astream_events(**kwargs)

        return {"stream": stream, "state": state, "config": config}

    async def _handle_single_event(self, event: Any, state) -> AsyncGenerator[str]:
        if event.get("event") == ag_ui_langgraph.LangGraphEventTypes.OnToolEnd:
            tool_call_output = event.get("data", {}).get("output")
            if isinstance(tool_call_output, Command):
                messages = tool_call_output.update.get("messages", [])
                tool_messages = [message for message in messages if isinstance(message, ToolMessage)]

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
                return

        # 1. 尝试提取 reasoning_data，用于判断是否命中需要修复的逻辑分支
        # 注意：你需要确保引入了 resolve_reasoning_content 和 LangGraphEventTypes
        event_type = event.get("event")
        chunk = event.get("data", {}).get("chunk")

        reasoning_data = None
        if event_type == ag_ui_langgraph.LangGraphEventTypes.OnChatModelStream and chunk:
            reasoning_data = ding_resolve_reasoning_content(chunk)

        if reasoning_data:
            for evt in self.handle_thinking_event(reasoning_data):
                yield evt

            return

        async for evt in super()._handle_single_event(event, state):
            yield evt
