from collections.abc import Callable
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
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
        return Command(
            goto=agent_name,
            graph=Command.PARENT,
            update={
                "messages": [
                    *messages,
                    ToolMessage(content=f"Transferred to {agent_name}", tool_call_id=tool_call_id, name=tool_name),
                ],
                "active_agent": agent_name,
            },
        )

    return handoff_tool
