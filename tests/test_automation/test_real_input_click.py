"""真实键鼠输入通道的**点击**路径测试（从 `test_real_input.py` 按被测对象拆出）。

覆盖：左键点击原语 `send_left_click`（按下 → 保持 → 抬起；长按切片检查急停；
任何退出路径都在 `finally` 抬起），`RealInputSender.click_at` 的输入时间线
（两步移动光标、按下前等待、置前后等待、延迟后分帧还原光标），以及它的失败路径
（无法置前时拒绝输入并取消本次置顶、越界 / 光标未到位时跳过）。

全部注入假 user32：单测**零真实输入**。
"""

import logging
import threading

import pytest

from luoluotool.automation import input_sender, real_input
from luoluotool.automation.input_sender import RealInputSender, WindowUnavailableError

from test_automation.real_input_helpers import (
    _RecordingRealInput,
    _capture_logs,
    recording,
    user32,
)


# ------------------------------------------------ 左键点击原语（按下 → 保持 → 抬起）


def test_send_left_click_presses_then_releases(user32) -> None:
    """左键点击：按下 + 抬起两条事件，顺序正确；默认按住 CLICK_HOLD_SECONDS。"""
    slept: list[float] = []
    real_input.send_left_click(sleep=slept.append)
    flags = [event["flags"] for event in user32.sent]
    assert flags[0] & real_input.MOUSEEVENTF_LEFTDOWN
    assert flags[1] & real_input.MOUSEEVENTF_LEFTUP
    assert slept == [real_input.CLICK_HOLD_SECONDS]


def test_send_left_click_honours_requested_hold(user32) -> None:
    """点击时长：按下后按住指定秒数再抬起（游戏吞掉瞬时点击时需要调大）。"""
    slept: list[float] = []
    assert real_input.send_left_click(sleep=slept.append, hold_seconds=0.3) is True
    flags = [event["flags"] for event in user32.sent]
    assert flags[0] & real_input.MOUSEEVENTF_LEFTDOWN and flags[1] & real_input.MOUSEEVENTF_LEFTUP
    assert abs(sum(slept) - 0.3) < 1e-6 and all(0 < s <= real_input.CLICK_SLICE_SECONDS for s in slept)


def test_send_left_click_with_zero_hold_does_not_sleep(user32) -> None:
    """点击时长 0 = 瞬时点击：按下后立刻抬起，不做任何等待。"""
    slept: list[float] = []
    real_input.send_left_click(sleep=slept.append, hold_seconds=0.0)
    assert slept == []
    assert len(user32.sent) == 2


def test_send_left_click_checks_stop_while_holding(user32) -> None:
    """长按期间收到停止请求：立刻抬起（绝不把左键卡在按下状态）。"""
    class _Stop:
        def __init__(self) -> None:
            self.checks = 0

        def is_set(self) -> bool:
            self.checks += 1
            return self.checks > 1          # 第一次允许按住，之后请求停止

    stop = _Stop()
    slept: list[float] = []
    real_input.send_left_click(sleep=slept.append, hold_seconds=1.0, stop_event=stop)
    flags = [event["flags"] for event in user32.sent]
    assert flags[-1] & real_input.MOUSEEVENTF_LEFTUP
    assert sum(slept) < 1.0                 # 被停止请求提前打断


def test_send_left_click_releases_when_sleep_raises(user32) -> None:
    """按住期间 sleep 抛异常（例如被中断）：仍必须抬起左键。"""
    def boom(_seconds: float) -> None:
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError):
        real_input.send_left_click(sleep=boom, hold_seconds=0.5)
    flags = [event["flags"] for event in user32.sent]
    assert flags[-1] & real_input.MOUSEEVENTF_LEFTUP


# ------------------------------------------------ 点击时长（按住后再松开）


def test_real_sender_passes_click_hold_to_primitive(recording) -> None:
    """点击时长一路传到 send_left_click（秒）；不传时传 None（由 real_input 用默认值）。"""
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(120, 80, hold_seconds=0.25)
    sender.click_at(120, 80)
    assert recording.click_holds == [0.25, None]


def test_real_sender_click_hold_reaches_stop_event(recording) -> None:
    """真实通道把 stop_event 传给底层：按住期间可以响应急停。"""
    stop = threading.Event()
    sender = RealInputSender(555, sleep=lambda _s: None, stop_event=stop)
    sender.click_at(120, 80, hold_seconds=0.3)
    assert recording.click_stop_events == [stop]


# ------------------------------------------------ 点击前的事实核对（区分"没送到"与"送对了但游戏不认"）


def test_real_sender_logs_click_context_before_press(recording, caplog) -> None:
    """点击前把可核对的事实写进日志：客户区尺寸、目标屏幕点、实测光标、前台/置顶、光标处窗口。

    背景（2026-09-20 实测）：玩家报"同一坐标在某页能点、另一页点不动"，而日志两边都只写"完成"，
    无法区分是输入没送出去还是游戏不认 —— 这几条事实能一眼定位。
    """
    caplog.set_level(logging.INFO)
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(120, 80)

    assert "点击前核对" in caplog.text
    assert "客户区 1920x1080" in caplog.text          # recording 夹具的假客户区
    assert "屏幕 (130, 100)" in caplog.text            # 假 client_to_screen 是 +10/+20
    assert "实测光标 (130, 100)" in caplog.text
    assert "前台是否本窗口 True" in caplog.text
    assert "UnityWndClass" in caplog.text
    assert "光标处就是本窗口 True" in caplog.text


def test_real_sender_skips_click_when_cursor_did_not_move(recording, monkeypatch, caplog) -> None:
    """光标没移到目标位置时**不点击**：宁可跳过，也不能点到别的位置（游戏里可能误触）。"""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(real_input, "move_cursor_absolute", lambda x, y: True)   # 移动"无效"
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(120, 80)

    assert ("click",) not in recording.events
    assert "未到达目标" in caplog.text and "已跳过本次点击" in caplog.text


# --------------------------- 输入时间线加固（2026-09-20："某页点不动"排查）


def test_click_moves_cursor_in_two_steps_before_press(recording) -> None:
    """点击前分两步移动光标：先到中途点、再到目标（让游戏先建立 hover 再收到按下）。

    背景：只发一次绝对跳跃时，部分 Unity 界面来不及在当帧建立 hover，随后的按下会被丢掉。
    """
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(120, 80)

    moves = [event for event in recording.events if event[0] == "move_cursor"]
    assert moves == [("move_cursor", 465, 350), ("move_cursor", 130, 100)]
    click_index = recording.events.index(("click",))
    assert recording.events.index(moves[-1]) < click_index        # 两次移动都在按下之前


def test_click_skips_intermediate_move_when_already_at_target(recording, monkeypatch) -> None:
    """光标本来就在目标上时不多发一次移动（中途点等于目标就跳过）。"""
    recording.cursor_pos = (130, 100)          # 与 fake client_to_screen 的换算结果一致
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(120, 80)

    moves = [event for event in recording.events if event[0] == "move_cursor"]
    assert moves == [("move_cursor", 130, 100)]


def test_click_waits_before_restoring_cursor(recording) -> None:
    """松手后**延迟再分帧小步**还原光标 —— 一次跳回会让游戏把这次点击当成"指针已移出窗口"。

    2026-09-20 用户实测确认：关掉「把真实鼠标移回原位置」就立刻能点动，说明就是这一步 ——
    Unity 按帧采样指针位置，处理这次点击的那一帧里指针已经跳到另一个显示器，这次点击被丢弃。
    因此还原必须是"先等 `CLICK_RESTORE_DELAY_SECONDS`，再分帧小步移回"（禁止一次 SetCursorPos）。
    """
    events: list[tuple] = []
    recording.events = events
    sender = RealInputSender(555, sleep=lambda s: events.append(("sleep", round(s, 3))))
    sender.click_at(120, 80)

    click_index = events.index(("click",))
    restore_index = next(i for i, e in enumerate(events) if e[0] == "restore_cursor_smooth")
    delays = [e[1] for e in events[click_index:restore_index] if e[0] == "sleep"]
    assert delays, "点击与还原光标之间必须有等待"
    assert max(delays) >= input_sender.CLICK_RESTORE_DELAY_SECONDS
    assert not any(e[0] == "restore_cursor" for e in events), "不得用一次跳回（SetCursorPos）还原"


def test_focus_settle_is_long_enough_for_the_game() -> None:
    """置前成功后的稳定等待必须够长（游戏被唤醒需要几帧才响应输入）。"""
    assert real_input.FRONT_SETTLE_SECONDS >= 0.2
    assert real_input.INPUT_SETTLE_SECONDS >= 0.08


def test_activate_sleeps_for_the_focus_settle(user32) -> None:
    """`_activate` 置前后会按 `FRONT_SETTLE_SECONDS` 等待（不是立刻发输入）。"""
    slept: list[float] = []
    assert real_input._activate(555, slept.append) is True
    assert slept and min(slept) >= real_input.FRONT_SETTLE_SECONDS


def test_real_sender_logs_warning_when_hit_test_is_other_window(recording, monkeypatch, caplog) -> None:
    """光标处窗口不是游戏窗口时给 WARNING（但仍点击：可能只是子窗口/别名 hwnd）。"""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(real_input, "window_under_point", lambda x, y: 999)
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(120, 80)

    assert ("click",) in recording.events          # 仍然点击（不因命中测试不同就拒绝）
    assert "光标处窗口不是本窗口" in caplog.text


# ------------------------------------------------ 点击越界校验（必须在窗口内）


def test_real_sender_skips_click_outside_window(recording, monkeypatch, caplog) -> None:
    """点击坐标必须在游戏窗口客户区内：越界时**不点击**并给出日志提示。"""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(input_sender, "get_client_rect", lambda hwnd: (0, 0, 100, 50))
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(150, 10)
    assert recording.events == []                  # 不置顶、不记录光标、不移动、不点击
    assert "不在游戏窗口内" in caplog.text
    assert "已跳过" in caplog.text and "客户区 100x50" in caplog.text


def test_real_sender_click_bounds_are_exclusive(recording, monkeypatch, caplog) -> None:
    """边界语义：客户区为 [0,width)×[0,height)，右下边界点算越界。"""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(input_sender, "get_client_rect", lambda hwnd: (0, 0, 100, 50))
    sender = RealInputSender(555, sleep=lambda _s: None)
    for x, y in ((100, 10), (10, 50), (-1, 10), (10, -1)):
        sender.click_at(x, y)
    assert recording.events == []
    assert caplog.text.count("不在游戏窗口内") == 4


def test_real_sender_clicks_inside_window(recording, monkeypatch) -> None:
    """范围内的点击照常执行：顺序一致，另加"两步移动 + 点击前核对 + 分帧还原"。"""
    monkeypatch.setattr(input_sender, "get_client_rect", lambda hwnd: (0, 0, 200, 100))
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(120, 80)
    assert recording.events == [
        ("ensure_front", 555),
        ("get_cursor_pos",),
        ("move_cursor", 465, 350),              # 两步移动的中途点
        ("move_cursor", 130, 100),              # 客户区 (120,80) + (10,20)
        ("get_cursor_pos",),                    # 点击前核对：实测光标是否到位
        ("click",),
        ("restore_cursor_smooth", 800, 600),    # 延迟后分帧小步移回
        ("release_topmost", 555),
    ]


def test_real_sender_skips_click_when_bounds_unreadable(recording, monkeypatch, caplog) -> None:
    """读不到客户区（窗口已关闭/权限不足）时按越界处理：宁可不点击。"""
    caplog.set_level(logging.WARNING)

    def boom(hwnd: int):
        raise OSError("窗口已关闭")

    monkeypatch.setattr(input_sender, "get_client_rect", boom)
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(10, 10)
    assert recording.events == []
    assert "无法读取窗口客户区" in caplog.text


# ------------------------------------------------ 发送器：点击路径与失败路径


def test_real_sender_moves_cursor_clicks_and_restores(recording) -> None:
    """点击顺序：校验/置顶 → 记录光标 → 两步移动（先中途点）→ 核对到位 → 点击 → 延迟后分帧还原 → 取消置顶。"""
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(120, 80)
    assert recording.events == [
        ("ensure_front", 555),
        ("get_cursor_pos",),                    # 记下原位置（点击后要还原）
        ("move_cursor", 465, 350),              # 两步移动的中途点：(800,600) 与 (130,100) 的中点
        ("move_cursor", 130, 100),              # 客户区 (120,80) + (10,20)
        ("get_cursor_pos",),                    # 点击前核对：实测光标是否到位
        ("click",),
        ("restore_cursor_smooth", 800, 600),    # 延迟后**分帧小步**移回（不是一次跳回）
        ("release_topmost", 555),
    ]


def test_real_sender_checks_window_front_before_every_input(recording) -> None:
    """硬规则：**每一次**点击与按键前都要重新校验窗口是否在最顶层。"""
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(10, 10)
    sender.click_at(20, 20)
    sender.key_tap(0x41)
    assert len(recording.front_results) == 3
    assert recording.events[-1] == ("release_topmost", 555)


def test_real_sender_refuses_input_when_window_cannot_be_focused(monkeypatch) -> None:
    """无法置前时绝不输入（否则会点到/敲到别的窗口）。

    回归（评审 P1-3）：**本次由我们设置的置顶必须在失败路径上取消** —— 旧实现在这里直接抛错并丢弃
    `FrontResult`，`finally` 里的 `_release_topmost_if_needed` 永远走不到，于是窗口长期浮在最上层。
    """
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    recording = _RecordingRealInput(monkeypatch, front_ok=False)
    sender = RealInputSender(555, sleep=lambda _s: None)
    with pytest.raises(WindowUnavailableError, match="置前"):
        sender.click_at(10, 10)
    assert [event[0] for event in recording.events] == ["ensure_front", "release_topmost"]
    assert ("release_topmost", 555) in recording.events


def test_real_sender_does_not_release_topmost_when_it_was_not_ours(monkeypatch) -> None:
    """失败路径只取消**本次由我们设置的**置顶：置前失败但本来就没置顶时不得误取消别人的置顶。"""
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    recording = _RecordingRealInput(monkeypatch, front_ok=False, set_topmost=False)
    sender = RealInputSender(555, sleep=lambda _s: None)
    with pytest.raises(WindowUnavailableError, match="置前"):
        sender.click_at(10, 10)
    assert [event[0] for event in recording.events] == ["ensure_front"]


def test_real_sender_refuses_when_window_not_ready(monkeypatch) -> None:
    """窗口最小化/不可见时直接拒绝（假窗口同时给出合法客户区，确保走到就绪检查）。"""
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: False)
    monkeypatch.setattr(input_sender, "get_client_rect", lambda hwnd: (0, 0, 100, 100))
    sender = RealInputSender(555, sleep=lambda _s: None)
    with pytest.raises(WindowUnavailableError):
        sender.click_at(10, 10)


def test_real_sender_keeps_cursor_when_restore_disabled(recording) -> None:
    """可配置：关闭"点击后还原光标"时不还原（光标停在目标点）——用户实测这是能点动的那一档。"""
    sender = RealInputSender(555, restore_cursor=False, sleep=lambda _s: None)
    sender.click_at(120, 80)
    assert not any(e[0].startswith("restore_cursor") for e in recording.events)
    assert ("click",) in recording.events


def test_real_sender_restores_cursor_and_releases_topmost_even_on_error(recording, monkeypatch) -> None:
    """点击抛错时也必须还原光标并取消置顶（finally）。"""

    def boom(x, y):
        raise WindowUnavailableError("点击失败")

    monkeypatch.setattr(real_input, "move_cursor_absolute", boom)
    sender = RealInputSender(555, sleep=lambda _s: None)
    with pytest.raises(WindowUnavailableError):
        sender.click_at(10, 10)
    assert ("restore_cursor_smooth", 800, 600) in recording.events   # 延迟 + 分帧小步移回
    assert ("release_topmost", 555) in recording.events


def test_real_sender_releases_topmost_when_cursor_read_raises(recording, monkeypatch) -> None:
    """回归（复核发现）：读取光标位置抛异常时，也必须取消我们设置的置顶（否则窗口长期浮在最上层）。"""

    def boom():
        raise RuntimeError("GetCursorPos 调用失败（模拟）")

    monkeypatch.setattr(real_input, "get_cursor_pos", boom)
    sender = RealInputSender(555, sleep=lambda _s: None)
    with pytest.raises(RuntimeError):
        sender.click_at(10, 10)
    assert ("release_topmost", 555) in recording.events
    assert ("restore_cursor", 800, 600) not in recording.events  # 没读到位置就不该瞎还原


def test_real_sender_move_to_never_moves_the_real_cursor(recording) -> None:
    """悬停不点击：真实输入通道下不做任何光标移动（避免无意识干扰用户）。"""
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.move_to(50, 60)
    assert recording.events == []
