"""
Dingent CLI (跨平台兼容版本)

Commands:
  dingent run        Concurrently start backend + frontend
  dingent version    Show version
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import sys
import tempfile
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer
from alembic.config import Config as AlembicConfig
from rich.console import Console
from sqlalchemy import create_engine, inspect

from alembic import command as alembic_command

if sys.platform == "win32":
    os.environ["PYTHONUTF8"] = "1"
    # 保护性修改：防止在无控制台模式(pythonw)下报错
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

app = typer.Typer(help="Dingent Agent Framework CLI")
console = Console()

IS_DEV_MODE = os.getenv("DINGENT_DEV")
_TEMP_DIRS: list[tempfile.TemporaryDirectory] = []
IS_WINDOWS = sys.platform == "win32"


# --------- Service Definition ---------


@dataclass
class ServiceConfig:
    name: str
    command: list[str]
    color: str
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    health_check_url: str | None = None
    depends_on: list[str] = field(default_factory=list)
    open_browser_hint: bool = False


# --------- Async Service Manager ---------


class AsyncServiceManager:
    def __init__(self, auto_open_browser: bool = True):
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.ready_events: dict[str, asyncio.Event] = {}
        self.auto_open_browser = auto_open_browser
        self._browser_opened = False
        self._shutdown_event = asyncio.Event()
        self._print_lock = asyncio.Lock()

    async def _safe_print(self, message: str):
        """线程安全的打印"""
        async with self._print_lock:
            console.print(message)

    async def _health_check(self, url: str, timeout: float = 60) -> bool:
        """异步健康检查"""
        import aiohttp

        start = asyncio.get_event_loop().time()
        async with aiohttp.ClientSession() as session:
            while asyncio.get_event_loop().time() - start < timeout:
                if self._shutdown_event.is_set():
                    return False
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                        if resp.status == 200:
                            return True
                except Exception:
                    pass
                await asyncio.sleep(0.5)
        return False

    async def _wait_for_dependencies(self, service: ServiceConfig):
        """等待依赖服务就绪"""
        for dep_name in service.depends_on:
            if dep_name in self.ready_events:
                await self._safe_print(f"[cyan]⏳ {service.name} waiting for {dep_name}.. .[/cyan]")
                try:
                    await asyncio.wait_for(self.ready_events[dep_name].wait(), timeout=120)
                    await self._safe_print(f"[green]✓ {dep_name} is ready, starting {service.name}[/green]")
                except TimeoutError:
                    await self._safe_print(f"[bold red]❌ Timeout waiting for {dep_name}[/bold red]")
                    raise

    async def _run_service(self, service: ServiceConfig):
        """运行单个服务"""
        # 初始化就绪事件
        self.ready_events[service.name] = asyncio.Event()

        # 等待依赖
        await self._wait_for_dependencies(service)

        # 准备环境变量
        merged_env = {**os.environ, **service.env}

        # 启动进程
        proc = await asyncio.create_subprocess_exec(
            *service.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=merged_env,
            cwd=str(service.cwd) if service.cwd else None,
            limit=1024 * 1024 * 4,  # Increase buffer limit to 4MB to prevent LimitOverrunError
        )
        self.processes[service.name] = proc
        await self._safe_print(f"[bold green]✓ {service.name} (PID {proc.pid}) started:  {' '.join(service.command)}[/bold green]")

        # 启动健康检查（如果有）
        health_task = None
        if service.health_check_url:
            health_task = asyncio.create_task(self._monitor_health(service))
        else:
            # 无健康检查，直接标记就绪
            self.ready_events[service.name].set()

        # 流式读取输出
        await self._stream_output(service, proc)

        # 清理健康检查任务
        if health_task and not health_task.done():
            health_task.cancel()

        # 进程退出处理
        await proc.wait()
        if not self._shutdown_event.is_set():
            await self._safe_print(f"[bold red]✗ {service.name} exited unexpectedly (code {proc.returncode})[/bold red]")
            # 触发全局关闭
            self._shutdown_event.set()

    async def _stream_output(self, service: ServiceConfig, proc: asyncio.subprocess.Process):
        """流式输出日志"""
        port_regex = re.compile(r"http://localhost:(\d+)")

        if proc.stdout is None:
            raise RuntimeError(f"Process {service.name} has no stdout")
        while not self._shutdown_event.is_set():
            try:
                line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=0.5)
            except TimeoutError:
                if proc.returncode is not None:
                    break
                continue

            if not line_bytes:
                break

            line = line_bytes.decode(errors="replace").rstrip()
            await self._safe_print(f"[{service.color}][{service.name.upper():^8}][/] {line}")

            # 检测端口并打开浏览器
            if service.open_browser_hint and self.auto_open_browser and not self._browser_opened:
                match = port_regex.search(line)
                if match:
                    url = f"http://localhost:{match.group(1)}"
                    await self._safe_print(f"[bold blue]🌐 Opening browser:  {url}[/bold blue]")
                    try:
                        webbrowser.open_new_tab(url)
                        self._browser_opened = True
                    except Exception:
                        await self._safe_print("[yellow]⚠️ Could not open browser[/yellow]")

    async def _monitor_health(self, service: ServiceConfig):
        """监控服务健康状态"""
        if service.health_check_url is None:
            raise RuntimeError(f"Service {service.name} has no health check URL")
        if await self._health_check(service.health_check_url):
            await self._safe_print(f"[bold green]✓ {service.name} is healthy![/bold green]")
            self.ready_events[service.name].set()
        else:
            await self._safe_print(f"[bold red]❌ {service.name} health check failed[/bold red]")
            self._shutdown_event.set()

    async def shutdown(self):
        """优雅关闭所有服务"""
        if self._shutdown_event.is_set():
            return  # 防止重复关闭

        self._shutdown_event.set()
        await self._safe_print("\n[bold yellow]🛑 Shutting down all services.. .[/bold yellow]")

        # 逆序关闭（先关闭依赖者）
        for name in reversed(list(self.processes.keys())):
            proc = self.processes[name]
            if proc.returncode is None:
                await self._safe_print(f"[yellow]Stopping {name} (PID {proc.pid}).. .[/yellow]")
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=5)
                    await self._safe_print(f"[green]✓ {name} stopped[/green]")
                except TimeoutError:
                    await self._safe_print(f"[red]Force killing {name}.. .[/red]")
                    proc.kill()
                    await proc.wait()
                    await self._safe_print(f"[green]✓ {name} killed[/green]")
                except ProcessLookupError:
                    await self._safe_print(f"[yellow]✓ {name} already exited[/yellow]")

        # 清理临时目录
        for td in _TEMP_DIRS:
            try:
                td.cleanup()
            except Exception:
                pass
        _TEMP_DIRS.clear()

        await self._safe_print("[bold blue]✓ All services stopped[/bold blue]")

    async def run_all(self, services: list[ServiceConfig]):
        """运行所有服务"""
        await self._safe_print("[bold cyan]🚀 Starting services...[/bold cyan]")

        # 跨平台信号处理
        self._setup_signal_handlers()

        # 启动所有服务任务
        tasks = [asyncio.create_task(self._run_service(svc)) for svc in services]

        await self._safe_print("[bold green]✓ All services started[/bold green]")

        # 等待关闭事件或任意服务退出
        shutdown_task = asyncio.create_task(self._shutdown_event.wait())
        done, pending = await asyncio.wait([shutdown_task, *tasks], return_when=asyncio.FIRST_COMPLETED)

        # 确保完全关闭
        if not self._shutdown_event.is_set():
            await self.shutdown()

        # 取消剩余任务
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _setup_signal_handlers(self):
        """跨平台信号处理设置"""
        if IS_WINDOWS:
            # Windows:  使用线程来监听 Ctrl+C
            import threading

            def windows_signal_handler():
                """Windows 下在单独线程中等待信号"""
                import ctypes

                kernel32 = ctypes.windll.kernel32

                # 设置控制台处理程序
                def console_handler(ctrl_type):
                    if ctrl_type in (0, 1, 2):  # CTRL_C, CTRL_BREAK, CTRL_CLOSE
                        # 在事件循环中调度关闭
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.call_soon_threadsafe(lambda: asyncio.create_task(self.shutdown()))
                        except Exception:
                            pass
                        return True
                    return False

                # 注册处理程序
                HANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)
                handle = HANDLER_ROUTINE(console_handler)
                kernel32.SetConsoleCtrlHandler(handle, True)

                # 保持线程活着，直到关闭
                while not self._shutdown_event.is_set():
                    import time

                    time.sleep(0.1)

            thread = threading.Thread(target=windows_signal_handler, daemon=True)
            thread.start()
        else:
            # Unix/Linux/macOS: 使用标准的 signal handler
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))


# --------- CLI Commands ---------


def _run_async(coro):
    """运行异步函数的辅助方法"""
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        # Windows 下 Ctrl+C 可能直接抛出 KeyboardInterrupt
        console.print("\n[bold yellow]Interrupted by user[/bold yellow]")


def _get_alembic_config(database_url: str | None = None) -> AlembicConfig:
    """
    构造 Alembic 配置对象，自动处理打包后的路径问题
    """
    from dingent.core.paths import paths

    # 1. 确定基准路径（处理 PyInstaller 打包后的 _MEIPASS 路径）
    if getattr(sys, "frozen", False):
        # 打包环境
        base_dir = sys._MEIPASS  # type: ignore
    else:
        # 开发环境
        base_dir = os.getcwd()

    # 2. 定位 alembic 目录和 ini 文件
    # 假设你的目录结构是 root/alembic 和 root/alembic.ini
    script_location = os.path.join(base_dir, "alembic")
    ini_location = os.path.join(base_dir, "alembic.ini")

    # 3. 验证文件是否存在（便于调试）
    if not os.path.exists(script_location):
        console.print(f"[bold red]❌ Error:[/bold red] Migration script dir not found at {script_location}")
        sys.exit(1)

    # 4. 创建配置对象
    # 注意：我们不直接读取文件，而是编程方式设置，这样更稳健
    alembic_cfg = AlembicConfig(ini_location)

    # 强制设置 script_location 为绝对路径
    alembic_cfg.set_main_option("script_location", script_location)

    # 5. 设置数据库 URL
    # 优先使用传入的 URL，其次读取环境变量，最后兜底
    final_url = database_url or os.getenv("DATABASE_URL")
    if not final_url:
        if not paths.sqlite_path.exists():
            console.print("[bold red]❌ Error:[/bold red] DATABASE_URL not set.")
            sys.exit(1)
        final_url = f"sqlite:///{paths.sqlite_path}"

    alembic_cfg.set_main_option("sqlalchemy.url", final_url)

    # 禁用 logging 劫持，防止 alembic 弄乱你的 rich console
    alembic_cfg.attributes["configure_logger"] = False

    return alembic_cfg


def _is_new_database(database_url: str) -> bool:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        return not inspector.get_table_names()
    finally:
        engine.dispose()


def _run_migrations(url: str | None = None, stamp_only: bool = False):
    """执行数据库迁移的核心逻辑"""
    console.print("[cyan]🔄 Checking database migrations...[/cyan]")
    try:
        cfg = _get_alembic_config(url)
        if stamp_only:
            alembic_command.stamp(cfg, "head")
        else:
            # 捕获 stdout 以防止 alembic 输出干扰 CLI 界面（可选）
            # 这里直接调用 upgrade head
            alembic_command.upgrade(cfg, "head")
        console.print("[bold green]✓ Database is up to date.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]❌ Migration failed:[/bold red] {e}")
        # 在生产环境中，数据库迁移失败通常应该阻止启动
        sys.exit(1)


@app.command()
def run(
    host: str = "localhost",
    port: int = 8000,
    ui_port: int = 3000,
    no_browser: bool = False,
    data_dir: Annotated[Path | None, typer.Option("--data-dir", "-d")] = None,
    dev: bool = False,
    base_path: Annotated[str | None, typer.Option("--base-path", help="Base path for frontend (e.g., /myapp)")] = None,
    skip_migration: bool = False,  # 新增参数，允许跳过迁移
):
    """
    Concurrently starts the backend and frontend services.
    """
    # 1. 注入环境变量
    if data_dir:
        os.environ["DINGENT_HOME"] = str(data_dir.resolve())

    from dingent.core.db.session import create_db_and_tables
    from dingent.core.paths import paths

    database_url = f"sqlite:///{paths.sqlite_path}"
    is_new_database = _is_new_database(database_url)
    create_db_and_tables()
    if not skip_migration:
        _run_migrations(stamp_only=is_new_database)

    # 2. 导入依赖
    from dingent.cli.assets import asset_manager

    console.print("[cyan]🔍 Checking runtime environment...[/cyan]")

    # 3. 准备资源
    asset_paths = asset_manager.ensure_assets()
    node_bin = asset_paths["node_bin"]
    frontend_dir = asset_paths["frontend_dir"]
    frontend_script = asset_paths["frontend_script"]

    # 4. 构建服务配置
    if paths.is_frozen:
        backend_cmd = [sys.executable, "internal-backend", host, str(port)]
        backend_cwd = paths.bundle_dir
    else:
        backend_cmd = [
            "uvicorn",
            "dingent.server.main:app",
            "--host",
            host,
            "--port",
            str(port),
            "--reload",
        ]
        backend_cwd = paths.bundle_dir

    services: list[ServiceConfig] = [
        ServiceConfig(
            name="backend",
            command=backend_cmd,
            cwd=backend_cwd,
            color="magenta",
            env=dict(os.environ),
            health_check_url=f"http://{host}:{port}/api/v1/health",
        ),
    ]

    if not dev:
        frontend_env = {
            "DING_BACKEND_URL": f"http://{host}:{port}",
            "PORT": str(ui_port),
            "HOSTNAME": host,
        }
        if base_path:
            frontend_env["NEXT_PUBLIC_BASE_PATH"] = base_path

        services.append(
            ServiceConfig(
                name="frontend",
                command=[node_bin, frontend_script],
                cwd=frontend_dir,
                color="cyan",
                env=frontend_env,
                open_browser_hint=True,
                depends_on=["backend"],
            )
        )

    # 5. 运行服务
    manager = AsyncServiceManager(auto_open_browser=not no_browser and not dev)
    _run_async(manager.run_all(services))


@app.command(hidden=True)
def internal_backend(host: str, port: int):
    """(Internal) 仅供打包后调用"""
    import uvicorn

    uvicorn.run("dingent.server.main:app", host=host, port=port)


@app.command()
def upgrade_db(
    url: Annotated[str | None, typer.Option(help="Override Database URL")] = None,
    data_dir: Annotated[Path | None, typer.Option("--data-dir", "-d")] = None,
):
    """
    Manually run database migrations.
    """
    if data_dir:
        os.environ["DINGENT_HOME"] = str(data_dir.resolve())

    _run_migrations(url)


@app.command()
def version():
    """Show the Dingent version"""
    try:
        from importlib.metadata import version as _v

        ver = _v("dingent")
    except Exception:
        ver = "unknown"
    console.print(f"Dingent version:  {ver}")


@app.callback(invoke_without_command=True)
def main_entry(ctx: typer.Context):
    """Dingent Agent Framework CLI"""
    if ctx.invoked_subcommand is None:
        run(no_browser=False)


def main():
    app()


if __name__ == "__main__":
    main()
