"""GUI 提权测试：「以管理员身份重启」按钮、启动自动提权、不再询问与权限检测提示。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui_helpers import window_factory
from luoluotool.config.models import AppConfig

_APP = QApplication.instance() or QApplication([])


def test_restart_admin_button_confirmed(window_factory, tmp_path, monkeypatch) -> None:
    """确认后带 --config 参数请求提权重启；按钮场景不提供「不再询问」。"""
    from luoluotool.gui import elevation_flow
    from luoluotool.gui import main_window as mw

    recorded: dict[str, list[str]] = {}
    ask_flags: list[bool] = []
    monkeypatch.setattr(elevation_flow, "is_process_elevated", lambda: False)
    monkeypatch.setattr(
        elevation_flow, "restart_as_admin", lambda args: recorded.update(args=list(args)) or True
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
    from luoluotool.gui import elevation_flow
    from luoluotool.gui import main_window as mw

    called: list[list[str]] = []
    monkeypatch.setattr(elevation_flow, "is_process_elevated", lambda: False)
    monkeypatch.setattr(elevation_flow, "restart_as_admin", lambda args: called.append(list(args)) or True)
    monkeypatch.setattr(
        mw.MainWindow, "_ask_restart_confirmation", lambda self, allow_dont_ask=False: (False, False)
    )
    window = window_factory(tmp_path / "config.json")
    window.settings_page.restart_admin_button.click()
    assert called == []
    assert "取消" in window.statusBar().currentMessage() or "失败" in window.statusBar().currentMessage()


def test_restart_admin_button_when_already_elevated(window_factory, tmp_path, monkeypatch) -> None:
    """已是管理员权限：仅提示无需重启，不发起重启、不弹确认框。"""
    from luoluotool.gui import elevation_flow
    from luoluotool.gui import main_window as mw

    info_calls: list[str] = []
    restart_calls: list[list[str]] = []
    question_calls: list[tuple] = []
    monkeypatch.setattr(elevation_flow, "is_process_elevated", lambda: True)
    monkeypatch.setattr(
        mw.QMessageBox, "information",
        lambda parent, title, text, *args, **kwargs: info_calls.append(text),
    )
    monkeypatch.setattr(
        mw.MainWindow,
        "_ask_restart_confirmation",
        lambda self, allow_dont_ask=False: question_calls.append((allow_dont_ask,)) or (True, False),
    )
    monkeypatch.setattr(elevation_flow, "restart_as_admin", lambda args: restart_calls.append(list(args)) or True)
    window = window_factory(tmp_path / "config.json")
    window.settings_page.restart_admin_button.click()
    assert info_calls and "无需重启" in info_calls[0]
    assert question_calls == []
    assert restart_calls == []
    assert "无需重启" in window.statusBar().currentMessage()


def test_elevation_check_sets_settings_hint(window_factory, tmp_path, monkeypatch) -> None:
    """启动检测：游戏窗口权限更高且本工具未提权时，设置页给出提示。"""
    from luoluotool.gui import elevation_flow
    from luoluotool.gui import main_window as mw

    monkeypatch.setattr(elevation_flow, "is_process_elevated", lambda: False)
    monkeypatch.setattr(elevation_flow, "find_window", lambda keyword: 123)
    monkeypatch.setattr(elevation_flow, "is_window_elevated", lambda hwnd: True)
    window = window_factory(tmp_path / "config.json")
    window._check_elevation_need()
    label = window.settings_page.elevation_hint_label
    assert "管理员" in label.text()
    assert label.isHidden() is False


def test_startup_auto_elevate_prompts_and_restarts(window_factory, tmp_path, monkeypatch) -> None:
    """启动自动流程：非管理员 → 弹确认框（含「不再询问」）→ 确认后请求提权重启。"""
    from luoluotool.gui import elevation_flow
    from luoluotool.gui import main_window as mw

    recorded: dict[str, list[str]] = {}
    ask_flags: list[bool] = []
    monkeypatch.setattr(elevation_flow, "find_window", lambda keyword: None)
    monkeypatch.setattr(elevation_flow, "is_process_elevated", lambda: False)
    monkeypatch.setattr(
        mw.MainWindow,
        "_ask_restart_confirmation",
        lambda self, allow_dont_ask=False: ask_flags.append(allow_dont_ask) or (True, False),
    )
    monkeypatch.setattr(elevation_flow, "restart_as_admin", lambda args: recorded.update(args=list(args)) or True)
    window = window_factory(tmp_path / "config.json", auto_elevate=True)
    window._startup_elevation_flow()
    assert ask_flags == [True]
    assert recorded["args"] == ["--config", str(tmp_path / "config.json")]


def test_startup_auto_elevate_declined(window_factory, tmp_path, monkeypatch) -> None:
    """启动自动流程：用户拒绝 → 不重启，提示已取消。"""
    from luoluotool.gui import elevation_flow
    from luoluotool.gui import main_window as mw

    restart_calls: list[list[str]] = []
    monkeypatch.setattr(elevation_flow, "find_window", lambda keyword: None)
    monkeypatch.setattr(elevation_flow, "is_process_elevated", lambda: False)
    monkeypatch.setattr(
        mw.MainWindow, "_ask_restart_confirmation", lambda self, allow_dont_ask=False: (False, False)
    )
    monkeypatch.setattr(elevation_flow, "restart_as_admin", lambda args: restart_calls.append(list(args)) or True)
    window = window_factory(tmp_path / "config.json", auto_elevate=True)
    window._startup_elevation_flow()
    assert restart_calls == []
    assert "取消" in window.statusBar().currentMessage()


def test_startup_auto_elevate_when_admin_skips_modal(window_factory, tmp_path, monkeypatch) -> None:
    """启动自动流程：已是管理员 → 只提示无需重启，不弹任何确认框。"""
    from luoluotool.gui import elevation_flow
    from luoluotool.gui import main_window as mw

    questions: list[tuple] = []
    monkeypatch.setattr(elevation_flow, "find_window", lambda keyword: None)
    monkeypatch.setattr(elevation_flow, "is_process_elevated", lambda: True)
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
    from luoluotool.gui import elevation_flow
    from luoluotool.gui import main_window as mw

    questions: list[tuple] = []
    monkeypatch.setattr(elevation_flow, "find_window", lambda keyword: None)
    monkeypatch.setattr(elevation_flow, "is_process_elevated", lambda: False)
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

    from luoluotool.gui import elevation_flow
    from luoluotool.gui import main_window as mw

    monkeypatch.setattr(elevation_flow, "find_window", lambda keyword: None)
    monkeypatch.setattr(elevation_flow, "is_process_elevated", lambda: False)
    monkeypatch.setattr(elevation_flow, "restart_as_admin", lambda args: False)
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
    from luoluotool.gui import elevation_flow
    from luoluotool.gui import main_window as mw

    asked: list[bool] = []
    recorded: dict[str, list[str]] = {}
    monkeypatch.setattr(elevation_flow, "find_window", lambda keyword: None)
    monkeypatch.setattr(elevation_flow, "is_process_elevated", lambda: False)
    monkeypatch.setattr(
        mw.MainWindow,
        "_ask_restart_confirmation",
        lambda self, allow_dont_ask=False: asked.append(allow_dont_ask) or (False, False),
    )
    monkeypatch.setattr(elevation_flow, "restart_as_admin", lambda args: recorded.update(args=list(args)) or True)
    config = AppConfig.default()
    config.automation.ask_elevation_on_start = False
    window = window_factory(tmp_path / "config.json", config, auto_elevate=True)
    window._startup_elevation_flow()
    assert asked == []
    assert recorded["args"] == ["--config", str(tmp_path / "config.json")]


def test_startup_dont_ask_elevation_cancelled_keeps_running(window_factory, tmp_path, monkeypatch) -> None:
    """「不再询问」直连提权但用户取消了 UAC：程序继续以普通权限运行，不循环重试。"""
    from luoluotool.gui import elevation_flow
    from luoluotool.gui import main_window as mw

    calls: list[list[str]] = []
    monkeypatch.setattr(elevation_flow, "find_window", lambda keyword: None)
    monkeypatch.setattr(elevation_flow, "is_process_elevated", lambda: False)
    monkeypatch.setattr(elevation_flow, "restart_as_admin", lambda args: calls.append(list(args)) or False)
    config = AppConfig.default()
    config.automation.ask_elevation_on_start = False
    window = window_factory(tmp_path / "config.json", config, auto_elevate=True)
    window._startup_elevation_flow()
    assert len(calls) == 1
    assert window.isVisible() is False  # 未关闭主窗口，继续运行
    assert "取消" in window.statusBar().currentMessage() or "失败" in window.statusBar().currentMessage()
