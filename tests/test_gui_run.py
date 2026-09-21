"""GUI 主窗口测试：启动/停止、日志面板、状态栏、线程互斥、关闭窗口、窗口诊断与页签（offscreen）。"""

import logging
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui_helpers import _StubThread, _wait_finished, window_factory
from luoluotool.config.models import AppConfig

_APP = QApplication.instance() or QApplication([])


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
    config.features.daily_tasks.enabled = True     # A1 起总开关真的会挡队列，跑任务必须打开它
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


# --------------------------- 评审 P2-4 / P2-5 / P2-6 的回归（P3-9 见 test_gui_hotkey.py）


def test_stop_button_works_for_debug_test_without_ever_starting_task(window_factory, tmp_path) -> None:
    """回归（评审 P2-4）：只有调试测试在跑（从未点过「启动」）时，「停止」必须可用并真的请求停止。

    注意：这里不启动真实 `_DebugTestThread`（那样会被替身顶掉、触发 Qt 的
    "QThread: Destroyed while thread is still running" 而让测试进程 abort —— 正是 P2-6 那类崩溃）。
    """
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)

    stub = _StubThread(running=True)
    window._debug_thread = stub
    window._on_debug_thread_finished()      # 测试结束回调：按"是否还有长任务"决定按钮状态

    assert window.stop_button.isEnabled() is True      # 旧实现这里会是灰的

    window._on_stop_clicked()
    assert "request_stop" in stub.events
    assert "已请求停止" in window.statusBar().currentMessage()
    window._debug_thread = None
    window.stop_button.setEnabled(False)


def test_stop_without_any_job_reports_idle(window_factory, tmp_path) -> None:
    """没有任务/测试在跑时点「停止」：只提示，不报错。"""
    window = window_factory(tmp_path / "config.json", AppConfig.default())
    window._on_stop_clicked()
    assert "没有运行中的任务" in window.statusBar().currentMessage()


def test_debug_test_rejected_while_task_is_running(window_factory, tmp_path) -> None:
    """回归（评审 P2-5）：任务运行期间不接受调试输入测试（避免两路真实输入交错）。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)

    window._thread = _StubThread(running=True)          # 假装任务在跑
    window._on_debug_test("single_click", {"x": 1, "y": 2, "hold_ms": 40})

    assert window._debug_thread is None
    assert "任务正在运行" in window.debug_page.status_label.text()
    window._thread = None


def test_start_rejected_while_debug_test_is_running(window_factory, tmp_path) -> None:
    """回归（评审 P2-5）：调试测试运行期间拒绝启动任务。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)

    window._debug_thread = _StubThread(running=True)
    window._start()

    assert window._thread is None                       # 没有启动运行线程
    assert "调试测试正在运行" in window.statusBar().currentMessage()
    window._debug_thread = None


def test_close_event_waits_for_all_background_threads(window_factory, tmp_path, caplog) -> None:
    """回归（评审 P2-6）：关闭窗口时等待**全部**后台线程退出，超时要记 ERROR。"""
    window = window_factory(tmp_path / "config.json", AppConfig.default())
    running = {name: _StubThread(running=True) for name in ("_thread", "_debug_thread", "_capture_thread", "_diagnose_thread")}
    for name, stub in running.items():
        setattr(window, name, stub)

    window.close()

    for name, stub in running.items():
        assert any(event.startswith("wait:") for event in stub.events), f"{name} 未被等待"


def test_close_event_logs_error_when_thread_does_not_exit(window_factory, tmp_path, caplog) -> None:
    """线程等待超时必须记 ERROR（不能装作没事）。"""
    window = window_factory(tmp_path / "config.json", AppConfig.default())
    window._debug_thread = _StubThread(running=True, wait_result=False)
    caplog.set_level(logging.ERROR)

    window.close()

    assert "未退出" in caplog.text
    window._debug_thread = None


def test_diagnose_button_runs_and_reports(window_factory, tmp_path, monkeypatch) -> None:
    """窗口诊断：按钮触发工作线程，结果写入状态栏与日志面板。"""
    from luoluotool.automation.window import DiagnosticResult
    from luoluotool.gui import main_window as mw
    from luoluotool.gui import workers

    monkeypatch.setattr(
        workers, "diagnose_window",
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
    from luoluotool.gui import workers
    from luoluotool.gui import main_window as mw

    def boom(keyword, debug_dir):
        raise RuntimeError("模拟失败")

    monkeypatch.setattr(workers, "diagnose_window", boom)
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
    config.features.daily_tasks.enabled = True     # A1 起总开关真的会挡队列，跑任务必须打开它
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


def test_developer_tab_appears_and_disappears(window_factory, tmp_path) -> None:
    """勾选「开发者调试」→ 顶部出现第 6 个页签；取消勾选 → 页签移除。"""
    from luoluotool.gui.main_window import DEBUG_TAB_TITLE

    config = AppConfig.default()
    window = window_factory(tmp_path / "config.json", config)
    assert window.tabs.count() == 6
    window.settings_page.developer_box.setChecked(True)
    assert window.tabs.count() == 7
    assert window.tabs.tabText(window.tabs.count() - 1) == DEBUG_TAB_TITLE
    window.settings_page.developer_box.setChecked(False)
    assert window.tabs.count() == 6
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
