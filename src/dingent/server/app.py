from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dingent.core.context import initialize_app_context

from .api import api_router

from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlmodel import Session

from dingent.core.assistants.assistant_factory import AssistantFactory
from dingent.core.db.session import engine
from dingent.core.logs.log_manager import LogManager
from dingent.core.paths import paths
from dingent.core.plugins.market_service import MarketService
from dingent.core.plugins.plugin_manager import PluginManager
from dingent.core.plugins.plugin_registry import PluginRegistry
from dingent.core.workflows.graph_factory import GraphFactory
from dingent.server.api.schemas import GitHubMarketBackend
from dingent.server.services.copilotkit_service import CopilotKitSdk
from dingent.server.services.plugin_sync_service import PluginSyncService


def _setup_global_services(app: FastAPI):
    """初始化核心服务并挂载到 app.state"""
    # 1. 基础服务初始化
    log_manager = LogManager()
    plugin_registry = PluginRegistry(paths.plugins_dir, log_manager)
    plugin_registry.reload_plugins()

    # 2. 数据库同步 (同步操作)
    with Session(engine, expire_on_commit=False) as session:
        PluginSyncService(db_session=session, registry=plugin_registry).sync()

    # 3. 挂载到 App State
    app.state.log_manager = log_manager
    app.state.plugin_registry = plugin_registry
    app.state.plugin_manager = PluginManager(plugin_registry, log_manager)

    market_backend = GitHubMarketBackend(log_manager)
    app.state.market_service = MarketService(paths.plugins_dir, log_manager, market_backend)
    app.state.assistant_factory = AssistantFactory(app.state.plugin_manager, app.state.log_manager)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Unified lifespan: Merges Base startup logic with CopilotKit extension logic.
    """
    # --- [Phase 1: Base Startup] ---
    print("--- Application Startup (Base) ---")
    app.state.app_context = initialize_app_context()

    # --- [Phase 2: Initialize Core Services] ---
    # 在 Base Context 初始化后执行，确保环境准备就绪
    _setup_global_services(app)

    # --- [Phase 3: Initialize CopilotKit & Async Resources] ---
    # 使用 async with 确保 checkpointer 在 yield (应用运行) 期间保持打开
    async with AsyncSqliteSaver.from_conn_string(paths.sqlite_path.as_posix()) as checkpointer:
        # HACK:
        checkpointer.conn.is_alive = lambda: True

        # 构建 SDK 需要的 factory (依赖于 Phase 2 中初始化的 assistant_factory)
        graph_factory = GraphFactory(app.state.assistant_factory)

        # 初始化 SDK 并挂载
        sdk = CopilotKitSdk(graph_factory=graph_factory, checkpointer=checkpointer)
        app.state.copilot_sdk = sdk

        print("--- CopilotKit Extension Initialized ---")

        # --- [Phase 4: Application Running] ---
        # 此时应用开始接收请求
        yield

        # --- [Phase 5: CopilotKit Shutdown] ---
        print("--- CopilotKit Extension Shutdown ---")
        # 退出 async with 块时，AsyncSqliteSaver 会自动执行清理逻辑

    # --- [Phase 6: Base Shutdown] ---
    print("--- Application Shutdown (Base) ---")
    await app.state.app_context.close_async_components()


def create_app() -> FastAPI:
    """Creates and configures the base FastAPI application."""
    app = FastAPI(lifespan=lifespan, title="Dingent API")

    # CORS middleware
    origins = [
        "http://localhost",
        "http://localhost:3001",
        "http://localhost:8000",
        "http://localhost:5173",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
        "https://smith.langchain.com",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_origins=origins,
    )

    app.include_router(api_router, prefix="/api/v1")

    return app
