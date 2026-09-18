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

    def MapVirtualKeyW(self, vk, kind):
        self.calls.append(("MapVirtualKeyW", vk, kind))
        return 0x1E  # 任意扫描码即可（测试只关心 flags）

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


# ------------------------------------------------------------------- 发送器


class _RecordingRealInput:
    """把 real_input 的全部原语替换为记录器，验证发送器的调用顺序与守卫。"""

    def __init__(self, monkeypatch, front_ok: bool = True) -> None:
        self.events: list[tuple] = []
        self.front_results: list[bool] = []
        self.front_ok = front_ok
        self.cursor_to_restore = (800, 600)

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
        monkeypatch.setattr(real_input, "set_cursor_pos",
                            lambda x, y: self.events.append(("restore_cursor", x, y)))
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

    root = pathlib.Path(real_input.__file__).parent
    offenders = []
    for path in root.glob("*.py"):
        if path.name == "real_input.py":
            continue
        text = path.read_text(encoding="utf-8")
        for token in ("SendInput(", "SetCursorPos(", "mouse_event(", "keybd_event("):
            if token in text:
                offenders.append(f"{path.name}:{token}")
    assert offenders == [], f"这些模块不应直接调用输入注入 API：{offenders}"
