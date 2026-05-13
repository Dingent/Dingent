from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, model_validator


class MarketItemCategory(str, Enum):
    """Enumeration for different categories of items in the Dingent Hub."""

    PLUGIN = "plugin"
    ASSISTANT = "assistant"
    WORKFLOW = "workflow"
    ALL = "all"

    def __str__(self) -> str:
        """Return the string value of the enum member."""
        return self.value


class MarketMetadata(BaseModel):
    version: str
    updated_at: str
    categories: dict[str, int]


class MarketItem(BaseModel):
    id: str
    name: str
    description: str | None = None
    version: str | None = None
    author: str | None = None
    category: MarketItemCategory
    tags: list[str] = []
    license: str | None = None
    readme: str | None = None
    downloads: int | None = None
    rating: float | None = None
    created_at: str | None = None
    updated_at: str | None = None
    is_installed: bool = False
    installed_version: str | None = None
    update_available: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize_name_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            source_for_display_name = data.get("display_name") or data.get("name")
            if source_for_display_name:
                data["name"] = source_for_display_name

        return data


class MarketBackend(Protocol):
    async def get_metadata(self) -> MarketMetadata: ...
    async def list_items(
        self,
        category: MarketItemCategory,
        installed_map_tuple: tuple[tuple[str, str], ...],
    ) -> list[MarketItem]: ...
    async def get_readme(self, item_id: str, category: MarketItemCategory) -> str | None: ...
    async def download_item(self, item_id: str, category: MarketItemCategory, target_dir: Path) -> None: ...


class MarketDownloadRequest(BaseModel):
    item_id: str
    category: str  # "plugin" | "assistant" | "workflow"


class MarketDownloadResponse(BaseModel):
    success: bool
    message: str
    installed_path: str | None = None
