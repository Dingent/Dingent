from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from pydantic import Field as PydField
from sqlalchemy import JSON, Column, LargeBinary, Text
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from dingent.core.assistants.schemas import AssistantSpec, PluginSpec
from dingent.core.db.types import EncryptedJSON, EncryptedString
from dingent.core.types import WorkspaceRole
from dingent.core.utils import normalize_agent_name
from dingent.core.workflows.schemas import ExecutableWorkflow


class ToolOverrideConfig(BaseModel):
    """
    定义存储在数据库 JSON 字段中的单个工具覆盖配置的结构。
    这不是一个数据库表模型。
    """

    name: str = PydField(..., description="要配置的工具的唯一名称")
    enabled: bool = PydField(True, description="此 Assistant 是否启用该工具")
    description: str | None = PydField(None, description="可选的、为此 Assistant 定制的工具描述")
    # 未来可以扩展更多可覆盖的字段


# --- 用户与所有权模型 ---


class UserRoleLink(SQLModel, table=True):
    user_id: UUID = Field(foreign_key="user.id", primary_key=True)
    role_id: int = Field(foreign_key="role.id", primary_key=True)


class Role(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)  # 例如 "admin", "user"
    description: str | None = None

    users: list["User"] = Relationship(back_populates="roles", link_model=UserRoleLink)


class WorkspaceMember(SQLModel, table=True):
    """
    用户与工作空间的多对多关联，包含用户在这个空间的角色（如管理员、普通成员）
    """

    workspace_id: UUID = Field(default_factory=uuid4, foreign_key="workspace.id", primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", primary_key=True)

    role: WorkspaceRole = Field(default="member")
    joined_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    """
    用户模型：系统中的账户主体，所有用户资源都与此模型关联。
    """

    # 基本标识
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    username: str = Field(description="用户昵称，非唯一标识")
    email: str = Field(unique=True, index=True, description="用户邮箱（主要用于登录和通知）")
    roles: list[Role] = Relationship(back_populates="users", link_model=UserRoleLink)
    hashed_password: str
    encrypted_dek: bytes | None = Field(default=None, sa_column=Column(LargeBinary))

    # 用户状态
    is_active: bool = Field(default=True, description="账户是否激活")

    # 个人信息
    full_name: str | None = Field(default=None, description="真实姓名或昵称")
    avatar_url: str | None = Field(default=None, description="头像地址")

    # 审计字段
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def __repr__(self):
        return f"<User {self.username} ({self.email})>"

    # 关系
    resources: list["Resource"] = Relationship(back_populates="created_by", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    workspaces: list["Workspace"] = Relationship(back_populates="members", link_model=WorkspaceMember)


class Workspace(SQLModel, table=True):
    """
    工作空间/团队：资源（Assistant/Workflow）的真正持有者
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str = Field(index=True, description="工作空间的显示名称")
    slug: str = Field(index=True, description="工作空间的唯一标识符，用于 URL 等")
    avatar_url: str | None = Field(default=None, description="工作空间的头像地址")
    description: str | None = None
    allow_guest_access: bool = Field(default=False, index=True, description="是否允许游客访问此工作空间")

    members: list["User"] = Relationship(back_populates="workspaces", link_model=WorkspaceMember)

    assistants: list["Assistant"] = Relationship(back_populates="workspace", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    workflows: list["Workflow"] = Relationship(back_populates="workspace")
    resources: list["Resource"] = Relationship(back_populates="workspace", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    conversations: list["Conversation"] = Relationship(back_populates="workspace", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    model_configs: list["LLMModelConfig"] = Relationship(back_populates="workspace", sa_relationship_kwargs={"foreign_keys": "[LLMModelConfig.workspace_id]"})
    default_model_config_id: UUID | None = Field(default=None, foreign_key="llmmodelconfig.id")
    default_model_config: "LLMModelConfig" = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[Workspace.default_model_config_id]",
            "post_update": True,
        }
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- Assistant、Plugin 及其关联（多对多） ---


class AssistantPluginLink(SQLModel, table=True):
    """
    Assistant 与 Plugin 的多对多链接表；同时保存用户侧配置。
    """

    assistant_id: UUID = Field(
        foreign_key="assistant.id",
        primary_key=True,
        index=True,
    )
    plugin_id: UUID = Field(
        foreign_key="plugin.id",
        primary_key=True,
        index=True,
    )

    enabled: bool = True

    # --- 针对单个工具的覆盖配置 ---
    # 存储一个列表，每个元素都是一个符合 ToolOverrideConfig 结构的字典
    # 例如: [{"name": "get_weather", "enabled": false}, {"name": "send_email", "description": "Send email on behalf of the user"}]
    tool_configs: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(MutableList.as_mutable(JSON)),
    )

    # --- 用户为插件提供的配置值 (如 API Keys) ---
    user_plugin_config: dict[str, Any] | None = Field(
        default_factory=dict,
        sa_column=Column(MutableDict.as_mutable(EncryptedJSON)),
    )

    # 双向关系（注意 back_populates 名称需与目标模型中的属性名对应）
    assistant: "Assistant" = Relationship(back_populates="plugin_links")
    plugin: "Plugin" = Relationship(back_populates="assistant_links")

    def to_spec(self) -> PluginSpec:
        return PluginSpec(
            plugin_id=self.plugin.registry_id,
            registry_id=self.plugin.registry_id,
            config=self.user_plugin_config or {},
            tool_configs=self.tool_configs,
        )


class Assistant(SQLModel, table=True):
    """
    Assistant 模型：属于某个用户；可关联多个 Plugin（多对多）。
    """

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="unique_workspace_assistant_name"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str = Field(index=True)
    description: str | None = None
    instructions: str | None = Field(default=None, sa_column=Column(Text))
    version: str = "0.2.0"
    spec_version: str = "3.0"
    enabled: bool = True

    # 模型配置 (级联策略的最高优先级)
    model_config_id: UUID | None = Field(default=None, foreign_key="llmmodelconfig.id")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    # 外键：多对一 -> User
    created_by_id: UUID | None = Field(default=None, foreign_key="user.id")
    workspace_id: UUID = Field(foreign_key="workspace.id", index=True)  # <-- 新增这行
    workspace: Workspace = Relationship(back_populates="assistants")

    # 多对多：通过 link_model
    plugins: list["Plugin"] = Relationship(
        back_populates="assistants",
        link_model=AssistantPluginLink,
        sa_relationship_kwargs={"overlaps": "assistant,plugin_links"},
    )

    # 提供对链接记录本身的直达访问（便于读写 per-assistant 配置）
    plugin_links: list[AssistantPluginLink] = Relationship(back_populates="assistant", sa_relationship_kwargs={"cascade": "all, delete-orphan"})

    # 一个 Assistant 可被多个 WorkflowNode 引用
    workflow_nodes: list["WorkflowNode"] = Relationship(back_populates="assistant", sa_relationship_kwargs={"cascade": "all, delete-orphan"})

    def to_spec(self) -> AssistantSpec:
        return AssistantSpec(
            id=self.id,
            name=normalize_agent_name(self.name),
            description=self.description or "",
            instructions=self.instructions or "",
            plugins=[pl.to_spec() for pl in self.plugin_links],
        )


class Plugin(SQLModel, table=True):
    """
    插件的全局定义：系统级资源；用户侧配置在 AssistantPluginLink 中。
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    registry_id: str = Field(..., unique=True, index=True)  # 标识插件来源的 ID，如 LOCAL、或某个市场的 ID
    registry_name: str = "Local"
    display_name: str
    description: str
    version: str = "0.1.0"

    config_schema: dict[str, Any] = Field(default=None, sa_column=Column(JSON))

    # 多对多
    assistants: list["Assistant"] = Relationship(
        back_populates="plugins",
        link_model=AssistantPluginLink,
    )

    # 反向访问链接表
    assistant_links: list[AssistantPluginLink] = Relationship(back_populates="plugin", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


# --- Workflow 及其结构 ---


class Workflow(SQLModel, table=True):
    """
    Workflow：属于某个用户，包含节点与边。
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str
    description: str | None = None

    # 模型配置 (级联策略的中等优先级)
    model_config_id: UUID | None = Field(default=None, foreign_key="llmmodelconfig.id")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    # 外键：多对一 -> User
    workspace_id: UUID = Field(foreign_key="workspace.id", index=True)
    workspace: Workspace = Relationship(back_populates="workflows")
    created_by_id: UUID | None = Field(default=None, foreign_key="user.id")

    # 关系
    nodes: list["WorkflowNode"] = Relationship(back_populates="workflow", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    edges: list["WorkflowEdge"] = Relationship(back_populates="workflow", sa_relationship_kwargs={"cascade": "all, delete-orphan"})

    def to_spec(self) -> ExecutableWorkflow:
        """将数据库实体转化为纯业务 Spec"""
        start_node = None
        for n in self.nodes:
            if n.is_start_node:
                start_node = n
        assert start_node is not None, "Workflow must have a start node."
        adjacency_map = defaultdict(list)
        for edge in self.edges:
            src_name = normalize_agent_name(edge.source_node.name)
            tgt_name = normalize_agent_name(edge.target_node.name)
            adjacency_map[src_name].append(tgt_name)

        return ExecutableWorkflow(
            id=self.id,
            name=normalize_agent_name(self.name),
            start_node=normalize_agent_name(start_node.name),
            description=self.description or "",
            assistant_configs={normalize_agent_name(n.name): n.assistant.to_spec() for n in self.nodes},
            adjacency_map=adjacency_map,
        )


class WorkflowNode(SQLModel, table=True):
    """
    Workflow 中的节点：引用一个 Assistant。
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    workflow_id: UUID = Field(foreign_key="workflow.id", index=True)
    assistant_id: UUID = Field(foreign_key="assistant.id", index=True)

    # UI 相关
    type: str = "assistant"
    is_start_node: bool = Field(default=False, index=True)
    position: dict[str, float] = Field(sa_column=Column(MutableDict.as_mutable(JSON)))
    measured: dict[str, float] = Field(default_factory=dict, sa_column=Column(MutableDict.as_mutable(JSON)))
    # 关系：多对一 -> Workflow；多对一 -> Assistant
    workflow: Workflow = Relationship(back_populates="nodes")
    assistant: Assistant = Relationship(back_populates="workflow_nodes")

    @property
    def name(self) -> str:
        return self.assistant.name


class WorkflowEdge(SQLModel, table=True):
    """
    Workflow 中的边：连接两个 WorkflowNode。
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    workflow_id: UUID = Field(foreign_key="workflow.id", index=True)

    source_node_id: UUID = Field(foreign_key="workflownode.id", index=True)
    target_node_id: UUID = Field(foreign_key="workflownode.id", index=True)

    source_node: WorkflowNode = Relationship(sa_relationship_kwargs={"foreign_keys": "[WorkflowEdge.source_node_id]"})
    target_node: WorkflowNode = Relationship(sa_relationship_kwargs={"foreign_keys": "[WorkflowEdge.target_node_id]"})

    # UI 相关
    source_handle: str | None = None
    target_handle: str | None = None
    type: str = "default"
    mode: str = "single"

    workflow: Workflow = Relationship(back_populates="edges")


# --- 运行时数据模型 ---


class Resource(SQLModel, table=True):
    """
    存储工具结果的资源。属于某个用户。
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    version: str = "1.0"
    model_text: str = Field(sa_column=Column(Text))

    display: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    data: dict | str | list | None = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    created_by_id: UUID = Field(foreign_key="user.id", index=True)
    created_by: User = Relationship(back_populates="resources")

    workspace_id: UUID = Field(foreign_key="workspace.id", index=True)
    workspace: Workspace = Relationship(back_populates="resources")


# --- 大模型 --


class LLMModelConfig(SQLModel, table=True):
    """
    统一的模型配置表。
    每一行代表一个可供 Agent 调用的模型实例
    设计上完全对齐 LiteLLM 的参数需求。
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)

    # 归属权：模型配置通常属于一个工作空间，供空间内的成员共享使用
    workspace_id: UUID = Field(foreign_key="workspace.id", index=True)

    # 基础信息
    name: str = Field(description="用户给这个配置起的别名，如 'My Local Llama'")

    # LiteLLM 核心路由参数
    provider: str = Field(index=True, description="litellm provider, e.g., 'openai', 'azure', 'ollama', 'anthropic'")
    model: str = Field(description="实际传递给 provider 的模型名称, e.g., 'gpt-4-turbo', 'llama3'")

    # 连接参数
    api_base: str | None = Field(default=None, description="自定义 Base URL，用于 Ollama/vLLM/OneAPI")
    api_version: str | None = Field(default=None, description="主要用于 Azure OpenAI")

    # 敏感凭证 (存储加密后的 bytes)
    encrypted_api_key: str | None = Field(default=None, sa_type=EncryptedString)

    # 高级参数 (JSON)
    # 存储 temperature, max_tokens, presence_penalty, azure_deployment_name 等
    parameters: dict[str, Any] = Field(default_factory=dict, sa_column=Column(MutableDict.as_mutable(JSON)))

    # 状态
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})
    workspace: Workspace = Relationship(back_populates="model_configs", sa_relationship_kwargs={"foreign_keys": "[LLMModelConfig.workspace_id]"})

    def to_litellm_kwargs(self, decrypted_api_key: str | None) -> dict:
        """
        辅助方法：将数据库记录转换为 litellm.completion() 需要的参数字典
        """
        kwargs = {
            "model": self.model if self.provider == "openai" else f"{self.provider}/{self.model}",
            "api_key": decrypted_api_key,
            "api_base": self.api_base,
            **self.parameters,  # 展开存储的额外 JSON 参数
        }
        # 清理 None 值，避免覆盖 LiteLLM 默认值
        return {k: v for k, v in kwargs.items() if v is not None}


class Conversation(SQLModel, table=True):
    """
    业务层面的对话记录 (Thread)。
    它是 Checkpoint 的父级，用于权限控制和列表展示。
    """

    # 对应 LangGraph 的 thread_id
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True, description="即 LangGraph 的 thread_id")

    workspace_id: UUID = Field(foreign_key="workspace.id", index=True)
    workspace: Workspace = Relationship()

    # 身份标识
    user_id: UUID | None = Field(default=None, foreign_key="user.id", index=True)
    # 允许访客模式 (未登录用户)
    visitor_id: str | None = Field(default=None, index=True)

    title: str = Field(default="New Chat")

    # 统计信息 (可选，但推荐)
    message_count: int = Field(default=0)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    # 关系：一个对话有多个 Checkpoints (历史状态)
    checkpoints: list["LangGraphCheckpoint"] = Relationship(back_populates="conversation", sa_relationship_kwargs={"cascade": "all, delete-orphan"})

    # 关系：一个对话有多个 Writes (中间状态)
    writes: list["LangGraphCheckpointWrite"] = Relationship(back_populates="conversation", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class LangGraphCheckpoint(SQLModel, table=True):
    """
    映射 LangGraph 标准表 `checkpoints`。
    增加了 foreign_key 指向你的 Conversation 表，实现级联删除。
    """

    __tablename__ = "checkpoints"

    thread_id: str = Field(primary_key=True, foreign_key="conversation.id")

    # 复合主键 2: checkpoint_ns (命名空间，默认为空字符串)
    checkpoint_ns: str = Field(default="", primary_key=True)

    # 复合主键 3: checkpoint_id (UUID 字符串)
    checkpoint_id: str = Field(primary_key=True)

    # 上级指针
    parent_checkpoint_id: str | None = Field(default=None)

    type: str = Field(default="msgpack")

    # 核心数据 (Pickle 序列化)
    checkpoint: bytes = Field(sa_column=Column(LargeBinary))

    # 元数据
    metadata_: dict = Field(
        default_factory=dict,
        sa_column=Column("metadata", LargeBinary),  # 映射到数据库列名 "metadata"
    )

    # 关系回溯
    conversation: Conversation = Relationship(back_populates="checkpoints")


class LangGraphCheckpointWrite(SQLModel, table=True):
    """
    映射 LangGraph 标准表 `checkpoint_writes`。
    """

    __tablename__ = "writes"  # 强制使用 LangGraph 默认表名

    thread_id: str = Field(primary_key=True, foreign_key="conversation.id")
    checkpoint_ns: str = Field(default="", primary_key=True)
    checkpoint_id: str = Field(primary_key=True)
    task_id: str = Field(primary_key=True)
    idx: int = Field(primary_key=True)

    channel: str
    type: str = Field(default="msgpack")

    value: bytes = Field(sa_column=Column(LargeBinary))

    conversation: Conversation = Relationship(back_populates="writes")
