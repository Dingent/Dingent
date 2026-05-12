from collections.abc import Callable
from typing import Annotated, Any, cast

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command


# --- Handoff Tool ---
def create_handoff_tool(agent_name: str, description: str | None, log_method: Callable):
    tool_name = f"transfer_to_{agent_name}"
    tool_description = (
        f"Ask agent '{agent_name}' for help. "
        f"Use this tool ONLY when the user's request is about {description}. "
        f"This agent is a specialist in that domain. "
        "Provide a clear instruction for what this agent needs to do."
    )

    @tool(tool_name, description=tool_description)
    async def handoff_tool(state: Annotated[Any, InjectedState], tool_call_id: Annotated[str, InjectedToolCallId]):
        log_method("info", f"Handoff to {agent_name}", context={"id": tool_call_id})
        messages = list(state["messages"])
        pending_tool_messages = _build_pending_tool_messages(messages, tool_call_id, agent_name)
        return Command(
            goto=agent_name,
            graph=Command.PARENT,
            update={
                "messages": [
                    *messages,
                    *pending_tool_messages,
                    ToolMessage(content=f"Transferred to {agent_name}", tool_call_id=tool_call_id, name=tool_name),
                ],
                "active_agent": agent_name,
            },
        )

    return handoff_tool


def _build_pending_tool_messages(messages: list[BaseMessage], handoff_tool_call_id: str, agent_name: str) -> list[ToolMessage]:
    last_ai_index = next((index for index in range(len(messages) - 1, -1, -1) if isinstance(messages[index], AIMessage)), None)
    if last_ai_index is None:
        return []

    last_ai_message = cast(AIMessage, messages[last_ai_index])
    existing_tool_call_ids = {message.tool_call_id for message in messages[last_ai_index + 1 :] if isinstance(message, ToolMessage)}
    pending_tool_messages = []

    for tool_call in last_ai_message.tool_calls:
        sibling_tool_call_id = tool_call.get("id")
        if not sibling_tool_call_id or sibling_tool_call_id == handoff_tool_call_id or sibling_tool_call_id in existing_tool_call_ids:
            continue

        tool_name = tool_call.get("name") or "tool"
        pending_tool_messages.append(
            ToolMessage(
                content=f"Tool call '{tool_name}' result is unavailable after handoff to {agent_name}.",
                tool_call_id=sibling_tool_call_id,
                name=tool_name,
            )
        )

    return pending_tool_messages
