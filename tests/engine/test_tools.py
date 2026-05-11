import pytest
from dingent.engine.agents.tools import create_handoff_tool
from langgraph.types import Command
from langchain_core.messages import ToolMessage
import asyncio


@pytest.mark.asyncio
async def test_create_handoff_tool():
    log_calls = []

    def mock_log_method(level, message, context=None):
        log_calls.append({"level": level, "message": message, "context": context})

    # Create the tool
    tool = create_handoff_tool(agent_name="database_expert", description="SQL queries and database administration", log_method=mock_log_method)

    # Assert tool metadata
    assert tool.name == "transfer_to_database_expert"
    assert "database_expert" in tool.description
    assert "SQL queries and database administration" in tool.description

    # Execute the tool
    result = await tool.ainvoke({"name": "transfer_to_database_expert", "args": {}, "id": "test_call_123", "type": "tool_call"})

    # Assert result is a Command
    assert isinstance(result, Command)
    assert result.goto == "database_expert"
    assert result.graph == Command.PARENT

    # Assert messages update
    assert result.update is not None
    assert "messages" in result.update
    messages = result.update["messages"]
    assert len(messages) == 1

    msg = messages[0]
    assert isinstance(msg, ToolMessage)
    assert msg.content == "Transferred to database_expert"
    assert msg.tool_call_id == "test_call_123"
    assert msg.name == "transfer_to_database_expert"

    # Assert log_method was called correctly
    assert len(log_calls) == 1
    assert log_calls[0]["level"] == "info"
    assert log_calls[0]["message"] == "Handoff to database_expert"
    assert log_calls[0]["context"] == {"id": "test_call_123"}
