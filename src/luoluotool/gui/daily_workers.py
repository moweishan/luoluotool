"""日常任务页参考图的**后台工人**：解码线程、截图线程与它们的结果类型（从 `daily_media.py` 拆出）。

拆分原因（2026-09-22）：用户要求「选择图片可以多选」之后 `daily_media.py` 到 701 行，
超过 AGENTS §2 的 600 行硬线。**纯搬运**：搬过来的五个定义一行未改，唯一的改名是
`_PickBatch` → `PickBatch` —— 它现在被另一个模块的 `DailyMediaController` 使用，
而 AGENTS §2 要求跨模块共用的名字不要用下划线私有名。

约定：
- 这里只做"读图 / 截图"这类**在后台线程里跑**的活：不碰 Qt 界面、不写配置；
- 结果一律用信号回 GUI 线程（`ReferenceImageLoader.item_ready` / `DailyCaptureThread.captured`），
  由 `gui/daily_media.DailyMediaController` 决定怎么落到配置与界面上；
- 两个线程都有 `request_stop()`，主窗口的急停（F8 / 「停止」）与关窗都会叫停它们。

**测试里的补丁要打在这里**：`daily_workers.find_window` / `daily_workers.bring_to_front` /
`daily_workers.vision_actions.capture_window` —— `DailyCaptureThread.run` 查的是**本模块**的
全局名，打在没有被调用的命名空间上不会报错、只会静默失效（AGENTS §2）。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from luoluotool.automation.template_match import (
    RegionQuality,
    VisionError,
    assess_region_quality,
    load_template,
    read_image_bgr,
)
from luoluotool.automation.window import bring_to_front, find_window
from luoluotool.core import vision as vision_actions
from luoluotool.gui.dialogs.crop_dialog import to_qimage
from luoluotool.utils.paths import resolve_config_path

FRONT_SETTLE_SECONDS = 0.4        # 把游戏切前台后等这么久再截图（等它渲染出前台那一帧）
FRONT_SETTLE_SLICE_SECONDS = 0.05  # 等待切片，便于急停/关窗时尽快收手


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


@dataclass
class PickBatch:
    """一批「选择图片…」的解码进度：**每张回调一次**，全批到齐才写配置。"""

    prefix: str
    values: list[str]                       # 用户选中的路径（已去重、已限张数、按选择顺序）
    results: dict[str, ReferenceImageResult] = field(default_factory=dict)
    note: str = ""                          # 选图阶段就发现的提示（路径太长 / 超出张数上限）

    def is_complete(self) -> bool:
        return all(value in self.results for value in self.values)
