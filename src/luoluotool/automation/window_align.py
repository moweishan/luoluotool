"""点击前把游戏窗口对齐到真实光标下方（**不移动真实光标**）。

背景（2026-09-15 实测结论）：目标游戏（Unity 播放器）**按真实光标位置决定点击落点**，
窗口消息里的坐标会被忽略；而合成触摸/笔注入虽然点得准，却会被 Windows 抑制真实光标
（每次点击后指针消失），用户不接受。

方案：把「目标客户区坐标」搬到**静止的真实光标**底下——即移动窗口而不是移动光标——
再投递窗口消息点击，游戏按光标取点正好命中目标。真实光标全程不动、不消失。
做法参考 kotonebot 的 `windows_background` 通道（`send_message.py` 的 `_align_window`
与 `_wait_cursor_idle`），并补上它缺失的「还原窗口位置」。

安全约束：
- 只对齐窗口，绝不移动真实光标、绝不注入系统输入流；
- `SetWindowPos` 使用 `SWP_NOACTIVATE|SWP_NOZORDER|SWP_NOSIZE|SWP_NOREDRAW` 等标志，
  不抢焦点、不改 z 序、不改尺寸；
- 最大化窗口无法用 `SetWindowPos` 移动 → 上层必须拒绝并给出可读错误；
- 真实鼠标正在移动时不对齐、不点击（否则会点错位置），避免误操作。
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import win32con
import win32gui

logger = logging.getLogger(__name__)

SWP_NOSIZE = win32con.SWP_NOSIZE
SWP_NOREDRAW = win32con.SWP_NOREDRAW
SWP_NOACTIVATE = win32con.SWP_NOACTIVATE
SWP_NOZORDER = win32con.SWP_NOZORDER
SWP_NOCOPYBITS = win32con.SWP_NOCOPYBITS
SWP_NOSENDCHANGING = win32con.SWP_NOSENDCHANGING

# 对齐时用到的标志：移动位置但不改尺寸、不激活、不改 z 序、不动画/不重绘
ALIGN_FLAGS = (
    SWP_NOSIZE | SWP_NOREDRAW | SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOCOPYBITS | SWP_NOSENDCHANGING
)

CURSOR_IDLE_SPEED_PX_S = 50.0     # 与 kotonebot 的静止阈值一致
CURSOR_IDLE_TIMEOUT_SECONDS = 1.0
CURSOR_SAMPLE_SECONDS = 0.05
ALIGN_SETTLE_SECONDS = 0.05
ALIGN_TOLERANCE_PX = 1            # 对齐误差上限
CURSOR_DRIFT_TOLERANCE_PX = 2     # 对齐后光标漂移上限（超过则重新对齐）
ALIGN_MAX_ATTEMPTS = 2


def get_cursor_pos() -> tuple[int, int]:
    """读取真实光标位置（只读，不改变光标）。"""
    x, y = win32gui.GetCursorPos()
    return int(x), int(y)


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """窗口矩形（含边框），左、上、右、下。"""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return int(left), int(top), int(right), int(bottom)


def client_origin(hwnd: int) -> tuple[int, int]:
    """客户区原点在屏幕上的坐标。"""
    x, y = win32gui.ClientToScreen(hwnd, (0, 0))
    return int(x), int(y)


def is_maximized(hwnd: int) -> bool:
    """窗口是否已最大化（最大化窗口无法用 SetWindowPos 移动，必须提前拒绝）。

    pywin32 的 `win32gui` 未导出 `IsZoomed`，改用 `GetWindowPlacement` 的 showCmd。
    """
    try:
        placement = win32gui.GetWindowPlacement(hwnd)
    except Exception as exc:  # 窗口已关闭等 → 交给上层按「不可用」处理
        logger.warning("读取窗口放置状态失败（hwnd=%s）：%s", hwnd, exc)
        return False
    return int(placement[1]) == win32con.SW_SHOWMAXIMIZED


def _move_window(hwnd: int, left: int, top: int) -> bool:
    """只移动窗口左上角（不改尺寸、不激活、不改 z 序）；失败返回 False。

    注意：pywin32 的 `win32gui.SetWindowPos` **成功时返回 `None`、失败时抛异常**，
    因此不能用 `bool(...)` 判成败（否则永远为假，对齐通道会在真实窗口上必然失败）。
    """
    try:
        win32gui.SetWindowPos(hwnd, 0, int(left), int(top), 0, 0, ALIGN_FLAGS)
    except Exception as exc:  # 窗口已关闭 / 权限不足 / 句柄失效等
        logger.warning("移动窗口失败（hwnd=%s，目标位置=(%s, %s)）：%s", hwnd, left, top, exc)
        return False
    return True


def compute_window_origin(
    cursor: tuple[int, int],
    target_client: tuple[int, int],
    frame_offset: tuple[int, int],
) -> tuple[int, int]:
    """纯计算：把目标客户区坐标搬到光标下方所需的窗口左上角坐标。

    `frame_offset` = 客户区原点 - 窗口左上角（标题栏 + 边框），移动窗口时保持不变。
    """
    return (
        cursor[0] - target_client[0] - frame_offset[0],
        cursor[1] - target_client[1] - frame_offset[1],
    )


def wait_cursor_idle(
    timeout: float = CURSOR_IDLE_TIMEOUT_SECONDS,
    threshold: float = CURSOR_IDLE_SPEED_PX_S,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[bool, float]:
    """等真实光标静止（玩家手停下），返回 (是否静止, 最后一次实测速度 px/s)。

    不会移动光标、不会阻塞玩家操作：仅仅观察，直到手停下或超时。
    """
    start = clock()
    x0, y0 = get_cursor_pos()
    t0 = start
    speed = 0.0
    while clock() - start < timeout:
        sleep(CURSOR_SAMPLE_SECONDS)
        x1, y1 = get_cursor_pos()
        t1 = clock()
        elapsed = max(t1 - t0, 1e-6)
        speed = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / elapsed
        if speed <= threshold:
            return True, speed
        x0, y0, t0 = x1, y1, t1
    return False, speed


@dataclass
class AlignResult:
    """对齐结果：是否成功、误差、所用光标位置、以及对齐前的窗口矩形。"""

    aligned: bool
    error: tuple[int, int]
    cursor: tuple[int, int]
    rect_before: tuple[int, int, int, int]
    reason: str = ""
    attempts: int = field(default=1)


def align_window(
    hwnd: int,
    x: int,
    y: int,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = ALIGN_MAX_ATTEMPTS,
) -> AlignResult:
    """把客户区点 (x, y) 对齐到当前真实光标下方。

    对齐后回读客户区原点校验误差；若期间真实光标漂移，则按新光标位置重新对齐
    （最多 `attempts` 次）。返回结果里带 `rect_before`，供调用方还原窗口。
    """
    rect_before = window_rect(hwnd)
    result = AlignResult(False, (0, 0), get_cursor_pos(), rect_before, "未执行")
    for attempt in range(1, attempts + 1):
        cursor = get_cursor_pos()
        origin = client_origin(hwnd)
        offset = (origin[0] - window_rect(hwnd)[0], origin[1] - window_rect(hwnd)[1])
        left, top = compute_window_origin(cursor, (x, y), offset)
        if not _move_window(hwnd, left, top):
            return AlignResult(
                False, (0, 0), cursor, rect_before, "SetWindowPos 失败（窗口可能已最大化或已关闭）", attempt
            )
        sleep(ALIGN_SETTLE_SECONDS)
        origin_after = client_origin(hwnd)
        error = (origin_after[0] + x - cursor[0], origin_after[1] + y - cursor[1])
        drift_cursor = get_cursor_pos()
        drift = max(abs(drift_cursor[0] - cursor[0]), abs(drift_cursor[1] - cursor[1]))
        aligned = abs(error[0]) <= ALIGN_TOLERANCE_PX and abs(error[1]) <= ALIGN_TOLERANCE_PX
        if aligned and drift <= CURSOR_DRIFT_TOLERANCE_PX:
            return AlignResult(True, error, cursor, rect_before, "", attempt)
        result = AlignResult(
            False, error, drift_cursor, rect_before,
            f"对齐误差={error} 光标漂移={drift}px（已尝试 {attempt} 次）", attempt,
        )
    return result


def restore_window(
    hwnd: int,
    rect: tuple[int, int, int, int],
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """把窗口还原到对齐前的位置；返回是否精确还原。"""
    if not _move_window(hwnd, rect[0], rect[1]):
        return False
    sleep(ALIGN_SETTLE_SECONDS)
    return window_rect(hwnd)[:2] == (rect[0], rect[1])


def ensure_alignment_supported(hwnd: int) -> None:
    """对齐方案的前置条件检查；不满足时抛可读错误（绝不静默降级成错误点击）。"""
    from luoluotool.automation.input_sender import WindowUnavailableError  # 避免循环导入

    if is_maximized(hwnd):
        raise WindowUnavailableError(
            "游戏窗口已最大化：对齐窗口方案需要窗口化运行（点“还原”后重试）。"
            "若继续用普通窗口消息，本游戏会按真实光标落点点击，可能误触其他位置。"
        )
