import json
from typing import Annotated, Any, Awaitable, Sequence, cast, override
from langchain.agents import AgentState, create_agent


from langchain.agents.middleware.todo import WRITE_TODOS_SYSTEM_PROMPT, WRITE_TODOS_TOOL_DESCRIPTION, Todo
from langchain.agents.middleware.types import ModelCallResult, ToolCallRequest
from langchain.tools import BaseTool, InjectedToolCallId, tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph.state import CompiledStateGraph, RunnableConfig
from langgraph.types import Checkpointer, Command

from .messages import ActivityMessage
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse, TodoListMiddleware
from langchain.agents import create_agent
from typing import Any, Callable


def mcp_artifact_to_agui_display(tool_name, query_args: dict, surface_base_id: str | list[str], artifact: list[dict[str, Any]], update_data=False) -> dict[str, list[dict]]:
    if not isinstance(artifact, list):
        return [artifact]
    else:
        return cast(Any, artifact)
    agui_display = {"operations": []}

    if isinstance(surface_base_id, list):
        assert len(surface_base_id) == len(artifact), "Surface base ID and artifact length mismatch"

    for i, item in enumerate(artifact):
        # 1. 基础渲染信号
        surface_id = f"{surface_base_id}-{i}" if isinstance(surface_base_id, str) else surface_base_id[i]

        type_ = item.get("type")
        if update_data:
            columns = item.get("columns", [])  # 预期格式: [{"key": "id", "label": "ID"}, ...]
            rows = item.get("rows", [])
            title = item.get("title", "Table Data")
            a2ui_rows = _transform_rows_to_a2ui(columns, rows)
            agui_display["operations"].append(
                {
                    "dataModelUpdate": {
                        "surfaceId": surface_id,
                        "contents": [
                            {"key": "rows", "valueMap": a2ui_rows},
                            # 初始化分页状态
                            {"key": "pageInfo", "valueString": "Page 1"},
                            {"key": "isFirstPage", "valueBoolean": True},
                            {"key": "isLastPage", "valueBoolean": False},
                        ],
                    }
                }
            )
            break

        # === 处理文本类型 ===
        if type_ == "text":
            raise NotImplementedError("Text type rendering not implemented in this snippet.")

        # === 处理表格类型 ===
        elif type_ == "table":
            columns = item.get("columns", [])  # 预期格式: [{"key": "id", "label": "ID"}, ...]
            rows = item.get("rows", [])
            title = item.get("title", "Table Data")

            # --- A. 动态构建组件列表 ---
            components = []

            # 1. Root Container (包含标题、表头、列表、分页)
            components.append(
                {
                    "id": "root",
                    "component": {
                        "Column": {"children": {"explicitList": ["tableTitle", "tableHeader", "tableBody", "paginationRow"]}, "alignment": "stretch", "distribution": "start"}
                    },
                }
            )

            # 2. Table Title
            components.append({"id": "tableTitle", "component": {"Text": {"text": {"literalString": title}, "usageHint": "h3"}}})

            # 3. 动态表头 (Header Row)
            header_child_ids = []
            for col in columns:
                col_id = f"header_{col}"
                header_child_ids.append(col_id)
                components.append(
                    {
                        "id": col_id,
                        "component": {
                            "Text": {
                                "text": {"literalString": col},
                                "usageHint": "caption",
                                "weight": 1,  # 均匀分布
                            }
                        },
                    }
                )

            components.append({"id": "tableHeader", "component": {"Row": {"children": {"explicitList": header_child_ids}, "distribution": "spaceBetween", "alignment": "center"}}})

            # 4. 动态行模板 (Row Template)
            # 这里是关键：template 中的组件绑定相对路径
            row_child_ids = []
            for col in columns:
                cell_id = f"cell_{col}"
                row_child_ids.append(cell_id)
                components.append(
                    {
                        "id": cell_id,
                        "component": {
                            "Text": {
                                # 动态绑定：如果列key是 "email"，路径就是 "/email"
                                "text": {"path": f"/{col}"},
                                "weight": 1,
                            }
                        },
                    }
                )

            components.append({"id": "rowTemplate", "component": {"Row": {"children": {"explicitList": row_child_ids}, "distribution": "spaceBetween", "alignment": "center"}}})

            # 5. 列表容器 (The List)
            components.append(
                {
                    "id": "tableBody",
                    "component": {
                        "List": {
                            "children": {
                                "template": {
                                    "componentId": "rowTemplate",
                                    "dataBinding": "/rows",  # 绑定到数据模型的 /rows 数组
                                }
                            },
                            "direction": "vertical",
                        }
                    },
                }
            )

            # 6. 分页控件
            page_number = int(query_args.get("page", 1))
            components.extend(
                [
                    {
                        "id": "paginationRow",
                        "component": {"Row": {"children": {"explicitList": ["prevBtn", "pageInfo", "nextBtn"]}, "distribution": "center", "alignment": "center"}},
                    },
                    {
                        "id": "prevBtn",
                        "component": {
                            "Button": {
                                "child": "prevBtnText",
                                "action": {
                                    "name": tool_name,
                                    "context": [
                                        {
                                            "key": "query_args",
                                            "value": {"literalString": json.dumps({**query_args, "page": page_number})},
                                        }
                                    ],
                                },
                                "disabled": {"path": "/isFirstPage"},
                            }
                        },
                    },
                    {"id": "prevBtnText", "component": {"Text": {"text": {"literalString": "Previous"}}}},
                    {"id": "pageInfo", "component": {"Text": {"text": {"path": "/pageInfo"}, "usageHint": "caption"}}},
                    {
                        "id": "nextBtn",
                        "component": {
                            "Button": {
                                "child": "nextBtnText",
                                "action": {
                                    "name": tool_name,
                                    "context": [
                                        {
                                            "key": "query_args",
                                            "value": {"literalString": json.dumps({**query_args, "page": page_number + 2})},
                                        }
                                    ],
                                },
                                "disabled": {"path": "/isLastPage"},
                            }
                        },
                    },
                    {"id": "nextBtnText", "component": {"Text": {"text": {"literalString": "Next"}}}},
                ]
            )

            # 添加 SurfaceUpdate 消息
            agui_display["operations"].append({"surfaceUpdate": {"surfaceId": surface_id, "components": components}})

            # --- B. 数据模型转换 ---
            # 将 Python 字典列表转换为 A2UI 的 adjacency list 格式
            a2ui_rows = _transform_rows_to_a2ui(columns, rows)

            # 添加 DataModelUpdate 消息
            agui_display["operations"].append(
                {
                    "dataModelUpdate": {
                        "surfaceId": surface_id,
                        "contents": [
                            {"key": "rows", "valueMap": a2ui_rows},
                            # 初始化分页状态
                            {"key": "pageInfo", "valueString": "Page 1"},
                            {"key": "isFirstPage", "valueBoolean": True},
                            {"key": "isLastPage", "valueBoolean": False},
                        ],
                    }
                }
            )
        if not update_data:
            agui_display["operations"].append({"beginRendering": {"surfaceId": surface_id, "root": "root", "styles": {"primaryColor": "#1976D2", "font": "Roboto"}}})

    return agui_display


def _transform_rows_to_a2ui(columns: list[str], rows: list[list[str | int | Any]]) -> list[dict]:
    """
    辅助函数：将 [{'id': 1, 'name': 'A'}] 转换为 A2UI 的 valueMap 结构
    A2UI 数组本质上是一个 Map，Key 是索引字符串 "0", "1", ...
    """
    a2ui_list = []
    for idx, row_data in enumerate(rows):
        # 构建每一行的数据对象
        row_fields = []
        for k, v in zip(columns, row_data, strict=False):
            entry: dict[str, Any] = {"key": k}
            # 根据类型填充 valueString, valueNumber 等
            if isinstance(v, bool):
                entry["valueBoolean"] = v
            elif isinstance(v, int | float):
                entry["valueNumber"] = v
            else:
                entry["valueString"] = str(v)
            row_fields.append(entry)

        # 将行数据放入列表，Key 是索引
        a2ui_list.append({"key": str(idx), "valueMap": row_fields})
    return a2ui_list


class DingMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        all_messages = request.messages
        filtered_messages: list[AnyMessage] = [msg for msg in all_messages if isinstance(msg, (SystemMessage, HumanMessage, AIMessage, ToolMessage))]
        request = request.override(messages=filtered_messages)
        result = await handler(request)

        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tool_call = request.tool_call
        tool_call_id = tool_call.get("id") or "unknown_tool_call_id"
        tool_name = request.tool.name

        try:
            result = await handler(request)

            # --- 分支 A: 处理 ToolMessage ---
            if isinstance(result, ToolMessage):
                content = result.content
                artifact = None
                data = {}
                if result.artifact:
                    structured_content = result.artifact["structured_content"]
                    if isinstance(structured_content, dict):
                        data = structured_content
                    elif isinstance(structured_content, str) and structured_content.strip():
                        try:
                            data = json.loads(structured_content)
                        except json.JSONDecodeError:
                            pass  # 保持默认的 model_text

                if isinstance(data, dict) and "display" in data:
                    artifact = cast(dict[str, list[dict]], data.get("display"))
                    model_text = data.get("model_text", content)
                else:
                    model_text = content

                # 构建消息列表
                collected_messages: list = [ToolMessage(content=model_text, tool_call_id=tool_call_id, artifact=artifact)]

                # 如果有 artifact，生成 ActivityMessage
                if artifact:
                    agui_display = mcp_artifact_to_agui_display(
                        tool_name=tool_name,
                        query_args=tool_call.get("args", {}),
                        surface_base_id=tool_call_id,
                        artifact=artifact,
                    )
                    collected_messages.append(ActivityMessage(content=agui_display))

                return Command(update={"messages": collected_messages})

            # --- 分支 B: 处理 Command ---
            elif isinstance(result, Command):
                # 如果是 Graph 更新，不需要追加全部历史消息，LangGraph 的 add_messages reducer 会自动处理追加。
                # 之前在这里直接使用 append 会导致 state 原地突变并在多轮对话中引起无限复制消息的问题。
                return result

            else:
                raise ValueError(f"Unsupported result type: {type(result)}")

        except Exception as e:
            raise e
            return Command(update={"messages": [ToolMessage(content=f"Execution Error: {str(e)}", tool_call_id=tool_call_id, is_error=True)]})


class JsonTodoListMiddleware(TodoListMiddleware):
    """
    A subclass of TodoListMiddleware that ensures the `write_todos` tool
    returns a valid JSON string result, fixing frontend parsing issues.
    """

    def __init__(
        self,
        *,
        system_prompt: str = WRITE_TODOS_SYSTEM_PROMPT,
        tool_description: str = WRITE_TODOS_TOOL_DESCRIPTION,
    ) -> None:
        # 初始化父类
        super().__init__(system_prompt=system_prompt, tool_description=tool_description)

        # 重新定义 write_todos 工具，覆盖父类的实现
        @tool(description=self.tool_description)
        def write_todos(todos: list[Todo], tool_call_id: Annotated[str, InjectedToolCallId]) -> Command[Any]:
            """Create and manage a structured task list for your current work session."""

            return Command(
                update={
                    "todos": todos,
                    "messages": [
                        ToolMessage(
                            f"Updated todo list to {todos}",
                            tool_call_id=tool_call_id,
                            name="write_todos",
                        )
                    ],
                }
            )

        # 将覆盖后的工具赋值给 self.tools
        self.tools = [write_todos]


middleware = [DingMiddleware(), JsonTodoListMiddleware()]


def build_simple_react_agent(
    name: str,
    llm: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str | None = None,
    max_iterations: int = 6,
) -> CompiledStateGraph:
    # 使用 create_react_agent 并传入 middleware
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware,
        debug=True,
    )
    agent.name = name
    return agent
