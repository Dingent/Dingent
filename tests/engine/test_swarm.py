import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from dingent.engine.factories.swarm import create_assistant_graphs
from dingent.core.workflows.schemas import ExecutableWorkflow


from langchain_core.tools import tool


@tool
def dummy_tool() -> str:
    """A dummy tool."""
    return "dummy"


@pytest.mark.asyncio
async def test_create_assistant_graphs():
    # 1. Setup mocks
    # Mock LLM resolver
    llm_instance = MagicMock()
    llm_instance.name = "mock_llm"

    def llm_resolver(assistant_id):
        return llm_instance

    # Mock Log Method
    log_calls = []

    def mock_log(*args, **kwargs):
        log_calls.append((args, kwargs))

    # Mock Assistant Factory
    mock_factory = AsyncMock()
    mock_runtime = AsyncMock()

    class MockToolWrapper:
        def __init__(self):
            self.tool = dummy_tool

        async def run(self, kwargs):
            return "run"

    mock_tool = MockToolWrapper()

    # Setting up the async context manager for load_tools
    class MockToolContextManager:
        async def __aenter__(self):
            return [mock_tool]

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_runtime.load_tools = MagicMock(return_value=MockToolContextManager())
    mock_factory.create_runtime.return_value = mock_runtime

    # 2. Setup Workflow
    # A workflow with two assistants
    assistant1_id = uuid4()
    assistant2_id = uuid4()

    # Using MagicMock to mock the Pydantic model structure to avoid validation errors
    # if the schemas are complex
    assistant_config1 = MagicMock()
    assistant_config1.instructions = "You are A"
    assistant_config1.plugins = []

    assistant_config2 = MagicMock()
    assistant_config2.instructions = "You are B"
    assistant_config2.plugins = []

    workflow = MagicMock()
    workflow.assistant_configs = {"AgentA": assistant_config1, "AgentB": assistant_config2}
    workflow.adjacency_map = {"AgentA": ["AgentB"], "AgentB": []}

    assistant_id_map = {"AgentA": assistant1_id, "AgentB": assistant2_id}

    # 3. Call the function
    async with create_assistant_graphs(
        assistant_factory=mock_factory, workflow=workflow, llm_or_resolver=llm_resolver, log_method=mock_log, assistant_id_map=assistant_id_map
    ) as graphs:
        # 4. Asserts
        assert "AgentA" in graphs
        assert "AgentB" in graphs

        agent_a = graphs["AgentA"]
        agent_b = graphs["AgentB"]

        assert agent_a.name == "AgentA"
        assert agent_b.name == "AgentB"

        # Verify that tools were fetched correctly
        mock_factory.create_runtime.assert_any_call(assistant_config1)
        mock_factory.create_runtime.assert_any_call(assistant_config2)

        # Verify load_tools was called
        assert mock_runtime.load_tools.call_count == 2
