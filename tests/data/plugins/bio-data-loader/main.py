from typing import Literal, Optional
from fastmcp import FastMCP
import scanpy as sc
import os
import requests
import tarfile
import zipfile

# 创建 MCP Server
mcp = FastMCP("Bio-Data-Loader")

# 设置工作目录
WORK_DIR = os.path.abspath("./bio_workspace")
os.makedirs(WORK_DIR, exist_ok=True)


def _download_file(url: str, dest_folder: str) -> str:
    """内部辅助函数：流式下载文件"""
    local_filename = url.split("/")[-1]
    # 处理一些 URL 结尾没有文件名的情况
    if not local_filename or len(local_filename) > 100:
        local_filename = "downloaded_data.tmp"

    path = os.path.join(dest_folder, local_filename)

    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return path
    except Exception as e:
        raise RuntimeError(f"Download failed: {str(e)}")


def _extract_archive(file_path: str, extract_to: str):
    """内部辅助函数：解压 .zip 或 .tar.gz"""
    if file_path.endswith("tar.gz") or file_path.endswith(".tgz"):
        with tarfile.open(file_path, "r:gz") as tar:
            tar.extractall(path=extract_to)
    elif file_path.endswith(".zip"):
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(extract_to)
    else:
        raise ValueError("Unsupported archive format. Use .tar.gz or .zip")


@mcp.tool(task=True)
async def fetch_file_from_url(
    url: str, file_type: Literal["h5ad", "archive", "auto"] = "auto"
) -> str:
    """
    从 URL 下载真实数据。

    Args:
        url: 文件的直接下载链接。
        file_type:
            - 'h5ad': 直接下载并保存为 .h5ad (适用于 CellxGene 等)。
            - 'archive': 下载压缩包(.zip/.tar.gz)并解压，通常用于 10x 原始数据。
            - 'auto': 尝试根据 URL 后缀自动判断。

    Returns:
        下载后的文件路径或解压后的文件夹路径。
    """
    try:
        # 1. 下载文件
        print(f"Downloading from {url}...")
        downloaded_path = _download_file(url, WORK_DIR)

        # 2. 判断是否需要解压
        is_archive = False
        if file_type == "archive":
            is_archive = True
        elif file_type == "auto":
            if downloaded_path.endswith((".zip", ".tar.gz", ".tgz")):
                is_archive = True

        if is_archive:
            # 创建解压目录
            extract_dir = os.path.join(
                WORK_DIR, os.path.basename(downloaded_path) + "_extracted"
            )
            os.makedirs(extract_dir, exist_ok=True)
            _extract_archive(downloaded_path, extract_dir)
            return f"Success: Archive downloaded and extracted to: {extract_dir}"
        else:
            return f"Success: File downloaded to: {downloaded_path}"

    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool(task=True)
async def convert_10x_to_h5ad(
    input_path: str, output_filename: str = "converted.h5ad"
) -> str:
    """
    将 10x Genomics 格式 (matrix.mtx, barcodes.tsv, features.tsv) 转换为 .h5ad。

    Args:
        input_path: 包含 10x 文件的文件夹路径 (通常是 fetch_file_from_url 解压后的路径)。
        output_filename: 输出的 .h5ad 文件名。
    """
    try:
        # Scanpy 能够自动递归查找目录下的 10x 文件
        # cache=True 可以加速后续读取
        adata = sc.read_10x_mtx(
            input_path,
            var_names="gene_symbols",  # 使用基因名作为索引
            cache=True,
        )

        # 消除重复基因名 (10x 数据常见问题)
        adata.var_names_make_unique()

        save_path = os.path.join(WORK_DIR, output_filename)
        adata.write(save_path)

        return f"Success: Converted 10x data to {save_path}. Cells: {adata.n_obs}, Genes: {adata.n_vars}."
    except Exception as e:
        return f"Error converting 10x data: {str(e)}. Please ensure the folder contains matrix.mtx, barcodes.tsv and features.tsv (or genes.tsv)."


@mcp.tool(task=True)
async def convert_csv_to_h5ad(csv_path: str, transpose: bool = True) -> str:
    """
    将 CSV 表达矩阵转换为 .h5ad。

    Args:
        csv_path: CSV 文件路径。
        transpose: 是否转置。
                   Scanpy 默认期望 行=Obs(细胞), 列=Var(基因)。
                   如果 CSV 是 行=基因, 列=细胞 (常见情况)，则需要 transpose=True。
    """
    try:
        adata = sc.read_csv(csv_path)
        if transpose:
            adata = adata.T

        new_path = csv_path.replace(".csv", ".h5ad")
        adata.write(new_path)
        return f"Success: Converted CSV to {new_path}"
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool(task=True)
async def load_demo_dataset(dataset_name: Literal["pbmc3k", "paul15"]) -> str:
    """加载内置 Demo 数据 (仅用于测试)。"""
    try:
        if dataset_name == "pbmc3k":
            adata = sc.datasets.pbmc3k()
        elif dataset_name == "paul15":
            adata = sc.datasets.paul15()

        adata.var_names_make_unique()
        save_path = os.path.join(WORK_DIR, f"{dataset_name}.h5ad")
        adata.write(save_path)
        return f"Success: Loaded {dataset_name} to {save_path}"
    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    mcp.run()
