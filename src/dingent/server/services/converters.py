from dingent.core.assistants.assistant import AssistantRuntime
from dingent.core.assistants.schemas import AssistantRead
from dingent.core.db.models import Assistant, AssistantPluginLink
from dingent.core.plugins.plugin import PluginRuntime
from dingent.core.plugins.schemas import PluginConfigItemRead, PluginRead, ToolConfigItemRead


async def _build_plugin_read(plugin_link: AssistantPluginLink, runtime_plugin: PluginRuntime | None) -> PluginRead:
    """
    辅助函数：从数据库和运行时模型构建单个 PluginRead DTO。
    """
    plugin_db = plugin_link.plugin

    # 1. 处理 Tools (保持原有逻辑不变，除非 Runtime 也有变动)
    plugin_status = "inactive"
    merged_tools: list[ToolConfigItemRead] = []

    if runtime_plugin:
        plugin_status = runtime_plugin.status
        if plugin_status == "active":
            # 获取运行时工具列表
            tools = await runtime_plugin.list_tools()
            # 获取数据库中关于工具的配置（开关状态）
            db_tool_configs = {item["name"]: item for item in plugin_link.tool_configs}

            for tool in tools:
                tool_config = db_tool_configs.get(tool.name, {})
                merged_tool = ToolConfigItemRead(
                    name=tool.name,
                    enabled=tool_config.get("enabled", True),
                    description=tool_config.get("description", tool.description),
                )
                merged_tools.append(merged_tool)

    # 2. 处理 Config (核心修改部分)
    # 获取用户当前存储的值
    current_values = plugin_link.user_plugin_config or {}

    # 获取标准 JSON Schema 定义
    # 数据库现在存的是 {"type": "object", "properties": {...}, "required": [...]}
    json_schema = plugin_db.config_schema or {}

    properties = json_schema.get("properties", {})
    required_fields = set(json_schema.get("required", []))  # 转为集合查询更快

    merged_config: list[PluginConfigItemRead] = []

    for field_key, field_def in properties.items():
        # field_def 是单个属性的定义 dict

        # 提取基础信息
        field_type = field_def.get("type", "string")
        description = field_def.get("description", "")
        title = field_def.get("title", field_key)  # 如果没有 title 就用 key
        default_val = field_def.get("default")
        raw_value = current_values.get(field_key)

        final_value = raw_value
        if field_type in ["object", "dict"] and raw_value is not None:
            final_value = str(raw_value)

        # 判断是否必填
        is_required = field_key in required_fields

        # 判断是否敏感字段
        is_secret = field_def.get("writeOnly", False) or field_def.get("x-ui-secret", False)

        item = PluginConfigItemRead(
            name=field_key,
            title=title,
            type=field_type,
            description=description,
            default=default_val,
            required=is_required,
            secret=is_secret,
            value=final_value,
        )
        merged_config.append(item)

    return PluginRead(
        registry_id=plugin_db.registry_id,
        display_name=plugin_db.display_name,
        description=plugin_db.description,
        enabled=plugin_link.enabled,
        status=plugin_status,
        version=plugin_db.version,
        tools=merged_tools,
        config=merged_config,
    )


async def _build_assistant_read(assistant: Assistant, runtime_assistant: AssistantRuntime | None) -> AssistantRead:
    """
    主映射函数：从 Assistant 的持久化模型和运行时模型构建 AssistantRead DTO。
    """
    # 校验输入的一致性
    if runtime_assistant:
        assert assistant.id == runtime_assistant.id, "Mismatched Assistant and AssistantRuntime IDs"

    # 确定顶层状态
    assistant_status = "active" if runtime_assistant else "inactive"

    # 可以在这里加入更复杂的逻辑，例如检查runtime_assistant内部的错误状态
    # if runtime_assistant and runtime_assistant.has_error:
    #     assistant_status = "error"

    # 递归构建嵌套的 plugins 列表
    plugins_read_list: list[PluginRead] = []
    for plugin_link in assistant.plugin_links:
        runtime_plugin = None
        if runtime_assistant:
            # 从运行时实例中通过 ID 找到对应的插件实例
            runtime_plugin = runtime_assistant.plugin_instances.get(str(plugin_link.plugin.registry_id))

        # 调用辅助函数来构建每个 PluginRead 对象
        plugin_read_dto = await _build_plugin_read(plugin_link, runtime_plugin)
        plugins_read_list.append(plugin_read_dto)

    # 4. 组装并返回最终的 AssistantRead 对象
    return AssistantRead(
        id=str(assistant.id),
        name=assistant.name,
        description=assistant.description or "No description",
        instructions=assistant.instructions,
        status=assistant_status,
        plugins=plugins_read_list,
        version=assistant.version,
        spec_version=assistant.spec_version,
        enabled=assistant.enabled,
        model_config_id=assistant.model_config_id,
    )
