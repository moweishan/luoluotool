"""真实键鼠输入通道的**滑动**路径测试（从 `test_real_input.py` 按被测对象拆出）。

覆盖：缓出曲线与轨迹构造（`ease_out_quad` / `interpolate_points` / `build_drag_path`
的末尾静止帧）、`send_left_drag` 的分帧移动与末尾静止、松手后复查左键、任何退出路径
释放左键、每步移动失败即报错，以及 `RealInputSender.drag` 的越界跳过与
「延迟 + 分帧小步还原光标」。

全部注入假 user32：单测**零真实输入**。
"""

import ctypes
import logging

import pytest

from luoluotool.automation import input_sender, real_input
from luoluotool.automation.input_sender import RealInputSender, WindowUnavailableError

from test_automation.real_input_helpers import _FakeUser32, _capture_logs, recording, user32


# -------------------------------------- 滑动越界校验（起终点都必须在窗口内）


def test_real_sender_skips_drag_when_start_outside_window(recording, monkeypatch, caplog) -> None:
    """滑动起点越界：不滑动、不置顶、不移动光标，只写 WARNING。"""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(input_sender, "get_client_rect", lambda hwnd: (0, 0, 100, 50))
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.drag((200, 10), (50, 10), 0.2)
    assert recording.events == []
    assert "滑动起点 (200, 10) 不在游戏窗口内" in caplog.text
    assert "已跳过本次滑动" in caplog.text and "客户区 100x50" in caplog.text


def test_real_sender_skips_drag_when_end_outside_window(recording, monkeypatch, caplog) -> None:
    """滑动终点越界同样跳过（即使起点合法）。"""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(input_sender, "get_client_rect", lambda hwnd: (0, 0, 100, 50))
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.drag((50, 10), (10, 999), 0.2)
    assert recording.events == []
    assert "滑动终点 (10, 999) 不在游戏窗口内" in caplog.text


def test_real_sender_skips_drag_when_both_points_outside(recording, monkeypatch, caplog) -> None:
    """起终点都越界时，日志把两个越界点都列出来。"""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(input_sender, "get_client_rect", lambda hwnd: (0, 0, 100, 50))
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.drag((200, 10), (10, 999), 0.2)
    assert recording.events == []
    assert "起点 (200, 10)、终点 (10, 999) 不在游戏窗口内" in caplog.text


def test_real_sender_drag_inside_window_runs(recording, monkeypatch) -> None:
    """起终点都在窗口内：滑动照常执行，顺序与不带校验时一致。"""
    monkeypatch.setattr(input_sender, "get_client_rect", lambda hwnd: (0, 0, 200, 100))
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.drag((10, 20), (30, 40), 0.5)
    assert recording.events == [
        ("ensure_front", 555),
        ("get_cursor_pos",),
        ("drag", (20, 40), (40, 60), 0.5),      # 客户区 + (10,20) 偏移
        ("restore_cursor_smooth", 800, 600),
        ("release_topmost", 555),
    ]


def test_real_sender_skips_drag_when_bounds_unreadable(recording, monkeypatch, caplog) -> None:
    """读不到客户区时按越界处理：滑动也不执行。"""
    caplog.set_level(logging.WARNING)

    def boom(hwnd: int):
        raise OSError("窗口已关闭")

    monkeypatch.setattr(input_sender, "get_client_rect", boom)
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.drag((10, 10), (20, 20), 0.2)
    assert recording.events == []
    assert "不在游戏窗口内" in caplog.text and "已跳过本次滑动" in caplog.text


# ------------------------------------------------------------------- 滑动


def test_interpolate_points_is_linear_and_inclusive(user32) -> None:
    """插值纯函数：不含起点、含终点，末点必须精确落在终点。"""
    points = real_input.interpolate_points((0, 0), (100, 50), 5)
    assert len(points) == 5
    assert points[-1] == (100, 50)
    assert points[1] == (40, 20)
    # 退化情形：步数为 0/负数也要至少给一个终点
    assert real_input.interpolate_points((0, 0), (10, 10), 0) == [(10, 10)]


def test_interpolate_points_supports_easing(user32) -> None:
    """插值支持缓动：给定 easing 时按 `easing(进度)` 采样（拖动走缓出曲线）。"""
    eased = real_input.interpolate_points((0, 0), (100, 0), 4, easing=real_input.ease_out_quad)
    assert eased == [(44, 0), (75, 0), (94, 0), (100, 0)]
    assert real_input.ease_out_quad(0.0) == 0.0
    assert real_input.ease_out_quad(1.0) == 1.0


def test_send_left_drag_reports_failure_when_move_fails(user32, monkeypatch) -> None:
    """回归（评审 P3-8）：拖动中光标移动失败必须反映到返回值（旧实现忽略返回值仍可能报成功）。"""
    real_move = real_input.move_cursor_absolute
    calls = {"count": 0}

    def flaky(x, y):
        calls["count"] += 1
        if calls["count"] == 3:            # 中间某一帧移动失败
            return False
        return real_move(x, y)

    monkeypatch.setattr(real_input, "move_cursor_absolute", flaky)
    ok, interrupted = real_input.send_left_drag((0, 0), (10, 10), 0.2, sleep=lambda _s: None)

    assert ok is False
    assert interrupted is False


def test_send_left_drag_moves_in_steps_between_press_and_release(user32, monkeypatch) -> None:
    """滑动顺序：移动起点 → 按下左键 → 多次插值移动 → 抬起左键。"""
    monkeypatch.setattr(real_input, "virtual_desktop", lambda: (0, 0, 1000, 1000))
    ok, interrupted = real_input.send_left_drag((0, 0), (100, 0), 0.1, sleep=lambda _s: None)
    assert (ok, interrupted) == (True, False)
    moves = [event for event in user32.sent if event["flags"] & real_input.MOUSEEVENTF_MOVE]
    assert len(moves) >= real_input.DRAG_MIN_STEPS            # 分帧移动，不是一次瞬移
    down_index = next(i for i, e in enumerate(user32.sent) if e["flags"] & real_input.MOUSEEVENTF_LEFTDOWN)
    up_index = max(i for i, e in enumerate(user32.sent) if e["flags"] & real_input.MOUSEEVENTF_LEFTUP)
    assert down_index < up_index
    assert all(
        user32.sent[i]["flags"] & real_input.MOUSEEVENTF_MOVE for i in range(down_index + 1, up_index)
    )
    assert user32.sent[up_index]["flags"] & real_input.MOUSEEVENTF_LEFTUP


def test_send_left_drag_aborts_on_stop_and_releases_button(user32) -> None:
    """急停：滑动中途收到停止请求必须立即中断并松开左键（不卡住鼠标）。"""
    class _Stop:
        def __init__(self) -> None:
            self.calls = 0

        def is_set(self) -> bool:
            self.calls += 1
            return self.calls > 1     # 第二次检查（即滑了几帧后）触发急停

    ok, interrupted = real_input.send_left_drag((0, 0), (500, 500), 0.2, sleep=lambda _s: None,
                                               stop_event=_Stop())
    assert interrupted is True
    assert user32.sent[-1]["flags"] & real_input.MOUSEEVENTF_LEFTUP


def test_send_left_drag_releases_button_on_exception(user32) -> None:
    """滑动过程中抛异常也必须松开左键。"""
    calls = {"n": 0}

    def boom(seconds: float) -> None:
        calls["n"] += 1
        raise RuntimeError("sleep 中断")

    with pytest.raises(RuntimeError):
        real_input.send_left_drag((0, 0), (10, 10), 0.1, sleep=boom)
    assert user32.sent[-1]["flags"] & real_input.MOUSEEVENTF_LEFTUP


# ------------------------------------------------ 发送器：滑动路径与光标还原


def test_real_sender_drag_restores_cursor_after_drag(recording) -> None:
    """发送器层滑动：校验/置顶 → 记录光标 → 滑动 → **平滑还原光标** → 取消置顶。

    用户实测反馈：勾选「把真实鼠标移回原位置」后滑动结束却停在终点，因此滑动必须
    同样遵守该设置；但还原方式是"延迟 + 分帧小步"（一次跳回会被残留拖拽状态算成
    巨大位移而让画面乱飘，见 `restore_cursor_smooth`）。
    """
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.drag((10, 20), (30, 40), 0.5)
    assert recording.events == [
        ("ensure_front", 555),
        ("get_cursor_pos",),
        ("drag", (20, 40), (40, 60), 0.5),      # 客户区 + (10,20) 偏移
        ("restore_cursor_smooth", 800, 600),
        ("release_topmost", 555),
    ]
    # 必须是分帧还原，不能是一次 SetCursorPos 跳跃
    assert not any(event[0] == "restore_cursor" for event in recording.events)


def test_real_sender_drag_waits_before_restoring_cursor(recording) -> None:
    """还原光标前先等一小段：给引擎时间处理完"抬起"，避免被当成继续拖动。"""
    waits: list[float] = []
    sender = RealInputSender(555, sleep=waits.append)
    sender.drag((0, 0), (10, 10), 0.3)
    assert waits == [real_input.DRAG_RESTORE_DELAY_SECONDS]
    assert real_input.DRAG_RESTORE_DELAY_SECONDS > 0
    assert recording.events[-2][0] == "restore_cursor_smooth"


def test_real_sender_drag_restores_cursor_even_if_wait_raises(recording) -> None:
    """还原前的等待抛异常（例如急停打断）：仍必须把光标送回去。"""
    def boom(_seconds: float) -> None:
        raise RuntimeError("停止请求")

    sender = RealInputSender(555, sleep=boom)
    sender.drag((0, 0), (10, 10), 0.3)
    assert any(event[0] == "restore_cursor_smooth" for event in recording.events)
    assert recording.events[-1] == ("release_topmost", 555)


def test_real_sender_drag_keeps_cursor_when_restore_disabled(recording) -> None:
    """关闭「还原光标」时，滑动结束光标就停在终点（不做任何还原）。"""
    sender = RealInputSender(555, restore_cursor=False, sleep=lambda _s: None)
    sender.drag((0, 0), (10, 10), 0.3)
    assert not any(event[0].startswith("restore_cursor") for event in recording.events)


def test_real_sender_drag_refuses_when_window_cannot_be_focused(monkeypatch) -> None:
    """无法确保窗口在最前时绝不滑动（否则会拖到别的窗口）；失败路径同样要取消本次置顶（P1-3）。"""
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    from test_automation.real_input_helpers import _RecordingRealInput
    recording = _RecordingRealInput(monkeypatch, front_ok=False)
    sender = RealInputSender(555, sleep=lambda _s: None)
    with pytest.raises(WindowUnavailableError, match="最前"):
        sender.drag((0, 0), (10, 10), 0.3)
    assert [event[0] for event in recording.events] == ["ensure_front", "release_topmost"]


def test_real_sender_drag_logs_interruption(recording, caplog) -> None:
    """滑动被急停中断：写 WARNING 日志。"""
    caplog.set_level("WARNING")
    recording.drag_result = (True, True)
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.drag((0, 0), (10, 10), 0.3)
    assert any("被停止请求中断" in record.message for record in caplog.records)


def test_dry_run_sender_logs_drag_without_input(caplog) -> None:
    """干跑：滑动只写日志，零真实输入。"""
    caplog.set_level("INFO")
    input_sender.DryRunSender().drag((1, 2), (3, 4), 0.5)
    assert "干跑：模拟滑动 (1, 2) → (3, 4) 用时 0.50s" in caplog.text


def test_build_drag_path_is_eased_out_with_still_tail() -> None:
    """拖动轨迹：缓出（先快后慢）+ 末尾在终点保持静止若干帧（消除甩动惯性）。"""
    path = real_input.build_drag_path((0, 0), (100, 0), 10, tail_hold_steps=4)
    assert path[-1] == (100, 0)
    assert path[-4:] == [(100, 0)] * 4           # 末尾静止保持
    moves = path[:10]
    first_delta = moves[1][0] - moves[0][0]
    last_delta = moves[-1][0] - moves[-2][0]
    assert first_delta > last_delta > 0          # 减速（ease-out）
    assert moves[-1] == (100, 0)


def test_drag_pre_clears_stuck_button_before_pressing(user32, monkeypatch) -> None:
    """开始拖动前若左键是按下状态（上次异常残留），必须先补发抬起再开始。"""
    state = {"down": True}

    def fake_async(vk):
        return 0x8000 if state["down"] else 0

    def fake_send_input(count, inputs_ptr, size):
        items = ctypes.cast(inputs_ptr, ctypes.POINTER(real_input.INPUT))
        for index in range(count):
            flags = items[index].u.mi.dwFlags
            if flags & real_input.MOUSEEVENTF_LEFTUP:
                state["down"] = False
            elif flags & real_input.MOUSEEVENTF_LEFTDOWN:
                state["down"] = True
        return _FakeUser32.SendInput(user32, count, inputs_ptr, size)

    monkeypatch.setattr(user32, "GetAsyncKeyState", fake_async)
    monkeypatch.setattr(user32, "SendInput", fake_send_input)
    ok, interrupted = real_input.send_left_drag((0, 0), (10, 0), 0.05, sleep=lambda _s: None)
    assert (ok, interrupted) == (True, False)
    flags = [event["flags"] for event in user32.sent]
    assert flags.count(real_input.MOUSEEVENTF_LEFTUP) >= 2   # 预清理 + 正常松手
    assert state["down"] is False


def test_drag_reports_failure_when_button_cannot_be_released(user32, monkeypatch) -> None:
    """松手后复查仍为按下、补发也无效时：返回失败（上层抛可读错误并提示手动点击左键）。"""
    monkeypatch.setattr(user32, "GetAsyncKeyState", lambda vk: 0x8000)   # 永远"按下"
    monkeypatch.setattr(real_input, "_send", lambda inputs: True)
    monkeypatch.setattr(real_input, "move_cursor_absolute", lambda x, y: True)
    ok, _interrupted = real_input.send_left_drag((0, 0), (10, 0), 0.05, sleep=lambda _s: None)
    assert ok is False


def test_drag_path_holds_still_before_release(user32, monkeypatch) -> None:
    """松手前的最后若干次移动都停在终点（不再产生位置变化），避免被识别成甩动。"""
    monkeypatch.setattr(real_input, "virtual_desktop", lambda: (0, 0, 1000, 1000))
    real_input.send_left_drag((0, 0), (200, 100), 0.1, sleep=lambda _s: None)
    moves = [event for event in user32.sent if event["flags"] & real_input.MOUSEEVENTF_MOVE]
    # 归一化后的坐标：末尾 DRAG_TAIL_HOLD_STEPS 次移动的 dy 相同（都停在终点）
    tail = moves[-real_input.DRAG_TAIL_HOLD_STEPS:]
    assert len({(event["dx"], event["dy"]) for event in tail}) == 1
