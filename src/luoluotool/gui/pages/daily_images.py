"""日常任务页的「参考图」显示与交互：多选缩略图条 + 大图 + 移除/清空（从 `daily.py` 拆出）。

拆分原因（2026-09-22）：用户要求「选择图片可以多选」之后，`daily.py` 到 605 行，超过
AGENTS §2 的 600 行硬线。**纯搬运**：这些方法一行未改，只是搬进 `DailyImagesMixin`，
`DailyPage(DailyImagesMixin, ScrollablePage)` 继承它。

约定（与 `gui/dialogs/crop_view_zoom.ZoomPanMixin` 同样的做法）—— 本 mixin 假设宿主 `DailyPage`：

- 在 `__init__` 里建好 `self._ref_edits` / `self._previews` / `self._strips` / `self._clear_buttons`
  / `self._reference_paths`；
- 声明了 `preview_requested(str, int)` / `remove_image_requested(str, int)` / `clear_images_requested(str)`；
- 在 `_building_box()` 里把每个建筑的输入框 / 大图 / 缩略图条登记进上面那几个字典。

线程约定：**图片由控制器在后台线程解码**后交进来（`set_reference_images` / `set_reference_thumbnail`），
本模块不碰文件、不写配置。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QPushButton

from luoluotool.config.models import MAX_REFERENCE_IMAGES
from luoluotool.gui.pages.daily_fields import building_title
from luoluotool.gui.widgets import ImagePreview, ThumbnailStrip

logger = logging.getLogger(__name__)


class DailyImagesMixin:
    """参考图的多选显示与交互（由 `DailyPage` 继承；见模块说明里的约定）。"""

    def set_reference_images(self, prefix: str, paths: list[str],
                             images: list[QImage | None]) -> None:
        """整批换掉某个建筑的参考图（路径进输入框、图片进缩略图条、大图显示第一张）。

        图片可以是 `None`＝"还在后台解码"（控制器解码完一张就调 `set_reference_thumbnail`）。
        **不写配置**（那是控制器的活）：控制器负责"选/截/删 → 存盘 → 通知页面显示"。
        """
        self._apply_reference_view(prefix, paths, images, selected=0)

    def set_reference_thumbnail(self, prefix: str, index: int, image: QImage | None) -> None:
        """后台解码完一张：只换那张缩略图；若它正是当前选中项，大图也跟着更新。"""
        strip = self._strips[prefix]
        strip.set_image_at(index, image)
        if index == strip.selected_index():
            self._show_selected(prefix)

    def append_reference_image(self, prefix: str, path: str, image: QImage | None) -> None:
        """追加一张并选中它（「截取游戏画面」的产物走这条路）。"""
        paths = self.reference_images(prefix) + [path]
        images = list(self._strips[prefix].images()) + [image]
        self._apply_reference_view(prefix, paths, images, selected=len(paths) - 1)

    def remove_reference_image(self, prefix: str, index: int) -> None:
        """从显示里移除第 index 张（配置由控制器改；这里保持显示同步）。"""
        paths = self.reference_images(prefix)
        if not 0 <= index < len(paths):
            return
        images = list(self._strips[prefix].images())
        del paths[index]
        del images[index]
        self._apply_reference_view(
            prefix, paths, images, selected=min(index, len(paths) - 1) if paths else 0
        )

    def clear_reference_images(self, prefix: str) -> None:
        """清空某个建筑的参考图显示。"""
        self._apply_reference_view(prefix, [], [], selected=0)

    def reference_images(self, prefix: str) -> list[str]:
        """当前显示的参考图路径列表（顺序＝用户选择顺序）。"""
        return list(self._reference_paths.get(prefix, []))

    def selected_index(self, prefix: str) -> int:
        """当前大图显示的是第几张（0 起）。"""
        strip = self._strips.get(prefix)
        return strip.selected_index() if strip is not None else 0

    def preview_widget(self, prefix: str) -> ImagePreview | None:
        """某个建筑的「选择的图片」大图区（测试与控制器用）。"""
        return self._previews.get(prefix)

    def thumbnail_strip(self, prefix: str) -> ThumbnailStrip | None:
        """某个建筑的缩略图条（测试与控制器用）。"""
        return self._strips.get(prefix)

    def clear_button(self, prefix: str) -> QPushButton | None:
        """某个建筑缩略图条旁**可见的**「清空全部」按钮（测试与状态同步用）。"""
        return self._clear_buttons.get(prefix)

    def _apply_reference_view(self, prefix: str, paths: list[str],
                              images: list[QImage | None], *, selected: int) -> None:
        """把"路径列表 + 图片列表"一次落到界面（输入框文案 / 缩略图条 / 大图）并记住路径。"""
        paths = list(paths)
        self._reference_paths[prefix] = paths
        edit = self._ref_edits[prefix]
        edit.setText(_reference_summary(paths))
        edit.setToolTip(_reference_tooltip(prefix, paths))
        strip = self._strips[prefix]
        strip.set_images(list(images) + [None] * (len(paths) - len(images)))
        strip.select(selected)
        self._sync_clear_button(prefix, len(paths))
        self._show_selected(prefix)
        logger.debug("参考图已刷新：%s 共 %d 张", prefix, len(paths))

    def _sync_clear_button(self, prefix: str, count: int) -> None:
        """「清空全部」按钮的可用性：没图时禁用（点它什么都不会发生，别让用户白点）。

        有图时的提示要说清两件事：会清掉几张、以及**会连磁盘文件一起删**（先弹一次确认）。
        """
        button = self._clear_buttons.get(prefix)
        if button is None:
            return
        button.setEnabled(count > 0)
        button.setToolTip(
            f"清空{building_title(prefix)}的 {count} 张参考图（会先弹一次确认；确认后连磁盘文件"
            f"一起删 —— 只删 assets/templates 与 assets/anchors 里的图片）"
            if count else f"还没选图片，没有可清空的（{building_title(prefix)}）"
        )

    def _show_selected(self, prefix: str) -> None:
        """把"当前选中那张"画进大图区。"""
        strip = self._strips[prefix]
        self._previews[prefix].set_image(strip.image_at(strip.selected_index()))

    def _on_thumbnail_selected(self, prefix: str, _index: int) -> None:
        self._show_selected(prefix)          # 点缩略图＝换大图（不发放大请求，只换显示）

    def _emit_preview(self, prefix: str, index: int | None = None) -> None:
        """双击（缩略图或大图）→ 请求放大：默认放大当前选中的那张。"""
        if index is None:
            index = self._strips[prefix].selected_index()
        self.preview_requested.emit(prefix, index)

    def _on_preview_context_menu(self, prefix: str) -> None:
        """大图上的右键菜单（与缩略图条一致：移除当前这张 / 清空全部）。"""
        if not self.reference_images(prefix):
            return
        from PySide6.QtWidgets import QMenu

        index = self._strips[prefix].selected_index()
        menu = QMenu(self)
        remove = menu.addAction(f"移除第 {index + 1} 张")
        remove.triggered.connect(
            lambda _checked=False: self.remove_image_requested.emit(prefix, index)
        )
        clear = menu.addAction("清空全部")
        clear.triggered.connect(lambda _checked=False: self.clear_images_requested.emit(prefix))
        menu.exec(self._previews[prefix].mapToGlobal(self._previews[prefix].rect().center()))


def _reference_summary(paths: list[str]) -> str:
    """参考图输入框里显示的一行文案：1 张＝路径；多张＝"共 N 张：文件名、文件名…"。"""
    if not paths:
        return ""                                   # 空串＝显示占位提示「尚未选择图片」
    if len(paths) == 1:
        return paths[0]                             # 单张显示完整路径（与旧行为一致）
    names = "、".join(Path(item).name for item in paths)
    return f"共 {len(paths)} 张：{names}"


def _reference_tooltip(prefix: str, paths: list[str]) -> str:
    """参考图输入框的悬停提示：完整路径逐行列出（多张时输入框里看不到全路径）。"""
    header = (
        f"只能选择图片文件（可多选，最多 {MAX_REFERENCE_IMAGES} 张）；"
        f"由「选择图片…」或「截取游戏画面」填写"
    )
    if not paths:
        return header
    lines = "\n".join(f"{index + 1}. {item}" for index, item in enumerate(paths))
    return f"{building_title(prefix)}已选 {len(paths)} 张：\n{lines}\n\n{header}"
