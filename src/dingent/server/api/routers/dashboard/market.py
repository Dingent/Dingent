from fastapi import APIRouter, Depends, HTTPException

from dingent.core.market_schemas import MarketDownloadRequest, MarketDownloadResponse, MarketItem, MarketItemCategory, MarketMetadata
from dingent.core.plugins.market_service import MarketService
from dingent.core.plugins.plugin_manager import PluginManager
from dingent.server.api.dependencies import (
    get_market_service,
    get_plugin_manager,
    get_user_plugin_service,
)
from dingent.server.services.user_plugin_service import UserPluginService

router = APIRouter(prefix="/market", tags=["Market"])


@router.get("/metadata", response_model=MarketMetadata)
async def get_market_metadata(
    market_service: MarketService = Depends(get_market_service),
):
    return await market_service.get_market_metadata()


@router.get("/items", response_model=list[MarketItem])
async def get_market_items(
    category: str,
    market_service: MarketService = Depends(get_market_service),
    plugin_service: UserPluginService = Depends(get_user_plugin_service),
):
    """
    category: 'plugin', 'assistant', 'workflow', or 'all'
    """
    try:
        cat_enum = MarketItemCategory(category)
        # 获取本地已安装插件用于对比版本
        local_plugins = plugin_service.get_visible_plugins()

        return await market_service.get_market_items(cat_enum, installed_plugins=local_plugins)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download", response_model=MarketDownloadResponse)
async def download_market_item(
    request: MarketDownloadRequest,
    market_service: MarketService = Depends(get_market_service),
    plugin_manager: PluginManager = Depends(get_plugin_manager),
):
    try:
        cat_enum = MarketItemCategory(request.category)
        result = await market_service.download_item(request.item_id, cat_enum)

        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])

        # 如果是插件，触发一次刷新
        if cat_enum == MarketItemCategory.PLUGIN:
            plugin_manager.list_visible_plugins()
            await plugin_manager.reload_plugins()
        return MarketDownloadResponse(**result)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid category")


@router.get("/items/{item_id}/readme")
async def get_readme(
    item_id: str,
    category: str,
    market_service: MarketService = Depends(get_market_service),
):
    try:
        cat_enum = MarketItemCategory(category)
        content = await market_service.get_item_readme(item_id, cat_enum)
        if not content:
            raise HTTPException(status_code=404, detail="README not found")
        return {"readme": content}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid category")
