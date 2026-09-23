"""参考图的「移除 / 清空」：二次确认 + 连磁盘文件一起删（从 `daily_media.py` 拆出）。

拆分原因（2026-09-22）：加上「删真实文件 + 二次确认」之后 `daily_media.py` 到 645 行，
超过 AGENTS §2 的 600 行硬线。做法与 `pages/daily_images.DailyImagesMixin` 一致：
把**这一件事**（移除/清空）收成一个 mixin，宿主 `DailyMediaController(DailyDeletionMixin, QObject)`
继承它 —— 不是"顺手重构"，是同一批需求的落点太胖。

用户选定的三个口径（用户 2026-09-22 当场选的）：
① 只真删工具管理的两个目录里的图片（`assets/templates/`、`assets/anchors/`），
   仓库外选的图片（比如从桌面选的）只从列表移除 —— 判断在 `gui/daily_files.py`；
② 「×」与「清空全部」两个入口都要**先弹一次确认**，取消＝配置/界面/磁盘三者全不动；
③ 同一张图**还被别的建筑引用**时不删文件（否则那一组会变成"找不到文件"）。

约定 —— 本 mixin 假设宿主控制器提供：
`self._page` / `self._values(prefix)` / `self._get_config()` / `self._on_changed()` /
`self._set_status(text)`，并在 `__init__` 里把页面信号接到 `remove_image` / `clear_images`。

**测试补丁要打在这里**：`daily_deletion.confirm_destructive`（本模块的全局名，
打在 `daily_media` 上不会生效 —— AGENTS §2④）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from luoluotool.gui.daily_files import (
    DeletionOutcome,
    DeletionPlan,
    delete_files,
    plan_deletions,
)
from luoluotool.gui.dialogs.confirm import confirm_destructive
from luoluotool.gui.pages.daily_fields import BUILDINGS, building_title, ref_image_field
from luoluotool.utils.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

LOG_PATH_HINT = PROJECT_ROOT / "logs" / "luoluotool.log"


def _display_path(path: Path) -> str:
    """给人看的路径：仓库内显示相对仓库根的路径，仓库外显示绝对路径。"""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _deletion_suffix(plan: DeletionPlan, outcome: DeletionOutcome) -> str:
    """状态栏后缀：删了几个、哪些**没删**（以及为什么），失败时给出日志路径。

    三种"没删"必须各自说出来，否则用户会以为图已经没了、结果文件还在。
    """
    parts: list[str] = []
    if outcome.deleted:
        parts.append(f"并删除 {len(outcome.deleted)} 个文件")
    if plan.kept_outside:
        parts.append(f"{len(plan.kept_outside)} 个文件不在工具目录里，只从列表移除")
    if plan.kept_shared:
        parts.append(f"{len(plan.kept_shared)} 个文件还被其它建筑引用，未删除")
    if plan.missing:
        parts.append(f"{len(plan.missing)} 个文件本来就不在")
    if outcome.failed:
        parts.append(
            f"{len(outcome.failed)} 个文件没删掉：{outcome.failed[0][1]}（详见 {LOG_PATH_HINT}）"
        )
    return f"（{'；'.join(parts)}）" if parts else ""


class DailyDeletionMixin:
    """「移除这一张 / 清空全部」：先确认、再删文件、最后改配置与界面（由控制器继承）。"""

    def remove_image(self, prefix: str, index: int) -> None:
        """移除第 index 张（「×」角标 / 右键菜单来的；越界或用户取消时什么都不做）。

        **二次确认**（用户 2026-09-22）：先算出"会删哪些文件"再弹一次框，确认后
        ① 删文件（只限工具管理的两个目录、且没被别的建筑引用）② 从配置与界面移除。
        取消 = 配置、界面、磁盘三者全都不动。
        """
        values = self._values(prefix)
        if not 0 <= index < len(values):
            return
        removed = values[index]
        plan = plan_deletions([removed], still_referenced=self._other_references(prefix))
        if not self._confirm_deletion(
            prefix, plan, title=f"删除参考图并删除文件？（{building_title(prefix)}）",
            text=f"要移除{building_title(prefix)}的第 {index + 1} 张参考图："
                 f"{Path(removed).name}",
            confirm_text="删除并移除",
        ):
            logger.info("已取消移除参考图（%s 第 %d 张）", prefix, index + 1)
            self._set_status(f"已取消移除（{building_title(prefix)}的参考图未改动）")
            return
        outcome = delete_files(plan, logger)
        values = values[:index] + values[index + 1:]
        setattr(self._get_config().features.daily_tasks, ref_image_field(prefix), values)
        self._on_changed()
        self._page.remove_reference_image(prefix, index)
        logger.info("参考图已移除：%s → %s（还剩 %d 张）；%s",
                    prefix, removed, len(values), plan.describe())
        self._set_status(
            f"已移除 {Path(removed).name}（{building_title(prefix)}还剩 {len(values)} 张）"
            + _deletion_suffix(plan, outcome)
        )

    def clear_images(self, prefix: str) -> None:
        """清空某个建筑的全部参考图（「清空全部」按钮 / 右键菜单来的，同样先确认）。"""
        values = self._values(prefix)
        if not values:
            return
        plan = plan_deletions(list(values), still_referenced=self._other_references(prefix))
        if not self._confirm_deletion(
            prefix, plan, title=f"清空参考图并删除文件？（{building_title(prefix)}）",
            text=f"要清空{building_title(prefix)}的 {len(values)} 张参考图："
                 f"{'、'.join(Path(value).name for value in values)}",
            confirm_text="清空并删除",
        ):
            logger.info("已取消清空参考图（%s，原有 %d 张）", prefix, len(values))
            self._set_status(f"已取消清空（{building_title(prefix)}的参考图未改动）")
            return
        outcome = delete_files(plan, logger)
        setattr(self._get_config().features.daily_tasks, ref_image_field(prefix), [])
        self._on_changed()
        self._page.clear_reference_images(prefix)
        logger.info("参考图已清空：%s（原有 %d 张）；%s", prefix, len(values), plan.describe())
        self._set_status(
            f"已清空{building_title(prefix)}的 {len(values)} 张参考图"
            + _deletion_suffix(plan, outcome)
        )

    # ---------------------------------------------------------------- 内部
    def _other_references(self, prefix: str) -> set[str]:
        """**别的建筑**当前引用的路径（同一张图还被别人用着时不许删文件）。"""
        referenced: set[str] = set()
        for _title, other, _word, _field, _capture in BUILDINGS:
            if other != prefix:
                referenced.update(self._values(other))
        return referenced

    def _confirm_deletion(self, prefix: str, plan: DeletionPlan, *, title: str, text: str,
                          confirm_text: str) -> bool:
        """弹一次确认；`plan` 里的三种"不会删"的情况都写进说明里，别让用户以为都删了。"""
        detail_parts = []
        if plan.will_delete():
            detail_parts.append(
                "确认后会同时删除磁盘上的文件："
                + "、".join(_display_path(path) for _value, path in plan.deletable)
            )
            detail_parts.append(
                "删除不可撤销（assets/templates 里入库的图片可用 git 恢复；"
                "assets/anchors 里的框选产物不入库，删了就没了）。"
            )
        else:
            detail_parts.append("这次只会把它从参考图列表里移除，不删除磁盘文件。")
        if plan.kept_outside:
            detail_parts.append(
                f"有 {len(plan.kept_outside)} 个文件不在 assets/templates / assets/anchors 里，"
                f"只从列表移除。"
            )
        if plan.kept_shared:
            detail_parts.append(
                f"有 {len(plan.kept_shared)} 个文件还被其它建筑引用，只从列表移除。"
            )
        return confirm_destructive(
            self._page, title, text, detail="\n".join(detail_parts), confirm_text=confirm_text
        )
