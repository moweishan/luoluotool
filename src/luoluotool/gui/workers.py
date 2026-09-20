"""后台线程与调试动作分发：任务线程、调试测试线程、框选截图线程、窗口诊断线程。

分层：gui 层。线程体只调用 core / automation（`core.debug`、`core.vision`、`automation.window`、
`core.runner`），不直接做输入注入；干跑/真实通道由 `core.debug` 复用正式通道决定。

拆分说明（2026-09-20）：这些原本是 `gui/main_window.py` 的模块级定义，现原样搬到这里；
`main_window` 再导入使用（同时兼容旧引用，如 `main_window.run_debug_action`）。

注意（测试）：`diagnose_window` 在本模块命名空间里查 —— monkeypatch 目标是 `gui.workers`，
不是 `gui.main_window`。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from luoluotool.automation.window import diagnose_window
from luoluotool.config.models import AppConfig
from luoluotool.core import debug as debug_actions
from luoluotool.core import vision as vision_actions
from luoluotool.core.runner import Runner

logger = logging.getLogger(__name__)


class _RunnerThread(QThread):
    """在工作线程中执行 Runner.start()（阻塞主循环）。"""

    def __init__(self, runner: Runner, parent=None) -> None:
        super().__init__(parent)
        self._runner = runner

    def run(self) -> None:
        self._runner.start()


class _DebugTestThread(QThread):
    """在后台线程执行开发者调试动作（不阻塞 GUI；可被停止请求中断）。"""

    finished_message = Signal(str)
    failed_message = Signal(str)

    def __init__(self, config, kind: str, params: dict, log: logging.Logger) -> None:
        super().__init__()
        self._config = config
        self._kind = kind
        self._params = params
        self._log = log
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        try:
            message = run_debug_action(self._config, self._kind, self._params, self._log, self._stop_event)
        except Exception as exc:   # 记录完整堆栈并回报可读信息
            self._log.exception("开发者调试动作失败：%s", exc)
            self.failed_message.emit(f"{type(exc).__name__}: {exc}")
        else:
            self._log.info("开发者调试结果：%s", message)
            self.finished_message.emit(message)


def run_debug_action(config, kind: str, params: dict, log, stop_event) -> str:
    """把界面请求映射到 `core.debug` 的具体动作（便于单测直接调用）。"""
    if kind == "single_click":
        return debug_actions.run_single_click(
            config, params["x"], params["y"], log, stop_event,
            hold_ms=params.get("hold_ms", debug_actions.DEFAULT_CLICK_HOLD_MS),
        )
    if kind == "repeat_click":
        return debug_actions.run_repeat_click(
            config, params["x"], params["y"], params["count"], params["interval_ms"], log, stop_event,
            hold_ms=params.get("hold_ms", debug_actions.DEFAULT_CLICK_HOLD_MS),
        )
    if kind == "swipe":
        return debug_actions.run_swipe(
            config, (params["from_x"], params["from_y"]), (params["to_x"], params["to_y"]),
            params["duration_ms"], log, stop_event,
        )
    if kind == "key":
        return debug_actions.run_key(
            config, params["combo"], params["count"], params["interval_ms"], log, stop_event
        )
    if kind == "vision":
        # 图像识别：找窗口 → 截图（只截一次）→ 逐张模板匹配 → 返回命中位置（客户区坐标）
        # 多张模板：第一张达到阈值的直接用它的结果；一张模板命中多处则全部列出。
        return vision_actions.recognize_in_window(
            config, params["images"], threshold=params["threshold"],
            max_results=params["max_results"],
        ).message
    raise ValueError(f"未知的调试测试类型：{kind}")


class _CaptureThread(QThread):
    """在后台线程截取游戏窗口客户区（供「框选截图生成模板」用，避免卡住界面）。"""

    captured = Signal(object, object)          # (numpy 图像, (宽, 高))
    failed_message = Signal(str)

    def __init__(self, config: AppConfig, log: logging.Logger) -> None:
        super().__init__()
        self._config = config
        self._log = log

    def run(self) -> None:
        image, message = vision_actions.capture_window(self._config)
        if image is None:
            self._log.warning("框选模板：截图失败：%s", message)
            self.failed_message.emit(message)
            return
        height, width = image.shape[:2]
        self._log.info("框选模板：已截取客户区 %dx%d", width, height)
        self.captured.emit(image, (int(width), int(height)))


class _DiagnoseThread(QThread):

    finished_message = Signal(str, bool)

    def __init__(self, keyword: str, debug_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self._keyword = keyword
        self._debug_dir = debug_dir

    def run(self) -> None:
        try:
            result = diagnose_window(self._keyword, self._debug_dir)
            self.finished_message.emit(result.message, result.needs_elevation)
        except Exception:
            logger.exception("窗口诊断失败")
            self.finished_message.emit("窗口诊断失败，详见日志", False)


class TemplateProbeThread(QThread):
    """在后台线程做「在本图试识别」（框选弹窗自检，D1）。

    为什么必须放线程里：模板匹配是 CPU 密集的，全屏截图配大模板要 1–2 秒，
    放 GUI 线程会把弹窗卡住（AGENTS §2：长任务一律放工作线程）。

    公共名字（无下划线）：它被 `gui/dialogs/crop_dialog.py` 使用，
    跨模块共用私有名是明令禁止的（AGENTS §2「同一件事只允许有一份」第 ③ 条）。
    """

    finished_probe = Signal(object)            # TemplateProbeResult
    failed_message = Signal(str)

    def __init__(self, image, region: tuple[int, int, int, int], threshold: float,
                 max_results: int) -> None:
        super().__init__()
        self._image = image
        self._region = region
        self._threshold = threshold
        self._max_results = max_results

    def run(self) -> None:
        try:
            result = vision_actions.probe_region_on_image(
                self._image, self._region,
                threshold=self._threshold, max_results=self._max_results,
            )
        except Exception as exc:   # 越界/太小/匹配异常都转成可读提示，不抛给 GUI
            logger.exception("框选自检失败：%s", exc)
            self.failed_message.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished_probe.emit(result)
