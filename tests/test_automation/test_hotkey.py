"""automation.hotkey 测试：注册/注销与失败路径（注入假 windll，不注册真实热键）。"""

import pytest

from luoluotool.automation import hotkey


class _FakeUser32:
    def __init__(self, register_result: int = 1) -> None:
        self.register_result = register_result
        self.registered = 0
        self.unregistered = 0

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, vk):
        self.registered += 1
        return self.register_result

    def UnregisterHotKey(self, hwnd, hotkey_id):
        self.unregistered += 1


@pytest.fixture
def fake_windll(monkeypatch):
    fake = _FakeUser32()
    wrapper = type("Windll", (), {"user32": fake})()
    monkeypatch.setattr(hotkey.ctypes, "windll", wrapper)
    return wrapper


def test_register_success(fake_windll) -> None:
    registrar = hotkey.HotkeyRegistrar()
    assert registrar.register() is True
    assert fake_windll.user32.registered == 1
    assert registrar._registered is True


def test_register_is_idempotent(fake_windll) -> None:
    registrar = hotkey.HotkeyRegistrar()
    assert registrar.register() is True
    assert registrar.register() is True
    assert fake_windll.user32.registered == 1


def test_register_failure_returns_false(fake_windll) -> None:
    fake_windll.user32.register_result = 0
    registrar = hotkey.HotkeyRegistrar()
    assert registrar.register() is False
    assert registrar._registered is False


def test_unregister_idempotent(fake_windll) -> None:
    registrar = hotkey.HotkeyRegistrar()
    registrar.register()
    registrar.unregister()
    assert fake_windll.user32.unregistered == 1
    registrar.unregister()
    assert fake_windll.user32.unregistered == 1


def test_non_windows_platform_skips(monkeypatch) -> None:
    monkeypatch.setattr(hotkey.sys, "platform", "linux")
    registrar = hotkey.HotkeyRegistrar()
    assert registrar.register() is False
