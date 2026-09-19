"""真实键鼠输入通道（SendInput）测试。

硬规则（用户 2026-09-16 指定）：**每次鼠标点击与键盘输入前都必须校验游戏窗口是否在最顶层，
不在最顶层时先置顶再输入**；无法确保窗口在最前时绝不输入。

全部注入假 user32：单测**零真实输入**（不会真的移动光标、不会真的按键）。
"""

import ctypes
from ctypes import wintypes

import pytest

from luoluotool.automation import input_sender, real_input
from luoluotool.automation.input_sender import RealInputSender, WindowUnavailableError


@pytest.fixture(autouse=True)
def _capture_logs(caplog):
    caplog.set_level("INFO")


# --------------------------------------------------------------------- 假 user32


class _FakeUser32:
    """记录所有调用的假 user32（含 SendInput 的 INPUT 内容）。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.sent: list[dict] = []
        self.foreground = 111  # 当前前台窗口
        self.topmost_style = 0  # 目标窗口 exstyle
        self.minimized = False
        self.set_foreground_result = 1
        self.set_window_pos_result = 1
        self.cursor = (800, 600)

    # --- 窗口状态 ---
    def GetForegroundWindow(self):
        self.calls.append(("GetForegroundWindow",))
        return self.foreground

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("SetForegroundWindow", hwnd))
        if self.set_foreground_result:
            self.foreground = hwnd
        return self.set_foreground_result

    def BringWindowToTop(self, hwnd):
        self.calls.append(("BringWindowToTop", hwnd))
        return 1

    def ShowWindow(self, hwnd, cmd):
        self.calls.append(("ShowWindow", hwnd, cmd))
        self.minimized = False
        return 1

    def IsIconic(self, hwnd):
        self.calls.append(("IsIconic", hwnd))
        return int(self.minimized)

    def GetAsyncKeyState(self, vk):
        """默认左键未按下；具体测试可覆盖它以模拟"卡住"或"已松开"。"""
        self.calls.append(("GetAsyncKeyState", vk))
        return 0

    def MapVirtualKeyW(self, vk, kind):
        """返回确定性伪扫描码（vk & 0xFF），便于测试按扫描码断言按键身份。

        真实系统中扫描码由 Windows 提供，且扫描码路径下 wVk 按硬件语义填 0。
        """
        self.calls.append(("MapVirtualKeyW", vk, kind))
        return int(vk) & 0xFF

    def GetWindowLongPtrW(self, hwnd, index):
        self.calls.append(("GetWindowLongPtrW", hwnd, index))
        return self.topmost_style

    def AttachThreadInput(self, source, target, attach):
        self.calls.append(("AttachThreadInput", source, target, attach))
        return 1

    def GetWindowThreadProcessId(self, hwnd, pid_ptr):
        self.calls.append(("GetWindowThreadProcessId", hwnd))
        return 4242

    def GetCurrentThreadId(self):
        self.calls.append(("GetCurrentThreadId",))
        return 4242

    def GetCursorPos(self, ptr):
        ctypes.cast(ptr, ctypes.POINTER(wintypes.POINT)).contents = wintypes.POINT(*self.cursor)
        self.calls.append(("GetCursorPos",))
        return 1

    def SetCursorPos(self, x, y):
        self.calls.append(("SetCursorPos", x, y))
        self.cursor = (x, y)
        return 1

    def SendInput(self, count, inputs_ptr, size):
        self.calls.append(("SendInput", count))
        items = ctypes.cast(inputs_ptr, ctypes.POINTER(real_input.INPUT))
        for index in range(count):
            item = items[index]
            if item.type == real_input.INPUT_MOUSE:
                self.sent.append({"type": item.type, "flags": item.u.mi.dwFlags,
                                  "dx": item.u.mi.dx, "dy": item.u.mi.dy, "scan": 0, "vk": 0})
            else:  # 键盘事件必须读 ki 分支（union 读错字段会得到 0）
                self.sent.append({"type": item.type, "flags": item.u.ki.dwFlags,
                                  "dx": 0, "dy": 0, "scan": item.u.ki.wScan, "vk": item.u.ki.wVk})
        return count

    def GetSystemMetrics(self, index):
        return {76: 0, 77: 0, 78: 3840, 79: 1080}.get(index, 0)


@pytest.fixture
def user32(monkeypatch):
    fake = _FakeUser32()
    monkeypatch.setattr(real_input, "user32", fake)
    monkeypatch.setattr(real_input, "_get_window_long", lambda hwnd, index: fake.GetWindowLongPtrW(hwnd, index))

    def fake_set_window_pos(hwnd, insert_after, flags):
        """模拟 pywin32 的 z 序调整：记录调用并按需成功/失败。"""
        fake.calls.append(("SetWindowPos", hwnd, insert_after, flags))
        if not fake.set_window_pos_result:
            return False
        if insert_after == real_input.HWND_TOPMOST:
            fake.topmost_style = real_input.WS_EX_TOPMOST
        elif insert_after == real_input.HWND_NOTOPMOST:
            fake.topmost_style = 0
        return True

    monkeypatch.setattr(real_input, "_set_window_pos", fake_set_window_pos)
    return fake


def test_set_window_pos_wrapper_treats_pywin32_none_as_success(monkeypatch) -> None:
    """回归：pywin32 的 SetWindowPos 成功返回 None、失败抛异常，不能按返回值判成败。"""
    calls: list[tuple] = []

    def fake(hwnd, insert_after, x, y, cx, cy, flags):
        calls.append((hwnd, insert_after, flags))
        return None

    monkeypatch.setattr(real_input.win32gui, "SetWindowPos", fake)
    assert real_input._set_window_pos(555, real_input.HWND_TOPMOST, real_input.TOP_FLAGS) is True
    assert calls == [(555, real_input.HWND_TOPMOST, real_input.TOP_FLAGS)]


def test_set_window_pos_wrapper_reports_exception_as_failure(monkeypatch) -> None:
    """pywin32 抛异常（句柄失效/拒绝访问）时必须返回 False。"""

    def boom(*args, **kwargs):
        raise OSError("拒绝访问（5）")

    monkeypatch.setattr(real_input.win32gui, "SetWindowPos", boom)
    assert real_input._set_window_pos(555, real_input.HWND_TOPMOST, real_input.TOP_FLAGS) is False


# --------------------------------------------------------- ensure_window_front


def test_ensure_window_front_sets_topmost_and_foreground_when_not_front(user32) -> None:
    """不在最前/最顶层时：先恢复（若最小化）→ 置顶 → 置前，并报告"本次是我们置的顶"。"""
    user32.foreground = 999  # 别的窗口在前台
    result = real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert result.ok is True
    assert result.set_topmost is True
    kinds = [call[0] for call in user32.calls]
    assert "SetWindowPos" in kinds and "SetForegroundWindow" in kinds
    assert kinds.index("SetWindowPos") < kinds.index("SetForegroundWindow")


def test_ensure_window_front_restores_minimized_window_first(user32) -> None:
    """最小化的窗口无法接收输入：必须先 SW_RESTORE。"""
    user32.minimized = True
    user32.foreground = 999
    real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert ("ShowWindow", 555, real_input.SW_RESTORE) in user32.calls


def test_ensure_window_front_is_noop_when_already_front_and_topmost(user32) -> None:
    """已经在前台且已置顶：不再做任何窗口操作（不打扰用户）。"""
    user32.foreground = 555
    user32.topmost_style = real_input.WS_EX_TOPMOST
    result = real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert result.ok is True
    assert result.set_topmost is False
    kinds = [call[0] for call in user32.calls]
    assert "SetWindowPos" not in kinds
    assert "SetForegroundWindow" not in kinds


def test_ensure_window_front_sets_foreground_when_only_topmost(user32) -> None:
    """已置顶但不在前台（键盘收不到）：仍需置前。"""
    user32.foreground = 999
    user32.topmost_style = real_input.WS_EX_TOPMOST
    result = real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert result.ok is True
    assert result.set_topmost is False  # 顶层本来就是它，不需要我们改
    assert ("SetForegroundWindow", 555) in user32.calls


def test_ensure_window_front_uses_attach_thread_input_fallback(user32) -> None:
    """前台锁定导致 SetForegroundWindow 无效时，用 AttachThreadInput 兜底。"""
    user32.foreground = 999
    user32.set_foreground_result = 0  # 直接置前失败

    real_calls: list[str] = []
    original_attach = user32.AttachThreadInput

    def attach_and_report(source, target, attach):
        if attach:  # 只统计"附加"这一次（解除附加不该计数）
            real_calls.append("attach")
            user32.foreground = 555  # 兜底成功
        return original_attach(source, target, attach)

    user32.AttachThreadInput = attach_and_report
    result = real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert result.ok is True
    assert real_calls == ["attach"]


def test_ensure_window_front_fails_with_readable_reason(user32) -> None:
    """无法把窗口置前时必须报告失败（调用方据此拒绝输入），而不是硬着头皮点。"""
    user32.foreground = 999
    user32.set_foreground_result = 0
    result = real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert result.ok is False
    assert "置前" in result.reason or "最前" in result.reason


def test_release_topmost_clears_flag(user32) -> None:
    """输入结束后取消 TOPMOST，避免游戏窗口长期浮在所有窗口之上。"""
    user32.topmost_style = real_input.WS_EX_TOPMOST
    assert real_input.release_topmost(555) is True
    assert user32.topmost_style == 0


def test_release_topmost_skips_when_not_topmost(user32) -> None:
    """本来就不是 TOPMOST：不做任何窗口操作。"""
    user32.topmost_style = 0
    real_input.release_topmost(555)
    assert ("SetWindowPos", 555, real_input.HWND_NOTOPMOST, real_input.RELEASE_FLAGS) not in user32.calls


# --------------------------------------------------------------- 输入原语


def test_normalize_absolute_maps_virtual_desktop() -> None:
    """绝对坐标归一化：0..65535 对应虚拟桌面范围。"""
    assert real_input.normalize_absolute(0, 0, (0, 0, 1920, 1080)) == (0, 0)
    assert real_input.normalize_absolute(1919, 1079, (0, 0, 1920, 1080)) == (65535, 65535)
    # 多显示器（虚拟桌面以负坐标起始）也要正确
    nx, ny = real_input.normalize_absolute(0, 0, (-1920, 0, 3840, 1080))
    assert 32000 < nx < 33500 and ny == 0


def test_move_cursor_absolute_sends_single_move_event(user32) -> None:
    """移动真实光标：一次 MOUSEEVENTF_MOVE|ABSOLUTE|VIRTUALDESK，不带按键。"""
    real_input.move_cursor_absolute(700, 500)
    assert len(user32.sent) == 1
    event = user32.sent[0]
    assert event["flags"] & real_input.MOUSEEVENTF_MOVE
    assert event["flags"] & real_input.MOUSEEVENTF_ABSOLUTE
    assert event["flags"] & real_input.MOUSEEVENTF_VIRTUALDESK
    assert not event["flags"] & real_input.MOUSEEVENTF_LEFTDOWN


def test_send_left_click_presses_then_releases(user32) -> None:
    """左键点击：按下 + 抬起两条事件，顺序正确。"""
    real_input.send_left_click(sleep=lambda _s: None)
    flags = [event["flags"] for event in user32.sent]
    assert flags[0] & real_input.MOUSEEVENTF_LEFTDOWN
    assert flags[1] & real_input.MOUSEEVENTF_LEFTUP


def test_send_key_tap_uses_scancode_down_then_up(user32) -> None:
    """键盘：用扫描码（更接近真实硬件、兼容读 GetKeyState 的游戏），先按下后抬起。"""
    real_input.send_key_tap(0x41, sleep=lambda _s: None)  # 'A'
    assert len(user32.sent) == 2
    down, up = user32.sent
    assert down["type"] == real_input.INPUT_KEYBOARD and up["type"] == real_input.INPUT_KEYBOARD
    assert down["flags"] & real_input.KEYEVENTF_SCANCODE
    assert not down["flags"] & real_input.KEYEVENTF_KEYUP
    assert up["flags"] & real_input.KEYEVENTF_KEYUP


def test_set_cursor_pos_clamps_into_virtual_desktop(user32) -> None:
    """还原光标位置：直接 SetCursorPos（不需要按下抬起语义）。"""
    real_input.set_cursor_pos(321, 654)
    assert ("SetCursorPos", 321, 654) in user32.calls


def test_restore_cursor_smooth_moves_in_small_steps(user32, monkeypatch) -> None:
    """平滑还原光标：分帧小步移回（不是一次跳跃），末点精确落在目标位置。"""
    moves: list[tuple[int, int]] = []
    monkeypatch.setattr(real_input, "get_cursor_pos", lambda: (800, 600))
    monkeypatch.setattr(real_input, "move_cursor_absolute",
                        lambda x, y: (moves.append((x, y)), True)[1])
    assert real_input.restore_cursor_smooth((100, 300), sleep=lambda _s: None) is True
    assert len(moves) == real_input.DRAG_RESTORE_MAX_STEPS >= 4   # 多步，不是一次跳跃
    assert moves[0] != (100, 300)                                 # 第一步不跳到位
    assert moves[-1] == (100, 300)                                # 末点精确
    assert all(call[0] != "SetCursorPos" for call in user32.calls)  # 不用跳跃式复位


def test_restore_cursor_smooth_skips_when_already_at_target(user32, monkeypatch) -> None:
    """光标已经在目标位置：不产生任何移动。"""
    moves: list[tuple[int, int]] = []
    monkeypatch.setattr(real_input, "get_cursor_pos", lambda: (100, 300))
    monkeypatch.setattr(real_input, "move_cursor_absolute",
                        lambda x, y: moves.append((x, y)) or True)
    assert real_input.restore_cursor_smooth((100, 300), sleep=lambda _s: None) is True
    assert moves == []


def test_restore_cursor_smooth_survives_sleep_interruption(user32, monkeypatch) -> None:
    """还原过程中的等待抛异常（例如急停）：仍要把光标送回去。"""
    moves: list[tuple[int, int]] = []
    monkeypatch.setattr(real_input, "get_cursor_pos", lambda: (800, 600))
    monkeypatch.setattr(real_input, "move_cursor_absolute",
                        lambda x, y: moves.append((x, y)) or True)

    def boom(_seconds: float) -> None:
        raise RuntimeError("停止请求")

    assert real_input.restore_cursor_smooth((100, 300), sleep=boom) is True
    assert moves[-1] == (100, 300)


def test_restore_cursor_smooth_falls_back_when_read_fails(user32, monkeypatch) -> None:
    """读光标位置失败：退回 `SetCursorPos` 直接复位（不静默什么都不做）。"""
    def boom() -> tuple[int, int]:
        raise RuntimeError("读不到光标")

    monkeypatch.setattr(real_input, "get_cursor_pos", boom)
    assert real_input.restore_cursor_smooth((444, 555), sleep=lambda _s: None) is True
    assert ("SetCursorPos", 444, 555) in user32.calls


# ------------------------------------------------------------------- 发送器


class _RecordingRealInput:
    """把 real_input 的全部原语替换为记录器，验证发送器的调用顺序与守卫。"""

    def __init__(self, monkeypatch, front_ok: bool = True) -> None:
        self.events: list[tuple] = []
        self.front_results: list[bool] = []
        self.front_ok = front_ok
        self.cursor_to_restore = (800, 600)
        self.hold_result = (True, False)
        self.drag_result = (True, False)

        def ensure_front(hwnd, log=None, sleep=None):
            self.events.append(("ensure_front", hwnd))
            self.front_results.append(self.front_ok)
            return real_input.FrontResult(self.front_ok, True, "" if self.front_ok else "无法置前")

        monkeypatch.setattr(real_input, "ensure_window_front", ensure_front)
        monkeypatch.setattr(real_input, "get_cursor_pos",
                            lambda: (self.events.append(("get_cursor_pos",)), self.cursor_to_restore)[1])
        monkeypatch.setattr(real_input, "move_cursor_absolute",
                            lambda x, y: self.events.append(("move_cursor", x, y)))
        monkeypatch.setattr(real_input, "send_left_click",
                            lambda sleep=None: self.events.append(("click",)) or True)
        monkeypatch.setattr(real_input, "send_key_tap",
                            lambda vk, sleep=None: self.events.append(("key", vk)) or True)
        monkeypatch.setattr(real_input, "send_left_drag",
                            lambda start, end, duration, sleep=None, stop_event=None:
                            self.events.append(("drag", start, end, round(duration, 3)))
                            or self.drag_result)
        monkeypatch.setattr(real_input, "send_key_combo",
                            lambda combo, sleep=None: self.events.append(("combo", combo)) or True)
        monkeypatch.setattr(real_input, "send_key_hold",
                            lambda combo, seconds, sleep=None, stop_event=None, slice_seconds=0.1:
                            self.events.append(("hold", combo, round(seconds, 3)))
                            or self.hold_result)
        monkeypatch.setattr(real_input, "set_cursor_pos",
                            lambda x, y: self.events.append(("restore_cursor", x, y)))
        monkeypatch.setattr(real_input, "restore_cursor_smooth",
                            lambda target, sleep=None, **kwargs:
                            self.events.append(("restore_cursor_smooth", target[0], target[1])) or True)
        monkeypatch.setattr(real_input, "release_topmost",
                            lambda hwnd: self.events.append(("release_topmost", hwnd)) or True)
        monkeypatch.setattr(real_input, "client_to_screen",
                            lambda hwnd, point: (point[0] + 10, point[1] + 20))


@pytest.fixture
def recording(monkeypatch):
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    return _RecordingRealInput(monkeypatch)


def test_real_sender_moves_cursor_clicks_and_restores(recording) -> None:
    """点击顺序：校验/置顶 → 记录光标 → 移动光标 → 点击 → 还原光标 → 取消置顶。"""
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.click_at(120, 80)
    assert recording.events == [
        ("ensure_front", 555),
        ("get_cursor_pos",),
        ("move_cursor", 130, 100),   # 客户区 (120,80) + (10,20)
        ("click",),
        ("restore_cursor", 800, 600),
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
    """无法置前时绝不输入（否则会点到/敲到别的窗口）。"""
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    recording = _RecordingRealInput(monkeypatch, front_ok=False)
    sender = RealInputSender(555, sleep=lambda _s: None)
    with pytest.raises(WindowUnavailableError, match="置前"):
        sender.click_at(10, 10)
    assert all(event[0] in ("ensure_front",) for event in recording.events)


def test_real_sender_refuses_when_window_not_ready(monkeypatch) -> None:
    """窗口最小化/不可见时直接拒绝。"""
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: False)
    sender = RealInputSender(555, sleep=lambda _s: None)
    with pytest.raises(WindowUnavailableError):
        sender.click_at(10, 10)


def test_real_sender_keeps_cursor_when_restore_disabled(recording) -> None:
    """可配置：关闭"点击后还原光标"时不还原（光标停在目标点）。"""
    sender = RealInputSender(555, restore_cursor=False, sleep=lambda _s: None)
    sender.click_at(120, 80)
    assert ("restore_cursor", 800, 600) not in recording.events
    assert ("click",) in recording.events


def test_real_sender_restores_cursor_and_releases_topmost_even_on_error(recording, monkeypatch) -> None:
    """点击抛错时也必须还原光标并取消置顶（finally）。"""

    def boom(x, y):
        raise WindowUnavailableError("点击失败")

    monkeypatch.setattr(real_input, "move_cursor_absolute", boom)
    sender = RealInputSender(555, sleep=lambda _s: None)
    with pytest.raises(WindowUnavailableError):
        sender.click_at(10, 10)
    assert ("restore_cursor", 800, 600) in recording.events
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


def test_real_sender_key_tap_checks_front_and_releases(recording) -> None:
    """按键：校验/置顶 → 发扫描码 → 取消置顶。"""
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.key_tap(0x1B)  # ESC
    assert recording.events == [
        ("ensure_front", 555),
        ("key", 0x1B),
        ("release_topmost", 555),
    ]


def test_real_sender_move_to_never_moves_the_real_cursor(recording) -> None:
    """悬停不点击：真实输入通道下不做任何光标移动（避免无意识干扰用户）。"""
    sender = RealInputSender(555, sleep=lambda _s: None)
    sender.move_to(50, 60)
    assert recording.events == []


def test_build_channel_uses_real_input_in_real_mode(monkeypatch) -> None:
    """真实模式（dry_run=False）下通道固定使用 RealInputSender（唯一保留的实现方式）。"""
    import threading

    from luoluotool.config.models import AppConfig

    monkeypatch.setattr(input_sender, "find_window", lambda keyword: 777)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    config = AppConfig.default()
    config.automation.dry_run = False
    config.automation.restore_cursor_after_click = False
    channel = input_sender.build_channel(config, threading.Event(), lambda _s: None)
    assert isinstance(channel.sender, RealInputSender)
    assert channel.sender.restore_cursor is False
    assert channel.readiness is not None


def test_sendinput_is_confined_to_real_input_module() -> None:
    """架构约束：输入注入 API 只能出现在 real_input 模块里（便于审计与回归）。"""
    import pathlib

    src_root = pathlib.Path(real_input.__file__).resolve().parents[1]  # src/luoluotool
    offenders = []
    for path in src_root.rglob("*.py"):
        if path.name == "real_input.py":
            continue
        text = path.read_text(encoding="utf-8")
        for token in ("SendInput(", "SetCursorPos(", "mouse_event(", "keybd_event("):
            if token in text:
                offenders.append(f"{path.name}:{token}")
    assert offenders == [], f"这些模块不应直接调用输入注入 API：{offenders}"


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
    """无法确保窗口在最前时绝不滑动（否则会拖到别的窗口）。"""
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    from tests.test_automation.test_real_input import _RecordingRealInput
    recording = _RecordingRealInput(monkeypatch, front_ok=False)
    sender = RealInputSender(555, sleep=lambda _s: None)
    with pytest.raises(WindowUnavailableError, match="最前"):
        sender.drag((0, 0), (10, 10), 0.3)
    assert all(event[0] == "ensure_front" for event in recording.events)


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
