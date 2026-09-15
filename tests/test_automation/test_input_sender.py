"""automation.input_sender 测试：窗口消息发送、干跑降级、窗口就绪守卫（全部注入假 API）。"""

import logging
import threading
from pathlib import Path

import pytest

from luoluotool.automation import input_sender
from luoluotool.config.models import AppConfig

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(autouse=True)
def _capture_info_logs(caplog):
    caplog.set_level(logging.INFO)


class _FakeUser32:
    def __init__(self, post_result: int = 1) -> None:
        self.posted: list[tuple[int, int, int, int]] = []
        self.post_result = post_result

    def PostMessageW(self, hwnd, message, wparam, lparam):
        self.posted.append((hwnd, message, wparam, lparam))
        return self.post_result


@pytest.fixture
def fake_windll(monkeypatch):
    fake = _FakeUser32()
    wrapper = type("Windll", (), {"user32": fake})()
    monkeypatch.setattr(input_sender.ctypes, "windll", wrapper)
    return wrapper


def test_source_contains_no_input_takeover_apis() -> None:
    """红线：src 全量源码中不得出现接管真实键鼠的接口名。"""
    forbidden = ("Send" + "Input", "SetCursor" + "Pos", "mouse_" + "event")
    offenders: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.name}:{name}" for name in forbidden if name in text)
    assert offenders == []


def test_pack_point_packs_client_coordinates() -> None:
    assert input_sender._pack_point(0x1234, 0x5678) == 0x56781234
    assert input_sender._pack_point(0, 0) == 0


def test_dry_run_sender_only_logs(fake_windll, caplog) -> None:
    sender = input_sender.DryRunSender()
    sender.move_to(10, 20)
    sender.click(10, 20)
    sender.click_at(30, 40)
    sender.key_tap(0x77)
    assert fake_windll.user32.posted == []  # 干跑绝不能发送任何消息
    assert "模拟点击 (30, 40)" in caplog.text
    assert "模拟按键" in caplog.text


def test_window_sender_click_posts_three_messages(fake_windll) -> None:
    sender = input_sender.WindowMessageSender(hwnd=1234)
    sender.click(11, 22)
    assert fake_windll.user32.posted == [
        (1234, input_sender.WM_MOUSEMOVE, 0, input_sender._pack_point(11, 22)),
        (1234, input_sender.WM_LBUTTONDOWN, input_sender.MK_LBUTTON, input_sender._pack_point(11, 22)),
        (1234, input_sender.WM_LBUTTONUP, 0, input_sender._pack_point(11, 22)),
    ]


def test_window_sender_key_tap_posts_down_and_up(fake_windll) -> None:
    sender = input_sender.WindowMessageSender(hwnd=99)
    sender.key_tap(0x41)
    assert fake_windll.user32.posted == [
        (99, input_sender.WM_KEYDOWN, 0x41, 0),
        (99, input_sender.WM_KEYUP, 0x41, 0),
    ]


def test_window_sender_raises_when_post_fails(monkeypatch) -> None:
    fake = _FakeUser32(post_result=0)
    monkeypatch.setattr(input_sender.ctypes, "windll", type("Windll", (), {"user32": fake})())
    sender = input_sender.WindowMessageSender(hwnd=1)
    with pytest.raises(input_sender.WindowUnavailableError):
        sender.click(1, 1)


def test_build_channel_dry_run_needs_no_window(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("干跑模式不应查询窗口")

    monkeypatch.setattr(input_sender, "find_window", boom)
    config = AppConfig.default()
    channel = input_sender.build_channel(config, threading.Event(), lambda s: None, input_sender.logger)
    assert isinstance(channel.sender, input_sender.DryRunSender)
    assert channel.readiness is None


def test_build_channel_real_mode_missing_window(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "find_window", lambda keyword: None)
    config = AppConfig.default()
    config.automation.dry_run = False
    with pytest.raises(input_sender.WindowUnavailableError) as excinfo:
        input_sender.build_channel(config, threading.Event(), lambda s: None, input_sender.logger)
    assert "未找到" in str(excinfo.value)


def test_build_channel_real_mode_minimized_window(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "find_window", lambda keyword: 555)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: False)
    config = AppConfig.default()
    config.automation.dry_run = False
    with pytest.raises(input_sender.WindowUnavailableError) as excinfo:
        input_sender.build_channel(config, threading.Event(), lambda s: None, input_sender.logger)
    assert "最小化" in str(excinfo.value) or "不可见" in str(excinfo.value)


def test_build_channel_real_mode_returns_message_sender(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "find_window", lambda keyword: 777)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    config = AppConfig.default()
    config.automation.dry_run = False
    channel = input_sender.build_channel(config, threading.Event(), lambda s: None, input_sender.logger)
    assert isinstance(channel.sender, input_sender.WindowMessageSender)
    assert channel.sender.hwnd == 777
    assert channel.readiness is not None


def test_readiness_gate_ready_and_focused(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_foreground", lambda hwnd: True)
    gate = input_sender.WindowReadinessGate(1, True, threading.Event(), lambda s: None)
    assert gate.wait_until_ready() is True


def test_readiness_gate_pauses_until_focus_returns(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    states = {"focused": False}
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_foreground", lambda hwnd: states["focused"])

    def fake_sleep(seconds: float) -> None:
        states["focused"] = True  # 模拟用户重新聚焦窗口

    gate = input_sender.WindowReadinessGate(1, True, threading.Event(), fake_sleep)
    assert gate.wait_until_ready() is True
    assert "失焦" in caplog.text
    assert "重新聚焦" in caplog.text


def test_readiness_gate_returns_false_on_stop(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_foreground", lambda hwnd: False)
    stop_event = threading.Event()
    stop_event.set()
    gate = input_sender.WindowReadinessGate(1, True, stop_event, lambda s: None)
    assert gate.wait_until_ready() is False


def test_readiness_gate_stop_during_pause(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_foreground", lambda hwnd: False)
    stop_event = threading.Event()

    def fake_sleep(seconds: float) -> None:
        stop_event.set()

    gate = input_sender.WindowReadinessGate(1, True, stop_event, fake_sleep)
    assert gate.wait_until_ready() is False
    assert "停止" in caplog.text


def test_readiness_gate_waits_when_minimized_then_restored(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    states = {"ready": False}
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: states["ready"])
    monkeypatch.setattr(input_sender, "is_window_foreground", lambda hwnd: True)

    def fake_sleep(seconds: float) -> None:
        states["ready"] = True

    gate = input_sender.WindowReadinessGate(1, False, threading.Event(), fake_sleep)
    assert gate.wait_until_ready() is True
    assert "最小化" in caplog.text or "不可见" in caplog.text


def test_readiness_gate_raises_when_window_destroyed(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: False)
    gate = input_sender.WindowReadinessGate(1, True, threading.Event(), lambda s: None)
    with pytest.raises(input_sender.WindowUnavailableError):
        gate.wait_until_ready()


def test_is_window_ready_combines_checks(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(input_sender.win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(input_sender.win32gui, "IsIconic", lambda hwnd: False)
    assert input_sender.is_window_ready(1) is True
    monkeypatch.setattr(input_sender.win32gui, "IsIconic", lambda hwnd: True)
    assert input_sender.is_window_ready(1) is False