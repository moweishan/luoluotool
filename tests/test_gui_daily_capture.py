"""日常任务页「截取游戏画面」流程测试（从 `test_gui_daily_media.py` 拆出）。

拆分原因（2026-09-22）：原文件在第五轮评审修复后 604 行，超过 AGENTS §2 的 600 行硬线。
**纯搬运**：函数体一行未改，只搬走「截取游戏画面」整段（假线程替身 + 6 条用例）。
选图/解码/预览/刷新那几段仍在 `tests/test_gui_daily_media.py`；共享助手在 `gui_helpers.py`。

**绝不真的截图、绝不真的弹窗**：`find_window` / `bring_to_front` / `capture_window` /
`TemplateCropDialog` / `DailyCaptureThread` 全部被替换成假对象。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication, QDialog

from gui_helpers import (
    daily_media_controller,
    daily_media_page,
    wait_for_daily_decoding,
)
from luoluotool.config.models import AppConfig
from luoluotool.gui import daily_media
from luoluotool.gui.daily_media import DailyCaptureThread
from luoluotool.utils.paths import to_config_path

_APP = QApplication.instance() or QApplication([])


def _page(config: AppConfig, changes: list[str]):
    return daily_media_page(config, changes)


def _controller(page, config: AppConfig, changes: list[str]):
    return daily_media_controller(page, config, changes)


def _wait_for_decoding(controller, timeout_ms: int = 5000) -> None:
    wait_for_daily_decoding(controller, timeout_ms)


def test_capture_thread_brings_the_window_to_front_before_capturing(monkeypatch) -> None:
    """截图前**必须先把游戏窗口切到前台**（否则截到的是盖在上面的本工具窗口）。"""
    config = AppConfig.default()
    order: list[str] = []

    monkeypatch.setattr(daily_media, "find_window", lambda keyword: order.append("find") or 4242)
    monkeypatch.setattr(daily_media, "bring_to_front", lambda hwnd: order.append("front") or True)
    monkeypatch.setattr(
        daily_media.vision_actions, "capture_window",
        lambda cfg: order.append("capture") or (np.zeros((10, 20, 3), dtype=np.uint8), ""),
    )
    captured: list[tuple] = []
    failures: list[str] = []
    thread = DailyCaptureThread(config, daily_media.logger, settle=0.0)
    thread.captured.connect(lambda image, size: captured.append((image.shape, size)))
    thread.failed_message.connect(failures.append)

    thread.run()                                   # 同步执行，不真的起线程

    assert order == ["find", "front", "capture"]
    assert captured and captured[0][1] == (20, 10)
    assert failures == []


def test_capture_thread_reports_missing_window(monkeypatch) -> None:
    """找不到游戏窗口：给可读提示，**不截图**。"""
    config = AppConfig.default()
    monkeypatch.setattr(daily_media, "find_window", lambda keyword: None)
    called: list[str] = []
    monkeypatch.setattr(
        daily_media.vision_actions, "capture_window",
        lambda cfg: called.append("capture") or (None, ""),
    )
    failures: list[str] = []
    thread = DailyCaptureThread(config, daily_media.logger, settle=0.0)
    thread.failed_message.connect(failures.append)

    thread.run()

    assert called == []
    assert failures and "未找到" in failures[0]


def test_capture_thread_stops_before_screenshot_when_requested(monkeypatch) -> None:
    """等待切前台期间收到停止请求 → 不再截图（急停时不用白等）。"""
    config = AppConfig.default()
    monkeypatch.setattr(daily_media, "find_window", lambda keyword: 1)
    monkeypatch.setattr(daily_media, "bring_to_front", lambda hwnd: True)
    called: list[str] = []
    monkeypatch.setattr(
        daily_media.vision_actions, "capture_window",
        lambda cfg: called.append("capture") or (None, ""),
    )
    thread = DailyCaptureThread(config, daily_media.logger, settle=0.3)
    thread.request_stop()

    thread.run()

    assert called == []


class _StubCaptureThread(QThread):
    """假截图线程：不真起线程，记录 start / request_stop 次数（subclass 由各用例给风格）。"""

    captured = Signal(object, object)
    failed_message = Signal(str)
    emit_finished_on_start = False
    running = True

    def __init__(self, cfg=None, log=None, settle=0.0) -> None:
        super().__init__()
        self.stop_requests = 0
        self.started = 0

    def start(self) -> None:                     # noqa: N802 (QThread 接口)
        self.started += 1
        if self.emit_finished_on_start:
            self.finished.emit()

    def isRunning(self) -> bool:                 # noqa: N802 (QThread 接口)
        return self.running

    def request_stop(self) -> None:
        self.stop_requests += 1


def test_capture_image_wires_the_thread_and_clears_it_when_finished(monkeypatch) -> None:
    """`capture_image()` → `start()` → `finished` 槽把引用清掉（第五轮评审 P3-4 的接线缺口）。"""
    created: list[_StubCaptureThread] = []

    class _FinishesAtOnce(_StubCaptureThread):
        emit_finished_on_start = True
        running = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    monkeypatch.setattr(daily_media, "DailyCaptureThread", _FinishesAtOnce)

    controller.capture_image("coop")

    assert created and created[0].started == 1        # 线程确实被启动了
    assert controller.capture_thread() is None        # finished 槽按 sender 保护后置空
    assert controller.worker_threads() == ()
    page.close()


def test_capture_image_refuses_to_start_a_second_time(monkeypatch) -> None:
    """上一次截图还在跑时不重复发起（避免两路截图/两个框选窗口）。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    monkeypatch.setattr(daily_media, "DailyCaptureThread", _StubCaptureThread)

    controller.capture_image("coop")
    controller.capture_image("land")                  # 第二次必须被拒

    assert controller.capture_thread().started == 1
    assert "还没结束" in controller.statuses[-1]
    page.close()


def test_request_stop_reaches_capture_and_decoding_threads(monkeypatch, textured_png) -> None:
    """急停（F8 /「停止」）必须能叫停日常页的**截图与解码**线程（第五轮评审 P2-3）。

    否则按了停止之后 0.4 秒框选窗口照样弹出来，用户会以为"停止没生效"。
    """
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    monkeypatch.setattr(daily_media, "DailyCaptureThread", _StubCaptureThread)
    config.features.daily_tasks.coop_island_ref_image = to_config_path(textured_png("要解码.png"))

    controller.capture_image("coop")
    controller.refresh_previews()
    assert controller.loader_threads(), "刷新缩略图应该起解码线程"

    controller.request_stop()

    assert controller.capture_thread().stop_requests == 1
    assert all(loader.stop_requested() for loader in controller.loader_threads())
    _wait_for_decoding(controller)
    page.close()


def test_capture_ready_opens_crop_dialog_and_records_the_saved_anchor(
    tmp_path, monkeypatch, textured_png
) -> None:
    """截图完成 → 弹框选窗（拿到本次截图与文件名前缀）→ 保存后写配置 + 显示缩略图。"""
    config = AppConfig.default()
    config.features.daily_tasks.coop_island = 7
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    anchors = tmp_path / "anchors"
    monkeypatch.setattr(daily_media, "get_anchors_dir", lambda: anchors)
    saved = textured_png("coop_island_7.png")     # 假装是框选产物

    opened: list[tuple] = []

    class _FakeDialog:
        def __init__(self, image, window_size, save_dir, parent=None, threshold=None, file_stem=""):
            opened.append((image.shape, window_size, save_dir, threshold, file_stem))
            self.saved_path = saved

        def selection(self):
            return 12, 34, 50, 40

        def exec(self):
            return QDialog.DialogCode.Accepted

        def deleteLater(self):                     # noqa: N802 (QObject 接口)
            return None

    monkeypatch.setattr(daily_media, "TemplateCropDialog", _FakeDialog)
    controller._pending_prefix = "coop"            # 正常由 capture_image() 设置
    controller.on_capture_ready(np.zeros((50, 100, 3), dtype=np.uint8), (100, 50))

    assert opened and opened[0][1] == (100, 50) and opened[0][2] == anchors
    assert opened[0][4] == "鸡舍_岛屿7"            # 文件名带建筑名 + 岛屿编号，方便回看
    assert config.features.daily_tasks.coop_island_ref_image == to_config_path(saved)
    assert page.preview_widget("coop").image() is not None
    assert "参考图已保存" in controller.statuses[-1] and "选区 50x40" in controller.statuses[-1]
    page.close()


def test_capture_ready_keeps_the_old_image_when_the_user_cancels(tmp_path, monkeypatch,
                                                                 textured_png) -> None:
    """用户取消框选 → 只提示，配置与显示都保持原样。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    old = textured_png("旧的.png")
    controller.start_pick("aqua", old)
    _wait_for_decoding(controller)
    before = config.features.daily_tasks.aqua_ref_image
    changes.clear()

    class _CancelDialog:
        def __init__(self, *args, **kwargs):
            self.saved_path = None

        def exec(self):
            return QDialog.DialogCode.Rejected

        def deleteLater(self):                     # noqa: N802 (QObject 接口)
            return None

    monkeypatch.setattr(daily_media, "TemplateCropDialog", _CancelDialog)
    controller._pending_prefix = "aqua"
    controller.on_capture_ready(np.zeros((20, 20, 3), dtype=np.uint8), (20, 20))

    assert config.features.daily_tasks.aqua_ref_image == before
    assert changes == []
    assert page.reference_image("aqua") == before
    assert "已取消" in controller.statuses[-1]
    page.close()


def test_capture_failure_points_at_the_log_file() -> None:
    """截图失败：状态栏给原因 + **说清日志在哪**（用户 B9 的要求），不弹窗。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)

    controller.on_capture_failed("游戏窗口已最小化或不可见，请恢复窗口后重试")

    message = controller.statuses[-1]
    assert "截取游戏画面失败" in message and "最小化" in message
    assert "luoluotool.log" in message
    page.close()
