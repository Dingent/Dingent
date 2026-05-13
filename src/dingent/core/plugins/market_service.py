from pathlib import Path
from typing import Any

from dingent.core.logs.log_manager import LogManager
from dingent.core.market_schemas import MarketBackend, MarketItem, MarketItemCategory, MarketMetadata
from dingent.core.plugins.schemas import PluginRead


class MarketService:
    def __init__(self, plugin_path: Path, log_manager: LogManager, backend: MarketBackend):
        self._log_manager = log_manager
        self._backend = backend
        self.plugin_path = plugin_path
        self.TARGET_PATHS = {MarketItemCategory.PLUGIN: self.plugin_path}

    async def get_market_metadata(self) -> MarketMetadata:
        return await self._backend.get_metadata()

    async def get_market_items(
        self,
        category: MarketItemCategory,
        installed_plugins: list[PluginRead] | None = None,
    ) -> list[MarketItem]:
        """
        Orchestrates fetching items. Converts local objects to a hashable tuple for the backend cache.
        """
        installed_map = {}

        if installed_plugins:
            for p in installed_plugins:
                # Handle both Pydantic models and dicts
                pid = getattr(p, "registry_id", None) or (p.get("registry_id") if isinstance(p, dict) else None)
                ver = getattr(p, "version", "") or (p.get("version") if isinstance(p, dict) else "")
                if pid:
                    installed_map[str(pid)] = str(ver)

        installed_tuple = tuple(sorted(installed_map.items()))

        return await self._backend.list_items(category, installed_tuple)

    async def get_item_readme(self, item_id: str, category: MarketItemCategory) -> str | None:
        return await self._backend.get_readme(item_id, category)

    async def download_item(self, item_id: str, category: MarketItemCategory) -> dict[str, Any]:
        """
        High-level flow:
        1. Calculate Path
        2. Download (Backend)
        3. Register/Install (Service Logic)
        """
        try:
            target_dir = self.TARGET_PATHS.get(category)
            if not target_dir:
                raise ValueError(f"No target path configured for category: {category}")

            if category == MarketItemCategory.PLUGIN:
                target_dir = target_dir

            target_dir.mkdir(parents=True, exist_ok=True)

            # 1. Download Files
            await self._backend.download_item(item_id, category, target_dir)

            # 2. Post-Download Installation Logic
            await self._post_install_hook(item_id, category, target_dir)

            return {
                "success": True,
                "message": f"Successfully installed {item_id}",
                "installed_path": str(target_dir),
            }

        except Exception as e:
            self._log_manager.log_with_context("error", "Download process failed", context={"id": item_id, "cat": category.value, "error": str(e)})
            return {"success": False, "message": str(e), "installed_path": None}

    async def _post_install_hook(self, item_id: str, category: MarketItemCategory, path: Path):
        """Handle system registration after files are on disk."""
        if category == MarketItemCategory.PLUGIN:
            self._log_manager.log_with_context("info", f"New plugin downloaded: {item_id}. Validating structure...")
        elif category == MarketItemCategory.ASSISTANT:
            pass
