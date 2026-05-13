import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from dingent.engine.agents.simple_agent import DingMiddleware, _transform_rows_to_a2ui


def test_transform_rows_to_a2ui():
    columns = ["id", "name", "active", "score"]
    rows = [[1, "Alice", True, 95.5], [2, "Bob", False, 88.0]]

    result = _transform_rows_to_a2ui(columns, rows)

    # Check length
    assert len(result) == 2

    # Check Row 1
    row1 = result[0]
    assert row1["key"] == "0"
    fields1 = row1["valueMap"]
    assert len(fields1) == 4

    assert fields1[0] == {"key": "id", "valueNumber": 1}
    assert fields1[1] == {"key": "name", "valueString": "Alice"}
    assert fields1[2] == {"key": "active", "valueBoolean": True}
    assert fields1[3] == {"key": "score", "valueNumber": 95.5}

    # Check Row 2
    row2 = result[1]
    assert row2["key"] == "1"
    fields2 = row2["valueMap"]
    assert len(fields2) == 4
    assert fields2[0] == {"key": "id", "valueNumber": 2}
    assert fields2[1] == {"key": "name", "valueString": "Bob"}
    assert fields2[2] == {"key": "active", "valueBoolean": False}
    assert fields2[3] == {"key": "score", "valueNumber": 88.0}


@pytest.mark.asyncio
async def test_ding_middleware_awrap_tool_call_with_tool_message():
    middleware = DingMiddleware()

    # Mock request
    class MockTool:
        name = "test_tool"

    class MockRequest:
        tool_call = {"id": "call_123", "args": {}}
        tool = MockTool()
        state = {"messages": []}

    request = MockRequest()

    # Mock handler that returns a ToolMessage with an artifact
    async def mock_handler(req):  # noqa: ARG001
        return ToolMessage(
            content="Tool executed", tool_call_id="call_123", artifact={"structured_content": {"display": [{"type": "table", "rows": []}], "model_text": "Here is the table"}}
        )

    result = await middleware.awrap_tool_call(request, mock_handler)

    assert isinstance(result, Command)
    assert "messages" in result.update
    messages = result.update["messages"]

    assert len(messages) >= 1
    # First message should be ToolMessage with modified content
    assert isinstance(messages[0], ToolMessage)
    assert messages[0].content == "Here is the table"
    assert messages[0].tool_call_id == "call_123"


@pytest.mark.asyncio
async def test_ding_middleware_awrap_tool_call_with_command():
    middleware = DingMiddleware()

    class MockTool:
        name = "test_tool"

    class MockRequest:
        tool_call = {"id": "call_123"}
        tool = MockTool()
        state = {"messages": ["history_1", "history_2"]}

    request = MockRequest()

    async def mock_handler(req):  # noqa: ARG001
        return Command(graph="some_graph", update={"messages": ["new_message"]})

    result = await middleware.awrap_tool_call(request, mock_handler)

    assert isinstance(result, Command)
    assert "messages" in result.update
    messages = result.update["messages"]

    # It should NOT append the new message to the history messages, returning only the update
    assert len(messages) == 1
    assert messages == ["new_message"]

    # And it should not mutate the original state list
    assert request.state["messages"] == ["history_1", "history_2"]
