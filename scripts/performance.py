from contextlib import asynccontextmanager
import statistics

from langchain_core.tools import StructuredTool
import pytest
from sqlmodel.sql.expression import Select
import uuid
from unittest.mock import patch

from sqlmodel import Session
from fastapi.testclient import TestClient

from dingent.core.db.models import Conversation, Workflow, Workspace
from dingent.core.plugins.schemas import RunnableTool
from tests.setup_data import mock_full_single_cell_data
from tests.utils import create_replay_llm


class PerformanceMetrics:
    def __init__(self):
        self.latencies = []
        self.token_counts = []  # 如果Mock数据里包含token usage

    def record(self, duration_ms):
        self.latencies.append(duration_ms)

    def report(self):
        return {
            "avg_latency_ms": statistics.mean(self.latencies),
            "p95_latency_ms": statistics.quantiles(self.latencies, n=20)[18] if len(self.latencies) >= 20 else max(self.latencies),
            "min_latency_ms": min(self.latencies),
            "max_latency_ms": max(self.latencies),
        }


metrics = PerformanceMetrics()


# 1. 定义一个不需要 MCP 协议的"假工具"
def dummy_function(data: str):
    """A dummy tool that does nothing but return text."""
    return f"Processed: {data}"


# 将其转换为 LangChain Tool 对象


async def mock_run_tool(arguments, meta=None, **kwargs):
    return f"Mock Result for {arguments}"


# 3. 编写 Patch 逻辑
@pytest.fixture
def mock_assistant_tools():
    """
    劫持 AssistantRuntime.load_tools。
    使其不进行任何网络/IPC连接，直接返回准备好的内存工具。
    """

    tools_list = [
        "load_demo_dataset",
        "quality_control_analysis",
        "run_clustering_and_umap",
        "run_paga_trajectory",
        "find_marker_genes",
        "generate_markdown_report",
    ]
    mock_runnables = []
    for tool_name in tools_list:
        tool = StructuredTool.from_function(dummy_function, name=tool_name)
        mock_runnable = RunnableTool(
            tool=tool,
            plugin_id="mock-plugin-id",
            run=mock_run_tool,
        )
        mock_runnables.append(mock_runnable)

    # 模拟 asynccontextmanager 的行为
    @asynccontextmanager
    async def _mock_load_tools(self):
        # yield 一个列表，就像真正的 load_tools 一样
        yield mock_runnables

    # 应用 Patch
    # target 需要指向你 AssistantRuntime 类所在的具体路径
    target = "dingent.core.assistants.assistant.AssistantRuntime.load_tools"

    with patch(target, side_effect=_mock_load_tools, autospec=True) as mock:
        yield mock


def test_performance_batch(
    benchmark,
    client: TestClient,
    session: Session,
    create_workspace,
    mock_assistant_tools,
):
    """
    测试 /chat/agent/{id}/run 接口，使用回放数据模拟 LLM 返回
    """

    # ---------------------------------------------------------
    # 1. 准备数据库数据 (必不可少，否则接口报 404/403)
    # ---------------------------------------------------------

    ws: Workspace = create_workspace()
    data = mock_full_single_cell_data(ws.id, session)
    # wf: Workflow = data["workflow"]
    wf = session.get(Workflow, data["workflow"].id)

    assert wf and wf.name == "single-cell"

    # ---------------------------------------------------------
    # 2. 准备 Mock LLM
    # ---------------------------------------------------------
    # 加载我们之前导出的 MLflow 数据
    import os

    data_path = os.path.join(os.path.dirname(__file__), "data/trace.json")
    mock_llm_instance = create_replay_llm(data_path)

    # ---------------------------------------------------------
    # 3. 构造请求参数
    # ---------------------------------------------------------

    headers = {
        "X-Visitor-ID": "test-visitor-001",
    }

    def run_request():
        thread_id = str(uuid.uuid4())
        input_payload = {
            "threadId": thread_id,
            "runId": "f26e1be5-1ce9-423b-9d2d-652c472369ff",
            "tools": [],
            "context": [],
            "forwardedProps": {
                "authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0QHRlc3QuY29tIiwiZXhwIjoxNzcwODIwNTE0fQ.TyN5PNsVyfSlQYcs9Z1-Mloqdm99b4Cldp2Wl6UldCY",
                "workspace_slug": "Test Workspace",
                "is_guest": False,
            },
            "state": {},
            "messages": [
                {
                    "id": "522fa5a4-1586-4965-8447-dfb319ca527e",
                    "role": "user",
                    "content": "加载 paul15 造血干细胞数据集。除了基础的聚类外，我特别想看细胞的分化轨迹。请运行 PAGA 分析，并在报告中展示细胞是如何从干细胞分化成不同祖细胞的。",
                }
            ],
        }
        return client.post(f"/api/v1/{ws.slug}/chat/agent/{wf.name}/run", json=input_payload, headers=headers)

    # ---------------------------------------------------------
    # 4. 执行测试：Patch + Client.post
    # ---------------------------------------------------------

    # 拦截 litellm.completion，让它吐出 Mock 数据
    os.environ["OPENAI_API_KEY"] = "MOCK_KEY"
    target_path = "dingent.core.llms.service.get_llm_for_context"
    with patch(target_path) as mock_get_llm:
        mock_get_llm.return_value = mock_llm_instance
        response = benchmark(run_request)

        # A. 验证 HTTP 状态码
        assert response.status_code == 200, f"Error: {response.text}"

        # B. 验证流式输出
        # 因为是 StreamingResponse，我们需要读取内容
        content = response.content.decode("utf-8")
        assert len(content) > 0

        # 验证返回的内容里确实包含了我们的 Mock 数据
        # 假设 Mock 数据里有一句 "Senior Computational Biologist"
        assert "Senior Computational Biologist" in content

        # C. 验证数据库副作用 (Conversation 是否被更新)
        session.expire_all()  # 强制从数据库重读
        saved_conversation = session.exec(Select(Conversation)).first()

        assert saved_conversation is not None
