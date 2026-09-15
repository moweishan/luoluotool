"""automation.pointer_sender 测试：合成指针注入（全部注入假 user32，零真实注入）。"""

import ctypes
import logging

import pytest

from luoluotool.automation import pointer_sender
from luoluotool.automation.errors import WindowUnavailableError


class _FakeUser32:
    """假 user32：记录调用并回读注入结构体，绝不触碰真实输入。"""

    def __init__(self, synthetic_ok: bool = True, legacy_ok: bool = True, inject_ok: bool = True) -> None:
        self.calls: list[tuple] = []
        self.synthetic_ok = synthetic_ok
        self.legacy_ok = legacy_ok
        self.inject_ok = inject_ok
        self.destroyed: list[int] = []

    def CreateSyntheticPointerDevice(self, pointer_type, max_count, mode):
        self.calls.append(("create", pointer_type, max_count, mode))
        return 0x1234 if self.synthetic_ok else 0

    def InjectSyntheticPointerInput(self, device, info_ref, count):
        info = info_ref._obj
        pointer = info.touchInfo.pointerInfo if info.type == pointer_sender.PT_TOUCH else info.penInfo.pointerInfo
        self.calls.append(
            (
                "inject_pointer",
                device,
                info.type,
                pointer.pointerFlags,
                pointer.hwndTarget,
                pointer.ptPixelLocation.x,
                pointer.ptPixelLocation.y,
            )
        )
        return 1 if self.inject_ok else 0

    def DestroySyntheticPointerDevice(self, device):
        self.destroyed.append(device)

    def InitializeTouchInjection(self, count, mode):
        self.calls.append(("init_touch", count, mode))
        return 1 if self.legacy_ok else 0

    def InjectTouchInput(self, count, info_ref):
        info = info_ref._obj
        self.calls.append(
            (
                "inject_touch",
                count,
                info.pointerInfo.pointerFlags,
                info.pointerInfo.hwndTarget,
                info.pointerInfo.ptPixelLocation.x,
                info.pointerInfo.ptPixelLocation.y,
            )
        )
        return 1 if self.inject_ok else 0


@pytest.fixture(autouse=True)
def _capture_info_logs(caplog):
    caplog.set_level(logging.DEBUG)


@pytest.fixture
def fake_user32(monkeypatch):
    fake = _FakeUser32()
    monkeypatch.setattr(pointer_sender.ctypes, "windll", type("W", (), {"user32": fake})())
    monkeypatch.setattr(pointer_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(
        pointer_sender.win32gui, "ClientToScreen", lambda hwnd, point: (1000 + point[0], 500 + point[1])
    )
    return fake


def test_structure_layout_matches_winuser_header() -> None:
    """ctypes 结构体布局必须与 winuser.h 一致（x64）。"""
    assert ctypes.sizeof(pointer_sender.POINTER_INFO) == 96
    assert ctypes.sizeof(pointer_sender.TOUCH_INFO) == 144
    assert ctypes.sizeof(pointer_sender.POINTER_TYPE_INFO) == 152


def test_click_injects_down_then_up_with_screen_coordinates(fake_user32) -> None:
    sender = pointer_sender.SyntheticPointerSender(hwnd=777, sleep=lambda s: None)
    sender.click_at(10, 20)

    assert ("create", pointer_sender.PT_TOUCH, 1, pointer_sender.POINTER_FEEDBACK_DEFAULT) in fake_user32.calls
    injections = [call for call in fake_user32.calls if call[0] == "inject_pointer"]
    assert len(injections) == 2
    down, up = injections
    assert down[3] == pointer_sender.POINTER_FLAG_DOWN | pointer_sender.POINTER_FLAG_INRANGE | pointer_sender.POINTER_FLAG_INCONTACT | pointer_sender.POINTER_FLAG_PRIMARY
    assert up[3] == pointer_sender.POINTER_FLAG_UP | pointer_sender.POINTER_FLAG_INRANGE | pointer_sender.POINTER_FLAG_INCONTACT
    # 客户区 (10, 20) → 屏幕 (1010, 520)
    assert down[5:] == (1010, 520)
    assert up[5:] == (1010, 520)
    assert down[4] == 777 and up[4] == 777  # hwndTarget 指向游戏窗口
    assert fake_user32.destroyed == [0x1234]  # 设备必须释放


def test_click_uses_pen_when_configured(fake_user32) -> None:
    sender = pointer_sender.SyntheticPointerSender(hwnd=1, pointer_type="pen", sleep=lambda s: None)
    sender.click(5, 5)
    assert ("create", pointer_sender.PT_PEN, 1, pointer_sender.POINTER_FEEDBACK_DEFAULT) in fake_user32.calls
    assert all(call[2] == pointer_sender.PT_PEN for call in fake_user32.calls if call[0] == "inject_pointer")


def test_falls_back_to_legacy_touch_injection(monkeypatch) -> None:
    fake = _FakeUser32(synthetic_ok=False)
    monkeypatch.setattr(pointer_sender.ctypes, "windll", type("W", (), {"user32": fake})())
    monkeypatch.setattr(pointer_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(pointer_sender.win32gui, "ClientToScreen", lambda hwnd, point: point)
    sender = pointer_sender.SyntheticPointerSender(hwnd=1, sleep=lambda s: None)
    sender.click(1, 2)
    kinds = [call[0] for call in fake.calls]
    assert "init_touch" in kinds
    assert kinds.count("inject_touch") == 2


def test_raises_readable_error_when_no_api_available(monkeypatch) -> None:
    fake = _FakeUser32(synthetic_ok=False, legacy_ok=False)
    monkeypatch.setattr(pointer_sender.ctypes, "windll", type("W", (), {"user32": fake})())
    monkeypatch.setattr(pointer_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(pointer_sender.win32gui, "ClientToScreen", lambda hwnd, point: point)
    sender = pointer_sender.SyntheticPointerSender(hwnd=1, sleep=lambda s: None)
    with pytest.raises(WindowUnavailableError) as excinfo:
        sender.click(1, 2)
    assert "合成指针" in str(excinfo.value)


def test_raises_when_injection_returns_zero(monkeypatch) -> None:
    fake = _FakeUser32(inject_ok=False)
    monkeypatch.setattr(pointer_sender.ctypes, "windll", type("W", (), {"user32": fake})())
    monkeypatch.setattr(pointer_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(pointer_sender.win32gui, "ClientToScreen", lambda hwnd, point: point)
    sender = pointer_sender.SyntheticPointerSender(hwnd=1, sleep=lambda s: None)
    with pytest.raises(WindowUnavailableError):
        sender.click(1, 2)


def test_raises_when_window_gone(monkeypatch) -> None:
    fake = _FakeUser32()
    monkeypatch.setattr(pointer_sender.ctypes, "windll", type("W", (), {"user32": fake})())
    monkeypatch.setattr(pointer_sender, "window_exists", lambda hwnd: False)
    sender = pointer_sender.SyntheticPointerSender(hwnd=1, sleep=lambda s: None)
    with pytest.raises(WindowUnavailableError):
        sender.click(1, 2)
    assert fake.calls == []


def test_move_to_does_not_inject(fake_user32, caplog) -> None:
    sender = pointer_sender.SyntheticPointerSender(hwnd=1, sleep=lambda s: None)
    sender.move_to(3, 4)
    assert fake_user32.calls == []
    assert "悬停" in caplog.text


def test_key_tap_delegates_to_window_message_sender(monkeypatch) -> None:
    from luoluotool.automation import input_sender

    used: list[tuple] = []

    class _Recorder:
        def __init__(self, hwnd, log=None, sleep=None) -> None:
            used.append(("init", hwnd))

        def key_tap(self, vk: int) -> None:
            used.append(("key_tap", vk))

    monkeypatch.setattr(input_sender, "WindowMessageSender", _Recorder)
    pointer_sender.SyntheticPointerSender(hwnd=42, sleep=lambda s: None).key_tap(0x41)
    assert used == [("init", 42), ("key_tap", 0x41)]


def test_implements_input_sender_protocol() -> None:
    sender = pointer_sender.SyntheticPointerSender(hwnd=1, sleep=lambda s: None)
    for name in ("move_to", "click", "click_at", "key_tap"):
        assert callable(getattr(sender, name))
