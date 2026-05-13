import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.exceptions import HTTPException

from dingent.core.llms.analytics_manager import AnalyticsManager
from dingent.core.logs.log_manager import LogManager
from dingent.core.market_schemas import MarketItemCategory
from dingent.core.plugins.market_service import MarketService
from dingent.core.plugins.plugin_manager import PluginManager
from dingent.server.api.dependencies import (
    get_analytics_manager,
    get_log_manager,
    get_market_service,
    get_plugin_manager,
)

router = APIRouter(prefix="/overview", tags=["Overview"])


def _gather_plugins_section(plugin_manager: PluginManager) -> dict[str, Any]:
    manifests = plugin_manager.list_visible_plugins()
    items = []
    for manifest in manifests:
        tools = []
        try:
            tools = getattr(manifest, "tools", []) or []
        except Exception:
            pass
        items.append(
            {
                "id": manifest.id,
                "display_name": manifest.display_name,
                "version": manifest.version,
                "tool_count": len(tools),
            }
        )
    return {
        "installed_total": len(manifests),
        "list": items,
    }


def _gather_logs_section(log_manager: LogManager, limit: int = 20) -> dict[str, Any]:
    # recent logs
    try:
        recent = [e.to_dict() for e in log_manager.get_logs(limit=limit)]
    except Exception:
        recent = []
    # stats
    try:
        stats = log_manager.get_log_stats()
    except Exception:
        stats = {}
    return {"recent": recent, "stats": stats}


async def _gather_market_section(
    market_service: MarketService,
    plugin_manager: PluginManager,
) -> dict[str, Any]:
    metadata = None
    plugin_updates = 0
    try:
        metadata_obj = await market_service.get_market_metadata()
        metadata = metadata_obj.model_dump()
    except Exception:
        metadata = None

    try:
        local_versions = plugin_manager.get_installed_versions()  # {plugin_id: version}
        # 获取市场插件项目
        market_plugins = await market_service.get_market_items(MarketItemCategory.PLUGIN, installed_items={"plugins": local_versions})
        for item in market_plugins:
            # 假设 item.id 与 plugin_id 对应, item.version 字段存在
            local_ver = local_versions.get(item.id)
            if local_ver and local_ver != item.version:
                plugin_updates += 1
    except Exception:
        pass

    return {
        "metadata": metadata,
        "plugin_updates": plugin_updates,
    }


@router.get("")
async def get_overview(
    plugin_manager: PluginManager = Depends(get_plugin_manager),
    log_manager: LogManager = Depends(get_log_manager),
    market_service: MarketService = Depends(get_market_service),
):
    """
    聚合后台核心状态用于 Dashboard 展示的总览接口。
    返回结构示例：
    {
      "assistants": {...},
      "plugins": {...},
      "workflows": {...},
      "logs": {...},
      "market": {...},
      "llm": {...}
    }
    """
    asyncio.create_task(_gather_market_section(market_service, plugin_manager))

    # 同步部分
    plugins_section = _gather_plugins_section(plugin_manager)
    # workflows_section = _gather_workflows_section(workflow_manager)
    logs_section = _gather_logs_section(log_manager)

    return {
        "plugins": plugins_section,
        "workflows": {},
        "logs": logs_section,
    }


@router.get("/budget")
async def get_budget(
    # log_manager: LogManager = Depends(get_log_manager),
    analytics_manager: AnalyticsManager = Depends(get_analytics_manager),
):
    budget = analytics_manager.get_user_cost("admin")
    if not budget:
        raise HTTPException(status_code=404, detail="No budget data found")
    return budget
