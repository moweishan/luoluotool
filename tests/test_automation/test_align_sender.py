"""对齐窗口点击通道（WindowAlignSender）与 build_channel 分派测试。

全部使用注入的假实现：不投递任何真实消息、不移动任何窗口。
"""

import pytest

from luoluotool.automation import input_sender, window_align
from luoluotool.automation.input_sender import (
    WindowAlignSender,
    WindowMessageSender,
    WindowUnavailableError,
)
from luoluotool.config.models import INPUT_MODE_WINDOW_ALIGN, INPUT_MODE_WINDOW_MESSAGE, AppConfig


@pytest.fixture(autouse=True)
def _capture_info_logs(caplog):
    caplog.set_level("INFO")


class _FakeInner:
    """假的窗口消息发送器：记录调用，可按需抛错。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail: Exception | None = None

    def move_to(self, x: int, y: int) -> None:
        self.calls.append(("move_to", x, y))

    def click(self, x: int, y: int) -> None:
        self.calls.append(("click", x, y))
        if self.fail is not None:
            raise self.fail

    def click_at(self, x: int, y: int) -> None:
        self.click(x, y)

    def key_tap(self, vk: int) -> None:
        self.calls.append(("key_tap", vk))


@pytest.fixture
def align_env(monkeypatch):
    """脚本化对齐环境：记录调用顺序，默认对齐成功、还原成功、光标静止。"""
    inner = _FakeInner()
    events: list[str] = []
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    monkeypatch.setattr(window_align, "ensure_alignment_supported", lambda hwnd: events.append("check"))
    monkeypatch.setattr(
        window_align, "wait_cursor_idle",
        lambda **kwargs: (events.append("idle"), (True, 0.0))[1],
    )
    monkeypatch.setattr(
        window_align, "align_window",
        lambda hwnd, x, y, sleep=None: (
            events.append(f"align({x},{y})"),
            window_align.AlignResult(True, (0, 0), (800, 600), (0, 0, 1470, 863), "", 1),
        )[1],
    )
    monkeypatch.setattr(
        window_align, "restore_window",
        lambda hwnd, rect, sleep=None: (events.append("restore"), True)[1],
    )
    sender = WindowAlignSender(555, sleep=lambda _s: None)
    sender._inner = inner  # 注入假发送器
    return sender, inner, events


def test_align_sender_clicks_in_order_and_restores_window(align_env) -> None:
    """正常路径：前置检查 → 等光标静止 → 对齐 → 点击 → 还原窗口。"""
    sender, inner, events = align_env
    sender.click_at(120, 80)
    assert events == ["check", "idle", "align(120,80)", "restore"]
    assert inner.calls == [("click", 120, 80)]


def test_align_sender_refuses_when_window_not_ready(monkeypatch) -> None:
    """窗口最小化/不可见时绝不点击。"""
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: False)
    sender = WindowAlignSender(555, sleep=lambda _s: None)
    sender._inner = _FakeInner()
    with pytest.raises(WindowUnavailableError):
        sender.click_at(10, 10)
    assert sender._inner.calls == []


def test_align_sender_refuses_when_maximized(align_env, monkeypatch) -> None:
    """最大化窗口无法对齐 → 抛可读错误且不点击（避免落到错误位置）。"""

    def boom(hwnd):
        raise WindowUnavailableError("游戏窗口已最大化")

    monkeypatch.setattr(window_align, "ensure_alignment_supported", boom)
    sender, inner, events = align_env
    with pytest.raises(WindowUnavailableError, match="最大化"):
        sender.click_at(10, 10)
    assert inner.calls == []
    assert events == []


def test_align_sender_refuses_while_user_keeps_moving_mouse(align_env, monkeypatch) -> None:
    """真实鼠标持续移动时不对齐、不点击（否则会点错位置），错误信息可读。"""
    monkeypatch.setattr(window_align, "wait_cursor_idle", lambda **kwargs: (False, 1500.0))
    sender, inner, events = align_env
    with pytest.raises(WindowUnavailableError, match="正在移动"):
        sender.click_at(10, 10)
    assert inner.calls == []
    assert "align(10,10)" not in events


def test_align_sender_raises_and_restores_when_alignment_fails(align_env, monkeypatch) -> None:
    """对齐失败：还原窗口并抛可读错误，绝不点击。"""
    monkeypatch.setattr(
        window_align, "align_window",
        lambda hwnd, x, y, sleep=None: window_align.AlignResult(
            False, (5, 5), (800, 600), (0, 0, 1470, 863), "对齐误差=(5, 5)", 2
        ),
    )
    sender, inner, events = align_env
    with pytest.raises(WindowUnavailableError, match="对齐失败"):
        sender.click_at(10, 10)
    assert inner.calls == []
    assert "restore" in events


def test_align_sender_restores_window_even_when_click_fails(align_env) -> None:
    """点击过程抛错时也必须还原窗口（finally），错误继续向上抛。"""
    sender, inner, events = align_env
    inner.fail = WindowUnavailableError("窗口已关闭")
    with pytest.raises(WindowUnavailableError):
        sender.click_at(10, 10)
    assert events.count("restore") == 1
    assert inner.calls == [("click", 10, 10)]


def test_align_sender_logs_when_restore_fails(align_env, monkeypatch, caplog) -> None:
    """还原失败必须留下 ERROR 日志（窗口停在别处需要人工处理），但不掩盖点击结果。"""
    monkeypatch.setattr(window_align, "restore_window", lambda hwnd, rect, sleep=None: False)
    caplog.set_level("ERROR")
    sender, _inner, _events = align_env
    sender.click_at(10, 10)
    assert any("还原失败" in record.message for record in caplog.records)


def test_align_sender_move_to_does_not_align(align_env) -> None:
    """悬停不影响落点，不做窗口对齐（避免无意义的窗口位移）。"""
    sender, inner, events = align_env
    sender.move_to(30, 40)
    assert inner.calls == [("move_to", 30, 40)]
    assert events == []


def test_align_sender_key_tap_delegates(align_env) -> None:
    """按键仍走窗口消息通道（不需要对齐）。"""
    sender, inner, _events = align_env
    sender.key_tap(0x77)
    assert inner.calls == [("key_tap", 0x77)]


def test_build_channel_uses_align_sender_when_enabled(monkeypatch) -> None:
    """配置打开时 build_channel 返回对齐通道；关闭时仍是普通窗口消息通道。"""
    monkeypatch.setattr(input_sender, "find_window", lambda keyword: 777)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)

    config = AppConfig.default()
    config.automation.dry_run = False
    config.automation.input_mode = INPUT_MODE_WINDOW_ALIGN
    channel = input_sender.build_channel(config, __import__("threading").Event(), lambda _s: None)
    assert isinstance(channel.sender, WindowAlignSender)

    config.automation.input_mode = INPUT_MODE_WINDOW_MESSAGE
    channel = input_sender.build_channel(config, __import__("threading").Event(), lambda _s: None)
    assert isinstance(channel.sender, WindowMessageSender)
    assert not isinstance(channel.sender, WindowAlignSender)


def test_align_sender_source_has_no_cursor_moving_apis() -> None:
    """红线：对齐通道自身不得出现移动真实光标的 API。"""
    with open(input_sender.__file__, encoding="utf-8") as fp:
        text = fp.read()
    for forbidden in ("SetCursorPos", "mouse_event", "InjectSyntheticPointerInput"):
        assert forbidden not in text, f"input_sender 不应使用 {forbidden}"
