import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, cast

from copilotkit import a2ui
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse, TodoListMiddleware
from langchain.agents.middleware.todo import WRITE_TODOS_SYSTEM_PROMPT, WRITE_TODOS_TOOL_DESCRIPTION, Todo
from langchain.agents.middleware.types import ModelCallResult, ToolCallRequest
from langchain.tools import BaseTool, InjectedToolCallId, tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from .messages import ActivityMessage


def mcp_artifact_to_agui_display(
    tool_name: str, query_args: dict[str, Any], surface_base_id: str | list[str], artifact: list[dict[str, Any]], update_data: bool = False
) -> list[dict[str, Any]]:
    if not isinstance(artifact, list):
        return [artifact]
    agui_display: dict[str, Any] = {"a2ui_operations": [], "surfaceId": None}

    if isinstance(surface_base_id, list):
        if len(surface_base_id) != len(artifact):
            raise ValueError("Surface base ID and artifact length mismatch")

    for i, item in enumerate(artifact):
        surface_id = f"{surface_base_id}-{i}" if isinstance(surface_base_id, str) else surface_base_id[i]
        agui_display["surfaceId"] = surface_id

        type_ = item.get("type")
        if update_data:
            operations = [a2ui.update_data_model(surface_id, _build_table_data(item, query_args))]
            agui_display["a2ui_operations"].extend(json.loads(a2ui.render(operations))["a2ui_operations"])
            break

        if type_ == "text":
            title = str(item.get("title") or "Result")
            content = str(item.get("content") or "")
            components = [
                {"id": "root", "component": "Column", "children": ["title", "content"], "align": "stretch", "justify": "start"},
                {"id": "title", "component": "Text", "text": title, "variant": "h3"},
                {"id": "content", "component": "Text", "text": content},
            ]
            data: dict[str, Any] = {"title": title, "content": content}

        elif type_ == "table":
            components = _build_table_components(tool_name, query_args, item)
            data = _build_table_data(item, query_args)
        else:
            continue

        operations = [a2ui.create_surface(surface_id), a2ui.update_components(surface_id, components), a2ui.update_data_model(surface_id, data)]
        agui_display["a2ui_operations"].extend(json.loads(a2ui.render(operations))["a2ui_operations"])

    return [agui_display]


def _build_table_components(tool_name: str, query_args: dict[str, Any], item: dict[str, Any]) -> list[dict[str, Any]]:
    columns = [str(column) for column in item.get("columns", [])]
    rows = _table_rows_to_records(columns, item.get("rows", []))
    title = str(item.get("title") or "Table Data")
    page_number = int(query_args.get("page", 1))

    components: list[dict[str, Any]] = [
        {"id": "root", "component": "Column", "children": ["tableTitle", "tableHeader", *[f"row_{idx}" for idx in range(len(rows))], "paginationRow"], "align": "stretch"},
        {"id": "tableTitle", "component": "Text", "text": title, "variant": "h3"},
        {"id": "tableHeader", "component": "Row", "children": [f"header_{idx}" for idx in range(len(columns))], "justify": "spaceBetween", "align": "center"},
        {"id": "paginationRow", "component": "Row", "children": ["prevBtn", "pageInfo", "nextBtn"], "justify": "center", "align": "center"},
        {"id": "prevBtn", "component": "Button", "child": "prevBtnText", "action": {"event": {"name": tool_name, "context": {"query_args": {**query_args, "page": page_number}}}}},
        {"id": "prevBtnText", "component": "Text", "text": "Previous"},
        {"id": "pageInfo", "component": "Text", "text": f"Page {page_number}", "variant": "caption"},
        {
            "id": "nextBtn",
            "component": "Button",
            "child": "nextBtnText",
            "action": {"event": {"name": tool_name, "context": {"query_args": {**query_args, "page": page_number + 2}}}},
        },
        {"id": "nextBtnText", "component": "Text", "text": "Next"},
    ]

    for idx, column in enumerate(columns):
        components.append({"id": f"header_{idx}", "component": "Text", "text": column, "variant": "caption"})

    for row_idx, row in enumerate(rows):
        row_child_ids = []
        for col_idx, column in enumerate(columns):
            cell_id = f"row_{row_idx}_cell_{col_idx}"
            row_child_ids.append(cell_id)
            components.append({"id": cell_id, "component": "Text", "text": str(row.get(column, ""))})
        components.append({"id": f"row_{row_idx}", "component": "Row", "children": row_child_ids, "justify": "spaceBetween", "align": "center"})

    return components


def _build_table_data(item: dict[str, Any], query_args: dict[str, Any]) -> dict[str, Any]:
    columns = [str(column) for column in item.get("columns", [])]
    page_number = int(query_args.get("page", 1))
    return {
        "title": str(item.get("title") or "Table Data"),
        "columns": columns,
        "rows": _table_rows_to_records(columns, item.get("rows", [])),
        "pageInfo": f"Page {page_number}",
        "isFirstPage": page_number <= 1,
        "isLastPage": False,
    }


def _table_rows_to_records(columns: list[str], rows: list[list[str | int | Any]]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row_data, strict=False)) for row_data in rows]


class DingMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        all_messages = request.messages
        filtered_messages: list[AnyMessage] = [msg for msg in all_messages if isinstance(msg, SystemMessage | HumanMessage | AIMessage | ToolMessage)]
        model_settings = {**request.model_settings, "parallel_tool_calls": False}
        request = request.override(messages=filtered_messages, model_settings=model_settings)
        result = await handler(request)

        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tool_call = request.tool_call
        tool_call_id = tool_call.get("id") or "unknown_tool_call_id"
        tool_name = request.tool.name if request.tool else "tool"

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
                    artifact = cast(list[dict[str, Any]], data.get("display"))
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
    debug: bool = False,
) -> CompiledStateGraph:
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware,
        debug=debug,
    )
    agent.name = name
    return agent
