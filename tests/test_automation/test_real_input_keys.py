"""真实键鼠输入通道的**键盘**路径测试（从 `test_real_input.py` 按被测对象拆出）。

覆盖：`send_key_tap` 的扫描码、`parse_combo` 的键名表与可读报错、`send_key_combo`
（修饰键先按下、主键后抬起、**逆序释放**、主键失败也释放）、`send_key_hold`
（切片推进、急停中断、异常也释放、0 切片不死循环），以及 `RealInputSender` 的
按键路径（每次输入前校验置顶、未知键名在注入前拒绝、干跑只写日志）。

全部注入假 user32：单测**零真实输入**。
"""

import pytest

from luoluotool.automation import input_sender, real_input
from luoluotool.automation.input_sender import RealInputSender, WindowUnavailableError

from test_automation.real_input_helpers import _capture_logs, recording, user32


# ------------------------------------------------------------------ 键盘原语


def test_send_key_tap_uses_scancode_down_then_up(user32) -> None:
    """键盘：用扫描码（更接近真实硬件、兼容读 GetKeyState 的游戏），先按下后抬起。"""
    real_input.send_key_tap(0x41, sleep=lambda _s: None)  # 'A'
    assert len(user32.sent) == 2
    down, up = user32.sent
    assert down["type"] == real_input.INPUT_KEYBOARD and up["type"] == real_input.INPUT_KEYBOARD
    assert down["flags"] & real_input.KEYEVENTF_SCANCODE
    assert not down["flags"] & real_input.KEYEVENTF_KEYUP
    assert up["flags"] & real_input.KEYEVENTF_KEYUP


# ---------------------------------------------- 发送器：按键路径与未知键名拒绝


def test_real_sender_key_tap_checks_front_and_releases(recording) -> None:
    """按键：校验/置顶 → 发扫描码 → 取消置顶。"""
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.key_tap(0x1B)  # ESC
    assert recording.events == [
        ("ensure_front", 555),
        ("key", 0x1B),
        ("release_topmost", 555),
    ]


# ------------------------------------------------------------- 组合键与长按


def test_parse_combo_letters_digits_and_named_keys() -> None:
    """回归：字母键名是小写（曾经表里写成大写，导致 `ctrl+s` 报"未知按键名"）。"""
    assert real_input.parse_combo("s")[1] == 0x53
    assert real_input.parse_combo("A")[1] == 0x41          # 大小写都接受
    assert real_input.parse_combo("5")[1] == 0x35
    assert real_input.parse_combo("f5")[1] == 0x74
    assert real_input.parse_combo("enter")[1] == 0x0D
    assert real_input.parse_combo("esc")[1] == 0x1B
    assert real_input.parse_combo("space")[1] == 0x20
    assert real_input.parse_combo("left")[1] == 0x25


def test_parse_combo_splits_modifiers_and_key() -> None:
    """组合键解析：修饰键元组按书写顺序，主键为最后一段。"""
    modifiers, main_vk = real_input.parse_combo("ctrl+shift+s")
    assert modifiers == (real_input.MODIFIER_KEYS["ctrl"], real_input.MODIFIER_KEYS["shift"])
    assert main_vk == 0x53
    # 单独的修饰键：修饰键元组为空、主键就是它自己
    assert real_input.parse_combo("ctrl") == ((), real_input.MODIFIER_KEYS["ctrl"])


def test_parse_combo_rejects_bad_text_with_readable_reason() -> None:
    """非法组合键必须给出可读原因（GUI/校验据此提示用户）。"""
    for bad, keyword in (("", "不能为空"), ("ctrl+", "空片段"), ("ctrl+ctrl+s", "重复"),
                         ("meta+s", "未知修饰键"), ("ctrl+nosuchkey", "未知按键名")):
        with pytest.raises(ValueError) as excinfo:
            real_input.parse_combo(bad)
        assert keyword in str(excinfo.value), bad


def test_send_key_combo_presses_modifiers_then_key(user32) -> None:
    """注入顺序：控制键按下 → 主键按下/抬起 → 控制键抬起（逆序释放）。"""
    assert real_input.send_key_combo("ctrl+s", sleep=lambda _s: None) is True
    events = [(event["scan"], event["flags"]) for event in user32.sent]
    keys = [scan for scan, _flags in events]
    ctrl_scan = real_input.MODIFIER_KEYS["ctrl"] & 0xFF
    assert keys == [ctrl_scan, 0x53, 0x53, ctrl_scan]
    assert not events[0][1] & real_input.KEYEVENTF_KEYUP     # ctrl 按下
    assert events[2][1] & real_input.KEYEVENTF_KEYUP         # s 抬起
    assert events[3][1] & real_input.KEYEVENTF_KEYUP         # ctrl 抬起


def test_send_key_combo_uses_extended_flag_for_arrow_keys(user32) -> None:
    """方向键等扩展键必须带 EXTENDEDKEY，否则部分游戏识别不到。"""
    real_input.send_key_combo("left", sleep=lambda _s: None)
    assert all(event["flags"] & real_input.KEYEVENTF_EXTENDEDKEY for event in user32.sent)


def test_send_key_combo_releases_modifiers_even_when_key_injection_fails(user32, monkeypatch) -> None:
    """主键发送失败时也必须在 finally 里释放已按下的修饰键（绝不卡键）。"""
    monkeypatch.setattr(real_input, "send_key_tap", lambda vk, sleep=None: False)
    assert real_input.send_key_combo("ctrl+s", sleep=lambda _s: None) is False
    scans = [event["scan"] for event in user32.sent]
    assert scans == [real_input.MODIFIER_KEYS["ctrl"] & 0xFF] * 2
    assert user32.sent[-1]["flags"] & real_input.KEYEVENTF_KEYUP


def test_send_key_hold_runs_full_duration_and_releases(user32) -> None:
    """长按：按满时长后释放；返回 (成功, 是否被中断)。"""
    slept: list[float] = []
    ok, interrupted = real_input.send_key_hold("w", 0.25, sleep=slept.append, slice_seconds=0.1)
    assert (ok, interrupted) == (True, False)
    assert abs(sum(slept) - 0.25) < 1e-6
    scans = [event["scan"] for event in user32.sent]
    assert scans[0] == 0x57 and scans[-1] == 0x57
    assert user32.sent[-1]["flags"] & real_input.KEYEVENTF_KEYUP


def test_send_key_hold_aborts_on_stop_request_and_releases(user32) -> None:
    """急停期间长按必须立刻中断并释放按键（停止请求 500ms 内生效的要求）。"""
    class _Stop:
        def __init__(self) -> None:
            self.flag = False

        def is_set(self) -> bool:
            return self.flag

    stop = _Stop()

    def fake_sleep(seconds: float) -> None:
        stop.flag = True   # 第一个切片后就收到停止请求

    ok, interrupted = real_input.send_key_hold("w", 5.0, sleep=fake_sleep, stop_event=stop)
    assert ok is True
    assert interrupted is True
    assert user32.sent[-1]["flags"] & real_input.KEYEVENTF_KEYUP


def test_send_key_hold_releases_key_on_exception(user32) -> None:
    """长按过程中抛异常也必须释放按键。"""

    def boom(seconds: float) -> None:
        raise RuntimeError("sleep 中断")

    with pytest.raises(RuntimeError):
        real_input.send_key_hold("w", 1.0, sleep=boom)
    assert user32.sent[-1]["flags"] & real_input.KEYEVENTF_KEYUP


def test_real_sender_key_combo_checks_front_each_time(recording) -> None:
    """组合键：每次发送前都要校验/置顶窗口，成功则取消置顶。"""
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.key_combo("ctrl+s")
    assert recording.events == [
        ("ensure_front", 555), ("combo", "ctrl+s"), ("release_topmost", 555),
    ]


def test_real_sender_key_combo_rejects_unknown_name_without_injecting(recording) -> None:
    """未知键名在注入之前就以可读错误拒绝（不产生任何输入）。"""
    sender = RealInputSender(555, sleep=lambda _s: None)
    with pytest.raises(WindowUnavailableError, match="无法解析"):
        sender.key_combo("ctrl+nosuchkey")
    assert ("combo", "ctrl+nosuchkey") not in recording.events


def test_real_sender_key_hold_reports_interruption(recording, caplog) -> None:
    """长按被停止请求中断：写 WARNING 日志，并按配置取消置顶。"""
    caplog.set_level("WARNING")
    recording.hold_result = (True, True)
    sender = RealInputSender(555, stop_event=None, sleep=lambda _s: None)
    sender.key_hold("w", 3.0)
    assert ("hold", "w", 3.0) in recording.events
    assert ("release_topmost", 555) in recording.events
    assert any("被停止请求中断" in record.message for record in caplog.records)


def test_dry_run_sender_logs_keyboard_without_input(caplog) -> None:
    """干跑模式：组合键与长按只写日志，零真实输入。"""
    caplog.set_level("INFO")
    sender = input_sender.DryRunSender()
    sender.key_combo("ctrl+s")
    sender.key_hold("w", 0.8)
    assert "干跑：模拟按键组合 ctrl+s" in caplog.text
    assert "干跑：模拟长按 w 持续 0.80s" in caplog.text


def test_send_key_hold_tolerates_zero_slice(user32) -> None:
    """回归（评审 P3-8）：`slice_seconds <= 0` 不能死循环（旧实现 `remaining -= 0` 永远不减）。"""
    slept: list[float] = []
    ok, interrupted = real_input.send_key_hold(
        "a", 0.05, sleep=slept.append, slice_seconds=0.0,
    )
    assert ok is True and interrupted is False
    assert slept and all(step > 0 for step in slept)       # 每次都有正的推进量
