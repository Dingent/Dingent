import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from pathlib import Path
import sys
import glob
import os

# --- 1. 配置与环境检测 ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "test_results"


def configure_chinese_font():
    """配置中文字体"""
    font_names = ["WenQuanYi Micro Hei", "Microsoft YaHei", "SimHei", "DejaVu Sans"]
    found_font = False
    for font in font_names:
        try:
            if font in [f.name for f in fm.fontManager.ttflist]:
                plt.rcParams["font.sans-serif"] = [font]
                plt.rcParams["axes.unicode_minus"] = False
                print(f">>> 字体设置成功: 使用 '{font}'")
                found_font = True
                break
        except:
            continue
    if not found_font:
        print(">>> ⚠️ 警告: 未找到推荐的中文字体，图表中的中文可能显示为方框。")


def get_latest_run_dir():
    """查找最新结果目录"""
    if not RESULTS_DIR.exists():
        print(f"❌ 错误: 找不到结果目录: {RESULTS_DIR}")
        sys.exit(1)
    run_dirs = sorted(glob.glob(str(RESULTS_DIR / "run_*")))
    if not run_dirs:
        print(f"❌ 错误: 在 {RESULTS_DIR} 下没有找到测试记录。")
        sys.exit(1)
    return Path(run_dirs[-1])


# --- 2. 核心绘图逻辑 ---
def plot_charts():
    configure_chinese_font()

    # 1. 确定目标目录
    target_dir = get_latest_run_dir()
    print(f">>> 📂 正在分析: {target_dir.name}")
    output_dir = target_dir / "charts"
    output_dir.mkdir(exist_ok=True)

    # ---------------------------------------------------------
    # A. 读取 Locust 数据 (作为时间基准)
    # ---------------------------------------------------------
    csv_files = list(target_dir.glob("*_history.csv"))
    if not csv_files:
        print("❌ 错误: 找不到 Locust History CSV 文件")
        return
    history_csv = csv_files[0]

    try:
        df_locust = pd.read_csv(history_csv)
        # 获取压测开始的时间戳（作为 T=0 的基准）
        LOCUST_START_TIMESTAMP = df_locust["Timestamp"].min()

        # 处理 Locust 数据的时间轴
        df_locust["Time_Secs"] = df_locust["Timestamp"] - LOCUST_START_TIMESTAMP

        # 过滤 Aggregated
        if "Name" in df_locust.columns:
            df_locust = df_locust[df_locust["Name"] == "Aggregated"]

    except Exception as e:
        print(f"❌ 读取 Locust 数据失败: {e}")
        return

    # ---------------------------------------------------------
    # B. 绘制 Locust 标准图表 (图1 & 图2)
    # ---------------------------------------------------------
    try:
        # --- 图表 1: 负载与吞吐量 ---
        fig, ax1 = plt.subplots(figsize=(12, 6))
        color_users = "#d62728"
        ax1.set_xlabel("测试时长 (秒)", fontsize=12)
        ax1.set_ylabel("并发用户数 (Users)", color=color_users, fontsize=12, fontweight="bold")
        ax1.plot(df_locust["Time_Secs"], df_locust["User Count"], color=color_users, linestyle="--", label="并发用户数")
        ax1.tick_params(axis="y", labelcolor=color_users)
        ax1.grid(True, linestyle=":", alpha=0.6)

        ax2 = ax1.twinx()
        color_rps = "#1f77b4"
        ax2.set_ylabel("每秒请求数 (RPS)", color=color_rps, fontsize=12, fontweight="bold")
        ax2.plot(df_locust["Time_Secs"], df_locust["Requests/s"], color=color_rps, linewidth=2, label="吞吐量 (RPS)")
        ax2.tick_params(axis="y", labelcolor=color_rps)

        plt.title("系统负载与吞吐量趋势图", fontsize=16, pad=20)
        ax1.set_xlim(0, 300)
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
        plt.tight_layout()
        plt.savefig(output_dir / "1_throughput_load.png", dpi=300)
        print("✅ 生成: 1_throughput_load.png")

        # --- 图表 2: 响应时间 ---
        plt.figure(figsize=(12, 6))
        p50_col = "50%" if "50%" in df_locust.columns else "Total Median Response Time"
        p95_col = "95%" if "95%" in df_locust.columns else None

        if p50_col in df_locust.columns:
            plt.plot(df_locust["Time_Secs"], df_locust[p50_col], label="P50 响应时间", color="green", linewidth=1.5)
        if p95_col and p95_col in df_locust.columns:
            plt.plot(df_locust["Time_Secs"], df_locust[p95_col], label="P95 响应时间", color="#ff7f0e", linewidth=1.5)
        else:
            plt.plot(df_locust["Time_Secs"], df_locust["Total Average Response Time"], label="平均响应时间", color="blue", linestyle=":")

        plt.xlabel("测试时长 (秒)", fontsize=12)
        plt.ylabel("响应时间 (ms)", fontsize=12)
        plt.title("系统响应时间稳定性分析", fontsize=16, pad=20)
        plt.legend()
        plt.grid(True, linestyle="--", alpha=0.7)
        plt.xlim(0, 300)
        plt.tight_layout()
        plt.savefig(output_dir / "2_latency_trend.png", dpi=300)
        print("✅ 生成: 2_latency_trend.png")

    except Exception as e:
        print(f"❌ 绘制 Locust 图表失败: {e}")

    # ---------------------------------------------------------
    # C. 绘制资源监控图表 (新增功能)
    # ---------------------------------------------------------
    res_files = list(target_dir.glob("*metrics.csv")) + list(target_dir.glob("*monitor*.csv"))

    if res_files:
        try:
            res_csv = res_files[0]  # 取第一个匹配的
            print(f">>> 📄 读取资源数据: {res_csv.name}")
            df_res = pd.read_csv(res_csv)

            # 关键：对齐时间轴
            # 使用 Locust 的开始时间作为 T=0
            # 如果资源监控比 Locust 早启动，Time_Secs 会是负数，这很正常（预热阶段）
            df_res["Time_Secs"] = df_res["timestamp"] - LOCUST_START_TIMESTAMP

            fig, ax1 = plt.subplots(figsize=(12, 6))

            # --- 左轴：CPU 使用率 ---
            color_cpu = "#e377c2"  # 粉紫色
            ax1.set_xlabel("测试时长 (秒) [相对于压测开始时刻]", fontsize=12)
            ax1.set_ylabel("CPU 使用率 (%)", color=color_cpu, fontsize=12, fontweight="bold")

            # 兼容字段名：你的新脚本用 total_cpu_percent，旧脚本可能用 cpu_percent
            cpu_col = "total_cpu_percent" if "total_cpu_percent" in df_res.columns else "cpu_percent"

            # 绘制 CPU 曲线
            ax1.plot(df_res["Time_Secs"], df_res[cpu_col], color=color_cpu, linewidth=1.5, label="Total CPU Usage")
            ax1.tick_params(axis="y", labelcolor=color_cpu)
            ax1.grid(True, linestyle=":", alpha=0.6)

            # --- 右轴：内存 使用率 ---
            ax2 = ax1.twinx()
            color_mem = "#2ca02c"  # 绿色
            ax2.set_ylabel("内存使用量 (G)", color=color_mem, fontsize=12, fontweight="bold")

            mem_col = "total_memory_percent" if "total_memory_percent" in df_res.columns else "memory_percent"

            ax2.plot(df_res["Time_Secs"], df_res[mem_col], color=color_mem, linewidth=2, linestyle="--", label="Total Memory Usage")
            ax2.tick_params(axis="y", labelcolor=color_mem)

            # --- 标题与图例 ---
            # 如果有进程数量统计，加到标题里
            title_suffix = ""
            if "process_count" in df_res.columns:
                max_procs = df_res["process_count"].max()
                title_suffix = f" (Max Processes: {max_procs})"

            plt.title(f"服务端资源占用监控{title_suffix}", fontsize=16, pad=20)

            # 合并双轴图例
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

            ax1.set_xlim(0, 500)

            plt.tight_layout()
            plt.savefig(output_dir / "4_resource_usage.png", dpi=300)
            print("✅ 生成: 4_resource_usage.png (资源监控图)")

        except Exception as e:
            print(f"⚠️ 资源绘图失败 (可能是列名不匹配): {e}")
            import traceback

            traceback.print_exc()
    else:
        print(">>> ℹ️ 未找到资源监控文件 (*resources.csv)，跳过资源绘图。")

    # ---------------------------------------------------------
    # D. 数据库增长图 (保持不变)
    # ---------------------------------------------------------
    pg_csv = target_dir / "pg_growth.csv"
    if pg_csv.exists():
        try:
            df_pg = pd.read_csv(pg_csv)
            # 时间对齐
            df_pg["Time_Secs"] = df_pg["timestamp"] - LOCUST_START_TIMESTAMP

            plt.figure(figsize=(12, 6))
            plt.plot(df_pg["Time_Secs"], df_pg["db_size_bytes"] / 1024 / 1024, color="purple", linewidth=2, marker="o", markersize=4)
            plt.xlabel("测试时长 (秒)", fontsize=12)
            plt.ylabel("数据库大小 (MB)", fontsize=12)
            plt.title("PostgreSQL 数据量增长趋势", fontsize=16, pad=20)
            plt.grid(True)
            plt.xlim(0, 500)
            plt.tight_layout()
            plt.savefig(output_dir / "3_db_growth.png", dpi=300)
            print("✅ 生成: 3_db_growth.png")
        except Exception:
            pass


if __name__ == "__main__":
    plot_charts()
