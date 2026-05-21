from typing import Any
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from dingent.core.plugins.schemas import PluginRead, PluginUpdate


class AssistantBase(SQLModel):
    name: str = Field(..., description="The display name of the assistant.")
    description: str
    instructions: str | None = Field(None, description="Special instructions for the assistant.")
    version: str | float = Field("0.2.0", description="Assistant version.")
    spec_version: str | float = Field("2.0", description="Specification version.")
    enabled: bool = Field(True, description="Enable or disable the assistant.")
    model_config_id: UUID | None = Field(None, description="Override model configuration for this assistant.")


class AssistantRead(AssistantBase):
    id: str = Field(..., description="The unique and permanent ID for the assistant.")
    status: str = Field(..., description="运行状态 (active/inactive/error)")
    plugins: list[PluginRead]


class AssistantCreate(AssistantBase):
    pass


class AssistantUpdate(AssistantBase):
    plugins: list[PluginUpdate] | None = None


class PluginAddToAssistant(SQLModel):
    """
    Schema for the request body when adding a plugin to an assistant.
    """

    registry_id: str


class PluginUpdateOnAssistant(SQLModel):
    """
    Schema for updating a plugin's configuration within an assistant.
    All fields are optional for PATCH functionality.
    """

    enabled: bool | None = None
    tools_default_enabled: bool | None = None
    tools_override: list[dict[str, Any]] | None = None
    user_config_values: dict[str, Any] | None = None


class PluginSpec(SQLModel):
    plugin_id: str
    registry_id: str
    config: dict[str, Any]
    tool_configs: list[dict[str, Any]]


class AssistantSpec(SQLModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    plugins: list[PluginSpec] = []
    description: str
    instructions: str | None = None
