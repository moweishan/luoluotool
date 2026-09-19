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

from luoluotool.utils.keys import (  # 键名表与组合键解析（config 层共用）
    EXTENDED_VKS,
    KEY_NAME_TO_VK,
    MODIFIER_KEYS,
    parse_combo,
)

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

# ---- 键盘：时序常量（键名表与组合键解析在 utils/keys.py，config 层也要用） ----
DRAG_STEP_SECONDS = 0.016   # 滑动插值步长（≈60Hz）
DRAG_MIN_STEPS = 4
DRAG_TAIL_HOLD_STEPS = 4    # 松手前在终点保持静止的帧数（消除"甩动惯性"导致的画面继续飘）
DRAG_PRESS_SETTLE_SECONDS = 0.05
DRAG_RELEASE_SETTLE_SECONDS = 0.06
VK_LBUTTON = 0x01
KEY_COMBO_GAP_SECONDS = 0.02
KEY_HOLD_SLICE_SECONDS = 0.1


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


def _key_input(vk: int, up: bool, scan: int | None = None) -> INPUT:
    """构造一条键盘事件（优先用扫描码；扩展键带上 EXTENDEDKEY 标志）。"""
    if scan is None:
        try:
            scan = int(user32.MapVirtualKeyW(int(vk), 0))
        except Exception as exc:
            logger.warning("MapVirtualKeyW 失败（vk=%d），回退为虚拟键码：%s", vk, exc)
            scan = 0
    flags = 0
    if scan:
        flags |= KEYEVENTF_SCANCODE
    else:
        scan = 0
    if int(vk) in EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    if up:
        flags |= KEYEVENTF_KEYUP
    item = INPUT()
    item.type = INPUT_KEYBOARD
    # 有扫描码时 wVk 传 0（与真实硬件一致）；没有扫描码时回退用虚拟键码
    item.u.ki = KEYBDINPUT(0 if scan else int(vk), scan, flags, 0, None)
    return item


def ease_out_quad(t: float) -> float:
    """缓出曲线（纯函数）：`1 - (1 - t)²`，先快后慢、终点速度为 0。"""
    return 1 - (1 - float(t)) ** 2


def interpolate_points(
    start: tuple[int, int],
    end: tuple[int, int],
    steps: int,
    easing: Callable[[float], float] | None = None,
) -> list[tuple[int, int]]:
    """纯函数：在起点与终点之间插值出 `steps` 个中间点（不含起点、含终点）。

    真实鼠标滑动必须分帧移动：一次跳跃式移动会被很多游戏识别为瞬移而不是拖拽。
    `easing` 为 None 时线性；给定时按 `easing(进度)` 采样（拖动用缓出曲线）。
    """
    count = max(int(steps), 1)
    sx, sy = int(start[0]), int(start[1])
    ex, ey = int(end[0]), int(end[1])
    points: list[tuple[int, int]] = []
    for index in range(1, count + 1):
        progress = index / count
        fraction = easing(progress) if easing is not None else progress
        points.append((round(sx + (ex - sx) * fraction), round(sy + (ey - sy) * fraction)))
    return points


def build_drag_path(
    start: tuple[int, int],
    end: tuple[int, int],
    steps: int,
    tail_hold_steps: int = DRAG_TAIL_HOLD_STEPS,
) -> list[tuple[int, int]]:
    """生成拖动轨迹（纯函数）：**缓出采样** + 末尾在终点保持静止若干帧。

    为什么要缓出 + 末尾静止：很多游戏把"匀速甩到底再松手"识别成 flick，
    松手后镜头/画面会带着惯性继续飘。减速到静止再松手，引擎才会判定为"停住后松手"。
    """
    ex, ey = int(end[0]), int(end[1])
    path = interpolate_points(start, end, max(int(steps), DRAG_MIN_STEPS), easing=ease_out_quad)
    if path:
        path[-1] = (ex, ey)             # 保证末点精确落在终点
    hold = max(int(tail_hold_steps), 0)
    path.extend([(ex, ey)] * hold)      # 末尾静止保持（松手前的"停住"）
    return path


def is_left_button_down() -> bool:
    """左键当前是否处于按下状态（用于校验拖动结束后是否真的松开了）。"""
    try:
        return bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
    except Exception as exc:      # 查询失败不影响主流程，按"未知"处理
        logger.warning("查询左键状态失败：%s", exc)
        return False


def ensure_left_button_up(attempts: int = 3, sleep: Callable[[float], None] = time.sleep) -> bool:
    """确保左键处于抬起状态：已抬起则直接返回 True；否则补发抬起并复查。

    用途：① 拖动前清理可能残留的按下状态；② 拖动后确认真的松开（避免游戏继续拖拽）。
    """
    if not is_left_button_down():
        return True
    for attempt in range(1, attempts + 1):
        logger.warning("检测到左键仍处于按下状态，补发抬起（第 %d/%d 次）", attempt, attempts)
        _send([_mouse_input(MOUSEEVENTF_LEFTUP)])
        try:
            sleep(DRAG_RELEASE_SETTLE_SECONDS)
        except Exception as exc:   # 等待被中断也不能阻止后续复查/补发
            logger.warning("等待抬起复查时被中断（继续复查）：%s", exc)
        if not is_left_button_down():
            return True
    logger.error("左键未能释放：鼠标可能卡在按下状态，请手动点击一次左键")
    return False


def send_left_drag(
    from_screen: tuple[int, int],
    to_screen: tuple[int, int],
    duration_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    stop_event: "object | None" = None,
) -> tuple[bool, bool]:
    """按住左键从 `from_screen` 滑到 `to_screen`（插值移动），返回 (是否成功, 是否被中断)。

    - 分帧插值移动（按 `duration_seconds` 均分，最少 `DRAG_MIN_STEPS` 步）；
    - 期间切片检查停止请求（急停可立刻打断）；
    - **无论正常结束、异常还是被急停打断，都会在 `finally` 释放左键**（绝不卡住鼠标按键）。
    """
    duration = max(float(duration_seconds), 0.0)
    steps = max(int(round(duration / DRAG_STEP_SECONDS)), DRAG_MIN_STEPS) if duration else DRAG_MIN_STEPS
    points = build_drag_path(from_screen, to_screen, steps)
    per_step = duration / max(len(points) - DRAG_TAIL_HOLD_STEPS, 1) if duration else 0.0
    ok = True
    interrupted = False
    try:
        # ① 开始前清理可能残留的按下状态（否则本次拖动会从"已经在拖"的状态开始）
        ensure_left_button_up(sleep=sleep)
        ok = move_cursor_absolute(*from_screen) and ok
        sleep(INPUT_SETTLE_SECONDS)
        ok = _send([_mouse_input(MOUSEEVENTF_LEFTDOWN)]) and ok
        sleep(DRAG_PRESS_SETTLE_SECONDS)      # 让引擎先注册"按下"，再从起点开始移动
        for index, point in enumerate(points):
            if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
                interrupted = True
                break
            move_cursor_absolute(*point)
            if per_step > 0 and index < len(points) - DRAG_TAIL_HOLD_STEPS:
                sleep(per_step)
            elif per_step > 0:
                sleep(DRAG_STEP_SECONDS)      # 末尾静止保持帧：只等待、不移动
    finally:
        # ② 松手前先静一下，再抬起；抬起后③复查是否真的松开（没松开就补发）。
        #    注意：等待本身抛异常（例如被中断）也**必须**继续执行抬起，绝不卡住按键。
        try:
            sleep(DRAG_RELEASE_SETTLE_SECONDS)
        except Exception as exc:
            logger.warning("松手前等待被中断，仍然执行左键抬起：%s", exc)
        ok = _send([_mouse_input(MOUSEEVENTF_LEFTUP)]) and ok
        if not ensure_left_button_up(sleep=sleep):
            ok = False
    return ok, interrupted


def send_key_down(vk: int) -> bool:
    """按下单个键（不抬起）。"""
    return _send([_key_input(int(vk), up=False)])


def send_key_up(vk: int) -> bool:
    """抬起单个键（用于长按结束/异常兜底，避免卡键）。"""
    return _send([_key_input(int(vk), up=True)])


def send_key_tap(vk: int, sleep: Callable[[float], None] = time.sleep) -> bool:
    """真实按键：用扫描码按下 → 抬起（更接近真实硬件，兼容读 GetKeyState 的游戏）。"""
    ok = send_key_down(int(vk))
    sleep(CLICK_HOLD_SECONDS)
    # 无论按下是否成功都要抬起，避免出现"卡键"
    return send_key_up(int(vk)) and ok




def send_key_combo(combo: str, sleep: Callable[[float], None] = time.sleep) -> bool:
    """发送组合键：按顺序按下修饰键 → 敲主键 → 逆序释放修饰键。"""
    modifiers, main_vk = parse_combo(combo)
    return _send_combo(modifiers, main_vk, sleep)


def _send_combo(modifiers: tuple[int, ...], main_vk: int, sleep: Callable[[float], None]) -> bool:
    """按下修饰键与主键、敲击主键、再逆序释放修饰键（异常/失败也保证释放）。"""
    pressed: list[int] = []
    ok = True
    try:
        for vk in modifiers:
            ok = send_key_down(vk) and ok
            pressed.append(vk)
            sleep(KEY_COMBO_GAP_SECONDS)
        ok = send_key_tap(main_vk, sleep) and ok
    finally:
        for vk in reversed(pressed):
            send_key_up(vk)   # 兜底释放，避免修饰键卡住
    return ok


def send_key_hold(
    combo: str,
    hold_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    stop_event: "object | None" = None,
    slice_seconds: float = KEY_HOLD_SLICE_SECONDS,
) -> tuple[bool, bool]:
    """长按组合键 `hold_seconds` 秒，返回 (是否成功, 是否被停止请求中断)。

    长按按 `slice_seconds` 切片推进，期间可被停止请求（`stop_event`）打断；
    无论正常结束、异常还是被中断，都会在 `finally` 里释放按键（绝不卡键）。
    """
    modifiers, main_vk = parse_combo(combo)
    pressed: list[int] = []
    ok = True
    interrupted = False
    try:
        for vk in modifiers:
            ok = send_key_down(vk) and ok
            pressed.append(vk)
            sleep(KEY_COMBO_GAP_SECONDS)
        ok = send_key_down(main_vk) and ok
        remaining = max(float(hold_seconds), 0.0)
        while remaining > 0:
            if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
                interrupted = True
                break
            step = min(slice_seconds, remaining)
            sleep(step)
            remaining -= step
    finally:
        send_key_up(main_vk)
        for vk in reversed(pressed):
            send_key_up(vk)
    return ok, interrupted
