from typing import Any
from fastmcp import FastMCP
import scanpy as sc
import matplotlib.pyplot as plt
import io
import os
import base64
import json

# 创建 MCP Server
mcp = FastMCP("Single-Cell-Analyzer")

# --- 1. 全局图片缓存 (关键修改) ---
# 用于在内存中临时存储 Base64 图片数据，避免 LLM 上下文溢出
IMAGE_STORE = {}

# 全局绘图设置
sc.settings.set_figure_params(dpi=100, frameon=False, vector_friendly=True, color_map="viridis")
plt.switch_backend("Agg")


def get_top_markers_text(adata, n_top=5):
    """提取每个簇的前 n 个 Marker 基因，返回文本供 LLM 阅读"""
    result = {}
    groups = adata.uns["rank_genes_groups"]["names"].dtype.names
    for group in groups:
        genes = [str(adata.uns["rank_genes_groups"]["names"][i][group]) for i in range(n_top)]
        result[group] = genes
    return json.dumps(result, indent=2)


def save_plot_to_store(image_key: str) -> str:
    """
    将当前 Matplotlib 图片转换为 Base64，存入全局缓存，并返回 Base64 字符串。
    Args:
        image_key: 图片的唯一标识符 (例如 'qc_plot')
    """
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    b64_str = base64.b64encode(buf.read()).decode("utf-8")
    plt.close()

    # 构造完整的 Data URI
    full_b64 = f"data:image/png;base64,{b64_str}"

    # 存入全局缓存
    IMAGE_STORE[image_key] = full_b64

    return full_b64


def format_response(model_text: str, display_title: str, markdown_content: str) -> dict[str, Any]:
    return {
        "model_text": model_text,
        "display": [{"type": "markdown", "title": display_title, "content": markdown_content}],
    }


@mcp.tool()
def quality_control_analysis(file_path: str) -> dict[str, Any]:
    """
    执行质量控制 (QC)。
    分析完成后，图片会被缓存为 ID: 'qc_plot'。
    """
    if not os.path.exists(file_path):
        return {"model_text": "Error: File not found.", "display": []}

    adata = sc.read_h5ad(file_path)

    # 计算指标
    adata.var["mt"] = adata.var_names.str.startswith("MT-")
    sc.pp.calculate_qc_metrics(adata, qc_vars=["mt"], percent_top=None, log1p=False, inplace=True)

    # 绘图
    sc.pl.violin(
        adata,
        ["n_genes_by_counts", "total_counts", "pct_counts_mt"],
        jitter=0.4,
        multi_panel=True,
        show=False,
    )

    # --- 保存到缓存，Key 为 'qc_plot' ---
    img_b64 = save_plot_to_store("qc_plot")

    # 数据过滤
    original_cells = adata.n_obs
    adata = adata[adata.obs.n_genes_by_counts < 2500, :]
    adata = adata[adata.obs.pct_counts_mt < 5, :]
    remaining_cells = adata.n_obs

    new_path = file_path.replace(".h5ad", "_qc.h5ad")
    adata.write(new_path)

    # --- 告诉 LLM 图片 ID ---
    model_msg = (
        f"QC Analysis completed.\n"
        f"Original: {original_cells}, Remaining: {remaining_cells}.\n"
        f"Filtered data saved to: {new_path}.\n"
        f"IMPORTANT: The QC plot has been cached with ID 'qc_plot'. "
        f"When generating the report, use the placeholder {{{{qc_plot}}}} to insert it."
    )

    display_content = f"### 🧬 质量控制分析结果\n- **过滤前**: {original_cells}\n- **过滤后**: {remaining_cells}\n![QC Plot]({img_b64})"

    return format_response(model_msg, "QC Analysis Result", display_content)


@mcp.tool()
def run_clustering_and_umap(file_path: str) -> dict[str, Any]:
    """
    运行聚类。
    分析完成后，图片会被缓存为 ID: 'umap_plot'。
    """
    adata = sc.read_h5ad(file_path)

    # (标准分析流程，简化展示)
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, min_mean=0.0125, max_mean=3, min_disp=0.5)
    adata = adata[:, adata.var.highly_variable]
    sc.pp.scale(adata, max_value=10)
    sc.tl.pca(adata)
    sc.pp.neighbors(adata)
    sc.tl.leiden(adata)
    sc.tl.umap(adata)

    # 绘图
    sc.pl.umap(adata, color=["leiden"], title="Cell Clusters", show=False)

    # --- 保存到缓存，Key 为 'umap_plot' ---
    img_b64 = save_plot_to_store("umap_plot")

    num_clusters = len(adata.obs["leiden"].unique())
    new_path = file_path.replace(".h5ad", "_processed.h5ad")
    adata.write(new_path)

    model_msg = (
        f"Clustering completed. Found {num_clusters} clusters.\n"
        f"IMPORTANT: The UMAP plot has been cached with ID 'umap_plot'. "
        f"When generating the report, use the placeholder {{{{umap_plot}}}} to insert it."
        f" Data saved to: {new_path}."
    )

    display_content = f"### 🗺️ 聚类结果 (UMAP)\n共发现 **{num_clusters}** 个细胞簇。\n![UMAP Plot]({img_b64})"

    return format_response(model_msg, "Clustering Visualization", display_content)


@mcp.tool()
def find_marker_genes(file_path: str, groupby: str = "leiden") -> dict[str, Any]:
    """
    计算差异表达基因 (Marker Genes)，用于鉴定细胞类型。
    分析完成后，Dotplot 图片会被缓存为 ID: 'marker_plot'。
    """
    adata = sc.read_h5ad(file_path)

    # 确保已经做过聚类
    if groupby not in adata.obs:
        return {
            "model_text": f"Error: '{groupby}' not found. Run clustering first.",
            "display": [],
        }

    # 计算差异基因 (Wilcoxon rank-sum)
    sc.tl.rank_genes_groups(adata, groupby, method="wilcoxon")

    # 绘图：Dotplot 是最直观的 Marker 展示方式
    sc.pl.rank_genes_groups_dotplot(adata, n_genes=5, show=False)
    img_b64 = save_plot_to_store("marker_plot")

    # 提取 Top 基因列表给 LLM
    top_genes_json = get_top_markers_text(adata, n_top=5)

    # 保存结果
    new_path = file_path.replace(".h5ad", "_markers.h5ad")
    adata.write(new_path)

    model_msg = (
        f"Marker gene analysis completed.\n"
        f"Top 5 genes per cluster identified: {top_genes_json}\n"  # 把基因直接给 LLM，让 LLM 进行生物学注释
        f"IMPORTANT: The Dotplot has been cached as 'marker_plot'. Use {{marker_plot}} in the report.\n"
        f"TASK FOR LLM: Based on the gene list above, please infer the cell type for each cluster in your response."
        f" Data saved to: {new_path}."
    )

    display_content = (
        f"### 🧬 差异基因分析 (Markers)\n已通过 Wilcoxon 检验计算各簇特征基因。\n![Marker Dotplot]({img_b64})\n\n**Top Genes per Cluster:**\n```json\n{top_genes_json}\n```"
    )

    return format_response(model_msg, "Marker Analysis Result", display_content)


@mcp.tool()
def run_paga_trajectory(file_path: str) -> dict[str, Any]:
    """
    运行 PAGA (Partition-based Graph Abstraction) 并生成分化轨迹图。
    不仅生成拓扑图，还会生成基于 PAGA 初始化的单细胞嵌入图 (FA2布局)，
    这能最直观地展示细胞分化路径。
    """
    if not os.path.exists(file_path):
        return {"model_text": "Error: File not found.", "display": []}

    adata = sc.read_h5ad(file_path)

    # 检查必要条件
    if "leiden" not in adata.obs:
        return {
            "model_text": "Error: Clustering (leiden) data missing. Run clustering first.",
            "display": [],
        }

    # 1. 运行 PAGA 核心算法
    sc.tl.paga(adata, groups="leiden")

    sc.pl.paga(adata, show=False)

    # 2. 关键步骤：利用 PAGA 结果初始化 ForceAtlas2 (draw_graph) 布局
    # 这让单细胞图看起来像一颗发育树，而不是一团散沙
    # 注意：如果不安装 fa2 库，Scanpy 会回退到 fr 布局，效果稍差但也能用
    sc.tl.draw_graph(adata, init_pos="paga", layout="fa")

    # --- 绘图 1: 抽象拓扑图 (PAGA Graph) ---
    # 展示 Cluster 之间的连接强度
    sc.pl.paga(adata, threshold=0.03, show=False)
    paga_b64 = save_plot_to_store("paga_topology_plot")

    # --- 绘图 2: 单细胞轨迹嵌入图 (PAGA-initialized Embedding) ---
    # 展示每个细胞在树状结构上的位置，并按聚类着色
    sc.pl.draw_graph(
        adata,
        color=["leiden"],
        legend_loc="on data",
        title="Differentiation Trajectory",
        show=False,
    )
    trajectory_b64 = save_plot_to_store("trajectory_embedding_plot")

    # 保存结果
    new_path = file_path.replace(".h5ad", "_paga.h5ad")
    adata.write(new_path)

    model_msg = (
        f"PAGA Analysis & Trajectory Embedding completed.\n"
        f"1. Abstract Topology Graph cached as 'paga_topology_plot'.\n"
        f"2. Single-cell Trajectory Embedding (FA2) cached as 'trajectory_embedding_plot'.\n"
        f"Data saved to: {new_path}.\n"
        f"Observation: Look at the Trajectory Embedding plot to see how cells flow from one cluster to another."
    )

    display_content = (
        f"### 🕸️ 细胞分化轨迹分析\n"
        f"PAGA 分析已完成。下方展示了两种视角的轨迹：\n\n"
        f"#### 1. 簇间连通性 (拓扑结构)\n"
        f"展示了细胞群之间的主要连接路径。\n"
        f"![PAGA Topology]({paga_b64})\n\n"
        f"#### 2. 单细胞分化流 (Trajectory Embedding)\n"
        f"这是基于 PAGA 引导的力导向布局，展示细胞如何从干细胞（通常在图的一端）分化出去。\n"
        f"![Trajectory Flow]({trajectory_b64})"
    )

    return format_response(model_msg, "Trajectory Analysis Result", display_content)


@mcp.tool()
def generate_markdown_report(report_title: str, markdown_body: str) -> dict[str, Any]:
    """
    生成包含 Base64 图片的 Markdown 报告。

    Args:
        report_title: 报告标题
        markdown_body: 报告正文。
                       **关键**: 如果需要插入图片，请在文本中使用 {{image_id}} 占位符。
                       例如: "这是 QC 结果: {{qc_plot}}" 或 "这是聚类图: {{umap_plot}}"。
                       工具会自动将其替换为 Base64 图片代码。
    """

    # 1. 替换占位符
    # 我们遍历缓存中的图片，查找 markdown_body 中是否有对应的占位符 {{key}}
    # 如果有，替换为标准的 Markdown 图片语法 ![key](base64_data)

    processed_body = markdown_body

    for key, b64_data in IMAGE_STORE.items():
        placeholder = f"{{{{{key}}}}}"  # 匹配字符串 "{{key}}"
        if placeholder in processed_body:
            # 替换为 Markdown 图片语法
            markdown_image = f"![{key}]({b64_data})"
            processed_body = processed_body.replace(placeholder, markdown_image)

    # 2. 组装最终 Markdown 内容
    final_content = f"# {report_title}\n\n{processed_body}\n\n---\n*Generated by Single-Cell-Analyzer MCP*"

    # 3. 保存到本地文件 (Base64 很大，建议保存为文件查看)

    # 4. 构建返回信息
    # 注意：我们不在 model_text 里返回整个 Base64 内容，防止刷屏。
    model_msg = f"Report has been generated. All placeholders replaced with Base64 images."

    # 在前端展示部分，我们可以展示一个缩略版本，或者直接提示文件已生成

    return format_response(model_msg, "Report Generated", final_content)


if __name__ == "__main__":
    mcp.run()
