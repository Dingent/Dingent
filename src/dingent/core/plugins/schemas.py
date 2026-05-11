from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import toml
from fastmcp.mcp_config import MCPServerTypes
from pydantic import PrivateAttr, model_validator
from sqlmodel import Field, SQLModel
from langchain_core.tools import StructuredTool, Tool


class PluginConfigSchema(SQLModel):
    name: str = Field(..., description="配置项的名称 (环境变量名)")
    type: Literal["string", "float", "integer", "bool", "dict", "object"] = Field(..., description="配置项的期望类型 (e.g., 'string', 'number')")
    required: bool = Field(..., description="是否为必需项")
    secret: bool = Field(False, description="是否为敏感信息 (如 API Key)")
    description: str | None = Field(None, description="该配置项的描述")
    default: Any | None = Field(None, description="默认值 (如果存在)")


class PluginBase(SQLModel):
    display_name: str = Field(..., description="插件的显示名称")
    description: str = Field(..., description="插件描述")
    version: str | float = Field("0.1.0", description="插件版本")


class PluginManifest(PluginBase):
    """
    Acts as the static definition or blueprint of a plugin.
    Its sole source of truth is the plugin.toml file created by the plugin developer
    """

    id: str = Field(..., description="插件的本地标识符，从plugin.toml中读取,example: Weather_reporter")
    display_name: str = Field(..., description="插件的显示名称")
    spec_version: str | float = Field("2.0", description="插件规范版本 (遵循语义化版本)")
    servers: dict[str, MCPServerTypes] = Field(default_factory=dict, description="一组服务器配置")
    server: MCPServerTypes | None = Field(default=None, description="单个服务器配置快捷方式")
    dependencies: list[str] | None = None
    python_version: str | None = None
    config_schema: list["PluginConfigSchema"] | None = None
    _plugin_path: Path | None = PrivateAttr(default=None)

    @classmethod
    def from_toml(cls, toml_path: Path) -> "PluginManifest":
        if not toml_path.is_file():
            raise FileNotFoundError(f"'plugin.toml' not found at '{toml_path}'")

        plugin_dir = toml_path.parent
        pyproject_toml_path = plugin_dir / "pyproject.toml"

        base_meta = {}
        if pyproject_toml_path.is_file():
            pyproject_data = toml.load(pyproject_toml_path)
            project_section = pyproject_data.get("project", {})
            valid_keys = cls.model_fields.keys()
            base_meta = {k: v for k, v in project_section.items() if k in valid_keys}

        plugin_info = toml.load(toml_path)
        plugin_meta = plugin_info.get("plugin", {})
        final_meta = base_meta | plugin_meta

        manifest = cls(**final_meta)
        manifest._plugin_path = plugin_dir
        return manifest

    @model_validator(mode="after")
    def unify_servers_configuration(self) -> "PluginManifest":
        if self.server is not None:
            key_name = "default"

            if key_name not in self.servers:
                self.servers[key_name] = self.server

        if not self.servers:
            raise ValueError("Must provide either 'server' or 'servers' in configuration.")

        return self

    @property
    def path(self) -> Path:
        if self._plugin_path is None:
            raise AttributeError("Plugin path has not been set.")
        return self._plugin_path


class ToolOverrideConfig(SQLModel):
    name: str
    enabled: bool = True
    description: str | None = None


class PluginConfigItemRead(PluginConfigSchema):
    """Represents a single configuration item with its schema and value."""

    title: str | None

    value: Any | None = Field(None, description="用户设置的当前值")


class ToolConfigItemRead(SQLModel):
    name: str = Field(..., description="工具的名称")
    enabled: bool = Field(..., description="该工具是否启用")
    # inputSchema: dict[str, Any] | None = Field(None, description="工具输入的JSON Schema定义")
    # outputSchema: dict[str, Any] | None = Field(None, description="工具输出的JSON Schema定义")
    description: str | None = Field(None, description="工具的描述")


class PluginRead(PluginBase):
    registry_id: str = Field(..., description="插件的注册ID (来自插件注册表)")
    enabled: bool = True
    tools: list[ToolConfigItemRead] | None = None
    status: str | None = Field(None, description="运行状态 (active/inactive/error)")
    config: list[PluginConfigItemRead] | None = Field(None, description="用户为该插件设置的配置项")


class PluginCreate(PluginBase):
    spec_version: str | float = Field("2.0", description="插件规范版本 (遵循语义化版本)")


class PluginUpdate(PluginBase):
    registry_id: str = Field(..., description="插件的注册ID (来自插件注册表)")
    enabled: bool = Field(True, description="启用或禁用该插件")
    config: dict[str, Any] | None = Field(None, description="用户为该插件设置的配置项")
    tool_configs: list[ToolOverrideConfig] | None = Field(
        None,
        alias="tools",
        description="用户为该插件设置的工具配置项",
    )


class RunnableTool(SQLModel):
    tool: StructuredTool
    plugin_id: str
    run: Callable[[dict], Any]
