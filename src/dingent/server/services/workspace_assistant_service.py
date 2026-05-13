from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from dingent.core.assistants.assistant import AssistantRuntime
from dingent.core.assistants.assistant_factory import AssistantFactory
from dingent.core.assistants.schemas import AssistantCreate, AssistantRead, AssistantUpdate, PluginUpdateOnAssistant
from dingent.core.db.crud import assistant as crud_assistant
from dingent.core.db.models import Assistant

from .converters import _build_assistant_read


class WorkspaceAssistantService:
    def __init__(
        self,
        workspace_id: UUID,
        session: Session,
        assistant_factory: AssistantFactory,
    ):
        self.workspace_id = workspace_id
        self.session = session
        self._assistant_factory = assistant_factory
        self._runtimes: dict[UUID, AssistantRuntime] = {}  # 请求内缓存

    async def get_runtime_assistant(self, assistant_id: UUID) -> AssistantRuntime:
        # 1. 检查请求内缓存
        if assistant_id in self._runtimes:
            return self._runtimes[assistant_id]

        # 2. 缓存未命中，从数据库加载用户特定的配置
        #    这是 Service 的职责：处理权限和用户数据
        assistant_config = crud_assistant.get_workspace_assistant(db=self.session, assistant_id=assistant_id, workspace_id=self.workspace_id)

        if not assistant_config or not assistant_config.enabled:
            raise ValueError(f"Assistant '{assistant_id}' not found or disabled for workspace '{self.workspace_id}'.")

        # 3. 调用 Core Manager 来执行复杂的构建任务
        inst = await self._assistant_factory.create_runtime(assistant_config)

        # 4. 缓存结果并返回
        self._runtimes[assistant_id] = inst
        return inst

    async def get_all_runtime_assistants(self) -> dict[UUID, AssistantRuntime]:
        assistant_configs = crud_assistant.get_all_assistants(
            db=self.session,
            workspace_id=self.workspace_id,
        )
        if not assistant_configs:
            return {}
        for assistant in assistant_configs:
            if assistant.id not in self._runtimes and assistant.enabled:
                try:
                    inst = await self._assistant_factory.create_runtime(assistant)
                    self._runtimes[assistant.id] = inst
                except Exception:
                    pass
        return self._runtimes

    async def get_assistant_details(
        self,
        assistant_id: UUID,
    ) -> AssistantRead | None:
        """
        一个完整的服务函数：获取数据、处理逻辑、并返回 API 模型。
        """
        # 1. 从数据库获取
        assistant_db = crud_assistant.get_assistant_by_id(
            db=self.session,
            id=assistant_id,
        )
        if not assistant_db:
            return None

        # 2. 从管理器获取运行时状态
        runtime_assistant = None
        try:
            runtime_assistant = await self.get_runtime_assistant(assistant_id)
        except Exception:
            # 可以记录日志等
            pass

        # 3. 调用映射函数进行转换
        assistant_dto = await _build_assistant_read(assistant_db, runtime_assistant)

        return assistant_dto

    async def get_all_assistant_details(
        self,
        workspace_id: UUID,
    ) -> list[AssistantRead]:
        """
        一个完整的服务函数：获取所有 Assistant 的数据、处理逻辑、并返回 API 模型列表。
        采用批量操作以提高效率。
        """
        all_assistants_db = crud_assistant.get_all_assistants(db=self.session, workspace_id=workspace_id)

        all_runtime_assistants = await self.get_all_runtime_assistants()

        assistant_dto_list: list[AssistantRead] = []
        for assistant_db in all_assistants_db:
            runtime_assistant = all_runtime_assistants.get(assistant_db.id)

            assistant_dto = await _build_assistant_read(assistant_db, runtime_assistant)
            assistant_dto_list.append(assistant_dto)

        return assistant_dto_list

    async def create_assistant(
        self,
        assistant_in: AssistantCreate,
        user_id: UUID,
        workspace_id: UUID,
    ) -> AssistantRead:
        """
        一个完整的服务函数：校验数据、创建 Assistant、处理异常并返回 API 模型。
        """
        existing_assistant = crud_assistant.get_assistant_by_name(db=self.session, workspace_id=workspace_id, name=assistant_in.name)
        if existing_assistant:
            raise HTTPException(
                status_code=409,  # 409 Conflict 是表示资源冲突的正确状态码
                detail=f"An assistant with the name '{assistant_in.name}' already exists for this user.",
            )

        runtime_assistant = None
        db = self.session
        try:
            assistant_db = crud_assistant.create_assistant(
                db=self.session,
                workspace_id=workspace_id,
                user_id=user_id,
                assistant_in=assistant_in,
            )

            db.commit()
            db.refresh(assistant_db)

        except IntegrityError:
            db.rollback()  # 出现异常，回滚事务
            raise HTTPException(status_code=409, detail=f"An assistant with the name '{assistant_in.name}' was created just now. Please try a different name.")
        except Exception:
            db.rollback()
            raise HTTPException(status_code=500, detail="An internal error occurred while saving the assistant.")
        try:
            runtime_assistant = await self.get_runtime_assistant(assistant_db.id)
        except Exception:
            pass
        assistant_dto = _build_assistant_read(assistant_db, runtime_assistant)

        return await assistant_dto

    async def update_assistant(
        self,
        assistant_id: UUID,
        assistant_in: AssistantUpdate,
    ) -> AssistantRead:
        """
        更新一个 Assistant。
        """
        # 1. 获取数据库中的现有对象，同时验证所有权
        assistant_db = crud_assistant.get_workspace_assistant(
            db=self.session,
            assistant_id=assistant_id,
            workspace_id=self.workspace_id,
        )
        if not assistant_db:
            raise HTTPException(status_code=404, detail=f"Assistant with id '{assistant_id}' not found.")

        # 2. 如果名称被更改，检查新名称是否与该用户的其他助手冲突
        if assistant_in.name and assistant_in.name != assistant_db.name:
            existing_assistant = crud_assistant.get_assistant_by_name(
                db=self.session,
                name=assistant_in.name,
                workspace_id=self.workspace_id,
            )
            if existing_assistant and existing_assistant.id != assistant_id:
                raise HTTPException(
                    status_code=409,
                    detail=f"An assistant with the name '{assistant_in.name}' already exists.",
                )

        # 3. 更新数据库记录
        try:
            assistant_db = crud_assistant.update_assistant(db=self.session, db_assistant=assistant_db, assistant_in=assistant_in)
            self.session.commit()
            self.session.refresh(assistant_db)
        except Exception:
            self.session.rollback()
            raise

        # 4. 清除旧的缓存，因为配置可能已更改
        if assistant_id in self._runtimes:
            del self._runtimes[assistant_id]

        # 5. 尝试用新配置创建运行时实例
        runtime_assistant = None
        try:
            runtime_assistant = await self.get_runtime_assistant(assistant_db.id)
        except Exception as e:
            print(f"Could not get runtime for updated assistant {assistant_id}: {e}")
            pass

        # 6. 构建并返回 DTO
        assistant_dto = _build_assistant_read(assistant_db, runtime_assistant)
        return await assistant_dto

    async def delete_assistant(self, assistant_id: UUID) -> Assistant:
        """
        Deletes an assistant.
        """
        assistant_to_delete = crud_assistant.get_workspace_assistant(
            db=self.session,
            assistant_id=assistant_id,
            workspace_id=self.workspace_id,
        )
        if not assistant_to_delete:
            raise HTTPException(status_code=404, detail=f"Assistant with id '{assistant_id}' not found.")

        try:
            deleted_assistant = crud_assistant.remove_assistant(db=self.session, id=assistant_id)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise HTTPException(status_code=500, detail="An internal error occurred while deleting the assistant.")

        if assistant_id in self._runtimes:
            del self._runtimes[assistant_id]

        if not deleted_assistant:
            raise HTTPException(status_code=404, detail=f"Assistant with id '{assistant_id}' could not be deleted because it does not exist.")

        return deleted_assistant

    async def add_plugin_to_assistant(self, assistant_id: UUID, plugin_registry_id: str) -> AssistantRead:
        crud_assistant.add_plugin_to_assistant(db=self.session, assistant_id=assistant_id, plugin_registry_id=plugin_registry_id)
        assistant_dto = await self.get_assistant_details(assistant_id)
        if assistant_dto is None:
            raise RuntimeError("Assistant unexpectedly deleted during operation")
        return assistant_dto

    async def update_plugin_on_assistant(self, assistant_id: UUID, plugin_id: UUID, plugin_update: PluginUpdateOnAssistant) -> AssistantRead:
        crud_assistant.update_plugin_on_assistant(
            db=self.session,
            assistant_id=assistant_id,
            plugin_id=plugin_id,
            plugin_update=plugin_update,
        )
        assistant_dto = await self.get_assistant_details(assistant_id)
        if assistant_dto is None:
            raise RuntimeError("Assistant unexpectedly deleted during operation")
        return assistant_dto

    async def remove_plugin_from_assistant(self, assistant_id: UUID, registry_id: str) -> None:
        crud_assistant.remove_plugin_from_assistant(db=self.session, assistant_id=assistant_id, registry_id=registry_id)
        if assistant_id in self._runtimes:
            del self._runtimes[assistant_id]
        return
