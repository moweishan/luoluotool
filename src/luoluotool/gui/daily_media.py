"""日常任务页的「参考图」三件事：选择图片 / 截取游戏画面 / 放大预览。

**为什么单开一个模块**：`gui/pages/daily.py` 只允许"事件绑定与展示"（AGENTS §1.5），
选文件、截图、框选、写配置这些都带副作用，统一放这里；主窗口把页面的三个信号接过来。
（与开发者调试页「框选截图生成模板」是同一套零件：截图走 `core.vision.capture_window`、
框选走 `gui.dialogs.crop_dialog.TemplateCropDialog`、读图走 `automation.template_match`。）

用户 2026-09-22 选定的口径：
- **「选择图片…」**：默认打开 `assets/templates/` → 只收 png/jpg/jpeg/bmp/webp →
  **选中即校验**（纯色图直接拒收并提示换一张；辨识度偏低只提示不拦）；
- **「截取游戏画面」＝方案 2（框选）**：先把游戏窗口切到前台 → 等 `FRONT_SETTLE_SECONDS` →
  截客户区 → 弹出与调试页同一个框选窗口 → **只保存你框的那块**到 `assets/anchors/`
  （原始素材不入库，见 `.gitignore`）→ 回填路径 + 显示缩略图；
- **双击「选择的图片」**：工具内弹窗放大预览（等比缩放到屏幕的 80%），不调系统看图程序；
- 配置里存**相对仓库根**的路径（`utils.paths.to_config_path`），换目录后仍可读；
- 失败只写日志 + 状态栏提示（含日志路径提示），**不弹窗打断**、**不改动原有参考图**。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from luoluotool.automation.template_match import (
    DEFAULT_THRESHOLD,
    VisionError,
    assess_region_quality,
    load_template,
    read_image_bgr,
)
from luoluotool.automation.window import bring_to_front, find_window
from luoluotool.core import vision as vision_actions
from luoluotool.gui.dialogs.crop_dialog import TemplateCropDialog, to_qimage
from luoluotool.gui.pages.daily import (
    BUILDINGS,
    PICK_FILTER,
    DailyPage,
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

FRONT_SETTLE_SECONDS = 0.4        # 把游戏切前台后等这么久再截图（等它渲染出前台那一帧）
FRONT_SETTLE_SLICE_SECONDS = 0.05  # 等待切片，便于急停/关窗时尽快收手
PREVIEW_SCREEN_RATIO = 0.8        # 放大预览最多占屏幕的该比例


class DailyCaptureThread(QThread):
    """后台线程：把游戏窗口切到前台 → 稍等 → 截一张客户区。

    为什么要切前台：本工具的窗口此时通常正盖在游戏上面，而取景的最后兜底是"屏幕 BitBlt"
    （见 `automation.vision.capture_client_bgr` 的回退链）—— 游戏不在前台就只会截到
    本工具自己。这是用户 2026-09-22 明确选定的做法（会短暂抢一下焦点，截完立刻弹框选窗口）。

    线程体只调用 automation/core 的现成函数，不做输入注入，也不碰 Qt 界面。
    """

    captured = Signal(object, object)          # (numpy 图像, (宽, 高))
    failed_message = Signal(str)

    def __init__(self, config, log: logging.Logger, settle: float = FRONT_SETTLE_SECONDS) -> None:
        super().__init__()
        self._config = config
        self._log = log
        self._settle = float(settle)
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        """请求停止：还没截图就不要再截（已经发出的那一次无法中途打断）。"""
        self._stop_event.set()

    def run(self) -> None:
        keyword = self._config.automation.window_title_keyword
        hwnd = find_window(keyword)
        if hwnd is None:
            message = f"未找到标题含“{keyword}”的窗口，请确认游戏已窗口化运行"
            self._log.warning("截取游戏画面失败：%s", message)
            self.failed_message.emit(message)
            return
        if not bring_to_front(hwnd):
            # 置前失败不直接放弃：游戏可能本来就在前台（只是没有前台权限去确认），
            # 继续尝试截图，真截不到会在 capture_window 里给出可读原因。
            self._log.warning("把游戏窗口切到前台失败，仍尝试截图（截到黑帧会被识别为失败）")
        if not self._interruptible_sleep():
            self._log.info("截取游戏画面已取消（等待切前台期间收到停止请求）")
            return
        image, message = vision_actions.capture_window(self._config)
        if image is None:
            self._log.warning("截取游戏画面失败：%s", message)
            self.failed_message.emit(message)
            return
        if self._stop_event.is_set():
            self._log.info("截取游戏画面已取消：截图已完成但结果不再使用")
            return
        height, width = image.shape[:2]
        self._log.info("截取游戏画面：客户区 %dx%d（已把窗口切到前台）", width, height)
        self.captured.emit(image, (int(width), int(height)))

    def _interruptible_sleep(self) -> bool:
        """切片等待；期间收到停止请求返回 False。"""
        remaining = self._settle
        while remaining > 0:
            if self._stop_event.is_set():
                return False
            step = min(FRONT_SETTLE_SLICE_SECONDS, remaining)
            time.sleep(step)
            remaining -= step
        return not self._stop_event.is_set()


class DailyMediaController(QObject):
    """把日常任务页的「选图 / 截图 / 预览」请求落到文件、截图线程与框选弹窗上。"""

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
        self._pending_prefix: str | None = None
        page.pick_image_requested.connect(self.pick_image)
        page.capture_requested.connect(self.capture_image)
        page.preview_requested.connect(self.show_preview)

    # ---------------------------------------------------------------- 状态查询
    def capture_thread(self) -> DailyCaptureThread | None:
        """在飞的截图线程（主窗口关窗时要等它退出）。"""
        return self._thread

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    # ---------------------------------------------------------------- 选择图片…
    def pick_image(self, prefix: str) -> None:
        """弹文件对话框选一张识别图片（默认目录＝上次那张的目录，否则 `assets/templates/`）。"""
        title = building_title(prefix)
        start_dir = self._suggested_pick_dir(prefix)
        path, _selected = QFileDialog.getOpenFileName(
            self._page, f"选择{title}的识别图片", str(start_dir), PICK_FILTER
        )
        if not path:
            logger.info("已取消选择参考图（%s）", prefix)
            self._set_status(f"已取消选择图片（{title}的参考图未改动）")
            return
        self.adopt_image_file(prefix, Path(path))

    def _suggested_pick_dir(self, prefix: str) -> Path:
        """对话框的起始目录：配置里那张图所在目录 → 否则 `assets/templates/`。"""
        current = resolve_config_path(self._field_value(prefix))
        if current is not None:
            parent = current.parent
            if parent.is_dir():
                return parent
        return get_templates_dir()

    def adopt_image_file(self, prefix: str, path: Path) -> bool:
        """校验一张图片并把它记成该建筑的参考图（选图与测试都走这里）。

        返回是否采纳。**纯色/读不出的图直接拒收**（与 `load_template` 同一条规则：
        那种图拿去识别会满地"匹配度 1.000"），辨识度偏低只提示不拦。
        """
        try:
            image = load_template(path)
        except VisionError as exc:
            logger.warning("参考图被拒绝（%s）：%s", prefix, exc)
            self._set_status(f"这张图不能用：{exc}")
            return False
        quality = assess_region_quality(image)
        rel = to_config_path(path)
        setattr(self._get_config().features.daily_tasks, ref_image_field(prefix), rel)
        self._on_changed()
        self._page.set_reference_image(prefix, rel, to_qimage(image))
        note = "" if quality.level == "ok" else f"（{quality.message}）"
        self._set_status(
            f"已选择{building_title(prefix)}的参考图：{rel}"
            f"（{image.shape[1]}x{image.shape[0]}）{note}"
        )
        logger.info(
            "参考图已选择：%s → %s（%dx%d，辨识度 %s）",
            prefix, rel, image.shape[1], image.shape[0], quality.level,
        )
        return True

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
        """把框选产物记成该建筑的参考图（框选与测试都走这里）。"""
        try:
            template = load_template(saved_path)
        except VisionError as exc:                     # 理论上不该发生（弹窗已拦过一次）
            logger.warning("框选产物读不回来（%s）：%s", prefix, exc)
            self._set_status(f"框选结果不能用：{exc}")
            return False
        rel = to_config_path(saved_path)
        setattr(self._get_config().features.daily_tasks, ref_image_field(prefix), rel)
        self._on_changed()
        self._page.set_reference_image(prefix, rel, to_qimage(template))
        area = "" if selection is None else (
            f"，选区 {selection[2]}x{selection[3]}，客户区左上 ({selection[0]}, {selection[1]})"
        )
        self._set_status(f"{building_title(prefix)}的参考图已保存：{rel}{area}")
        logger.info("参考图已保存（框选）：%s → %s", prefix, rel)
        return True

    def on_capture_failed(self, message: str) -> None:
        """截图失败：只提示 + 日志（不弹窗），并说清去哪里看日志。"""
        log_path = PROJECT_ROOT / "logs" / "luoluotool.log"
        logger.warning("截取游戏画面失败：%s", message)
        self._set_status(f"截取游戏画面失败：{message}（详见 {log_path}）")

    def _on_thread_finished(self) -> None:
        if self.sender() is self._thread:              # 迟到信号不许清掉新一轮的引用
            self._thread = None

    def _island_of(self, prefix: str) -> int:
        return int(getattr(self._get_config().features.daily_tasks, island_field(prefix), 1))

    # ---------------------------------------------------------------- 放大预览
    def show_preview(self, prefix: str) -> None:
        dialog = self.build_preview_dialog(prefix)
        if dialog is None:
            return
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def build_preview_dialog(self, prefix: str) -> QDialog | None:
        """构造放大预览弹窗（**不** exec，便于测试）；图不存在/还没选时返回 None 并提示。"""
        title = building_title(prefix)
        path = resolve_config_path(self._field_value(prefix))
        if path is None:
            self._set_status(f"{title}还没选参考图")
            return None
        log_path = PROJECT_ROOT / "logs" / "luoluotool.log"
        if not path.is_file():
            logger.warning("参考图文件不存在：%s（配置里记的是 %s）", path, self._field_value(prefix))
            self._set_status(f"找不到{title}的参考图文件：{path}（配置没被改动，请重新选一张；详见 {log_path}）")
            return None
        try:
            image = read_image_bgr(path)               # 预览不做"纯色拒绝"（能看就行）
        except VisionError as exc:
            logger.warning("预览参考图失败：%s", exc)
            self._set_status(f"打不开这张图：{exc}")
            return None
        pixmap = QPixmap.fromImage(to_qimage(image))
        limit = self._preview_limit()
        if pixmap.width() > limit[0] or pixmap.height() > limit[1]:
            pixmap = pixmap.scaled(
                limit[0], limit[1], Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        dialog = QDialog(self._page)
        dialog.setWindowTitle(f"预览：{title}的参考图")
        layout = QVBoxLayout(dialog)
        label = QLabel()
        label.setPixmap(pixmap)
        scroll = QScrollArea(dialog)
        scroll.setWidget(label)
        scroll.setWidgetResizable(False)
        layout.addWidget(QLabel(f"{path}\n（{image.shape[1]}x{image.shape[0]} 像素）"))
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
        """按配置把三张参考图的缩略图重读一遍（加载配置/重载/恢复默认后由主窗口调用）。

        页面本身不做文件 IO，所以"配置里的路径 → 缩略图"这一步在这里补上；
        文件被删掉时**只清缩略图 + 记日志**，绝不悄悄把配置里的路径抹掉（用户可能只是换机器）。
        """
        for _title, prefix, _word, _field, _capture in BUILDINGS:
            value = self._field_value(prefix)
            path = resolve_config_path(value)
            if path is None:
                self._page.set_reference_image(prefix, "", None)
                continue
            if not path.is_file():
                logger.warning("参考图文件不存在，暂不显示缩略图：%s（配置仍保留该路径）", path)
                self._page.set_reference_image(prefix, value, None)
                continue
            try:
                image = read_image_bgr(path)
            except VisionError as exc:
                logger.warning("读取参考图失败（%s）：%s", prefix, exc)
                self._page.set_reference_image(prefix, value, None)
                continue
            self._page.set_reference_image(prefix, value, to_qimage(image))

    def _field_value(self, prefix: str) -> str:
        return str(getattr(self._get_config().features.daily_tasks, ref_image_field(prefix), "") or "")
