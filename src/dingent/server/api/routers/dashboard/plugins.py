from fastapi import APIRouter, Depends, HTTPException

from dingent.core.db.models import User
from dingent.core.plugins.plugin_manager import PluginManager
from dingent.core.plugins.schemas import PluginRead
from dingent.server.api.dependencies import (
    get_current_user,
    get_plugin_manager,
    get_user_plugin_service,
)
from dingent.server.services.user_plugin_service import UserPluginService

router = APIRouter(prefix="/plugins", tags=["Plugins"])


# WARN: plugin的实例就不能每次都重新创建，速度太慢了
@router.get("", response_model=list[PluginRead])
async def list_available_plugins(
    user_plugin_service: UserPluginService = Depends(get_user_plugin_service),
):
    return user_plugin_service.get_visible_plugins()


# admin only
@router.delete("/{plugin_id}")
async def remove_plugin_global(
    plugin_id: str,
    plugin_manager: PluginManager = Depends(get_plugin_manager),
    user: User = Depends(get_current_user),  # noqa: ARG001
):
    raise HTTPException(status_code=403, detail="Not authorized")  # TODO: admin check
    try:
        plugin_manager.delete_plugin(plugin_id=plugin_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    changed = False
    return {"status": "success", "assistants_updated": changed}
