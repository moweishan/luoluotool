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

    def make(path, config=None, auto_elevate=False):
        config = config if config is not None else AppConfig.default()
        window = MainWindow(
            config,
            path,
            runner_factory=lambda cfg: Runner(cfg, sleep=lambda s: None),
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


def test_start_saves_config_before_running(window_factory, tmp_path) -> None:
    """点击启动：先把当前配置落盘，再开始执行任务。"""
    import json

    config = AppConfig.default()
    config.features.daily_tasks.tasks["placeholder_task_a"].enabled = True
    window = window_factory(tmp_path / "config.json", config)
    window.settings_page.click_interval_spin.setValue(1234)
    assert window.windowTitle().endswith("*")  # 有未保存改动
    window._start()
    assert _wait_finished(window)
    assert window.windowTitle().endswith("*") is False
    on_disk = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert on_disk["automation"]["click_interval_ms"] == 1234
    assert on_disk["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["enabled"] is True
    text = window.log_panel.toPlainText()
    assert "配置已保存" in text
    assert "启动任务" in text


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


def test_diagnose_button_runs_and_reports(window_factory, tmp_path, monkeypatch) -> None:
    """窗口诊断：按钮触发工作线程，结果写入状态栏与日志面板。"""
    from luoluotool.automation.window import DiagnosticResult
    from luoluotool.gui import main_window as mw

    monkeypatch.setattr(
        mw, "diagnose_window",
        lambda keyword, debug_dir: DiagnosticResult(f"诊断结果: {keyword}", False),
    )
    window = window_factory(tmp_path / "config.json")
    window.settings_page.diagnose_button.click()
    thread = window._diagnose_thread
    assert thread is not None
    assert thread.wait(3000)
    _APP.processEvents()
    assert "诊断结果" in window.statusBar().currentMessage()
    assert "诊断结果" in window.log_panel.toPlainText()
    assert window.settings_page.diagnose_button.isEnabled() is True


def test_diagnose_failure_reports_error(window_factory, tmp_path, monkeypatch) -> None:
    """诊断抛异常时给出可读错误提示，程序不崩溃。"""
    from luoluotool.gui import main_window as mw

    def boom(keyword, debug_dir):
        raise RuntimeError("模拟失败")

    monkeypatch.setattr(mw, "diagnose_window", boom)
    window = window_factory(tmp_path / "config.json")
    window.settings_page.diagnose_button.click()
    assert window._diagnose_thread is not None
    assert window._diagnose_thread.wait(3000)
    _APP.processEvents()
    assert "窗口诊断失败" in window.statusBar().currentMessage()


def test_save_button_logs_and_status(window_factory, tmp_path) -> None:
    """保存：日志面板与状态栏都有提示。"""
    window = window_factory(tmp_path / "config.json")
    window.settings_page.click_interval_spin.setValue(1234)
    window._save()
    _APP.processEvents()
    text = window.log_panel.toPlainText()
    assert "配置已保存" in text
    assert "配置已保存" in window.statusBar().currentMessage()


def test_reset_button_logs_and_status(window_factory, tmp_path) -> None:
    """恢复默认：日志面板提示已恢复（并提醒需保存）。"""
    window = window_factory(tmp_path / "config.json")
    window.settings_page.click_interval_spin.setValue(1234)
    window._reset()
    _APP.processEvents()
    text = window.log_panel.toPlainText()
    assert "恢复默认" in text
    assert "保存" in text
    assert "恢复默认" in window.statusBar().currentMessage()


def test_stop_button_logs_when_no_task_running(window_factory, tmp_path) -> None:
    """停止处理器（无运行任务）：提示当前没有运行中的任务。

    空闲时停止按钮为禁用态（点击无效），因此直接调用处理器验证反馈逻辑。
    """
    window = window_factory(tmp_path / "config.json")
    assert window.stop_button.isEnabled() is False
    window._on_stop_clicked()
    _APP.processEvents()
    assert "没有运行中的任务" in window.log_panel.toPlainText()


def test_stop_button_logs_when_runner_active(window_factory, tmp_path) -> None:
    """停止（运行中）：日志出现「已请求停止」，且任务确实停止。"""
    config = AppConfig.default()
    config.features.daily_tasks.tasks["placeholder_task_a"].enabled = True
    config.features.daily_tasks.loop.enabled = True
    window = window_factory(tmp_path / "config.json", config)
    window._start()
    deadline = time.time() + 3
    while time.time() < deadline and "模拟点击" not in window.log_panel.toPlainText():
        _APP.processEvents()
        time.sleep(0.01)
    window.stop_button.click()
    _APP.processEvents()
    assert "已请求停止" in window.log_panel.toPlainText()
    assert _wait_finished(window)


def test_restart_admin_button_confirmed(window_factory, tmp_path, monkeypatch) -> None:
    """确认后带 --config 参数请求提权重启；按钮场景不提供「不再询问」。"""
    from luoluotool.gui import main_window as mw

    recorded: dict[str, list[str]] = {}
    ask_flags: list[bool] = []
    monkeypatch.setattr(mw, "is_process_elevated", lambda: False)
    monkeypatch.setattr(
        mw, "restart_as_admin", lambda args: recorded.update(args=list(args)) or True
    )
    monkeypatch.setattr(
        mw.MainWindow,
        "_ask_restart_confirmation",
        lambda self, allow_dont_ask=False: ask_flags.append(allow_dont_ask) or (True, False),
    )
    window = window_factory(tmp_path / "config.json")
    window.settings_page.restart_admin_button.click()
    assert recorded["args"] == ["--config", str(tmp_path / "config.json")]
    assert ask_flags == [False]


def test_restart_admin_button_cancelled_keeps_running(window_factory, tmp_path, monkeypatch) -> None:
    """取消确认时不重启，仅提示。"""
    from luoluotool.gui import main_window as mw

    called: list[list[str]] = []
    monkeypatch.setattr(mw, "is_process_elevated", lambda: False)
    monkeypatch.setattr(mw, "restart_as_admin", lambda args: called.append(list(args)) or True)
    monkeypatch.setattr(
        mw.MainWindow, "_ask_restart_confirmation", lambda self, allow_dont_ask=False: (False, False)
    )
    window = window_factory(tmp_path / "config.json")
    window.settings_page.restart_admin_button.click()
    assert called == []
    assert "取消" in window.statusBar().currentMessage() or "失败" in window.statusBar().currentMessage()


def test_restart_admin_button_when_already_elevated(window_factory, tmp_path, monkeypatch) -> None:
    """已是管理员权限：仅提示无需重启，不发起重启、不弹确认框。"""
    from luoluotool.gui import main_window as mw

    info_calls: list[str] = []
    restart_calls: list[list[str]] = []
    question_calls: list[tuple] = []
    monkeypatch.setattr(mw, "is_process_elevated", lambda: True)
    monkeypatch.setattr(
        mw.QMessageBox, "information",
        lambda parent, title, text, *args, **kwargs: info_calls.append(text),
    )
    monkeypatch.setattr(
        mw.MainWindow,
        "_ask_restart_confirmation",
        lambda self, allow_dont_ask=False: question_calls.append((allow_dont_ask,)) or (True, False),
    )
    monkeypatch.setattr(mw, "restart_as_admin", lambda args: restart_calls.append(list(args)) or True)
    window = window_factory(tmp_path / "config.json")
    window.settings_page.restart_admin_button.click()
    assert info_calls and "无需重启" in info_calls[0]
    assert question_calls == []
    assert restart_calls == []
    assert "无需重启" in window.statusBar().currentMessage()


def test_elevation_check_sets_settings_hint(window_factory, tmp_path, monkeypatch) -> None:
    """启动检测：游戏窗口权限更高且本工具未提权时，设置页给出提示。"""
    from luoluotool.gui import main_window as mw

    monkeypatch.setattr(mw, "is_process_elevated", lambda: False)
    monkeypatch.setattr(mw, "find_window", lambda keyword: 123)
    monkeypatch.setattr(mw, "is_window_elevated", lambda hwnd: True)
    window = window_factory(tmp_path / "config.json")
    window._check_elevation_need()
    label = window.settings_page.elevation_hint_label
    assert "管理员" in label.text()
    assert label.isHidden() is False


def test_startup_auto_elevate_prompts_and_restarts(window_factory, tmp_path, monkeypatch) -> None:
    """启动自动流程：非管理员 → 弹确认框（含「不再询问」）→ 确认后请求提权重启。"""
    from luoluotool.gui import main_window as mw

    recorded: dict[str, list[str]] = {}
    ask_flags: list[bool] = []
    monkeypatch.setattr(mw, "find_window", lambda keyword: None)
    monkeypatch.setattr(mw, "is_process_elevated", lambda: False)
    monkeypatch.setattr(
        mw.MainWindow,
        "_ask_restart_confirmation",
        lambda self, allow_dont_ask=False: ask_flags.append(allow_dont_ask) or (True, False),
    )
    monkeypatch.setattr(mw, "restart_as_admin", lambda args: recorded.update(args=list(args)) or True)
    window = window_factory(tmp_path / "config.json", auto_elevate=True)
    window._startup_elevation_flow()
    assert ask_flags == [True]
    assert recorded["args"] == ["--config", str(tmp_path / "config.json")]


def test_startup_auto_elevate_declined(window_factory, tmp_path, monkeypatch) -> None:
    """启动自动流程：用户拒绝 → 不重启，提示已取消。"""
    from luoluotool.gui import main_window as mw

    restart_calls: list[list[str]] = []
    monkeypatch.setattr(mw, "find_window", lambda keyword: None)
    monkeypatch.setattr(mw, "is_process_elevated", lambda: False)
    monkeypatch.setattr(
        mw.MainWindow, "_ask_restart_confirmation", lambda self, allow_dont_ask=False: (False, False)
    )
    monkeypatch.setattr(mw, "restart_as_admin", lambda args: restart_calls.append(list(args)) or True)
    window = window_factory(tmp_path / "config.json", auto_elevate=True)
    window._startup_elevation_flow()
    assert restart_calls == []
    assert "取消" in window.statusBar().currentMessage()


def test_startup_auto_elevate_when_admin_skips_modal(window_factory, tmp_path, monkeypatch) -> None:
    """启动自动流程：已是管理员 → 只提示无需重启，不弹任何确认框。"""
    from luoluotool.gui import main_window as mw

    questions: list[tuple] = []
    monkeypatch.setattr(mw, "find_window", lambda keyword: None)
    monkeypatch.setattr(mw, "is_process_elevated", lambda: True)
    monkeypatch.setattr(
        mw.MainWindow,
        "_ask_restart_confirmation",
        lambda self, allow_dont_ask=False: questions.append((allow_dont_ask,)) or (True, False),
    )
    window = window_factory(tmp_path / "config.json", auto_elevate=True)
    window._startup_elevation_flow()
    assert questions == []
    assert window.statusBar().currentMessage() == "当前已是管理员权限"


def test_startup_auto_elevate_disabled_in_smoke(window_factory, tmp_path, monkeypatch) -> None:
    """auto_elevate=False（冒烟/测试）：启动流程不弹确认框。"""
    from luoluotool.gui import main_window as mw

    questions: list[tuple] = []
    monkeypatch.setattr(mw, "find_window", lambda keyword: None)
    monkeypatch.setattr(mw, "is_process_elevated", lambda: False)
    monkeypatch.setattr(
        mw.MainWindow,
        "_ask_restart_confirmation",
        lambda self, allow_dont_ask=False: questions.append((allow_dont_ask,)) or (True, False),
    )
    window = window_factory(tmp_path / "config.json", auto_elevate=False)
    window._startup_elevation_flow()
    assert questions == []


def test_startup_dont_ask_persists_and_skips_next_time(window_factory, tmp_path, monkeypatch) -> None:
    """勾选「不再询问」：落盘为 false、设置页同步。"""
    import json

    from luoluotool.gui import main_window as mw

    monkeypatch.setattr(mw, "find_window", lambda keyword: None)
    monkeypatch.setattr(mw, "is_process_elevated", lambda: False)
    monkeypatch.setattr(mw, "restart_as_admin", lambda args: False)
    monkeypatch.setattr(
        mw.MainWindow, "_ask_restart_confirmation", lambda self, allow_dont_ask=False: (False, True)
    )
    window = window_factory(tmp_path / "config.json", auto_elevate=True)
    window._startup_elevation_flow()
    assert window._config.automation.ask_elevation_on_start is False
    assert window.settings_page.ask_elevation_box.isChecked() is False
    on_disk = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert on_disk["automation"]["ask_elevation_on_start"] is False


def test_startup_dont_ask_elevates_directly(window_factory, tmp_path, monkeypatch) -> None:
    """已设置「不再询问」：启动不弹框，直接请求提权重启。"""
    from luoluotool.gui import main_window as mw

    asked: list[bool] = []
    recorded: dict[str, list[str]] = {}
    monkeypatch.setattr(mw, "find_window", lambda keyword: None)
    monkeypatch.setattr(mw, "is_process_elevated", lambda: False)
    monkeypatch.setattr(
        mw.MainWindow,
        "_ask_restart_confirmation",
        lambda self, allow_dont_ask=False: asked.append(allow_dont_ask) or (False, False),
    )
    monkeypatch.setattr(mw, "restart_as_admin", lambda args: recorded.update(args=list(args)) or True)
    config = AppConfig.default()
    config.automation.ask_elevation_on_start = False
    window = window_factory(tmp_path / "config.json", config, auto_elevate=True)
    window._startup_elevation_flow()
    assert asked == []
    assert recorded["args"] == ["--config", str(tmp_path / "config.json")]


def test_startup_dont_ask_elevation_cancelled_keeps_running(window_factory, tmp_path, monkeypatch) -> None:
    """「不再询问」直连提权但用户取消了 UAC：程序继续以普通权限运行，不循环重试。"""
    from luoluotool.gui import main_window as mw

    calls: list[list[str]] = []
    monkeypatch.setattr(mw, "find_window", lambda keyword: None)
    monkeypatch.setattr(mw, "is_process_elevated", lambda: False)
    monkeypatch.setattr(mw, "restart_as_admin", lambda args: calls.append(list(args)) or False)
    config = AppConfig.default()
    config.automation.ask_elevation_on_start = False
    window = window_factory(tmp_path / "config.json", config, auto_elevate=True)
    window._startup_elevation_flow()
    assert len(calls) == 1
    assert window.isVisible() is False  # 未关闭主窗口，继续运行
    assert "取消" in window.statusBar().currentMessage() or "失败" in window.statusBar().currentMessage()
