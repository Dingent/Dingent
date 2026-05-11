from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler

from langchain.chat_models.base import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph, RunnableConfig
from langgraph_swarm import create_swarm

from dingent.core.assistants.assistant_factory import AssistantFactory
from dingent.core.workflows.schemas import ExecutableWorkflow
from dingent.engine import create_assistant_graphs
from dingent.engine.agents.state import MainState


@dataclass
class GraphArtifact:
    """包含编译后的图及其管理的资源 (Stack, Checkpointer)。"""

    workflow_id: uuid.UUID
    graph: CompiledStateGraph
    stack: AsyncExitStack
    checkpointer: Any

    async def aclose(self) -> None:
        """关闭 Artifact 持有的所有资源。"""
        await self.stack.aclose()


class GraphFactory:
    def __init__(self, assistant_factory: AssistantFactory):
        self.assistant_factory = assistant_factory

    async def build(
        self,
        workflow: ExecutableWorkflow,
        llm: BaseChatModel,
        checkpointer: Any,
        log_method: Callable,
        assistant_id_map: dict[str, Any] | None = None,  # Map assistant names to IDs
    ) -> GraphArtifact:
        """构建完整的 Swarm 运行图"""
        stack = AsyncExitStack()

        try:
            return await self._build_full(workflow, stack, llm, checkpointer, log_method, assistant_id_map)
        except Exception:
            # 如果构建过程出错，确保 stack 被释放
            await stack.aclose()
            raise

    async def _build_full(
        self,
        workflow: ExecutableWorkflow,
        stack: AsyncExitStack,
        llm: BaseChatModel,
        checkpointer: Any,
        log_method: Callable,
        assistant_id_map: dict[str, Any] | None = None,
    ) -> GraphArtifact:
        log_method("info", f"Building graph for workflow {workflow.id}")

        if not workflow.start_node:
            raise ValueError(f"Workflow '{workflow.id}' has no start node.")

        default_active = workflow.start_node

        # 2. 创建所有子 Agent 图 (使用 AsyncExitStack 管理工具资源的生命周期)
        assistants_ctx = create_assistant_graphs(
            self.assistant_factory,
            workflow,
            llm,
            log_method,
            assistant_id_map,  # Pass the assistant ID map
        )
        # 注意：这里进入上下文，stack 会负责在 artifact.aclose() 时退出
        assistants_map = await stack.enter_async_context(assistants_ctx)

        if default_active not in assistants_map:
            raise ValueError(f"Start node '{default_active}' not found in generated assistants: {list(assistants_map.keys())}")

        # 3. 组装 Swarm
        swarm_workflow = create_swarm(
            agents=list(assistants_map.values()),
            state_schema=MainState,
            default_active_agent=default_active,
            context_schema=dict,
        )

        compiled_swarm = swarm_workflow.compile()

        # 4. 包装安全层 (错误捕获)
        # 将整个 swarm 视为一个节点，包裹在 outer graph 中
        safe_swarm_node = self._create_safe_swarm_node(
            compiled_swarm,
            log_method,
        )

        outer = StateGraph(MainState)
        outer.add_node("swarm", safe_swarm_node)
        outer.add_edge(START, "swarm")
        outer.add_edge("swarm", END)

        # 5. 编译最终图
        final_graph = outer.compile(checkpointer=checkpointer)
        final_graph.name = "agent_system"

        return GraphArtifact(
            workflow_id=workflow.id,
            graph=final_graph,
            stack=stack,
            checkpointer=checkpointer,
        )

    def _create_safe_swarm_node(self, compiled_swarm: CompiledStateGraph, log_method: Callable):
        """
        创建一个包装节点，用于运行 Swarm 并捕获未处理的异常。
        这防止了单个 Agent 的崩溃导致整个应用程序崩溃。
        """

        async def safe_swarm_runner(state: MainState, config: RunnableConfig):
            try:
                # HACK:
                config["recursion_limit"] = 1000
                return await compiled_swarm.ainvoke(state, config=config)
            except Exception as e:
                import traceback

                error_msg = traceback.format_exc()
                print("捕获到的错误信息：\n", error_msg)
                error_type = type(e).__name__
                error_msg = f"Critical Swarm Error: {error_type}: {str(e)}"
                traceback.print_tb(e.__traceback__)

                log_method("error", "Swarm execution failed: {error_msg}", context={"error_type": error_type, "error": str(e)})

                messages = state.get("messages", [])
                error_message = AIMessage(
                    content=f"I encountered a system error and could not complete the request.\n\nDetails: {error_msg}", additional_kwargs={"error": True, "error_type": error_type}
                )

                # 返回修正后的状态，LangGraph 会将其合并
                return {"messages": messages + [error_message]}

        return safe_swarm_runner
