"""开发者调试动作测试：单点/连点/滑动/键盘（全部注入假 sender，零真实输入）。"""

import logging
import threading

import pytest

from luoluotool.automation.input_sender import DryRunSender, InputChannel
from luoluotool.config.models import AppConfig
from luoluotool.core import debug


@pytest.fixture(autouse=True)
def _capture_logs(caplog):
    caplog.set_level(logging.INFO)


class _RecordingSender:
    """假 sender：记录调用；绝不产生真实输入。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.click_holds: list[float | None] = []      # 每次点击带的"点击时长"（秒）

    def move_to(self, x: int, y: int) -> None:
        self.calls.append(("move_to", x, y))

    def click(self, x: int, y: int, hold_seconds: float | None = None) -> None:
        self.calls.append(("click", x, y))

    def click_at(self, x: int, y: int, hold_seconds: float | None = None) -> None:
        self.calls.append(("click_at", x, y))
        self.click_holds.append(hold_seconds)

    def drag(self, from_xy, to_xy, duration_seconds: float) -> None:
        self.calls.append(("drag", tuple(from_xy), tuple(to_xy), round(duration_seconds, 3)))

    def key_tap(self, vk: int) -> None:
        self.calls.append(("key_tap", vk))

    def key_combo(self, combo: str) -> None:
        self.calls.append(("key_combo", combo))

    def key_hold(self, combo: str, seconds: float) -> None:
        self.calls.append(("key_hold", combo, round(seconds, 3)))


@pytest.fixture
def fake_channel(monkeypatch):
    """把 core.debug 的通道构建替换为假 sender（真实模式下也不会碰到系统）。"""
    sender = _RecordingSender()
    monkeypatch.setattr(debug, "build_channel", lambda config, stop_event, sleep, log: InputChannel(sender, None))
    return sender


def _config(dry_run: bool = False) -> AppConfig:
    config = AppConfig.default()
    config.automation.dry_run = dry_run
    return config


# ------------------------------------------------------------------ 单点


def test_single_click_calls_sender_once(fake_channel) -> None:
    message = debug.run_single_click(_config(), 120, 80, logging.getLogger("t"))
    assert fake_channel.calls == [("click_at", 120, 80)]
    assert "单点测试完成" in message and "(x=120, y=80)" in message


def test_single_click_respects_stop_event(fake_channel) -> None:
    """已收到停止请求时不应产生任何输入。"""
    stop = threading.Event()
    stop.set()
    message = debug.run_single_click(_config(), 1, 2, logging.getLogger("t"), stop)
    assert fake_channel.calls == []
    assert "已取消" in message


@pytest.mark.parametrize("x, y", [(-1, 0), (0, -1), (10001, 0), (0, 10001), (True, 0), ("a", 0)])
def test_single_click_rejects_bad_coordinates(fake_channel, x, y) -> None:
    with pytest.raises(ValueError):
        debug.run_single_click(_config(), x, y, logging.getLogger("t"))
    assert fake_channel.calls == []


def test_single_click_passes_click_hold(fake_channel) -> None:
    """点击时长：按毫秒传进 sender（秒），并在结果消息里写清。"""
    message = debug.run_single_click(_config(), 120, 80, logging.getLogger("t"), hold_ms=250)
    assert fake_channel.calls == [("click_at", 120, 80)]
    assert fake_channel.click_holds == [0.25]
    assert "点击时长 250 ms" in message


def test_single_click_zero_hold_means_instant(fake_channel) -> None:
    """点击时长 0 = 瞬时点击（与"不传"不同：不传＝用引擎默认时长）。"""
    debug.run_single_click(_config(), 1, 2, logging.getLogger("t"), hold_ms=0)
    assert fake_channel.click_holds == [0.0]


def test_single_click_without_hold_keeps_engine_default(fake_channel) -> None:
    """不传点击时长时保持原行为：不向 sender 传 hold_seconds。"""
    debug.run_single_click(_config(), 1, 2, logging.getLogger("t"))
    assert fake_channel.click_holds == [None]


@pytest.mark.parametrize("hold_ms", [-1, 60000, True, "100"])
def test_single_click_rejects_bad_hold(fake_channel, hold_ms) -> None:
    """点击时长必须在 0–5000 ms 的整数范围内（挡掉负数/超长/布尔/字符串）。"""
    with pytest.raises(ValueError):
        debug.run_single_click(_config(), 1, 2, logging.getLogger("t"), hold_ms=hold_ms)
    assert fake_channel.calls == []


# ------------------------------------------------------------------ 连点


def test_repeat_click_clicks_count_times(fake_channel, monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(debug.time, "sleep", sleeps.append)
    message = debug.run_repeat_click(_config(), 10, 20, 3, 500, logging.getLogger("t"))
    assert fake_channel.calls == [("click_at", 10, 20)] * 3
    assert sleeps == [0.5, 0.5]           # 最后一次不额外等待
    assert "连点测试完成" in message and "3 次" in message


def test_repeat_click_stops_between_clicks(fake_channel, monkeypatch) -> None:
    stop = threading.Event()
    monkeypatch.setattr(debug.time, "sleep", lambda _s: stop.set())   # 第一次间隔后收到停止
    message = debug.run_repeat_click(_config(), 0, 0, 5, 100, logging.getLogger("t"), stop)
    assert fake_channel.calls == [("click_at", 0, 0)]
    assert "中断" in message and "1/5" in message


@pytest.mark.parametrize("count, interval", [(0, 500), (201, 500), (1, 10), (1, 6000), (True, 500)])
def test_repeat_click_rejects_bad_params(fake_channel, count, interval) -> None:
    with pytest.raises(ValueError):
        debug.run_repeat_click(_config(), 0, 0, count, interval, logging.getLogger("t"))
    assert fake_channel.calls == []


# ------------------------------------------------------------------ 滑动


def test_swipe_calls_sender_drag_with_duration(fake_channel) -> None:
    message = debug.run_swipe(_config(), (10, 20), (300, 400), 800, logging.getLogger("t"))
    assert fake_channel.calls == [("drag", (10, 20), (300, 400), 0.8)]
    assert "滑动测试完成" in message and "800 ms" in message


@pytest.mark.parametrize("duration", [0, 49, 10001, True])
def test_swipe_rejects_bad_duration(fake_channel, duration) -> None:
    with pytest.raises(ValueError):
        debug.run_swipe(_config(), (0, 0), (1, 1), duration, logging.getLogger("t"))
    assert fake_channel.calls == []


# ------------------------------------------------------------------ 键盘


def test_key_test_sends_combo_count_times(fake_channel, monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(debug.time, "sleep", sleeps.append)
    message = debug.run_key(_config(), "ctrl+s", 2, 300, logging.getLogger("t"))
    assert fake_channel.calls == [("key_combo", "ctrl+s")] * 2
    assert sleeps == [0.3]
    assert "键盘测试完成" in message


def test_key_test_rejects_unknown_key_name(fake_channel) -> None:
    """未知键名必须给出可读错误且不发送任何输入。"""
    with pytest.raises(ValueError, match="未知按键名"):
        debug.run_key(_config(), "ctrl+nosuchkey", 1, 300, logging.getLogger("t"))
    assert fake_channel.calls == []


def test_key_test_rejects_empty_combo(fake_channel) -> None:
    with pytest.raises(ValueError, match="不能为空"):
        debug.run_key(_config(), "   ", 1, 300, logging.getLogger("t"))
    assert fake_channel.calls == []


# ------------------------------------------------ 与真实通道的集成（干跑安全）


def test_dry_run_channel_produces_no_real_input(caplog) -> None:
    """走真实 build_channel：干跑模式下四个测试都只写日志、零真实输入。

    （这里刻意不 monkeypatch build_channel，以验证干跑分支本身；DryRunSender 不会调用系统 API。）
    """
    caplog.set_level("INFO")
    config = _config(dry_run=True)
    assert debug.run_single_click(config, 1, 2, logging.getLogger("t")).startswith("单点测试完成")
    assert debug.run_repeat_click(config, 1, 2, 2, 50, logging.getLogger("t")).startswith("连点测试完成")
    assert debug.run_swipe(config, (1, 2), (3, 4), 100, logging.getLogger("t")).startswith("滑动测试完成")
    assert debug.run_key(config, "enter", 1, 50, logging.getLogger("t")).startswith("键盘测试完成")
    assert "干跑：模拟点击 (1, 2)" in caplog.text
    assert "干跑：模拟滑动 (1, 2) → (3, 4) 用时 0.10s" in caplog.text
    assert "干跑：模拟按键组合 enter" in caplog.text


def test_dry_run_channel_reports_window_missing_in_real_mode(monkeypatch) -> None:
    """真实模式 + 找不到游戏窗口：必须抛可读错误，绝不产生输入。"""
    monkeypatch.setattr("luoluotool.automation.input_sender.find_window", lambda keyword: None)
    from luoluotool.automation.input_sender import WindowUnavailableError

    with pytest.raises(WindowUnavailableError, match="未找到"):
        debug.run_single_click(_config(dry_run=False), 10, 10, logging.getLogger("t"))


def test_debug_module_never_injects_directly() -> None:
    """架构约束：core.debug 只编排，不直接调用注入 API（注入只能在 real_input.py）。"""
    import pathlib

    text = pathlib.Path(debug.__file__).read_text(encoding="utf-8")
    for token in ("SendInput(", "SetCursorPos(", "mouse_event(", "keybd_event("):
        assert token not in text
