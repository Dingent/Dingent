from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import cast
from uuid import UUID
from langchain.tools import ToolException
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool, Tool
from langchain_mcp_adapters.tools import load_mcp_tools, _convert_call_tool_result
from langgraph.types import Command


from ..plugins.plugin import PluginRuntime
from ..plugins.plugin_manager import PluginManager
from ..plugins.schemas import RunnableTool
from .schemas import AssistantSpec


class AssistantRuntime:
    """Holds assistant metadata and live plugin runtimes.

    This runtime represents an instantiated Assistant with a set of enabled
    plugin runtimes and provides utilities to list and invoke MCP tools.

    Attributes:
        id (str): Assistant identifier.
        name (str): Assistant display name.
        description (str): Optional description of the assistant.
        plugin_instances (dict[str, PluginRuntime]): Live plugin runtimes keyed
            by their registry_id.
        destinations (list[str]): Downstream assistant names/IDs reachable in
            the active workflow (set by the workflow layer).
        _log_method (Callable): Logging function `(level, message, **context)`.
    """

    def __init__(
        self,
        assistant_id: UUID,
        name: str,
        log_method: Callable,
        description: str,
        plugin_instances: dict[str, PluginRuntime],
        plugin_configs: dict[str, dict],
    ):
        """Initialize the runtime with metadata and plugin instances.

        Args:
            assistant_id: Unique ID of the assistant.
            name: Human-readable assistant name.
            log_method: Logging callable used by this runtime.
            description: Optional textual description.
            plugin_instances: Mapping of registry_id -> PluginRuntime.
        """
        self.id = assistant_id
        self.name = name
        self.description = description
        self.plugin_instances = plugin_instances
        self.plugin_configs = plugin_configs
        self._log_method = log_method

    @classmethod
    async def create_runtime(
        cls,
        plugin_manager: PluginManager,
        assistant: AssistantSpec,
        log_method: Callable,
    ) -> AssistantRuntime:
        plugin_instances: dict[str, PluginRuntime] = {}
        plugin_configs: dict[str, dict] = {}
        for plugin_spec in assistant.plugins:
            try:
                inst = await plugin_manager.get_or_create_runtime(plugin_spec.registry_id)
                plugin_instances[plugin_spec.registry_id] = inst
                plugin_configs[plugin_spec.registry_id] = plugin_spec.config or {}
            except Exception as e:
                # Log and continue; this isolates failures per plugin.
                log_method(
                    "error",
                    "Create plugin instance failed (assistant={name} plugin={pid}): {e}",
                    context={"name": assistant.name, "pid": plugin_spec.registry_id, "e": e},
                )
                continue
        return cls(
            assistant_id=assistant.id,
            name=assistant.name,
            log_method=log_method,
            description=assistant.description or "",
            plugin_instances=plugin_instances,
            plugin_configs=plugin_configs,
        )

    @asynccontextmanager
    async def load_tools(self):
        runnable: list[RunnableTool] = []
        for registry_id, inst in self.plugin_instances.items():
            current_plugin_config = self.plugin_configs.get(registry_id, {})
            async with inst.mcp_client as client:
                tools = await load_mcp_tools(client.session)
            for t in tools:

                async def call_tool(
                    arguments: dict,
                    meta: dict | None = None,
                    _runtime=inst,
                    _tool=t,
                    _config=current_plugin_config,
                ):
                    meta = meta or {}
                    meta.update(_config)

                    async with _runtime.mcp_client as tool_client:
                        result = await tool_client.call_tool(
                            _tool.name,
                            arguments=arguments,
                            meta=meta,
                        )
                        result.isError = result.is_error
                        result.structuredContent = result.structured_content
                        result = _convert_call_tool_result(result)
                        return result

                runnable.append(RunnableTool(tool=cast(StructuredTool, t), plugin_id=inst.id, run=call_tool))
        yield runnable

    async def aclose(self):
        """Load MCP tools with connections held for the whole context.

        Keeps all plugin MCP connections open using `AsyncExitStack`, then
        invokes tools over those persistent clients. Prefer this for bursty
        workloads that will issue many tool calls in a short period.

        Yields:
            list[RunnableTool]: Runnable tools whose `run()` uses the already
            opened clients (lower overhead per call).

        Warning:
            Holding connections may increase server resource usage; ensure the
            context is kept as short as practical.
        """
        for inst in self.plugin_instances.values():
            try:
                await inst.aclose()
            except Exception as e:
                self._log_method("warning", "Error closing plugin instance (assistant={name}): {e}", context={"name": self.name, "e": e})
        self.plugin_instances.clear()
