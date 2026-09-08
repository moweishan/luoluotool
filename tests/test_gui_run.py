"""GUI 启动/停止、日志面板与 F8 过滤器测试（offscreen，虚拟时间）。"""

import logging
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from luoluotool.config.models import AppConfig
from luoluotool.core.runner import Runner
from luoluotool.gui.main_window import MainWindow

_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def window_factory(request):
    """创建主窗口（注入无等待 Runner 工厂）并注册清理。

    生产路径由 app.run -> setup_logging 把根级别设为 INFO；
    测试中 MainWindow 独立构造，这里模拟同等条件。
    """
    logging.getLogger().setLevel(logging.INFO)
    created = []

    def make(path, config=None):
        config = config if config is not None else AppConfig.default()
        window = MainWindow(config, path, runner_factory=lambda cfg: Runner(cfg, sleep=lambda s: None))
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


def test_start_runs_placeholder_and_logs_steps(window_factory, tmp_path) -> None:
    config = AppConfig.default()
    config.features.daily_tasks.enabled = True
    config.features.daily_tasks.tasks["placeholder_task_a"].enabled = True
    window = window_factory(tmp_path / "config.json", config)
    window._start()
    assert window.start_button.isEnabled() is False
    assert window.stop_button.isEnabled() is True
    assert "干跑" in window.statusBar().currentMessage()
    assert _wait_finished(window)
    text = window.log_panel.toPlainText()
    assert "模拟点击" in text
    assert "开始执行任务：placeholder_task_a" in text
    assert window.start_button.isEnabled() is True
    assert "版本" in window.statusBar().currentMessage()


def test_stop_button_stops_loop(window_factory, tmp_path) -> None:
    config = AppConfig.default()
    config.features.daily_tasks.enabled = True
    config.features.daily_tasks.tasks["placeholder_task_a"].enabled = True
    config.features.daily_tasks.loop.enabled = True
    config.features.daily_tasks.loop.interval_seconds = 5
    window = window_factory(tmp_path / "config.json", config)
    window._start()
    deadline = time.time() + 3
    while time.time() < deadline and "模拟点击" not in window.log_panel.toPlainText():
        _APP.processEvents()
        time.sleep(0.01)
    assert "模拟点击" in window.log_panel.toPlainText()
    window._stop()
    assert _wait_finished(window)
    assert window._runner is not None
    assert window._runner.state.name == "IDLE"
    assert window.start_button.isEnabled() is True


def test_start_without_tasks_logs_hint(window_factory, tmp_path) -> None:
    window = window_factory(tmp_path / "config.json", AppConfig.default())
    window._start()
    assert _wait_finished(window)
    assert "未选择任何任务" in window.log_panel.toPlainText()


def test_hotkey_registered_with_window_hwnd(window_factory, tmp_path, monkeypatch) -> None:
    """热键必须注册到主窗口句柄（hwnd=0 时 Qt 过滤器收不到 WM_HOTKEY）。"""
    from luoluotool.gui import main_window as mw

    captured: dict[str, int] = {}

    class FakeRegistrar:
        hotkey_id = 0xF8

        def register(self, hwnd: int = 0) -> bool:
            captured["register_hwnd"] = hwnd
            return True

        def unregister(self, hwnd: int = 0) -> None:
            captured["unregister_hwnd"] = hwnd

    monkeypatch.setattr(mw, "HotkeyRegistrar", lambda: FakeRegistrar())
    window = window_factory(tmp_path / "config.json")
    hwnd = int(window.winId())
    assert captured.get("register_hwnd") == hwnd
    window.close()
    assert captured.get("unregister_hwnd") == hwnd


def test_native_event_hotkey_triggers_failsafe(window_factory, tmp_path) -> None:
    """WM_HOTKEY 经 nativeEvent 触发急停回调；其他消息不触发。"""
    import ctypes
    from ctypes import wintypes

    import shiboken6

    from luoluotool.automation.hotkey import WM_HOTKEY

    window = window_factory(tmp_path / "config.json")
    hotkey_msg = wintypes.MSG()
    hotkey_msg.message = WM_HOTKEY
    hotkey_msg.wParam = 0xF8
    hotkey_ptr = shiboken6.VoidPtr(ctypes.addressof(hotkey_msg))
    result = window.nativeEvent(b"windows_generic_MSG", hotkey_ptr)
    assert result[0] is True
    _APP.processEvents()
    assert "急停触发" in window.log_panel.toPlainText()
    other_msg = wintypes.MSG()
    other_msg.message = 0x0100  # WM_KEYDOWN，非热键消息
    other_msg.wParam = 0xF8
    other_ptr = shiboken6.VoidPtr(ctypes.addressof(other_msg))
    assert window.nativeEvent(b"windows_generic_MSG", other_ptr)[0] is False
