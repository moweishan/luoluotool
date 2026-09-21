"""GUI 测试共享夹具与辅助（模块名不以 test_ 开头，pytest 不会收集本文件）。"""

import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from luoluotool.config.models import AppConfig
from luoluotool.core.runner import Runner
from luoluotool.gui.dialogs.crop_view import CropView
from luoluotool.gui.main_window import MainWindow

_APP = QApplication.instance() or QApplication([])


def crop_image(width: int = 400, height: int = 300) -> np.ndarray:
    """框选用测试底图：每个像素的 B 通道 = x、G 通道 = y（坐标可反推）。

    评审 P3-8：三个框选测试文件各抄了一份同名辅助，这里统一成全仓库唯一的一份
    （与 `window_factory` 同样的收敛规则）。
    """
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 0] = np.arange(width, dtype=np.uint8)
    image[:, :, 1] = np.arange(height, dtype=np.uint8).reshape(-1, 1)
    return image


def scaled_crop_view(image_size: tuple[int, int], scale: int = 2) -> CropView:
    """按固定倍数显示的 `CropView`（图像坐标 = 控件坐标 / scale），方便写几何断言。"""
    width, height = image_size
    view = CropView(crop_image(width, height))
    view.resize(width * scale, height * scale)
    return view


@pytest.fixture
def window_factory(request, tmp_path):
    """创建主窗口（注入无等待 Runner 工厂与安全输入通道）并注册清理。

    默认通道工厂始终返回干跑 sender：测试绝不触碰真实窗口、绝不产生真实输入。
    需要验证真实模式行为的用例请显式传入自己的 channel_factory。

    参数（评审 P3-2：全仓库只保留这一份夹具，各测试文件不再自带副本）：
    - `path` 省略时用 `tmp_path/config.json`（需要指定路径就显式传）；
    - `developer_mode` 只在显式传入时覆盖（不传则沿用配置里的值，默认 False）。
    """
    from luoluotool.automation.input_sender import DryRunSender, InputChannel

    logging.getLogger().setLevel(logging.INFO)
    created = []

    def _safe_channel(config, stop_event, sleep, log):
        return InputChannel(DryRunSender())

    def make(path=None, config=None, auto_elevate=False, channel_factory=None, developer_mode=None):
        config = config if config is not None else AppConfig.default()
        if developer_mode is not None:
            config.automation.developer_mode = developer_mode
        window = MainWindow(
            config,
            path if path is not None else tmp_path / "config.json",
            runner_factory=lambda cfg: Runner(
                cfg, sleep=lambda s: None, channel_factory=channel_factory or _safe_channel
            ),
            auto_elevate=auto_elevate,
        )
        created.append(window)
        return window

    def cleanup():
        for window in created:
            window.close()
            window.deleteLater()
        _APP.processEvents()

    request.addfinalizer(cleanup)
    return make


def _wait_finished(window, timeout_ms: int = 5000) -> bool:
    thread = window._thread
    if thread is None:
        return True
    ok = thread.wait(timeout_ms)
    _APP.processEvents()  # 触发 finished 槽与日志信号投递
    return ok


class _StubThread:
    """最小 QThread 替身：可控制 isRunning / wait 结果，并记录请求。"""

    def __init__(self, running: bool = True, wait_result: bool = True) -> None:
        self.running = running
        self.wait_result = wait_result
        self.events: list[str] = []

    def isRunning(self) -> bool:            # noqa: N802 (QThread 命名)
        return self.running

    def request_stop(self) -> None:
        self.events.append("request_stop")

    def wait(self, timeout=None) -> bool:   # noqa: N802
        self.events.append(f"wait:{timeout}")
        return self.wait_result


# ---------------------------------------------------------------- 日常任务页（参考图流程）
# 这些助手被 `test_gui_daily_media.py` 与 `test_gui_daily_capture.py` 共用（2026-09-22 拆文件时
# 下沉到这里，避免两个文件各抄一份 —— 与 `crop_image` / `window_factory` 同样的收敛规则）。


def daily_media_page(config: AppConfig, changes: list[str]):
    """日常任务页：控件改动只往 `changes` 里追加 `"dirty"`（不写盘）。"""
    from luoluotool.gui.pages.daily import DailyPage

    return DailyPage(config, lambda: changes.append("dirty"))


def daily_media_controller(page, config: AppConfig, changes: list[str]):
    """日常任务页的参考图控制器；状态栏消息收进返回值的 `.statuses` 便于断言。"""
    from luoluotool.gui.daily_media import DailyMediaController

    statuses: list[str] = []
    controller = DailyMediaController(
        page,
        get_config=lambda: config,
        on_changed=lambda: changes.append("dirty"),
        set_status=statuses.append,
    )
    controller.statuses = statuses
    return controller


def wait_for_daily_decoding(controller, timeout_ms: int = 5000) -> None:
    """等控制器的参考图解码线程跑完并把结果投递到主线程（测试的事件循环是手动的）。"""
    import time

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for thread in controller.loader_threads():
            thread.wait(50)
        _APP.processEvents()
        if not controller.loader_threads():
            _APP.processEvents()
            return
    raise AssertionError("参考图解码线程未在超时内结束")
