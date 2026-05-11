from __future__ import annotations

from pathlib import Path

from .schemas import PluginManifest


class PluginRegistry:
    """
    SINGLETON-LIKE SERVICE (由 DI 管理单例更合适)。
    - 启动时扫描插件目录并维护一份内存中的 PluginManifest 索引。
    - 只负责“发现、缓存、查询、刷新、增删 Manifest”，不涉及插件生命周期和文件删除。
    - 不关心用户/请求。
    """

    def __init__(self, plugin_dir: Path, log_manager):
        self.plugin_dir = plugin_dir
        self.log_manager = log_manager
        self._manifests: dict[str, PluginManifest] = {}
        self.reload_plugins()  # 首次加载

    # ---------- 查询接口 ----------
    def get_all_manifests(self) -> list[PluginManifest]:
        """返回已发现的全部插件清单（不做过滤）。"""
        return list(self._manifests.values())

    def find_manifest(self, plugin_id: str) -> PluginManifest | None:
        """按 ID 返回插件清单。"""
        return self._manifests.get(plugin_id)

    # ---------- 刷新 / 增量更新 ----------
    def reload_plugins(self) -> None:
        """
        全量刷新：扫描目录→构建临时字典→原子替换。
        """

        if not self.plugin_dir.is_dir():
            self.log_manager.log_with_context(
                "warning",
                "Plugin directory '{dir}' not found.",
                context={"dir": str(self.plugin_dir)},
            )
            self._manifests = {}
            return

        new_index: dict[str, PluginManifest] = {}

        for plugin_path in self.plugin_dir.iterdir():
            if not plugin_path.is_dir():
                self.log_manager.log_with_context(
                    "debug",
                    "Skipping '{path}' (not a directory).",
                    context={"path": str(plugin_path)},
                )
                continue

            toml_path = plugin_path / "plugin.toml"
            if not toml_path.is_file():
                self.log_manager.log_with_context(
                    "debug",
                    "Skipping '{path}' (missing plugin.toml).",
                    context={"path": str(plugin_path)},
                )
                continue

            try:
                mainfest = PluginManifest.from_toml(toml_path)
                # 简单防重：后发现的同 ID 会覆盖先前同 ID
                new_index[mainfest.id] = mainfest
            except Exception as e:
                self.log_manager.log_with_context(
                    "error",
                    f"Failed to load plugin from '{str(toml_path)}': {e}",
                )

        # 原子替换
        self._manifests = new_index
        self.log_manager.log_with_context(
            "info",
            "Plugin registry reloaded. Total discovered: {count}",
            context={"count": len(self._manifests)},
        )

    def add_manifest_from_dir(self, plugin_dir: Path) -> PluginManifest | None:
        """
        增量添加：从单个目录解析 manifest 并加入索引。
        - 不做任何生命周期调用。
        """
        toml_path = plugin_dir / "plugin.toml"
        if not toml_path.is_file():
            self.log_manager.log_with_context(
                "warning",
                "Cannot add plugin: 'plugin.toml' not found at '{path}'.",
                context={"path": str(toml_path)},
            )
            return None

        try:
            manifest = PluginManifest.from_toml(toml_path)
            self._manifests[manifest.id] = manifest
            self.log_manager.log_with_context(
                "info",
                "Plugin '{id}' added to registry from '{dir}'.",
                context={"id": manifest.id, "dir": str(plugin_dir)},
            )
            return manifest
        except Exception as e:
            self.log_manager.log_with_context(
                "error",
                "Failed to add plugin from '{path}': {error_msg}",
                context={"path": str(toml_path), "error_msg": f"{e}"},
            )
            return None

    def remove_manifest_by_id(self, plugin_id: str) -> bool:
        """
        增量移除：仅从索引中删除对应 ID 的 manifest。
        - 不做文件系统删除，不做 shutdown 等生命周期操作。
        - 返回是否实际移除。
        """
        existed = plugin_id in self._manifests
        if existed:
            self._manifests.pop(plugin_id, None)
            self.log_manager.log_with_context(
                "info",
                "Plugin '{id}' removed from registry.",
                context={"id": plugin_id},
            )
        else:
            self.log_manager.log_with_context(
                "debug",
                "Plugin '{id}' not found in registry; nothing to remove.",
                context={"id": plugin_id},
            )
        return existed
