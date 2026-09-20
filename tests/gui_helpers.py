"""GUI 测试共享夹具与辅助（模块名不以 test_ 开头，pytest 不会收集本文件）。"""

import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from luoluotool.config.models import AppConfig
from luoluotool.core.runner import Runner
from luoluotool.gui.main_window import MainWindow

_APP = QApplication.instance() or QApplication([])


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
