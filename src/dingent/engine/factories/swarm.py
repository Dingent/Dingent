from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from uuid import UUID

from langchain.tools import BaseTool

from dingent.core.assistants.assistant_factory import AssistantFactory
from dingent.core.utils import normalize_agent_name
from dingent.core.workflows.schemas import ExecutableWorkflow
from dingent.engine.agents.simple_agent import build_simple_react_agent
from dingent.engine.agents.tools import create_handoff_tool


@asynccontextmanager
async def create_assistant_graphs(
    assistant_factory: AssistantFactory,
    workflow: ExecutableWorkflow,
    llm_or_resolver,  # Can be either an LLM instance or a resolver function
    log_method: Callable,
    assistant_id_map: dict[str, UUID] | None = None,  # Map assistant names to their IDs
):
    """
    Create graphs for all assistants in a workflow.

    Args:
        assistant_factory: Factory for creating assistant runtimes
        workflow: The workflow specification
        llm_or_resolver: Either an LLM instance (legacy) or a function(assistant_id) -> LLM
        log_method: Logging method
        assistant_id_map: Optional mapping from assistant names to their database IDs
    """
    assistant_graphs = {}

    # 3. 构建每个 Agent 图
    async with AsyncExitStack() as stack:
        for name, assistant_config in workflow.assistant_configs.items():
            rt = await assistant_factory.create_runtime(assistant_config)
            raw_tools = await stack.enter_async_context(rt.load_tools())

            tool_configs = {tc["name"]: tc for p in assistant_config.plugins for tc in p.tool_configs}
            transformed_tools: list[BaseTool] = []
            for tool in raw_tools:
                config = tool_configs.get(tool.tool.name)
                original_tool = tool.tool
                custom_runner = tool.run

                async def run_adapter(
                    _runner=custom_runner,
                    **kwargs,
                ):
                    return await _runner(kwargs)

                original_tool.coroutine = run_adapter

                if config:
                    if "enabled" in config and not config["enabled"]:
                        continue
                    if "description" in config and config["description"]:
                        tool.tool.description = config["description"]
                transformed_tools.append(original_tool)

            # 筛选相关的 Handoff 工具

            destinations = workflow.adjacency_map.get(name, [])
            handoff_tools = [
                create_handoff_tool(normalize_agent_name(dest), description=f"{workflow.assistant_configs[normalize_agent_name(dest)].description}", log_method=log_method)
                for dest in destinations
            ]

            # Resolve LLM for this specific assistant
            if callable(llm_or_resolver) and assistant_id_map:
                # Use resolver function with assistant ID
                assistant_id = assistant_id_map.get(name)
                llm = llm_or_resolver(assistant_id) if assistant_id else llm_or_resolver(None)
            elif callable(llm_or_resolver):
                # Resolver without assistant IDs - use workflow-level resolution
                llm = llm_or_resolver(None)
            else:
                # Legacy: direct LLM instance
                llm = llm_or_resolver

            agent = build_simple_react_agent(
                name=name,
                llm=llm,
                tools=handoff_tools + transformed_tools,
                system_prompt=assistant_config.instructions,
            )
            assistant_graphs[name] = agent

        yield assistant_graphs
