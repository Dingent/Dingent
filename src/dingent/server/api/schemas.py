import asyncio
import os
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

import fsspec
import toml
from async_lru import alru_cache
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field, model_validator

# --- Admin Response Models ---


class ToolAdminDetail(BaseModel):
    name: str
    description: str
    enabled: bool


class AppAdminDetail(BaseModel):
    current_workflow: str | None = None
    workflows: list[dict[str, str]] = Field(default_factory=list)
    llm: dict[str, Any]


# --- Request Models ---


class AddPluginRequest(BaseModel):
    plugin_id: str
    config: dict[str, Any] | None = None
    enabled: bool = True
    tools_default_enabled: bool = True


class UpdatePluginConfigRequest(BaseModel):
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    tools_default_enabled: bool | None = None
    tools: list[str] | None = None


class SetActiveWorkflowRequest(BaseModel):
    workflow_id: str


class AgentExecuteRequest(BaseModel):
    threadId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    state: dict[str, Any] = {}
    messages: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    nodeName: str | None = None
    config: dict[str, Any] | None = None
    metaEvents: list[dict[str, Any]] = []


class ActionExecuteRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = {}


class AgentStateRequest(BaseModel):
    threadId: str


# --- Market Models ---
MARKET_REPO_OWNER = "saya-ashen"
MARKET_REPO_NAME = "dingent-hub"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_CONTENT_BASE = "https://ghfast.top/https://raw.githubusercontent.com/{owner}/{repo}/{branch}"


MARKET_REPO_OWNER = "saya-ashen"
MARKET_REPO_NAME = "dingent-hub"
MARKET_BRANCH = "main"


class MarketDownloadRequest(BaseModel):
    item_id: str
    category: str  # "plugin" | "assistant" | "workflow"


class MarketDownloadResponse(BaseModel):
    success: bool
    message: str
    installed_path: str | None = None


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


class GitHubMarketBackend:
    """
    使用 fsspec 重构的市场后端。
    """

    # 目录映射
    CATEGORY_DIR_MAP = {
        MarketItemCategory.PLUGIN: "plugins",
        MarketItemCategory.ASSISTANT: "assistants",
        MarketItemCategory.WORKFLOW: "workflows",
    }

    def __init__(self, log_manager):
        self._log_manager = log_manager
        self._fs = None

        self._fs_init_lock = asyncio.Lock()

    # --- 核心辅助：将 fsspec 的同步操作转为异步 ---
    async def _run_fs(self, func, *args, **kwargs):
        """在线程池中运行 fsspec 的同步操作，避免阻塞 Event Loop"""
        return await asyncio.to_thread(func, *args, **kwargs)

    async def _get_fs(self):
        """
        懒加载获取 fsspec 实例。
        如果尚未初始化，则在线程池中进行初始化。
        """
        if self._fs is not None:
            return self._fs

        async with self._fs_init_lock:
            # 双重检查锁定 (Double-checked locking)
            if self._fs is not None:
                return self._fs

            try:
                # 将 fsspec 的初始化也放入线程池，因为它可能会进行网络验证
                self._fs = await self._run_fs(
                    fsspec.filesystem, "github", org=MARKET_REPO_OWNER, repo=MARKET_REPO_NAME, sha=MARKET_BRANCH, username=os.getenv("GITHUB_USER"), token=os.getenv("GITHUB_TOKEN")
                )
                self._log_manager.log_with_context("info", "GitHub FS initialized successfully")
            except Exception as e:
                self._log_manager.log_with_context("error", "Failed to initialize GitHub FS", context={"error": str(e)})
                # 这里可以选择抛出异常，或者返回 None 让调用者处理
                raise e

            return self._fs

    # --- API 实现 ---

    @alru_cache(maxsize=1)
    async def get_metadata(self) -> MarketMetadata:
        try:
            # 直接读取文件内容，就像读本地文件一样
            fs = await self._get_fs()
            if await self._run_fs(fs.exists, "market.json"):
                content = await self._run_fs(fs.cat_file, "market.json")
                return MarketMetadata.model_validate_json(content)
        except Exception as e:
            self._log_manager.log_with_context("error", "Metadata parse error", context={"error": str(e)})

        return MarketMetadata(version="0.0.0", updated_at="", categories={})

    async def get_readme(self, item_id: str, category: MarketItemCategory) -> str | None:
        repo_dir = self.CATEGORY_DIR_MAP.get(category, f"{category.value}s")
        path = f"{repo_dir}/{item_id}/README.md"

        try:
            fs = await self._get_fs()
            if await self._run_fs(fs.exists, path):
                # fsspec 默认读取为 bytes，需要 decode
                content_bytes = await self._run_fs(fs.cat_file, path)
                return content_bytes.decode("utf-8")
        except Exception:
            pass  # File not found or error
        return None

    async def download_item(self, item_id: str, category: MarketItemCategory, target_dir: Path) -> None:
        repo_dir = self.CATEGORY_DIR_MAP.get(category, f"{category.value}s")
        remote_path = f"{repo_dir}/{item_id}"

        # 确保目标目录存在
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            fs = await self._get_fs()
            await self._run_fs(fs.get, remote_path, str(target_dir), recursive=True)
        except Exception as e:
            self._log_manager.log_with_context("error", "fsspec download failed", context={"remote": remote_path, "error": str(e)})
            raise

    # --- 列表获取逻辑 ---

    async def list_items(
        self,
        category: MarketItemCategory,
        installed_map_tuple: tuple[tuple[str, str], ...],
    ) -> list[MarketItem]:
        categories = [c for c in MarketItemCategory if c != MarketItemCategory.ALL] if category == MarketItemCategory.ALL else [category]

        tasks = [self._process_category(cat, installed_map_tuple) for cat in categories]
        results = await asyncio.gather(*tasks)
        return [item for sublist in results for item in sublist]

    @alru_cache(maxsize=16)
    async def _process_category(self, category: MarketItemCategory, installed_map_tuple: tuple[tuple[str, str], ...]) -> list[MarketItem]:
        repo_dir = self.CATEGORY_DIR_MAP.get(category, f"{category.value}s")
        installed_map = dict(installed_map_tuple)

        try:
            fs = await self._get_fs()
            paths = await self._run_fs(fs.ls, repo_dir, detail=False)
        except FileNotFoundError:
            return []

        items = []
        for path in paths:
            # fsspec 返回的 path 通常是完整的，需要取最后一部分作为 ID
            # 这里的 path 可能是 "plugins/plugin-a"
            item_id = path.rstrip("/").split("/")[-1]

            # 过滤掉非文件夹（如果 fs.ls 返回了文件）
            if "." in item_id:
                continue

            # 获取详情 (并发处理)
            items.append(self._fetch_item_details(category, item_id, path, installed_map.get(item_id)))

        # 并发读取所有 items 的配置文件
        return [i for i in await asyncio.gather(*items) if i is not None]

    async def _fetch_item_details(self, category: MarketItemCategory, item_id: str, remote_path: str, local_version: str | None) -> MarketItem | None:
        try:
            meta = {}

            # 定义需要读取的配置文件路径
            configs_to_read = []
            if category == MarketItemCategory.PLUGIN:
                configs_to_read = [f"{remote_path}/pyproject.toml", f"{remote_path}/plugin.toml"]

            # 并发读取配置文件内容
            read_tasks = [self._safe_read_toml(p) for p in configs_to_read]
            config_contents = await asyncio.gather(*read_tasks)

            # 合并配置
            for data in config_contents:
                if not data:
                    continue
                # 简单的合并策略：扁平化
                meta.update(data.get("project", {}))  # pyproject standard
                meta.update(data.get("plugin", data))  # plugin.toml custom structure

            # 如果没有读到任何配置，回退到默认值
            remote_version = str(meta.get("version", "0.0.0"))

            # 版本比较
            update_available = False
            if local_version:
                try:
                    update_available = Version(remote_version) > Version(local_version)
                except InvalidVersion:
                    pass

            return MarketItem(
                id=item_id,
                name=meta.get("name", item_id),
                description=meta.get("description"),
                version=remote_version,
                author=meta.get("author") or (meta.get("authors", [{}])[0].get("name") if "authors" in meta else None),
                category=category,
                tags=meta.get("tags", []),
                license=str(meta.get("license", {}).get("text", "Unknown")),
                is_installed=bool(local_version),
                installed_version=local_version,
                update_available=update_available,
            )

        except Exception as e:
            self._log_manager.log_with_context("warning", "Item details error", context={"id": item_id, "error": str(e)})
            return None

    async def _safe_read_toml(self, path: str) -> dict | None:
        """同步辅助函数：安全读取并解析 TOML"""
        try:
            fs = await self._get_fs()
            if fs.exists(path):
                content = fs.cat_file(path)
                return toml.loads(content.decode("utf-8"))
        except Exception:
            pass
        return None


# 模型相关


class LLMModelConfigBase(BaseModel):
    name: str = Field(..., description="配置名称，例如 'My GPT-4'")
    provider: str = Field(..., description="LiteLLM provider: openai, azure, ollama, anthropic")
    model: str = Field(..., description="模型名称: gpt-4, llama3")
    api_base: str | None = Field(None, description="API Base URL")
    api_version: str | None = Field(None, description="API Version (Azure)")
    parameters: dict[str, Any] = Field(default_factory=dict, description="额外参数 JSON")
    is_active: bool = True


# --- 写入/创建 (包含明文 Key) ---
class LLMModelConfigCreate(LLMModelConfigBase):
    api_key: str | None = Field(None, description="明文 API Key，后端会自动加密存储")


# --- 更新 (所有字段可选) ---
class LLMModelConfigUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    model: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    api_key: str | None = Field(None, description="如果为空则不更新，如果传值则覆盖旧 Key")
    parameters: dict[str, Any] | None = None
    is_active: bool | None = None


# --- 读取/返回 (不包含 Key，只返回状态) ---
class LLMModelConfigRead(LLMModelConfigBase):
    id: uuid.UUID
    workspace_id: uuid.UUID
    # 关键点：永远不要返回 encrypted_api_key 或解密后的 key
    # 前端只需要知道“是否已经设置了 Key”来显示 placeholder
    has_api_key: bool
    created_at: datetime
    updated_at: datetime


# --- 测试连接请求 ---
class TestConnectionRequest(LLMModelConfigCreate):
    """用于测试连接的临时请求体，不需要存库"""

    pass


class TestConnectionResponse(BaseModel):
    success: bool
    latency_ms: float
    message: str
