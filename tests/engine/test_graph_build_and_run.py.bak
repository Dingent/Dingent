import pytest
from langchain_core.messages import HumanMessage

from dingent.engine import graph
from tests.engine.dummy_env import (
    DummyConfig,
    DummyConfigManager,
    DummyLLMConfig,
    DummyLLMManager,
    DummyNode,
    DummyNodeData,
    DummyWorkflow,
    DummyWorkflowManager,
    build_dummy_assistants,
)


@pytest.fixture(scope="session")
def anyio_backend():
    # 允许 pytest-asyncio / anyio 协同
    return "asyncio"


@pytest.fixture(autouse=True)
def dummy_environment(monkeypatch):
    # 构建一个包含两个节点（起始节点指向 WeatherAgent）
    workflow = DummyWorkflow(
        id="wf_1",
        nodes=[
            DummyNode(DummyNodeData(assistantName="WeatherAgent", isStart=True)),
            DummyNode(DummyNodeData(assistantName="TimeAgent", isStart=False)),
        ],
    )
    config = DummyConfig(llm=DummyLLMConfig())
    assistants = build_dummy_assistants()

    # 准备假 manager
    fake_llm_manager = DummyLLMManager()
    fake_config_manager = DummyConfigManager(workflow=workflow, config=config)
    fake_workflow_manager = DummyWorkflowManager(assistants=assistants)

    # monkeypatch 原模块中的 manager 对象的方法
    monkeypatch.setattr(graph, "llm_manager", fake_llm_manager)
    monkeypatch.setattr(graph, "config_manager", fake_config_manager)
    monkeypatch.setattr(graph, "workflow_manager", fake_workflow_manager)

    return {
        "workflow": workflow,
        "assistants": assistants,
        "config": config,
    }


@pytest.mark.anyio
async def test_make_graph_build_and_run():
    async with graph.make_graph() as compiled:
        init_state = {
            "messages": [HumanMessage(content="查询北京的天气，然后查询当前的时间，一次可以调用多个工具")],
        }
        result_state = await compiled.ainvoke(init_state)
        assert result_state
