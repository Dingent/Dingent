import json
from typing import Any, List, Union


# 引入真实的 litellm 函数，重命名以避免混淆
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.language_models.fake_chat_models import FakeChatModel
from litellm import completion as actual_completion
from litellm import acompletion as actual_acompletion

fake_llm = FakeMessagesListChatModel(responses=[])

import json
from typing import List, Union
from langchain_core.messages import AIMessage, BaseMessage, ToolCall
from langchain_core.language_models import FakeMessagesListChatModel


class FakeChatModelWithTools(FakeMessagesListChatModel):
    """
    扩展标准的 FakeMessagesListChatModel，使其支持 bind_tools。
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeChatModelWithTools":
        return self


def create_replay_llm(json_path: str) -> FakeChatModelWithTools:
    responses: List[BaseMessage] = []

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Warning: Trace file {json_path} not found.")
        return FakeChatModelWithTools(responses=[AIMessage(content="Error: No trace file")])

    for msg in data.get("messages", []):
        if msg.get("role") == "assistant":
            content = msg.get("content") or ""  # 防止 content 为 None
            tool_calls_raw = msg.get("tool_calls", [])

            # 将原始 JSON 中的 tool_calls 转换为 LangChain 格式
            tool_calls: list[ToolCall] = []
            for tc in tool_calls_raw:
                function_body = tc.get("function", {})
                args_str = function_body.get("arguments", "{}")

                # 容错处理：args 可能是字符串也可能是已经解析的字典
                if isinstance(args_str, str):
                    try:
                        args = json.loads(args_str)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = args_str

                tool_calls.append(
                    {
                        "name": function_body.get("name"),
                        "args": args,
                        "id": tc.get("id"),
                        "type": "tool_call",  # LangChain 标准字段
                    }
                )

            # 只有当有内容或有工具调用时才添加消息
            if content or tool_calls:
                responses.append(AIMessage(content=content, tool_calls=tool_calls))

    # 兜底：如果列表为空，添加一条停止消息
    if not responses:
        responses.append(AIMessage(content="STOP_REPLAY (No data loaded)"))

    return FakeChatModelWithTools(responses=responses)
