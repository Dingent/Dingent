import ast
import json
from uuid import UUID

from fastapi import HTTPException, status
from jsonschema import ValidationError, validate
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from dingent.core.assistants.schemas import AssistantCreate, AssistantUpdate, PluginUpdateOnAssistant
from dingent.core.db.models import Assistant, AssistantPluginLink, Plugin


def _preprocess_json_fields(config_data: dict, schema: dict | None):
    """
    尝试解析 JSON 字符串。
    策略：先尝试标准 JSON 解析，如果失败，再尝试 Python 字面量解析（支持单引号）。
    """
    if not schema or not config_data:
        return

    properties = schema.get("properties", {})

    for key, value in config_data.items():
        # 如果不是字符串，说明不需要解析，跳过
        if not isinstance(value, str):
            continue

        field_def = properties.get(key)
        if not field_def:
            continue

        expected_type = field_def.get("type")

        # 针对 object (dict) 和 array (list) 类型尝试解析
        if expected_type in ["object", "array"]:
            parsed_value = None

            # --- 方案 1: 尝试标准 JSON 解析 (最快，最标准) ---
            try:
                parsed_value = json.loads(value)
            except json.JSONDecodeError as json_err:
                # --- 方案 2: JSON 失败，尝试 Python 字面量解析 (支持单引号) ---
                try:
                    # ast.literal_eval 只能解析基础数据结构，非常安全，不会执行恶意代码
                    parsed_value = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    # 如果两个都失败了，抛出原始的 JSON 错误，提示用户格式不对
                    # 也可以把 json_err 和 ast 的错误一起 log 出来
                    raise HTTPException(
                        status_code=400, detail=(f"Field '{key}' invalid. Expected valid JSON (double quotes) or Python dict (single quotes). Error: {str(json_err)}")
                    )

            # --- 解析成功，检查类型是否匹配 ---
            # json.loads 可能把 "123" 解析成 int，但我们需要 object/list
            # 注意：Python 中 dict 对应 JSON object, list 对应 JSON array
            if expected_type == "object" and not isinstance(parsed_value, dict):
                raise HTTPException(status_code=400, detail=f"Field '{key}' parsed successfully but result is not a Dictionary.")

            if expected_type == "array" and not isinstance(parsed_value, list):
                raise HTTPException(status_code=400, detail=f"Field '{key}' parsed successfully but result is not a List.")

            # --- 原地更新配置 ---
            config_data[key] = parsed_value


def get_assistant_by_id(*, db: Session, id: UUID):
    return db.get(Assistant, id)


def get_assistant_by_name(db: Session, workspace_id: UUID, name: str) -> Assistant | None:
    """
    修改：现在在 workspace 范围内查找同名 Assistant
    """
    return db.exec(select(Assistant).where(Assistant.workspace_id == workspace_id, Assistant.name == name)).first()


def get_workspace_assistant(db: Session, assistant_id: UUID, workspace_id: UUID) -> Assistant | None:
    """
    修改：验证 Assistant 是否属于该 Workspace
    原名: get_user_assistant
    """
    return db.exec(select(Assistant).where(Assistant.id == assistant_id, Assistant.workspace_id == workspace_id)).first()


def get_all_assistants(db: Session, workspace_id: UUID) -> list[Assistant]:
    """
    修改：获取该 Workspace 下的所有 Assistant
    """
    statement = select(Assistant).where(Assistant.workspace_id == workspace_id)
    results = db.exec(statement).all()
    results = list(results)
    return results


def create_assistant(db: Session, assistant_in: AssistantCreate, workspace_id: UUID, user_id: UUID) -> Assistant:
    """
    修改：
    1. 接收 workspace_id 作为资源归属。
    2. 接收 user_id 作为 created_by_id (审计用)。
    """
    # 构造数据：必须包含 workspace_id，可选包含 created_by_id
    db_obj_data = assistant_in.model_dump()

    new_assistant = Assistant(
        **db_obj_data,
        workspace_id=workspace_id,
        created_by_id=user_id,  # 记录是谁创建的
    )

    db.add(new_assistant)
    try:
        db.commit()
        db.refresh(new_assistant)
    except IntegrityError:
        db.rollback()
        # 错误信息现在反映的是 Workspace 内的冲突
        raise HTTPException(
            status_code=409,
            detail=f"Assistant with name '{assistant_in.name}' already exists in this workspace.",
        )

    return new_assistant


def remove_assistant(db: Session, *, id: UUID) -> Assistant | None:
    """
    保持不变。
    注意：在调用此函数前的 API 层（Router），你应该先调用 get_workspace_assistant
    来确保当前用户有权限删除这个 Workspace 下的 Assistant。
    """
    assistant_to_delete = db.get(Assistant, id)

    if not assistant_to_delete:
        return None

    db.delete(assistant_to_delete)
    db.commit()

    return assistant_to_delete


def update_assistant(
    db: Session,
    db_assistant: Assistant,
    assistant_in: AssistantUpdate,
) -> Assistant:
    """
    逻辑基本保持不变。
    """
    update_data = assistant_in.model_dump(exclude={"plugins"}, exclude_unset=True)
    for k, v in update_data.items():
        setattr(db_assistant, k, v)

    if assistant_in.plugins:
        # 建立索引：plugin_registry_id -> link 对象
        link_by_registry_id: dict[str, AssistantPluginLink] = {link.plugin.registry_id: link for link in db_assistant.plugin_links}

        for plugin_cfg in assistant_in.plugins:
            link = link_by_registry_id.get(plugin_cfg.registry_id)
            if link is None:
                continue

            plugin_update_data = plugin_cfg.model_dump(exclude_unset=True)

            # 更新 enabled 状态
            if "enabled" in plugin_update_data:
                link.enabled = plugin_cfg.enabled

            # 处理 config 更新与验证
            if "config" in plugin_update_data:
                new_conf = plugin_update_data["config"] or {}

                schema = link.plugin.config_schema
                _preprocess_json_fields(new_conf, schema)

                current_conf = link.user_plugin_config or {}

                merged_conf = current_conf.copy()
                merged_conf.update(new_conf)

                if schema:
                    try:
                        validate(instance=merged_conf, schema=schema)
                    except ValidationError as e:
                        raise HTTPException(status_code=400, detail=f"Plugin '{plugin_cfg.registry_id}' configuration error: {e.message}")

                link.user_plugin_config = merged_conf
            if "tool_configs" in plugin_update_data:
                new_tool_confs = plugin_update_data["tool_configs"] or []

                link.tool_configs = new_tool_confs

    db.add(db_assistant)
    db.commit()
    db.refresh(db_assistant)
    return db_assistant


def add_plugin_to_assistant(db: Session, *, assistant_id: UUID, plugin_registry_id: str) -> Assistant:
    """
    Links an existing plugin to an assistant by creating an AssistantPluginLink record.

    This function performs crucial validation:
    1. Checks if the plugin exists.
    2. Checks if the plugin is already linked to the assistant to prevent duplicates.
    """
    # 1. 验证 Plugin 是否存在
    # plugin = db.get(Plugin, plugin_id)
    plugin = db.exec(select(Plugin).where(Plugin.registry_id == plugin_registry_id)).first()
    if not plugin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Plugin with id {plugin_registry_id} not found.")

    # 2. 验证是否已经存在链接，防止重复添加
    plugin_pk = plugin.id
    existing_link = db.exec(select(AssistantPluginLink).where(AssistantPluginLink.assistant_id == assistant_id, AssistantPluginLink.plugin_id == plugin_pk)).first()

    if existing_link:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Plugin '{plugin.display_name}' is already added to assistant '{assistant_id}'.")

    # 3. 创建链接记录
    assistant = db.get(Assistant, assistant_id)
    if not assistant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Assistant with id {assistant_id} not found.")
    link = AssistantPluginLink(assistant_id=assistant.id, plugin_id=plugin.id)
    db.add(link)
    db.commit()

    # 刷新 assistant 对象以加载新的 plugin_links 关系
    db.refresh(assistant)

    return assistant


def update_plugin_on_assistant(db: Session, *, assistant_id: UUID, plugin_id: UUID, plugin_update: PluginUpdateOnAssistant) -> Assistant:
    """
    Updates the configuration of a plugin for a specific assistant.
    """
    # 1. Find the specific link to update
    statement = select(AssistantPluginLink).where(AssistantPluginLink.assistant_id == assistant_id, AssistantPluginLink.plugin_id == plugin_id)
    link_to_update = db.exec(statement).first()

    if not link_to_update:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This plugin is not associated with the assistant")

    # 2. Get update data, excluding fields that were not sent
    update_dict = plugin_update.model_dump(exclude_unset=True)
    assistant = db.get(Assistant, assistant_id)
    if not assistant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Assistant with id {assistant_id} not found.")
    if not update_dict:
        # No changes were requested
        return assistant

    # 3. Apply the changes
    for key, value in update_dict.items():
        setattr(link_to_update, key, value)

    db.add(link_to_update)
    db.commit()
    db.refresh(assistant)

    return assistant


def remove_plugin_from_assistant(db: Session, *, assistant_id: UUID, registry_id: str) -> None:
    """
    Removes the link between a plugin and an assistant. This is an idempotent operation.
    """
    # 1. Find the specific link to delete
    plugin_statement = select(Plugin).where(Plugin.registry_id == registry_id)
    plugin = db.exec(plugin_statement).first()
    if not plugin:
        return
    statement = select(AssistantPluginLink).where(AssistantPluginLink.assistant_id == assistant_id, AssistantPluginLink.plugin_id == plugin.id)
    link_to_delete = db.exec(statement).first()

    # 2. If the link exists, delete it. If not, do nothing (idempotency).
    if link_to_delete:
        db.delete(link_to_delete)
        db.commit()

    return
