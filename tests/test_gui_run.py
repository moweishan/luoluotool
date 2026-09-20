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
    """创建主窗口（注入无等待 Runner 工厂与安全输入通道）并注册清理。

    默认通道工厂始终返回干跑 sender：测试绝不触碰真实窗口、绝不产生真实输入。
    需要验证真实模式行为的用例请显式传入自己的 channel_factory。
    """
    from luoluotool.automation.input_sender import DryRunSender, InputChannel

    logging.getLogger().setLevel(logging.INFO)
    created = []

    def _safe_channel(config, stop_event, sleep, log):
        return InputChannel(DryRunSender())

    def make(path, config=None, auto_elevate=False, channel_factory=None):
        config = config if config is not None else AppConfig.default()
        window = MainWindow(
            config,
            path,
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
    config.features.daily_tasks.tasks["placeholder_task_a"].params = {
        "click_points": [[11, 22]],
        "wait_after_ms": 0,
    }
    window = window_factory(tmp_path / "config.json", config)
    window._start()
    assert window.start_button.isEnabled() is False
    assert window.stop_button.isEnabled() is True
    assert "干跑" in window.statusBar().currentMessage()
    assert _wait_finished(window)
    text = window.log_panel.toPlainText()
    assert "干跑：模拟点击 (11, 22)" in text
    assert "开始执行任务：placeholder_task_a" in text
    assert window.start_button.isEnabled() is True
    assert "版本" in window.statusBar().currentMessage()


def test_real_mode_requires_confirmation(window_factory, tmp_path, monkeypatch) -> None:
    """真实模式：未确认时不启动任何任务。"""
    from luoluotool.gui import main_window as mw

    monkeypatch.setattr(mw.MainWindow, "_confirm_real_mode", lambda self: False)
    config = AppConfig.default()
    config.automation.dry_run = False
    window = window_factory(tmp_path / "config.json", config)
    window._start()
    assert window._thread is None
    assert window.start_button.isEnabled() is True
    assert "取消" in window.statusBar().currentMessage()


def test_real_mode_warning_text_discloses_real_side_effects(window_factory, tmp_path) -> None:
    """真实模式确认文案必须如实告知副作用（曾经的文案是反向失实的）。

    历史缺陷：旧文案写「发送模拟点击/按键消息」「不接管你的真实鼠标键盘（执行期间键鼠仍可正常使用）」
    「游戏窗口失焦时按配置暂停」——三项都与真实键鼠通道的实际行为相反，属于低估风险的安全门问题。
    """
    config = AppConfig.default()
    config.automation.dry_run = False
    config.automation.failsafe_hotkey = "F8"
    window = window_factory(tmp_path / "config.json", config)
    text = window._real_mode_warning_text()

    # 必须如实说明：真实移动鼠标、抢前台、急停键、封号风险
    assert "真实移动鼠标" in text
    assert "抢前台" in text
    assert "F8" in text
    assert "封号风险自负" in text
    # 不得再出现与实现相反的旧声明
    assert "不接管你的真实鼠标键盘" not in text
    assert "键鼠仍可正常使用" not in text
    assert "失焦时按配置暂停" not in text
    assert "发送模拟点击/按键消息" not in text


def test_real_mode_confirmed_uses_sender_and_red_status(window_factory, tmp_path, monkeypatch) -> None:
    """真实模式：确认后经注入的 sender 发送序列，状态栏红色提示，结束后复位。"""
    from luoluotool.automation.input_sender import InputChannel
    from luoluotool.gui import main_window as mw

    sent: list[tuple] = []

    class _FakeSender:
        def move_to(self, x, y): sent.append(("move_to", x, y))
        def click(self, x, y): sent.append(("click", x, y))
        def click_at(self, x, y): sent.append(("click_at", x, y))
        def key_tap(self, vk): sent.append(("key_tap", vk))

    def fake_channel(config, stop_event, sleep, log):
        return InputChannel(_FakeSender())

    monkeypatch.setattr(mw.MainWindow, "_confirm_real_mode", lambda self: True)
    config = AppConfig.default()
    config.automation.dry_run = False
    config.features.daily_tasks.tasks["placeholder_task_a"].enabled = True
    config.features.daily_tasks.tasks["placeholder_task_a"].params = {
        "click_points": [[5, 6]],
        "wait_after_ms": 0,
    }
    window = window_factory(tmp_path / "config.json", config, channel_factory=fake_channel)
    window._start()
    assert "真实模式" in window.statusBar().currentMessage()
    assert window.statusBar().styleSheet() != ""  # 红色醒目样式
    assert _wait_finished(window)
    assert sent == [("click_at", 5, 6)]
    assert window.statusBar().styleSheet() == ""
    assert "版本" in window.statusBar().currentMessage()


def test_save_reapplies_hotkey_change(window_factory, tmp_path, monkeypatch, caplog) -> None:
    """修改急停键并保存后：注销旧键并注册新键。"""
    from luoluotool.gui import main_window as mw

    calls: list[tuple] = []

    class FakeRegistrar:
        def __init__(self, hotkey_id=0xF8, vk=0x77, modifiers=0, name="F8") -> None:
            self.hotkey_id = hotkey_id
            self.vk = vk
            self.name = name

        def register(self, hwnd: int = 0) -> bool:
            calls.append(("register", self.name, self.vk))
            return True

        def unregister(self, hwnd: int = 0) -> None:
            calls.append(("unregister", self.name))

    monkeypatch.setattr(mw, "HotkeyRegistrar", FakeRegistrar)
    window = window_factory(tmp_path / "config.json")
    calls.clear()
    window.settings_page.hotkey_combo.setCurrentText("F9")
    window._save()
    assert ("unregister", "F8") in calls
    assert ("register", "F9", 0x78) in calls
    assert "急停热键已更新为 F9" in caplog.text or "急停热键已更新为 F9" in window.log_panel.toPlainText()


def test_stop_button_stops_loop(window_factory, tmp_path) -> None:
    config = AppConfig.default()
    config.features.daily_tasks.enabled = True
    config.features.daily_tasks.tasks["placeholder_task_a"].enabled = True
    config.features.daily_tasks.tasks["placeholder_task_a"].params = {
        "click_points": [[100, 100]],
        "wait_after_ms": 1000,
    }
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

        def __init__(self, hotkey_id: int = 0xF8, vk: int = 0x77, modifiers: int = 0, name: str = "F8") -> None:
            self.hotkey_id = hotkey_id
            self.vk = vk
            self.name = name

        def register(self, hwnd: int = 0) -> bool:
            captured["register_hwnd"] = hwnd
            return True

        def unregister(self, hwnd: int = 0) -> None:
            captured["unregister_hwnd"] = hwnd

    monkeypatch.setattr(mw, "HotkeyRegistrar", FakeRegistrar)
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
    config = AppConfig.default()
    config.automation.developer_mode = True     # 调试页选项需调试开关开启才生效
    window = window_factory(tmp_path / "config.json", config)
    window.debug_page.diagnose_button.click()
    thread = window._diagnose_thread
    assert thread is not None
    assert thread.wait(3000)
    _APP.processEvents()
    assert "诊断结果" in window.statusBar().currentMessage()
    assert "诊断结果" in window.log_panel.toPlainText()
    assert window.debug_page.diagnose_button.isEnabled() is True


def test_diagnose_failure_reports_error(window_factory, tmp_path, monkeypatch) -> None:
    """诊断抛异常时给出可读错误提示，程序不崩溃。"""
    from luoluotool.gui import main_window as mw

    def boom(keyword, debug_dir):
        raise RuntimeError("模拟失败")

    monkeypatch.setattr(mw, "diagnose_window", boom)
    config = AppConfig.default()
    config.automation.developer_mode = True     # 调试页选项需调试开关开启才生效
    window = window_factory(tmp_path / "config.json", config)
    window.debug_page.diagnose_button.click()
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


def test_developer_tab_appears_and_disappears(window_factory, tmp_path) -> None:
    """勾选「开发者调试」→ 顶部出现第 6 个页签；取消勾选 → 页签移除。"""
    from luoluotool.gui.main_window import DEBUG_TAB_TITLE

    config = AppConfig.default()
    window = window_factory(tmp_path / "config.json", config)
    assert window.tabs.count() == 5
    window.settings_page.developer_box.setChecked(True)
    assert window.tabs.count() == 6
    assert window.tabs.tabText(window.tabs.count() - 1) == DEBUG_TAB_TITLE
    window.settings_page.developer_box.setChecked(False)
    assert window.tabs.count() == 5
    assert window.tabs.indexOf(window.debug_page) < 0


def test_developer_tab_does_not_change_page_heights(window_factory, tmp_path) -> None:
    """回归：挂载「开发者调试」页不得改变页签区与其它页的高度（调试页内容必须可滚动）。

    用户实测：勾选开发者调试后所有 tab 页高度都会变——调试页原来是一整列不滚动控件，
    其最小高度（488）成为 `QTabWidget` 的最小高度，把窗口最小高度从 381 顶到 658，
    于是窗口被撑高、日志面板被压扁、所有页签跟着变高。
    """
    config = AppConfig.default()
    window = window_factory(tmp_path / "config.json", config)
    window.show()
    _APP.processEvents()
    assert window.debug_page.minimumSizeHint().height() < 200   # 内容可滚动，不撑高页面
    before_tabs = window.tabs.minimumSizeHint().height()
    before_window = window.minimumSizeHint().height()
    before_pages = [page.height() for page in (window.settings_page, window.daily_page)]
    before_log = window.log_panel.height()

    window.settings_page.developer_box.setChecked(True)
    _APP.processEvents()
    assert window.tabs.indexOf(window.debug_page) >= 0
    assert window.tabs.minimumSizeHint().height() == before_tabs
    assert window.minimumSizeHint().height() == before_window
    assert window.minimumSizeHint().height() <= 640            # 默认 960×640 放得下，无需撑高
    assert [page.height() for page in (window.settings_page, window.daily_page)] == before_pages
    assert window.log_panel.height() == before_log

    window.settings_page.developer_box.setChecked(False)
    _APP.processEvents()
    assert window.tabs.minimumSizeHint().height() == before_tabs
    assert [page.height() for page in (window.settings_page, window.daily_page)] == before_pages


def test_feature_page_switches_add_placeholder_tasks_to_queue(window_factory, tmp_path) -> None:
    """Phase 6 闭环：卡订单/功能三/功能四页的开关勾选后进入运行队列（开关 → 运行 → 日志）。"""
    from luoluotool.core.runner import Runner

    config = AppConfig.default()
    window = window_factory(tmp_path / "config.json", config)
    assert Runner(config).queued_tasks() == []      # 默认全部关闭 → 空队列

    window.order_hold_page.enabled_box.setChecked(True)
    window.feature3_page.enabled_box.setChecked(True)
    window.feature4_page.enabled_box.setChecked(True)
    window.order_hold_page.reserved_box_1.setChecked(True)   # 预留开关：零行为
    window.order_hold_page.reserved_box_2.setChecked(True)
    assert Runner(config).queued_tasks() == ["order_hold", "feature_3", "feature_4"]

    window.order_hold_page.enabled_box.setChecked(False)
    assert Runner(config).queued_tasks() == ["feature_3", "feature_4"]


def test_feature_task_run_logs_planned_message_end_to_end(window_factory, tmp_path, caplog) -> None:
    """Phase 6 闭环：开关开启 → 运行 → 日志出现「该功能尚未实现真实逻辑（规划中）」。"""
    import logging as _logging

    from luoluotool.core.runner import Runner

    config = AppConfig.default()
    window = window_factory(tmp_path / "config.json", config)
    window.order_hold_page.enabled_box.setChecked(True)
    window.feature3_page.enabled_box.setChecked(True)
    caplog.set_level(_logging.INFO)
    Runner(config, sleep=lambda _s: None).start()
    planned = [record.message for record in caplog.records if "尚未实现" in record.message]
    assert len(planned) == 2
    assert "order_hold" in planned[0] and "feature_3" in planned[1]


def test_run_debug_action_dispatches_vision(monkeypatch) -> None:
    """调试动作分发：kind="vision" 走 core.vision 识别，并把结果消息回给界面。"""
    from luoluotool.core import vision as vision_actions
    from luoluotool.gui import main_window as mw

    calls: list[tuple] = []

    class _Result:
        message = "识别成功：命中 1 处\n  1) 客户区 中心 (60, 35) 匹配度 1.000"

    def fake_recognize(config, images, threshold, max_results):
        calls.append((list(images), threshold, max_results))
        return _Result()

    monkeypatch.setattr(vision_actions, "recognize_in_window", fake_recognize)
    message = mw.run_debug_action(
        AppConfig.default(), "vision",
        {"images": ["a.png", "b.png"], "threshold": 0.8, "max_results": 7},
        logging.getLogger("t"), None,
    )
    assert calls == [(["a.png", "b.png"], 0.8, 7)]
    assert "识别成功" in message and "(60, 35)" in message


def test_vision_debug_action_reports_missing_template(monkeypatch, tmp_path) -> None:
    """端到端（不经真实截图）：模板文件不存在时，调试线程回传可读消息而不抛异常。

    多张模板共用同一张截图，所以截图排在模板读取之前 —— 这里把截图换成假画面。
    """
    import numpy as np

    from luoluotool.core import vision as vision_actions
    from luoluotool.gui import main_window as mw

    monkeypatch.setattr(vision_actions, "find_window", lambda keyword: 555)
    monkeypatch.setattr(vision_actions, "is_window_ready", lambda hwnd: True)
    monkeypatch.setattr(
        vision_actions, "capture_client_bgr",
        lambda hwnd: np.full((40, 60, 3), 30, dtype=np.uint8),
    )
    messages: list[str] = []
    thread = mw._DebugTestThread(
        AppConfig.default(), "vision",
        {"images": [str(tmp_path / "缺失.png")], "threshold": 0.85, "max_results": 20},
        logging.getLogger("t"),
    )
    thread.finished_message.connect(messages.append)
    thread.run()                       # 同步执行（不等待线程）
    assert messages and "无法读取模板图片" in messages[0]


def test_crop_flow_saves_template_and_fills_path(window_factory, tmp_path, monkeypatch) -> None:
    """框选流程：主窗口把截图交给对话框，保存后把模板路径回填到调试页并提示。"""
    import numpy as np

    from luoluotool.gui import main_window as mw

    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)

    opened: list[tuple] = []
    saved = tmp_path / "anchor_test.png"

    class _FakeDialog:
        def __init__(self, image, window_size, save_dir, parent=None):
            opened.append((image.shape, window_size, save_dir))
            self.saved_path = saved

        def selection(self):          # 与真实对话框接口一致（保存后主窗口会用它拼提示）
            return 10, 20, 30, 40

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def deleteLater(self):        # noqa: N802 (QObject 接口)
            return None

    monkeypatch.setattr(mw, "TemplateCropDialog", _FakeDialog)
    window._on_capture_ready(np.zeros((50, 100, 3), dtype=np.uint8), (100, 50))

    assert opened and opened[0][0] == (50, 100, 3) and opened[0][1] == (100, 50)
    assert window.debug_page.vision_templates() == [str(saved)]
    assert "模板已保存" in window.debug_page.status_label.text()
    assert "选区 30x40" in window.debug_page.status_label.text()


def test_crop_flow_writes_only_selected_region(window_factory, tmp_path, monkeypatch) -> None:
    """全链路（真实对话框）：框选 → 「保存为模板」→ 只写选区尺寸的模板 → 加入模板列表。

    回归：这个按钮以前只连 accept()，"保存为模板"实际什么都没存（主窗口随后报未选区域）。
    """
    import numpy as np

    from luoluotool.automation.vision import load_template
    from luoluotool.gui import main_window as mw

    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)
    anchors = tmp_path / "anchors"
    monkeypatch.setattr(mw, "get_anchors_dir", lambda: anchors)

    class _AutoCrop(mw.TemplateCropDialog):
        """替代 exec()：模拟用户拖框并点「保存为模板」，再返回真实对话框结果。"""

        def exec(self):
            self.view.resize(400, 400)
            self.set_selection_in_image(30, 20, 50, 40)
            self.save_button.click()
            return self.result()

    monkeypatch.setattr(mw, "TemplateCropDialog", _AutoCrop)
    # 画布要有纹理：纯色块会被纯色模板守卫拦下（那是另一条规则），这里测的是"只存选区"
    image = np.zeros((300, 400, 3), dtype=np.uint8)
    image[:, :, 0] = np.arange(400, dtype=np.uint8)
    image[:, :, 1] = np.arange(300, dtype=np.uint8).reshape(-1, 1)
    window._on_capture_ready(image, (400, 300))

    files = list(anchors.glob("anchor_*.png"))
    assert len(files) == 1, "「保存为模板」必须写出一个模板文件"
    saved = load_template(files[0])
    assert saved.shape == (40, 50, 3)              # 只存框选的那块，不是整屏 300x400
    assert window.debug_page.vision_templates() == [str(files[0])]
    assert "模板已保存" in window.debug_page.status_label.text()


def test_crop_request_is_rejected_when_developer_mode_off(window_factory, tmp_path, caplog) -> None:
    """开发者调试未开启：框选截图入口同样不生效（不起线程、不弹窗）。"""
    import logging as _logging

    config = AppConfig.default()
    window = window_factory(tmp_path / "config.json", config)
    caplog.set_level(_logging.WARNING)
    window.debug_page.crop_requested.emit()
    assert window._capture_thread is None
    assert "不生效" in window.debug_page.status_label.text()


def test_crop_capture_failure_reports_message(window_factory, tmp_path) -> None:
    """截图失败（窗口最小化等）：把可读消息写进调试页状态区。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)
    window._on_capture_failed("游戏窗口已最小化或不可见，请恢复窗口后重试")
    assert "最小化" in window.debug_page.status_label.text()


def test_debug_actions_are_rejected_when_developer_mode_off(window_factory, tmp_path, caplog) -> None:
    """开发者调试未开启：调试动作（测试/诊断/布局测量）一律拒绝执行并给出提示。"""
    import logging as _logging

    config = AppConfig.default()
    window = window_factory(tmp_path / "config.json", config)
    caplog.set_level(_logging.WARNING)
    assert window.tabs.indexOf(window.debug_page) < 0

    window.debug_page.test_requested.emit("single_click", {"x": 1, "y": 2})
    window.debug_page.diagnose_requested.emit()
    window.debug_page.layout_measure_requested.emit()

    assert window._debug_thread is None      # 没有起任何调试线程
    assert window._diagnose_thread is None   # 没有发起窗口诊断
    assert "不生效" in window.debug_page.status_label.text()
    assert caplog.text.count("开发者调试未开启") == 3


def test_debug_actions_run_when_developer_mode_on(window_factory, tmp_path) -> None:
    """开发者调试开启：布局测量（纯几何）正常执行，状态区出现报告。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)
    window.debug_page.layout_measure_requested.emit()
    assert "布局测量" in window.debug_page.status_label.text()


def test_turning_developer_mode_off_stops_running_debug_action(window_factory, tmp_path) -> None:
    """关闭开发者调试：正在跑的调试动作被立即中断，调试页禁用。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)

    stopped: list[str] = []

    class _FakeDebugThread:
        def isRunning(self) -> bool:      # noqa: N802 (QThread 命名)
            return True

        def request_stop(self) -> None:
            stopped.append("stop")

    window._debug_thread = _FakeDebugThread()
    window.settings_page.developer_box.setChecked(False)
    assert stopped == ["stop"]
    assert window.tabs.indexOf(window.debug_page) < 0
    assert window.debug_page.isEnabled() is False
    assert "不生效" in window.debug_page.status_label.text()


def test_developer_mode_from_config_mounts_tab_at_startup(window_factory, tmp_path) -> None:
    """配置里 developer_mode=true 时启动即挂载调试页。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)
    assert window.tabs.indexOf(window.debug_page) >= 0


def test_run_debug_action_dispatches_all_kinds(monkeypatch) -> None:
    """主窗口的调试动作分发：四种类型分别调用 core.debug 的对应函数。"""
    from luoluotool.gui import main_window as mw

    calls: list[tuple] = []
    for name in ("run_single_click", "run_repeat_click", "run_swipe", "run_key"):
        monkeypatch.setattr(mw.debug_actions, name, (lambda n: lambda *args, **kwargs: calls.append((n, args[1:])) or n)(name))

    config = AppConfig.default()
    log = logging.getLogger("t")
    mw.run_debug_action(config, "single_click", {"x": 1, "y": 2}, log, None)
    mw.run_debug_action(config, "repeat_click", {"x": 1, "y": 2, "count": 3, "interval_ms": 100}, log, None)
    mw.run_debug_action(config, "swipe", {"from_x": 1, "from_y": 2, "to_x": 3, "to_y": 4, "duration_ms": 500}, log, None)
    mw.run_debug_action(config, "key", {"combo": "a", "count": 1, "interval_ms": 100}, log, None)
    assert [name for name, _args in calls] == [
        "run_single_click", "run_repeat_click", "run_swipe", "run_key",
    ]
    assert calls[2][1][0] == (1, 2) and calls[2][1][1] == (3, 4)   # 滑动起终点

    with pytest.raises(ValueError, match="未知的调试测试类型"):
        mw.run_debug_action(config, "nope", {}, log, None)


def test_run_debug_action_passes_click_hold(monkeypatch) -> None:
    """单点/连点分发都把「点击时长」传下去；旧载荷（没有 hold_ms）走默认值而不是报错。"""
    from luoluotool.gui import main_window as mw

    seen: list[dict] = []
    monkeypatch.setattr(
        mw.debug_actions, "run_single_click",
        lambda config, x, y, log, stop_event=None, **kwargs: seen.append(
            {"kind": "single", "x": x, "y": y, **kwargs}
        ) or "ok",
    )
    monkeypatch.setattr(
        mw.debug_actions, "run_repeat_click",
        lambda config, x, y, count, interval_ms, log, stop_event=None, **kwargs: seen.append(
            {"kind": "repeat", "x": x, "y": y, "count": count, **kwargs}
        ) or "ok",
    )
    log = logging.getLogger("t")
    config = AppConfig.default()

    mw.run_debug_action(config, "single_click", {"x": 5, "y": 6, "hold_ms": 250}, log, None)
    mw.run_debug_action(config, "single_click", {"x": 7, "y": 8}, log, None)
    mw.run_debug_action(
        config, "repeat_click",
        {"x": 9, "y": 10, "count": 3, "interval_ms": 100, "hold_ms": 180}, log, None,
    )
    mw.run_debug_action(
        config, "repeat_click", {"x": 11, "y": 12, "count": 2, "interval_ms": 100}, log, None,
    )

    assert seen[0]["hold_ms"] == 250
    assert "hold_ms" in seen[1] and seen[1]["hold_ms"] >= 0      # 缺省时用引擎默认时长
    assert seen[2]["hold_ms"] == 180 and seen[2]["count"] == 3
    assert "hold_ms" in seen[3] and seen[3]["count"] == 2
