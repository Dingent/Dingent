import shutil
import os
import sys
import tempfile
import uvicorn

current_dir = os.path.dirname(os.path.abspath(__file__))

project_root = os.path.dirname(current_dir)

if project_root not in sys.path:
    sys.path.insert(0, project_root)

import uuid
from unittest.mock import patch
from contextlib import asynccontextmanager, ExitStack, contextmanager

from dingent.core.plugins.schemas import RunnableTool
from langchain_core.tools import StructuredTool

from tests.utils import create_replay_llm


# ==========================================
# 1. 定义 Mock 逻辑 (保持不变)
# ==========================================
def dummy_function(data: str):
    "Fake tool function that simulates processing and returns a predictable result."
    return f"Processed: {data}"


async def mock_run_tool(arguments, meta=None, **kwargs):
    return f"Mock Result for {arguments}"


@contextmanager
def setup_temp_home():
    """
    创建一个临时目录作为 DINGENT_HOME，并重置 paths 配置。
    这等同于你 pytest 中的 mock_app_paths fixture。
    """
    # 1. 创建临时目录
    # prefix 可以方便你在 /tmp 中找到它（如果程序崩了没清理的话）
    test_home = tempfile.mkdtemp(prefix="dingent_load_test_")
    print(f"\n[Environment] Created temp DINGENT_HOME: {test_home}")

    # 2. 设置环境变量
    os.environ["DINGENT_HOME"] = test_home
    from dingent.core.paths import paths

    paths.__init__()

    # 验证是否生效
    if str(paths.data_root) != str(test_home):
        print(f"⚠️ Warning: paths.data_root ({paths.data_root}) != test_home ({test_home})")
    else:
        print(f"[Environment] paths re-initialized successfully.")

    try:
        yield test_home
    finally:
        # 4. 清理工作
        print(f"[Environment] Cleaning up {test_home}...")
        try:
            shutil.rmtree(test_home)
        except Exception as e:
            print(f"Error cleaning up temp dir: {e}")

        if "DINGENT_HOME" in os.environ:
            del os.environ["DINGENT_HOME"]


@asynccontextmanager
async def _mock_load_tools(self):
    tools_list = [
        "load_demo_dataset",
        "quality_control_analysis",
        "run_clustering_and_umap",
        "run_paga_trajectory",
        "find_marker_genes",
        "generate_markdown_report",
    ]
    mock_runnables = [
        RunnableTool(
            tool=StructuredTool.from_function(dummy_function, name=name),
            plugin_id="mock-plugin-id",
            run=mock_run_tool,
        )
        for name in tools_list
    ]
    yield mock_runnables


# ==========================================
# 2. 数据初始化函数 (关键修改)
# ==========================================
def init_load_test_data():
    """
    手动获取 Session 并插入压测所需的数据
    """
    print("--- 正在初始化压测数据 ---")

    # get_db_session 通常是一个 yield session 的生成器
    # 我们需要手动 next() 它来获取实际的 session 对象
    from dingent.server.api.dependencies import get_db_session
    from sqlmodel import Session
    from dingent.core.db.models import Workspace

    session_generator = get_db_session()
    session: Session = next(session_generator)

    try:
        ws_slug = "Test Workspace"
        ws = Workspace(
            name="Test Workspace",
            slug=ws_slug,
            allow_guest_access=True,
        )
        session.add(ws)
        session.commit()
        session.refresh(ws)

        # 2. 调用你的数据准备函数
        from tests.setup_data import mock_full_single_cell_data

        data = mock_full_single_cell_data(ws.id, session)

        # 3. 提取关键信息用于配置 Locust
        wf = data["workflow"]

        print("\n" + "=" * 50)
        print("✅ 数据准备完成！请将以下信息填入 locustfile.py:")
        print(f'WORKSPACE_SLUG = "{ws.slug}"')
        print(f'WORKFLOW_NAME  = "{wf.name}"')
        print("=" * 50 + "\n")

    except Exception as e:
        print(f"❌ 数据初始化失败: {e}")
        raise e
    finally:
        # 关闭 Session
        session_generator.close()


# ==========================================
# 3. 主启动流程
# ==========================================
def start_server():
    # A. 准备 Mock LLM
    # 假设 start_mock_server.py 在 scripts/ 目录下，调整路径指向 tests/data
    base_dir = os.path.dirname(os.path.dirname(__file__))  # 回退到项目根目录
    data_path = os.path.join(base_dir, "tests/data/trace.json")

    if not os.path.exists(data_path):
        raise FileNotFoundError(f"找不到 Trace 文件: {data_path}")

    mock_llm_instance = create_replay_llm(data_path)

    # B. 设置 Patch 目标
    target_tools = "dingent.core.assistants.assistant.AssistantRuntime.load_tools"
    target_llm = "dingent.core.llms.service.get_llm_for_context"

    # C. 应用 Patch 并启动
    with ExitStack() as stack:
        # 应用 Mock
        stack.enter_context(setup_temp_home())
        from dingent.core.paths import paths
        from dingent.core.config import settings

        paths.__init__()
        settings.DATABASE_URL = f"sqlite:///{paths.sqlite_path}"

        stack.enter_context(patch(target_tools, side_effect=_mock_load_tools, autospec=True))
        mock_get_llm = stack.enter_context(patch(target_llm))
        mock_get_llm.return_value = mock_llm_instance

        os.environ["OPENAI_API_KEY"] = "MOCK_KEY"

        from dingent.core.db.session import create_db_and_tables

        create_db_and_tables()
        init_load_test_data()

        print("--- Starting Uvicorn Server on Port 8000 ---")
        # 启动 Server
        from dingent.server.app import create_app

        app = create_app()
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="debug")


if __name__ == "__main__":
    start_server()
