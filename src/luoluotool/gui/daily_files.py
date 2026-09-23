"""移除参考图时"要不要连磁盘文件一起删"：策略与执行（纯逻辑，可单测）。

用户 2026-09-22 选定的三个口径：
① **只真删工具管理的两个目录**里的图片（`assets/templates/` ＝ 用户整理的识别图片、
   `assets/anchors/` ＝ 框选产物）；仓库外的图片（比如从桌面选的）**只从列表移除**；
② 「×」与「清空全部」两个入口都要**二次确认**（弹框在 `gui/dialogs/confirm.py`）——
   所以这里先算出"到底会删哪些文件"，让弹框能把文件名点出来，用户点了取消就什么都不做；
③ 同一张图**还被别的建筑引用**时不删文件（否则那一组会变成"找不到文件"）。

为什么不直接删：`assets/templates/` 里是**入库**的人工图片（git 里能恢复），
`assets/anchors/` 里的框选产物**不入库**（删了就没了）—— 所以凡是"不确定"的情况一律**不删**，
宁可留下一个没用的文件，也不要删掉用户还要用的东西。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from luoluotool.utils.paths import (
    get_anchors_dir,
    get_templates_dir,
    resolve_config_path,
)

logger = logging.getLogger(__name__)


def managed_roots() -> tuple[Path, ...]:
    """工具自己管的两个图片目录（**只有这里面的文件**才会被真删）。"""
    return (get_templates_dir().resolve(), get_anchors_dir().resolve())


def _inside_managed(path: Path) -> bool:
    resolved = path.resolve()
    return any(root == resolved or root in resolved.parents for root in managed_roots())


@dataclass(frozen=True)
class DeletionPlan:
    """一次移除/清空会碰到的文件：能删的、跳过的、本来就没了的分开记。"""

    deletable: tuple[tuple[str, Path], ...] = ()   # (配置里的路径值, 磁盘路径)
    kept_outside: tuple[str, ...] = ()             # 不在管理目录里 → 只从列表移除
    kept_shared: tuple[str, ...] = ()              # 还被别的建筑引用 → 只从列表移除
    missing: tuple[str, ...] = ()                  # 磁盘上本来就没有（或空值）

    def will_delete(self) -> bool:
        return bool(self.deletable)

    def names(self) -> list[str]:
        return [path.name for _value, path in self.deletable]

    def describe(self) -> str:
        """一句话说明这次会删什么（给状态栏与日志用；弹框那边自己组更长的文案）。"""
        parts: list[str] = []
        if self.deletable:
            parts.append(f"将删除 {len(self.deletable)} 个文件：" + "、".join(self.names()))
        else:
            parts.append("没有文件需要删除（只从列表移除）")
        if self.kept_outside:
            parts.append(f"{len(self.kept_outside)} 个不在 assets/templates / assets/anchors 里，未删除")
        if self.kept_shared:
            parts.append(f"{len(self.kept_shared)} 个还被其它建筑引用，未删除")
        if self.missing:
            parts.append(f"{len(self.missing)} 个文件本来就不在")
        return "；".join(parts)


@dataclass(frozen=True)
class DeletionOutcome:
    """真删之后的结果：删掉了哪些（配置里的路径值）、哪些失败了（值 + 原因）。"""

    deleted: list[str]
    failed: list[tuple[str, str]]

    def summary(self) -> str:
        if not self.deleted and not self.failed:
            return "没有文件需要删除"
        if not self.failed:
            return f"已删除 {len(self.deleted)} 个文件"
        if not self.deleted:
            return f"{len(self.failed)} 个文件删除失败"
        return f"已删除 {len(self.deleted)} 个文件，{len(self.failed)} 个文件删除失败"


def plan_deletions(values: list[str], *, still_referenced: set[str] | None = None) -> DeletionPlan:
    """算出一批参考图路径里"哪些文件要删"（**不碰磁盘**，只做判断）。"""
    referenced = still_referenced or set()
    deletable: list[tuple[str, Path]] = []
    kept_outside: list[str] = []
    kept_shared: list[str] = []
    missing: list[str] = []
    for value in values:
        path = resolve_config_path(value)
        if path is None or not path.is_file():
            missing.append(value)
        elif not _inside_managed(path):
            kept_outside.append(value)
        elif value in referenced:
            kept_shared.append(value)
        else:
            deletable.append((value, path))
    return DeletionPlan(tuple(deletable), tuple(kept_outside), tuple(kept_shared), tuple(missing))


def remove_file(path: Path) -> None:
    """真正删除一个文件（单独抽出来便于测试注入失败）。"""
    path.unlink()


def delete_files(plan: DeletionPlan, log: logging.Logger | None = None) -> DeletionOutcome:
    """按计划删文件；**单个失败不中断**（记 WARNING + 记进结果，由调用方提示用户）。"""
    log = log or logger
    deleted: list[str] = []
    failed: list[tuple[str, str]] = []
    for value, path in plan.deletable:
        try:
            remove_file(path)
        except OSError as exc:                     # 被占用 / 没权限 / 正在被别的程序读
            log.warning("参考图文件删除失败（%s）：%s", path, exc)
            failed.append((value, str(exc)))
        else:
            log.info("参考图文件已删除：%s", path)
            deleted.append(value)
    return DeletionOutcome(deleted=deleted, failed=failed)
