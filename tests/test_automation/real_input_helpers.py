"""`test_real_input*.py` 共用的夹具与假结构（拆文件后仍被多个文件复用）。

筛选标准是「被 2 个以上测试文件用到」：假 `user32`（`_FakeUser32` + `user32` 夹具）、
记录型 `real_input` 替身（`_RecordingRealInput` + `recording` 夹具），以及把 `caplog`
等级统一抬到 INFO 的 autouse 夹具 `_capture_logs`（4 个测试文件都显式导入它）。
文件名不以 `test_` 开头，pytest 不会把它当测试模块收集。

全部注入假 user32：单测**零真实输入**（不会真的移动光标、不会真的按键）。
"""

import ctypes
from ctypes import wintypes

import pytest

from luoluotool.automation import input_sender, real_input


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


# ------------------------------------------------------------------- 发送器


class _RecordingRealInput:
    """把 real_input 的全部原语替换为记录器，验证发送器的调用顺序与守卫。"""

    def __init__(self, monkeypatch, front_ok: bool = True, set_topmost: bool = True) -> None:
        self.events: list[tuple] = []
        self.front_results: list[bool] = []
        self.front_ok = front_ok
        self.set_topmost = set_topmost          # 置前失败时"本次是否已由我们置顶"
        self.cursor_to_restore = (800, 600)
        self.cursor_pos = (800, 600)                    # 当前光标位置（随移动/还原更新）
        self.hold_result = (True, False)
        self.drag_result = (True, False)
        self.click_holds: list[float | None] = []       # 每次点击带的"点击时长"（秒）
        self.click_stop_events: list[object | None] = []

        def ensure_front(hwnd, log=None, sleep=None):
            self.events.append(("ensure_front", hwnd))
            self.front_results.append(self.front_ok)
            return real_input.FrontResult(
                self.front_ok, self.set_topmost, "" if self.front_ok else "无法置前"
            )

        def fake_send_left_click(sleep=None, hold_seconds=None, stop_event=None):
            self.events.append(("click",))
            self.click_holds.append(hold_seconds)
            self.click_stop_events.append(stop_event)
            return True

        def fake_get_cursor_pos():
            self.events.append(("get_cursor_pos",))
            return self.cursor_pos

        def fake_move_cursor_absolute(x, y):
            self.events.append(("move_cursor", x, y))
            self.cursor_pos = (int(x), int(y))          # 真实移动会改变光标位置
            return True

        def fake_set_cursor_pos(x, y):
            self.events.append(("restore_cursor", x, y))
            self.cursor_pos = (int(x), int(y))
            return True

        monkeypatch.setattr(real_input, "ensure_window_front", ensure_front)
        monkeypatch.setattr(real_input, "get_cursor_pos", fake_get_cursor_pos)
        monkeypatch.setattr(real_input, "move_cursor_absolute", fake_move_cursor_absolute)
        monkeypatch.setattr(real_input, "window_under_point", lambda x, y: 555)
        monkeypatch.setattr(real_input, "describe_window",
                            lambda hwnd: f"hwnd={hwnd} class='UnityWndClass' title='测试游戏'")
        # 置前校验（ensure_window_front）返回 ok=True 就意味着"已在前台且已置顶"，这里让读数一致
        monkeypatch.setattr(real_input, "is_foreground", lambda hwnd: True)
        monkeypatch.setattr(real_input, "is_topmost", lambda hwnd: True)
        monkeypatch.setattr(real_input, "send_left_click", fake_send_left_click)
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
        # 假窗口客户区 1920x1080：点击越界校验需要一个尺寸（真实实现读 GetClientRect）
        monkeypatch.setattr(input_sender, "get_client_rect", lambda hwnd: (0, 0, 1920, 1080))


@pytest.fixture
def recording(monkeypatch):
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    return _RecordingRealInput(monkeypatch)
