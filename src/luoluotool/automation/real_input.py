"""真实键鼠输入：`SendInput` 移动真实光标 + 模拟真实鼠标/键盘（用户 2026-09-16 选定方案）。

硬规则（**每次**输入前都必须执行，用户明确要求）：

1. 校验游戏窗口是否在最顶层；不在则**先置顶**（`HWND_TOPMOST`）**再置前**（`SetForegroundWindow`）；
2. 无法确保窗口在最前时**绝不输入**（返回 `FrontResult.ok=False`，由上层抛可读错误）；
3. 输入结束后取消**本次由我们设置**的 TOPMOST，避免游戏窗口长期浮在所有窗口之上。

与已撤回的合成指针通道的区别（用户已知情并选择）：本通道**会移动真实光标**（点击后按配置还原），
但不会让系统隐藏指针；代价是输入期间会**抢前台**，因此运行时不宜同时操作其它软件。
"""

import ctypes
import logging
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

import win32con
import win32gui

logger = logging.getLogger(__name__)

# ctypes 入口集中在这里（测试会整体替换为假实现，保证单测零真实输入）
user32 = ctypes.windll.user32

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
SW_RESTORE = 9
HWND_TOPMOST = win32con.HWND_TOPMOST
HWND_NOTOPMOST = win32con.HWND_NOTOPMOST
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
TOP_FLAGS = SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW | SWP_NOACTIVATE
RELEASE_FLAGS = SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW | SWP_NOACTIVATE
CLICK_HOLD_SECONDS = 0.04
INPUT_SETTLE_SECONDS = 0.05
FRONT_SETTLE_SECONDS = 0.05
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


@dataclass
class FrontResult:
    """「把窗口置于最前」的结果：是否成功、以及本次是否由我们设置了 TOPMOST。"""

    ok: bool
    set_topmost: bool = False
    reason: str = ""


# ------------------------------------------------------------------ 窗口状态与置前


def _get_window_long(hwnd: int, index: int) -> int:
    """读取窗口扩展样式（单独抽出，便于测试注入假实现）。"""
    try:
        return int(win32gui.GetWindowLong(hwnd, index) or 0)
    except Exception as exc:
        logger.warning("读取窗口样式失败（hwnd=%s）：%s", hwnd, exc)
        return 0


def _set_window_pos(hwnd: int, insert_after: int, flags: int) -> bool:
    """调整窗口 z 序（置顶/取消置顶）。

    注意：pywin32 的 `win32gui.SetWindowPos` **成功返回 None、失败抛异常**，
    不能按返回值判成败（Phase 5.2 曾因此踩坑）。
    """
    try:
        win32gui.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags)
    except Exception as exc:
        logger.warning("调整窗口置顶状态失败（hwnd=%s，insert_after=%s）：%s", hwnd, insert_after, exc)
        return False
    return True


def is_topmost(hwnd: int) -> bool:
    """窗口当前是否带 WS_EX_TOPMOST。"""
    return bool(_get_window_long(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def is_foreground(hwnd: int) -> bool:
    """窗口是否为当前前台窗口（键盘输入只会送到前台窗口）。"""
    return int(user32.GetForegroundWindow() or 0) == int(hwnd)


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


def client_to_screen(hwnd: int, point: tuple[int, int]) -> tuple[int, int]:
    """客户区坐标 → 屏幕坐标。"""
    x, y = win32gui.ClientToScreen(hwnd, (int(point[0]), int(point[1])))
    return int(x), int(y)


def release_topmost(hwnd: int) -> bool:
    """取消 TOPMOST（仅当当前确实置顶）；返回是否真的做了取消操作。"""
    if not is_topmost(hwnd):
        return False
    if _set_window_pos(hwnd, HWND_NOTOPMOST, RELEASE_FLAGS):
        logger.debug("已取消窗口置顶（hwnd=%s）", hwnd)
        return True
    logger.warning("取消窗口置顶失败（hwnd=%s），窗口可能仍浮在最上层", hwnd)
    return False


def _activate(hwnd: int, sleep: Callable[[float], None]) -> bool:
    """置前（SetForegroundWindow，失败时用 AttachThreadInput 兜底）。"""
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception as exc:
        logger.warning("SetForegroundWindow 调用异常（hwnd=%s）：%s", hwnd, exc)
    sleep(FRONT_SETTLE_SECONDS)
    if is_foreground(hwnd):
        return True
    foreground = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
    our_thread = user32.GetCurrentThreadId()
    attached = False
    try:
        attached = bool(user32.AttachThreadInput(our_thread, foreground_thread, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    except Exception as exc:
        logger.warning("AttachThreadInput 兜底置前失败（hwnd=%s）：%s", hwnd, exc)
    finally:
        if attached:
            try:
                user32.AttachThreadInput(our_thread, foreground_thread, False)
            except Exception as exc:
                logger.warning("解除线程输入附加失败：%s", exc)
    sleep(FRONT_SETTLE_SECONDS)
    return is_foreground(hwnd)


def ensure_window_front(
    hwnd: int,
    log: logging.Logger | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> FrontResult:
    """每次输入前的硬校验：确保游戏窗口在最顶层并处于前台。

    - 最小化 → 先 `SW_RESTORE`；
    - 未置顶 → `HWND_TOPMOST`；
    - 不在前台 → `SetForegroundWindow`（必要时 AttachThreadInput 兜底）；
    - 仍不在前台 → 返回 `ok=False` 并把原因交给上层（**绝不带着错误状态输入**）。
    """
    log = log or logger
    if is_minimized(hwnd):
        log.info("游戏窗口已最小化，先恢复窗口再输入")
        try:
            user32.ShowWindow(hwnd, SW_RESTORE)
        except Exception as exc:
            log.warning("恢复最小化窗口失败：%s", exc)
        sleep(FRONT_SETTLE_SECONDS)

    set_topmost = False
    if not is_topmost(hwnd):
        if _set_window_pos(hwnd, HWND_TOPMOST, TOP_FLAGS):
            set_topmost = True
            log.info("游戏窗口不在最顶层，已置顶（输入结束后会取消置顶）")
            sleep(FRONT_SETTLE_SECONDS)
        else:
            log.warning("游戏窗口置顶失败，仍尝试置前")

    if not is_foreground(hwnd):
        log.info("游戏窗口不在前台，正在置前（真实键鼠输入只能送到前台窗口）")
        _activate(hwnd, sleep)

    if not is_foreground(hwnd):
        return FrontResult(
            False, set_topmost,
            "无法把游戏窗口置于最前（前台被其它程序占用或 SetForegroundWindow 被系统拒绝）",
        )
    return FrontResult(True, set_topmost)


# ---------------------------------------------------------------------- 输入原语


def virtual_desktop() -> tuple[int, int, int, int]:
    """虚拟桌面矩形（多显示器下的绝对坐标基准）。"""
    return (
        int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    )


def normalize_absolute(x: int, y: int, desktop: tuple[int, int, int, int]) -> tuple[int, int]:
    """把屏幕坐标归一化为 0..65535（SendInput 绝对坐标要求），并夹到合法范围。"""
    left, top, width, height = desktop
    nx = int(round((x - left) * 65535 / max(width - 1, 1)))
    ny = int(round((y - top) * 65535 / max(height - 1, 1)))
    return max(0, min(65535, nx)), max(0, min(65535, ny))


def _send(inputs: list[INPUT]) -> bool:
    """调用 SendInput 发送一批事件；返回是否全部被系统接受。"""
    count = len(inputs)
    array = (INPUT * count)(*inputs)
    try:
        sent = int(user32.SendInput(count, ctypes.byref(array), ctypes.sizeof(INPUT)) or 0)
    except Exception as exc:
        logger.exception("SendInput 调用异常：%s", exc)
        return False
    if sent != count:
        logger.warning("SendInput 未全部被接受（发送 %d，系统接受 %d）", count, sent)
        return False
    return True


def _mouse_input(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    item = INPUT()
    item.type = INPUT_MOUSE
    item.u.mi = MOUSEINPUT(int(dx), int(dy), 0, int(flags), 0, None)
    return item


def get_cursor_pos() -> tuple[int, int]:
    """读取真实光标位置（只读，不改变光标）。"""
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return int(point.x), int(point.y)


def set_cursor_pos(x: int, y: int) -> bool:
    """把真实光标还原到指定位置。"""
    try:
        return bool(user32.SetCursorPos(int(x), int(y)))
    except Exception as exc:
        logger.warning("还原光标位置失败（%s, %s）：%s", x, y, exc)
        return False


def move_cursor_absolute(x: int, y: int) -> bool:
    """把真实光标移动到屏幕坐标 (x, y)（绝对移动，不按键）。"""
    nx, ny = normalize_absolute(int(x), int(y), virtual_desktop())
    return _send([_mouse_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny)])


def send_left_click(sleep: Callable[[float], None] = time.sleep) -> bool:
    """真实左键点击：按下 → 短暂保持 → 抬起。"""
    ok = _send([_mouse_input(MOUSEEVENTF_LEFTDOWN)])
    sleep(CLICK_HOLD_SECONDS)
    ok = _send([_mouse_input(MOUSEEVENTF_LEFTUP)]) and ok
    return ok


def send_key_tap(vk: int, sleep: Callable[[float], None] = time.sleep) -> bool:
    """真实按键：用扫描码按下 → 抬起（更接近真实硬件，兼容读 GetKeyState 的游戏）。"""
    try:
        scan = int(user32.MapVirtualKeyW(int(vk), 0))
    except Exception as exc:
        logger.warning("MapVirtualKeyW 失败（vk=%d），回退为虚拟键码：%s", vk, exc)
        scan = 0
    if scan:
        down_flags, up_flags = KEYEVENTF_SCANCODE, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
    else:
        down_flags, up_flags = 0, KEYEVENTF_KEYUP
    down, up = INPUT(), INPUT()
    down.type = INPUT_KEYBOARD
    down.u.ki = KEYBDINPUT(0, scan, down_flags, 0, None)
    up.type = INPUT_KEYBOARD
    up.u.ki = KEYBDINPUT(0, scan, up_flags, 0, None)
    ok = _send([down])
    sleep(CLICK_HOLD_SECONDS)
    # 无论按下是否成功都要抬起，避免出现"卡键"
    ok = _send([up]) and ok
    return ok
