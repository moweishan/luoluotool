"""GUI 急停热键测试：注册到主窗口句柄、WM_HOTKEY 分发、失败提示与保存/重载后重新注册。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui_helpers import window_factory
from luoluotool.config.models import AppConfig

_APP = QApplication.instance() or QApplication([])


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


def test_reload_and_reset_reapply_hotkey(window_factory, tmp_path, monkeypatch) -> None:
    """回归（评审 P3-9）：重载 / 恢复默认后，配置里的急停键立即重新注册。"""
    config = AppConfig.default()
    window = window_factory(tmp_path / "config.json", config)
    applied: list[str] = []
    monkeypatch.setattr(window, "_apply_hotkey_config", lambda: applied.append("apply"))

    window._reload()
    window._reset()

    assert applied == ["apply", "apply"]


def test_hotkey_failure_is_visible_in_ui(window_factory, tmp_path, monkeypatch) -> None:
    """回归（评审 P3-9）：热键注册失败时必须让用户看得见（状态栏 + 设置页提示），不能只写日志。

    本机 F8 常被占用 → 此时「停止」按钮是唯一中断手段。
    """
    window = window_factory(tmp_path / "config.json", AppConfig.default())
    monkeypatch.setattr(window._hotkey, "register", lambda hwnd=0: False)

    window._register_hotkey_or_hint()

    label = window.settings_page.hotkey_hint_label
    assert "急停热键" in window.statusBar().currentMessage()
    assert label.isHidden() is False
    assert "停止" in label.text()


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
