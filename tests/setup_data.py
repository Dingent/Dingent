from datetime import datetime
import uuid
from sqlmodel import Session

from dingent.core.db.models import Assistant, AssistantPluginLink, Plugin, Workflow, WorkflowEdge, WorkflowNode


def mock_full_single_cell_data(workspace_id, session: Session):
    """
    插入完整的 single-cell 模拟数据，包括：
    1. Plugins (Bio Data Loader, Single Cell Analyzer)
    2. Assistants (DataGetter, Analyst)
    3. AssistantPlugin (关联配置)
    4. Workflow & Nodes & Edges
    """

    # ==========================================
    # 1. 预先生成所有需要的 UUID
    # ==========================================
    # Workflow 相关
    wf_id = uuid.uuid4()
    node_start_id = uuid.uuid4()
    node_second_id = uuid.uuid4()

    user_id = uuid.uuid4()  # created_by_id

    # Assistant & Plugin 相关
    plugin_loader_id = uuid.uuid4()  # 对应 bio-data-loader
    plugin_analyzer_id = uuid.uuid4()  # 对应 single-cell-analyzer

    assist_getter_id = uuid.uuid4()  # 对应 DataGetter
    assist_analyst_id = uuid.uuid4()  # 对应 Analyst

    now = datetime.utcnow()

    # ==========================================
    # 2. 创建 Plugins
    # ==========================================
    plugin_loader = Plugin(
        id=plugin_loader_id,
        registry_id="bio-data-loader",
        registry_name="Local",
        display_name="Bio Data Loader",
        description="Bio Data Loader",
        version="1.1.0",
        config_schema={},  # JSON 字段
    )

    plugin_analyzer = Plugin(
        id=plugin_analyzer_id,
        registry_id="Single-Cell-Analyzer",
        registry_name="Local",
        display_name="Single Cell Analyzer",
        description="Single Cell Analyzer",
        version="1.0.0",
        config_schema={},
    )

    # ==========================================
    # 3. 创建 Assistants
    # ==========================================
    # Assistant 1: DataGetter
    assist_getter = Assistant(
        id=assist_getter_id,
        name="DataGetter",
        description="No description",
        version="0.2.0",
        spec_version="2.0",
        enabled=True,
        model_config_id=None,
        created_at=now,
        updated_at=now,
        # created_by_id=user_id,
        workspace_id=workspace_id,
        instructions=(
            "You are an expert Data Engineer specializing in Single-Cell Sequencing data preparation. "
            "Your sole objective is to provide a clean, standardized `.h5ad` file path for downstream analysis.\n\n"
            "**Workflow Protocol:**\n\n"
            "1.  **Input Analysis**:\n"
            "    * If the user"
        ),
    )

    # Assistant 2: Analyst
    assist_analyst = Assistant(
        id=assist_analyst_id,
        name="Analyst",
        description=(
            "### 🔬 Single-Cell Analyzer MCP\n\n"
            "A specialized bioinformatics toolkit designed to transform processed single-cell data (.h5ad) "
            "into biological insights and visual reports.\n\n"
            "**Core Capabilities:**\n"
            "* **QC & Filtering**: Automatically filters low-quality cel"
        ),
        version="0.2.0",
        spec_version="2.0",
        enabled=True,
        model_config_id=None,
        created_at=now,
        updated_at=now,
        # created_by_id=user_id,
        workspace_id=workspace_id,
        instructions=(
            "You are a Senior Computational Biologist. Your goal is to analyze single-cell data (`.h5ad`) "
            "and generate a scientifically meaningful report.\n\n"
            "**Analysis Pipeline (Execute in Order):**\n\n"
            "1.  **Quality Control (QC)**:\n"
            "    * Run `quality_control_analysis` fi"
        ),
    )

    # ==========================================
    # 4. 创建 AssistantPlugin (关联表)
    # ==========================================
    # 关联: DataGetter -> Bio Data Loader
    ap_getter = AssistantPluginLink(
        assistant_id=assist_getter_id,
        plugin_id=plugin_loader_id,
        enabled=True,
        tool_configs=[],  # JSON List
    )

    # 关联: Analyst -> Single Cell Analyzer
    ap_analyst = AssistantPluginLink(
        assistant_id=assist_analyst_id,
        plugin_id=plugin_analyzer_id,
        enabled=True,
        tool_configs=[],
    )

    # ==========================================
    # 5. 创建 Workflow & Nodes (引用上面的 Assistant ID)
    # ==========================================
    workflow = Workflow(
        id=wf_id,
        name="single-cell",
        created_at=now,
        updated_at=now,
        workspace_id=workspace_id,
        # created_by_id=user_id,
    )

    # Node 1: 使用 DataGetter (Start Node)
    node_start = WorkflowNode(
        id=node_start_id,
        workflow_id=wf_id,
        assistant_id=assist_getter_id,  # <--- 引用 DataGetter
        type="assistant",
        is_start_node=True,
        position={"x": 62.33331298828125, "y": 266.3333282470703},
        measured={"width": 100.0, "height": 80.0},
    )

    # Node 2: 使用 Analyst
    node_second = WorkflowNode(
        id=node_second_id,
        workflow_id=wf_id,
        assistant_id=assist_analyst_id,  # <--- 引用 Analyst
        type="assistant",
        is_start_node=False,
        position={"x": 254.99996948242188, "y": 290.99999237060547},
        measured={"width": 100.0, "height": 80.0},
    )

    edge = WorkflowEdge(
        id=uuid.uuid4(),
        workflow_id=wf_id,
        source_node_id=node_start_id,
        target_node_id=node_second_id,
        source_handle="right-out",
        target_handle="left-in",
        type="directional",
        mode="single",
    )

    # ==========================================
    # 6. 提交到数据库
    # ==========================================
    # 添加 Plugins
    session.add(plugin_loader)
    session.add(plugin_analyzer)

    # 添加 Assistants
    session.add(assist_getter)
    session.add(assist_analyst)

    # 添加 AssistantPlugins (如果这是中间表对象)
    # 注意：如果你的 Assistant 模型有关联属性 (e.g. assistant.plugins.append)，也可以用那种方式。
    # 这里假设是手动操作中间表对象：
    session.add(ap_getter)
    session.add(ap_analyst)

    # 添加 Workflow
    session.add(workflow)
    session.add(node_start)
    session.add(node_second)
    session.add(edge)

    session.commit()

    return {
        "workflow": workflow,
        "assistants": {"getter": assist_getter, "analyst": assist_analyst},
        "nodes": [node_start, node_second],
    }
