"""日常任务页的「参考图」三件事：选择图片 / 截取游戏画面 / 放大预览。

**为什么单开一个模块**：`gui/pages/daily.py` 只允许"事件绑定与展示"（AGENTS §1.5），
选文件、截图、框选、写配置这些都带副作用，统一放这里；主窗口把页面的三个信号接过来。
（与开发者调试页「框选截图生成模板」是同一套零件：截图走 `core.vision.capture_window`、
框选走 `gui.dialogs.crop_dialog.TemplateCropDialog`、读图走 `automation.template_match`。）

用户 2026-09-22 选定的口径：
- **「选择图片…」**：默认打开 `assets/templates/` → 只收 png/jpg/jpeg/bmp/webp →
  **选中即校验**（纯色图直接拒收并提示换一张；辨识度偏低只提示不拦）；
- **「截取游戏画面」＝方案 2（框选）**：先把游戏窗口切到前台 → 等
  `daily_workers.FRONT_SETTLE_SECONDS` →
  截客户区 → 弹出与调试页同一个框选窗口 → **只保存你框的那块**到 `assets/anchors/`
  （原始素材不入库，见 `.gitignore`）→ 回填路径 + 显示缩略图；
- **双击「选择的图片」**：工具内弹窗放大预览（等比缩放到屏幕的 80%），不调系统看图程序；
- 配置里存**相对仓库根**的路径（`utils.paths.to_config_path`），换目录后仍可读；
- 失败只写日志 + 状态栏提示（含日志路径提示），**不弹窗打断**、**不改动原有参考图**。

**线程约定（第五轮评审 P2-3/P2-4）**：
- 解码（4K 截图单张最坏 ~0.37 s，`refresh_previews()` 三张最坏 ~1.1 s）一律走
  `ReferenceImageLoader` 后台线程 → 结果用信号回 GUI 线程，**只有 GUI 线程写配置/刷界面**；
- 截图线程与解码线程都支持 `request_stop()`，主窗口急停（F8 / 「停止」）与关窗都会调用
  `DailyMediaController.request_stop()` / `worker_threads()` —— 否则"已请求停止"之后
  0.4 秒框选窗口照样弹出来，等于急停按不动。

**2026-09-22 拆出 `gui/daily_workers.py`**：解码线程与截图线程（`ReferenceImageLoader` /
`DailyCaptureThread`）连同结果类型搬去那边 —— 本模块曾到 701 行，超 AGENTS §2 的 600 行硬线；
这里保留控制器，并把搬走的名字**再导出**，调用方一行不用改。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from luoluotool.automation.template_match import DEFAULT_THRESHOLD
from luoluotool.config.models import MAX_IMAGE_PATH_LENGTH, MAX_REFERENCE_IMAGES
from luoluotool.gui.daily_workers import (
    DailyCaptureThread,
    PickBatch,
    ReferenceImageLoader,
    ReferenceImageResult,
    decode_reference_image,
)
from luoluotool.gui.dialogs.crop_dialog import TemplateCropDialog
from luoluotool.gui.pages.daily import PICK_FILTER
from luoluotool.gui.pages.daily_fields import (
    BUILDINGS,
    building_title,
    island_field,
    ref_image_field,
)
from luoluotool.utils.paths import (
    PROJECT_ROOT,
    get_anchors_dir,
    get_templates_dir,
    resolve_config_path,
    to_config_path,
)

logger = logging.getLogger(__name__)

PREVIEW_SCREEN_RATIO = 0.8        # 放大预览最多占屏幕的该比例
LOG_PATH_HINT = PROJECT_ROOT / "logs" / "luoluotool.log"


class DailyMediaController(QObject):
    """把日常任务页的「选图 / 截图 / 预览 / 移除」请求落到文件、后台线程与框选弹窗上。

    线程登记：截图线程最多一个（`capture_thread()`），解码线程可能同时有多个
    （选图/预览/刷新各一批）——`worker_threads()` 给主窗口关窗与急停用。

    参考图**每个建筑最多 `MAX_REFERENCE_IMAGES` 张**（用户 2026-09-22 要求可多选）：
    「选择图片…」＝多选并**替换**整批；「截取游戏画面」＝把框选产物**追加**到末尾；
    缩略图/大图右键＝移除某张或清空。
    """

    def __init__(
        self,
        page: DailyPage,
        *,
        get_config: Callable[[], object],
        on_changed: Callable[[], None],
        set_status: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._page = page
        self._get_config = get_config
        self._on_changed = on_changed
        self._set_status = set_status
        self._thread: DailyCaptureThread | None = None
        self._loaders: set[ReferenceImageLoader] = set()
        self._pending_prefix: str | None = None
        self._pending_pick: PickBatch | None = None
        # 「哪一批解码的结果才算数」：同一用途重复发起时，旧批次的迟到结果必须丢弃
        self._generation: dict[str, int] = {"pick": 0, "preview": 0, "refresh": 0}
        page.pick_image_requested.connect(self.pick_image)
        page.capture_requested.connect(self.capture_image)
        page.preview_requested.connect(self.show_preview)
        page.remove_image_requested.connect(self.remove_image)
        page.clear_images_requested.connect(self.clear_images)

    # ---------------------------------------------------------------- 线程登记
    def capture_thread(self) -> DailyCaptureThread | None:
        """在飞的截图线程。"""
        return self._thread

    def loader_threads(self) -> tuple[ReferenceImageLoader, ...]:
        """在飞的解码线程（测试与关窗等待用）。"""
        return tuple(self._loaders)

    def worker_threads(self) -> tuple[QThread, ...]:
        """所有在飞线程：主窗口关窗等待 + `_long_job_running()` 判定。"""
        threads: list[QThread] = [loader for loader in self._loaders]
        if self._thread is not None:
            threads.append(self._thread)
        return tuple(threads)

    def request_stop(self) -> None:
        """请求停止在飞线程（急停 / 「停止」按钮 / 关窗都走这里，评审 P2-3）。"""
        if self._thread is not None:
            self._thread.request_stop()
        for loader in tuple(self._loaders):
            loader.request_stop()

    def is_busy(self) -> bool:
        """有截图在飞（截图期间不接受第二次截图）。"""
        return self._thread is not None and self._thread.isRunning()

    # ---------------------------------------------------------------- 解码调度
    def _start_decoding(self, requests: list[tuple[str, str]], *, validate: bool,
                        intent: str) -> ReferenceImageLoader:
        """起一批解码；同一 `intent` 只有最新一批的结果算数。"""
        self._generation[intent] = self._generation.get(intent, 0) + 1
        token = self._generation[intent]
        loader = ReferenceImageLoader(requests, logger, validate=validate)
        self._loaders.add(loader)
        loader.item_ready.connect(
            lambda prefix, value, result, i=intent, t=token: self._dispatch(i, t, prefix, value, result)
        )
        loader.finished.connect(lambda item=loader: self._on_loader_finished(item))
        loader.start()
        return loader

    def _on_loader_finished(self, loader: ReferenceImageLoader) -> None:
        self._loaders.discard(loader)

    def _dispatch(self, intent: str, token: int, prefix: str, value: str, result) -> None:
        if self._generation.get(intent) != token:
            logger.info("参考图解码结果已作废（%s：%s，已被更新的请求取代）", intent, prefix)
            return
        handler = {
            "pick": self.on_pick_ready,
            "preview": self.on_preview_ready,
            "refresh": self.on_thumbnails_ready,
        }[intent]
        handler(prefix, value, result)

    # ---------------------------------------------------------------- 选择图片…（可多选）
    def pick_image(self, prefix: str) -> None:
        """弹文件对话框**多选**识别图片（默认目录＝已有图片的目录，否则 `assets/templates/`）。

        一次选中的这几张**替换**该建筑原来的列表（对话框里选了什么就是什么）；
        想在某几张基础上再加，就用「截取游戏画面」（它是**追加**，用户 2026-09-22 选定）。
        """
        title = building_title(prefix)
        start_dir = self._suggested_pick_dir(prefix)
        paths, _selected = QFileDialog.getOpenFileNames(
            self._page, f"选择{title}的识别图片（可多选，最多 {MAX_REFERENCE_IMAGES} 张）",
            str(start_dir), PICK_FILTER,
        )
        if not paths:
            logger.info("已取消选择参考图（%s）", prefix)
            self._set_status(f"已取消选择图片（{title}的参考图未改动）")
            return
        self.start_pick(prefix, [Path(item) for item in paths])

    def _suggested_pick_dir(self, prefix: str) -> Path:
        """对话框的起始目录：已有图片所在目录 → 否则 `assets/templates/`。"""
        values = self._values(prefix)
        if values:
            current = resolve_config_path(values[0])
            if current is not None and current.parent.is_dir():
                return current.parent
        return get_templates_dir()

    def start_pick(self, prefix: str, paths: list[Path]) -> bool:
        """校验并采纳一批参考图；**解码与校验在后台线程**（4K 图单张最坏约 0.37 s）。

        规则（都在这里一次说清）：
        - 路径过长（> `MAX_IMAGE_PATH_LENGTH`）的那几张**直接丢掉**并提示（超长路径写进配置会让
          `store.save` 抛 `ConfigSaveError`，导致**本次所有改动都不落盘**，第五轮评审 P3-1）；
        - 超过 `MAX_REFERENCE_IMAGES` 张时**只取前 N 张**并提示（界面能选的数量必须与校验器一致）；
        - 重复路径去重（同一张图选两次没有意义）。
        """
        title = building_title(prefix)
        kept: list[str] = []
        too_long = 0
        for path in paths:
            value = to_config_path(path)
            if len(value) > MAX_IMAGE_PATH_LENGTH:
                too_long += 1
                logger.warning("参考图路径过长（%d 字符）：%s", len(value), value)
                continue
            if value not in kept:
                kept.append(value)
        if not kept:
            self._set_status(
                f"没有可用的图片：路径太长（配置最多 {MAX_IMAGE_PATH_LENGTH} 字符）——"
                f"请把{title}的图片放到仓库里的 assets/ 下再选"
            )
            return False
        notes: list[str] = []
        if too_long:
            notes.append(f"{too_long} 张路径太长已跳过")
        if len(kept) > MAX_REFERENCE_IMAGES:
            notes.append(f"最多 {MAX_REFERENCE_IMAGES} 张，已只取前 {MAX_REFERENCE_IMAGES} 张")
            kept = kept[:MAX_REFERENCE_IMAGES]
        self._pending_pick = PickBatch(prefix=prefix, values=kept, note="；".join(notes))
        self._set_status(f"正在校验并载入{title}的 {len(kept)} 张参考图…")
        self._start_decoding([(prefix, value) for value in kept], validate=True, intent="pick")
        return True

    def on_pick_ready(self, prefix: str, value: str, result: ReferenceImageResult) -> None:
        """选图解码完成（GUI 线程，**逐张**回调）：全批到齐后再一次性写配置 + 显示。"""
        batch = self._pending_pick
        if batch is None or batch.prefix != prefix:
            logger.info("参考图解码结果没有对应的选图批次，已忽略：%s", value)
            return
        batch.results[value] = result
        if not batch.is_complete():
            return
        self._pending_pick = None
        self._finish_pick(batch)

    def _finish_pick(self, batch: PickBatch) -> None:
        """一批选图都解码完了：把合格的写进配置（不合格的逐张说明原因）。"""
        ok_values: list[str] = []
        ok_images: list[QImage | None] = []
        rejected: list[tuple[str, str]] = []
        low_quality = 0
        for value in batch.values:                     # 保持用户选择顺序
            result = batch.results.get(value)
            if result is None:
                continue
            if not result.ok:
                rejected.append((value, result.message))
                continue
            ok_values.append(value)
            ok_images.append(result.image)
            if result.quality is not None and result.quality.level != "ok":
                low_quality += 1
        if not ok_values:
            logger.warning("选图全部被拒绝（%s）：%s", batch.prefix, rejected)
            first = rejected[0][1] if rejected else "读不出图片"
            self._set_status(f"这些图都不能用：{first}")
            return
        notes = [batch.note] if batch.note else []
        if rejected:
            names = "、".join(Path(value).name for value, _message in rejected)
            notes.append(f"{len(rejected)} 张被拒（{names}）：{rejected[0][1]}")
        if low_quality:
            notes.append(f"{low_quality} 张辨识度偏低")
        self.apply_reference_images(batch.prefix, ok_values, ok_images, note="；".join(notes))

    def apply_reference_images(self, prefix: str, values: list[str],
                               images: list[QImage | None], *, note: str = "") -> bool:
        """写配置 + 整批显示（**只在 GUI 线程调用**：写配置不允许在后台线程做）。"""
        if any(len(value) > MAX_IMAGE_PATH_LENGTH for value in values):
            return self._path_length_ok(prefix, next(
                value for value in values if len(value) > MAX_IMAGE_PATH_LENGTH
            ))
        if len(values) > MAX_REFERENCE_IMAGES:
            self._set_status(
                f"最多只能选 {MAX_REFERENCE_IMAGES} 张{building_title(prefix)}的参考图"
                f"（当前要存 {len(values)} 张）"
            )
            return False
        setattr(self._get_config().features.daily_tasks, ref_image_field(prefix), list(values))
        self._on_changed()
        self._page.set_reference_images(prefix, list(values), list(images))
        title = building_title(prefix)
        if len(values) == 1:
            suffix = f"（{note}）" if note else ""
            self._set_status(f"已选择{title}的参考图：{values[0]}{suffix}")
        else:
            names = "、".join(Path(value).name for value in values)
            suffix = f"（{note}）" if note else ""
            self._set_status(f"已选择{title}的 {len(values)} 张参考图：{names}{suffix}")
        logger.info("参考图已选择：%s → %s%s", prefix, values, f"（{note}）" if note else "")
        return True

    def _path_length_ok(self, prefix: str, value: str) -> bool:
        if len(value) <= MAX_IMAGE_PATH_LENGTH:
            return True
        logger.warning("参考图路径过长（%d 字符 > %d）：%s", len(value), MAX_IMAGE_PATH_LENGTH, value)
        self._set_status(
            f"路径太长（{len(value)} 字符，配置最多 {MAX_IMAGE_PATH_LENGTH}）："
            f"请把{building_title(prefix)}的图片放到仓库里的 assets/ 下再选，否则配置存不下"
        )
        return False

    # ---------------------------------------------------------------- 移除 / 清空
    def remove_image(self, prefix: str, index: int) -> None:
        """移除第 index 张（右键菜单来的；列表为空或下标越界时什么都不做）。"""
        values = self._values(prefix)
        if not 0 <= index < len(values):
            return
        removed = values[index]
        values = values[:index] + values[index + 1:]
        setattr(self._get_config().features.daily_tasks, ref_image_field(prefix), values)
        self._on_changed()
        self._page.remove_reference_image(prefix, index)
        logger.info("参考图已移除：%s → %s（还剩 %d 张）", prefix, removed, len(values))
        self._set_status(
            f"已移除 {Path(removed).name}（{building_title(prefix)}还剩 {len(values)} 张）"
        )

    def clear_images(self, prefix: str) -> None:
        """清空某个建筑的全部参考图（右键菜单来的）。"""
        count = len(self._values(prefix))
        if count == 0:
            return
        setattr(self._get_config().features.daily_tasks, ref_image_field(prefix), [])
        self._on_changed()
        self._page.clear_reference_images(prefix)
        logger.info("参考图已清空：%s（原有 %d 张）", prefix, count)
        self._set_status(f"已清空{building_title(prefix)}的 {count} 张参考图")

    # ---------------------------------------------------------------- 截取游戏画面
    def capture_image(self, prefix: str) -> None:
        """方案 2：切前台 → 截客户区 → 框选 → 只保存框住的那块。"""
        if self.is_busy():
            self._set_status("上一次截图还没结束，请稍等（或点「停止」）")
            return
        self._pending_prefix = prefix
        self._set_status(f"正在把游戏窗口切到前台并截图（{building_title(prefix)}）…")
        thread = DailyCaptureThread(self._get_config(), logger)
        self._thread = thread
        thread.captured.connect(self.on_capture_ready)
        thread.failed_message.connect(self.on_capture_failed)
        thread.finished.connect(self._on_thread_finished)
        thread.start()

    def on_capture_ready(self, image, window_size) -> None:
        """截图完成（GUI 线程）：弹框选窗口，保存后把路径记进配置并显示缩略图。"""
        prefix = self._pending_prefix
        if prefix is None:
            logger.warning("截图完成但没有待处理的建筑，已忽略")
            return
        title = building_title(prefix)
        island = int(self._island_of(prefix))
        self._set_status(f"请在弹窗里框选{title}的位置（只保存你框的那块）…")
        dialog = TemplateCropDialog(
            image, window_size, get_anchors_dir(), self._page,
            threshold=DEFAULT_THRESHOLD, file_stem=f"{title}_岛屿{island}",
        )
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            dialog.deleteLater()
        if not accepted or dialog.saved_path is None:
            logger.info("已取消框选（%s 的参考图未改动）", prefix)
            self._set_status(f"已取消框选（{title}的参考图未改动）")
            return
        self.adopt_captured_image(prefix, dialog.saved_path, dialog.selection())

    def adopt_captured_image(self, prefix: str, saved_path: Path,
                             selection: tuple[int, int, int, int] | None = None) -> bool:
        """把框选产物**追加**成该建筑的一张参考图（用户 2026-09-22 选定：追加而不是替换）。

        产物很小，这里同步解码即可；已有 10 张（上限）时拒绝并提示先移除一张。
        """
        result = decode_reference_image(saved_path, validate=True)
        if not result.ok:                              # 理论上不该发生（弹窗已拦过一次）
            logger.warning("框选产物读不回来（%s）：%s", prefix, result.message)
            self._set_status(f"框选结果不能用：{result.message}")
            return False
        value = to_config_path(saved_path)
        values = self._values(prefix)
        if value in values:
            self._set_status(f"这张图已经在{building_title(prefix)}的列表里了（未重复添加）")
            return False
        if len(values) >= MAX_REFERENCE_IMAGES:
            logger.warning("参考图已达上限 %d，拒绝追加：%s", MAX_REFERENCE_IMAGES, prefix)
            self._set_status(
                f"{building_title(prefix)}已经有 {MAX_REFERENCE_IMAGES} 张参考图（上限）："
                f"请先在缩略图上右键移除一张，再截取"
            )
            return False
        setattr(self._get_config().features.daily_tasks, ref_image_field(prefix), values + [value])
        self._on_changed()
        self._page.append_reference_image(prefix, value, result.image)
        area = "" if selection is None else (
            f"，选区 {selection[2]}x{selection[3]}，客户区左上 ({selection[0]}, {selection[1]})"
        )
        self._set_status(
            f"{building_title(prefix)}的参考图已追加（第 {len(values) + 1} 张）：{value}{area}"
        )
        logger.info("参考图已保存（框选，追加）：%s → %s", prefix, value)
        return True

    def on_capture_failed(self, message: str) -> None:
        """截图失败：只提示 + 日志（不弹窗），并说清去哪里看日志。"""
        logger.warning("截取游戏画面失败：%s", message)
        self._set_status(f"截取游戏画面失败：{message}（详见 {LOG_PATH_HINT}）")

    def _on_thread_finished(self) -> None:
        if self.sender() is self._thread:              # 迟到信号不许清掉新一轮的引用
            self._thread = None

    def _island_of(self, prefix: str) -> int:
        return int(getattr(self._get_config().features.daily_tasks, island_field(prefix), 1))

    # ---------------------------------------------------------------- 放大预览
    def show_preview(self, prefix: str, index: int = 0) -> None:
        """双击缩略图/大图（或页面传来第几张）：先做路径检查（同步），解码走线程，图到了再开弹窗。

        `index` 是"第几张"（0 起，来自页面信号）；越界就退回第 1 张，从不报错。
        """
        title = building_title(prefix)
        values = self._values(prefix)
        if not values:
            self._set_status(f"{title}还没选参考图")
            return
        if not 0 <= index < len(values):
            index = 0
        value = values[index]
        path = resolve_config_path(value)
        if path is None or not path.is_file():
            logger.warning("参考图文件不存在：%s（配置里记的是 %s）", path, value)
            self._set_status(
                f"找不到{title}的第 {index + 1} 张参考图：{path}（配置没被改动，请重新选一张；"
                f"详见 {LOG_PATH_HINT}）"
            )
            return
        self._set_status(f"正在打开{title}的第 {index + 1}/{len(values)} 张预览…")
        self._start_decoding([(prefix, value)], validate=False, intent="preview")

    def on_preview_ready(self, prefix: str, value: str, result: ReferenceImageResult) -> None:
        if not result.ok or result.image is None:
            self._set_status(f"打不开这张图：{result.message}")
            return
        dialog = self.build_preview_dialog(prefix, result.image, path=value)
        if dialog is None:
            return
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def build_preview_dialog(self, prefix: str, image: QImage | None,
                             path: str | None = None) -> QDialog | None:
        """用**已经解码好的** QImage 构造放大预览弹窗（不 exec，便于测试）。

        `path` 只用来显示"这是第几张/哪个文件"；不传就用配置里的第一张。
        """
        if image is None:
            self._set_status(f"{building_title(prefix)}还没选参考图")
            return None
        if path is None:
            values = self._values(prefix)
            path = values[0] if values else ""
        values = self._values(prefix)
        position = f"第 {values.index(path) + 1}/{len(values)} 张 · " if path in values else ""
        pixmap = QPixmap.fromImage(image)
        limit = self._preview_limit()
        if pixmap.width() > limit[0] or pixmap.height() > limit[1]:
            pixmap = pixmap.scaled(
                limit[0], limit[1], Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        dialog = QDialog(self._page)
        dialog.setWindowTitle(f"预览：{building_title(prefix)}的参考图")
        layout = QVBoxLayout(dialog)
        label = QLabel()
        label.setPixmap(pixmap)
        scroll = QScrollArea(dialog)
        scroll.setWidget(label)
        scroll.setWidgetResizable(False)
        layout.addWidget(QLabel(
            f"{position}{path}\n（{image.width()}x{image.height()} 像素）"
        ))
        layout.addWidget(scroll)
        logger.info("打开参考图预览：%s", path)
        return dialog

    def _preview_limit(self) -> tuple[int, int]:
        """放大预览的最大尺寸（屏幕的 80%；拿不到屏幕信息时退回一个保守值）。"""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 1280, 800
        size = screen.availableGeometry().size()
        return (
            max(320, int(size.width() * PREVIEW_SCREEN_RATIO)),
            max(240, int(size.height() * PREVIEW_SCREEN_RATIO)),
        )

    # ---------------------------------------------------------------- 重新加载
    def refresh_previews(self) -> None:
        """按配置把三个建筑的参考图（可能各有多张）重读一遍缩略图。

        主窗口在"加载配置 / 重载 / 恢复默认"之后调用。路径列表**同步**先交给页面显示（不碰文件），
        解码**全部放后台线程**（评审 P2-4：一张 4K 最坏 ~0.37 s，十张不能占 GUI 线程）；
        文件被删掉时**只清缩略图 + 记日志**，绝不悄悄把配置里的路径抹掉（用户可能只是换机器）。
        """
        requests: list[tuple[str, str]] = []
        for _title, prefix, _word, _field, _capture in BUILDINGS:
            values = self._values(prefix)
            self._page.set_reference_images(prefix, values, [None] * len(values))
            requests.extend((prefix, value) for value in values)
        if requests:
            self._start_decoding(requests, validate=False, intent="refresh")

    def on_thumbnails_ready(self, prefix: str, value: str, result: ReferenceImageResult) -> None:
        """某张缩略图解码完成：成功就显示；失败保留路径文字、只清缩略图（不改配置）。"""
        values = self._values(prefix)
        if value not in values:            # 列表已经变了（用户又选/删了）→ 迟到结果丢弃
            logger.info("缩略图结果已作废（%s：%s 已不在列表里）", prefix, value)
            return
        self._page.set_reference_thumbnail(
            prefix, values.index(value), result.image if result.ok else None
        )

    def _values(self, prefix: str) -> list[str]:
        """配置里该建筑的参考图路径列表（永远是列表：域里是 list，缺字段回落空列表）。"""
        return list(getattr(self._get_config().features.daily_tasks, ref_image_field(prefix), []) or [])
