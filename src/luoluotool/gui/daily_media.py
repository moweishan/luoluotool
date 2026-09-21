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

**线程约定（第五轮评审 P2-3/P2-4）**：
- 解码（4K 截图单张最坏 ~0.37 s，`refresh_previews()` 三张最坏 ~1.1 s）一律走
  `ReferenceImageLoader` 后台线程 → 结果用信号回 GUI 线程，**只有 GUI 线程写配置/刷界面**；
- 截图线程与解码线程都支持 `request_stop()`，主窗口急停（F8 / 「停止」）与关窗都会调用
  `DailyMediaController.request_stop()` / `worker_threads()` —— 否则"已请求停止"之后
  0.4 秒框选窗口照样弹出来，等于急停按不动。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
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
    RegionQuality,
    VisionError,
    assess_region_quality,
    load_template,
    read_image_bgr,
)
from luoluotool.automation.window import bring_to_front, find_window
from luoluotool.config.models import MAX_IMAGE_PATH_LENGTH
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
LOG_PATH_HINT = PROJECT_ROOT / "logs" / "luoluotool.log"


@dataclass(frozen=True)
class ReferenceImageResult:
    """一张参考图的解码结果（线程 → GUI 线程传的就是这个对象）。"""

    ok: bool                      # validate=True 时＝"能不能当模板"；False 时＝"读出来了没有"
    image: QImage | None
    quality: RegionQuality | None  # 只有 validate=True 才有
    width: int
    height: int
    message: str                  # 失败原因（ok=True 时为空）

    @classmethod
    def failed(cls, message: str) -> ReferenceImageResult:
        return cls(False, None, None, 0, 0, message)


def decode_reference_image(path: Path, *, validate: bool) -> ReferenceImageResult:
    """读一张参考图（纯函数，**可在后台线程调用**）。

    `validate=True`＝按"能不能当模板"校验：`load_template` 拒纯色（那种图拿去识别会满地
    "匹配度 1.000"），并附上 `assess_region_quality` 的可辨识度结论（低辨识度只提示不拦）。
    `validate=False`＝只要能把图读出来就行（刷新缩略图、放大预览用它 —— 用户存了一张纯色图
    也不该让界面报错）。

    QImage 可以在非 GUI 线程创建（QPixmap 不行）；本函数全程不碰 QPixmap。
    """
    if not path.is_file():
        return ReferenceImageResult.failed(f"找不到文件：{path}")
    try:
        image = load_template(path) if validate else read_image_bgr(path)
    except VisionError as exc:                     # 读不出/纯色/不是图片，都转成可读消息
        return ReferenceImageResult.failed(str(exc))
    quality = assess_region_quality(image) if validate else None
    height, width = image.shape[:2]
    return ReferenceImageResult(True, to_qimage(image), quality, int(width), int(height), "")


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


class ReferenceImageLoader(QThread):
    """后台线程：把一到多张参考图解码成 `ReferenceImageResult`（评审 P2-4）。

    离屏实测：`read_image_bgr` 799x478 约 21 ms、1920x1052 约 41 ms、**3840x2160 约 118 ms**；
    `load_template`（含质量判据）4K 高达 **373 ms**。放 GUI 线程就是界面冻结，尤其
    `refresh_previews()` 一次三张最坏 ~1.1 s。这里放线程跑，结果用信号回 GUI 线程。

    `requests` 是 `[(建筑前缀, 配置里的路径值), ...]`；每个请求回一个 `item_ready`
    （解码失败也回，带上可读原因 —— 界面只负责显示，不负责判断）。
    """

    item_ready = Signal(str, str, object)      # prefix, 配置里的路径值, ReferenceImageResult

    def __init__(self, requests: list[tuple[str, str]], log: logging.Logger,
                 *, validate: bool = False) -> None:
        super().__init__()
        self._requests = list(requests)
        self._log = log
        self._validate = validate
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        """请求停止：剩下的请求不再解码（正在解码的那一张会跑完，结果由调用方按代次丢弃）。"""
        self._stop_event.set()

    def stop_requested(self) -> bool:
        """是否已经收到停止请求（急停链路的测试与日志用）。"""
        return self._stop_event.is_set()

    def run(self) -> None:
        for prefix, value in self._requests:
            if self._stop_event.is_set():
                self._log.info("参考图解码已取消（收到停止请求），剩余 %d 张不再处理",
                               len(self._requests))
                return
            path = resolve_config_path(value)
            result = (
                ReferenceImageResult.failed("配置里没有路径")
                if path is None
                else decode_reference_image(path, validate=self._validate)
            )
            if not result.ok:
                self._log.warning("参考图解码失败（%s，%s）：%s", prefix, value, result.message)
            self.item_ready.emit(prefix, value, result)


class DailyMediaController(QObject):
    """把日常任务页的「选图 / 截图 / 预览」请求落到文件、后台线程与框选弹窗上。

    线程登记：截图线程最多一个（`capture_thread()`），解码线程可能同时有多个
    （选图/预览/刷新各一批）——`worker_threads()` 给主窗口关窗与急停用。
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
        # 「哪一批解码的结果才算数」：同一用途重复发起时，旧批次的迟到结果必须丢弃
        self._generation: dict[str, int] = {"pick": 0, "preview": 0, "refresh": 0}
        page.pick_image_requested.connect(self.pick_image)
        page.capture_requested.connect(self.capture_image)
        page.preview_requested.connect(self.show_preview)

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
        self.start_pick(prefix, Path(path))

    def _suggested_pick_dir(self, prefix: str) -> Path:
        """对话框的起始目录：配置里那张图所在目录 → 否则 `assets/templates/`。"""
        current = resolve_config_path(self._field_value(prefix))
        if current is not None:
            parent = current.parent
            if parent.is_dir():
                return parent
        return get_templates_dir()

    def start_pick(self, prefix: str, path: Path) -> bool:
        """校验并采纳一张参考图；**解码与校验在后台线程**（4K 图单张最坏约 0.37 s）。

        路径过长当场拒绝（配置校验器限 `MAX_IMAGE_PATH_LENGTH`，评审 P3-1）：超长路径一旦
        写进配置，`store.save` 会抛 `ConfigSaveError`，导致**本次所有改动都不落盘**。
        """
        value = to_config_path(path)
        if not self._path_length_ok(prefix, value):
            return False
        self._set_status(f"正在校验并载入{building_title(prefix)}的参考图…")
        self._start_decoding([(prefix, value)], validate=True, intent="pick")
        return True

    def on_pick_ready(self, prefix: str, value: str, result: ReferenceImageResult) -> None:
        """选图解码完成（GUI 线程）：合格就写配置 + 显示，不合格只提示（不动原图）。"""
        if not result.ok:
            logger.warning("参考图被拒绝（%s）：%s", prefix, result.message)
            self._set_status(f"这张图不能用：{result.message}")
            return
        self.apply_reference_image(prefix, value, result)

    def apply_reference_image(self, prefix: str, value: str,
                              result: ReferenceImageResult) -> bool:
        """写配置 + 显示缩略图 + 提示（**只在 GUI 线程调用**：写配置不允许在后台线程做）。"""
        if not self._path_length_ok(prefix, value):
            return False
        setattr(self._get_config().features.daily_tasks, ref_image_field(prefix), value)
        self._on_changed()
        self._page.set_reference_image(prefix, value, result.image)
        note = "" if result.quality is None or result.quality.level == "ok" else f"（{result.quality.message}）"
        self._set_status(
            f"已选择{building_title(prefix)}的参考图：{value}"
            f"（{result.width}x{result.height}）{note}"
        )
        logger.info(
            "参考图已选择：%s → %s（%dx%d，辨识度 %s）",
            prefix, value, result.width, result.height,
            "ok" if result.quality is None else result.quality.level,
        )
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
        """把框选产物记成该建筑的参考图（产物很小，这里同步解码即可）。"""
        result = decode_reference_image(saved_path, validate=True)
        if not result.ok:                              # 理论上不该发生（弹窗已拦过一次）
            logger.warning("框选产物读不回来（%s）：%s", prefix, result.message)
            self._set_status(f"框选结果不能用：{result.message}")
            return False
        value = to_config_path(saved_path)
        if not self.apply_reference_image(prefix, value, result):
            return False
        area = "" if selection is None else (
            f"，选区 {selection[2]}x{selection[3]}，客户区左上 ({selection[0]}, {selection[1]})"
        )
        self._set_status(f"{building_title(prefix)}的参考图已保存：{value}{area}")
        logger.info("参考图已保存（框选）：%s → %s", prefix, value)
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
    def show_preview(self, prefix: str) -> None:
        """双击缩略图：先把路径检查做了（同步），解码走线程，图到了再开弹窗。"""
        title = building_title(prefix)
        value = self._field_value(prefix)
        path = resolve_config_path(value)
        if path is None:
            self._set_status(f"{title}还没选参考图")
            return
        if not path.is_file():
            logger.warning("参考图文件不存在：%s（配置里记的是 %s）", path, value)
            self._set_status(
                f"找不到{title}的参考图文件：{path}（配置没被改动，请重新选一张；详见 {LOG_PATH_HINT}）"
            )
            return
        self._set_status(f"正在打开{title}的参考图预览…")
        self._start_decoding([(prefix, value)], validate=False, intent="preview")

    def on_preview_ready(self, prefix: str, value: str, result: ReferenceImageResult) -> None:
        if not result.ok or result.image is None:
            self._set_status(f"打不开这张图：{result.message}")
            return
        dialog = self.build_preview_dialog(prefix, result.image)
        if dialog is None:
            return
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def build_preview_dialog(self, prefix: str, image: QImage | None) -> QDialog | None:
        """用**已经解码好的** QImage 构造放大预览弹窗（不 exec，便于测试）。"""
        if image is None:
            self._set_status(f"{building_title(prefix)}还没选参考图")
            return None
        value = self._field_value(prefix)
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
        layout.addWidget(QLabel(f"{value}\n（{image.width()}x{image.height()} 像素）"))
        layout.addWidget(scroll)
        logger.info("打开参考图预览：%s", value)
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

        页面本身不做文件 IO，解码也**放到后台线程**（评审 P2-4：三张 4K 最坏 ~1.1 s）；
        文件被删掉时**只清缩略图 + 记日志**，绝不悄悄把配置里的路径抹掉（用户可能只是换机器）。
        """
        requests: list[tuple[str, str]] = []
        for _title, prefix, _word, _field, _capture in BUILDINGS:
            value = self._field_value(prefix)
            if not value.strip():
                self._page.set_reference_image(prefix, "", None)
                continue
            requests.append((prefix, value))
        if requests:
            self._start_decoding(requests, validate=False, intent="refresh")

    def on_thumbnails_ready(self, prefix: str, value: str, result: ReferenceImageResult) -> None:
        """某张缩略图解码完成：成功就显示；失败保留路径文字、只清缩略图（不改配置）。"""
        if not result.ok:
            self._page.set_reference_image(prefix, value, None)
            return
        self._page.set_reference_image(prefix, value, result.image)

    def _field_value(self, prefix: str) -> str:
        return str(getattr(self._get_config().features.daily_tasks, ref_image_field(prefix), "") or "")
