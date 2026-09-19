"""窗口查找/置前/截图诊断（pywin32；不依赖 PySide6）。"""

import ctypes
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pywintypes
import win32con
import win32gui
import win32ui

from luoluotool.automation.elevation import is_process_elevated, is_window_elevated

logger = logging.getLogger(__name__)

PW_CLIENTONLY = 1
PW_RENDERFULLCONTENT = 2
SCREENSHOT_RETRIES = 3
SCREENSHOT_RETRY_DELAY_SECONDS = 0.5
ERROR_ACCESS_DENIED = 5


@dataclass
class DiagnosticResult:
    """窗口诊断结果：人读消息 + 是否需要管理员权限。"""

    message: str
    needs_elevation: bool = False


def find_window(keyword: str) -> int | None:
    """按标题关键字查找可见窗口；返回 hwnd（多个匹配取第一个并告警）。"""
    matches: list[int] = []

    def _collect(hwnd: int, _lparam) -> None:
        if win32gui.IsWindowVisible(hwnd) and keyword in win32gui.GetWindowText(hwnd):
            matches.append(hwnd)

    win32gui.EnumWindows(_collect, None)
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning("找到 %d 个匹配窗口，使用第一个", len(matches))
    return matches[0]


def bring_to_front(hwnd: int) -> bool:
    """恢复最小化、显示并置前窗口；返回是否成功。

    目标窗口若以更高权限运行（UIPI 隔离），会被系统拒绝（错误 5）。
    """
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
        )
        return True
    except pywintypes.error as exc:
        if getattr(exc, "winerror", None) == ERROR_ACCESS_DENIED:
            logger.warning("置前窗口被拒绝（错误 5）：目标窗口权限更高，游戏可能以管理员身份运行")
        else:
            logger.warning("置前窗口失败：%s", exc)
        return False
    except Exception as exc:
        logger.warning("置前窗口失败：%s", exc)
        return False


def get_client_rect(hwnd: int) -> tuple[int, int, int, int]:
    """返回客户区 (left, top, width, height)。"""
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    return left, top, right - left, bottom - top


def get_window_size(hwnd: int) -> tuple[int, int]:
    """返回**整个窗口**（含标题栏与边框）的 (宽, 高)。"""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return right - left, bottom - top


def client_area_offset(hwnd: int) -> tuple[int, int]:
    """客户区左上角相对**窗口**左上角的偏移（即标题栏高度 + 边框宽度）。

    取景/截图必须以它为原点取像素，否则抓到的第一行是标题栏、客户区底部会缺一截，
    识别出的坐标会整体偏下"标题栏高度"。
    实测（2026-09-20，本作窗口 1618x1070 / 客户区 1600x1024）：偏移 = (9, 37)，
    即从窗口 DC 的 (0,0) 直接抓会让坐标整体偏下 37px —— 这正是用户报告的现象。
    无边框（全屏）窗口该值为 (0, 0)，调用方据此自然退化为"不做偏移"。
    """
    window_left, window_top, _, _ = win32gui.GetWindowRect(hwnd)
    client_screen_x, client_screen_y = win32gui.ClientToScreen(hwnd, (0, 0))
    return client_screen_x - window_left, client_screen_y - window_top


def screenshot_client(hwnd: int, save_path: Path) -> Path:
    """截取客户区保存为 PNG 并返回路径。

    游戏窗口多为 GPU 渲染，BitBlt/PW_CLIENTONLY 会得到黑图；
    这里用 PW_RENDERFULLCONTENT 按窗口整体尺寸渲染（DWM 通道），
    再按客户区偏移裁出游戏画面，避免标题栏偏移与底部裁剪。
    """
    wx, wy, w_right, w_bottom = win32gui.GetWindowRect(hwnd)
    window_width, window_height = w_right - wx, w_bottom - wy
    _, _, client_width, client_height = get_client_rect(hwnd)
    offset_x, offset_y = client_area_offset(hwnd)

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    full_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    full_mem_dc = full_dc.CreateCompatibleDC()
    full_bitmap = win32ui.CreateBitmap()
    full_bitmap.CreateCompatibleBitmap(full_dc, window_width, window_height)
    full_mem_dc.SelectObject(full_bitmap)

    client_bitmap = win32ui.CreateBitmap()
    client_bitmap.CreateCompatibleBitmap(full_dc, client_width, client_height)
    client_dc = full_dc.CreateCompatibleDC()
    client_dc.SelectObject(client_bitmap)
    try:
        rendered = False
        for attempt in range(SCREENSHOT_RETRIES):
            rendered = ctypes.windll.user32.PrintWindow(
                hwnd, full_mem_dc.GetSafeHdc(), PW_RENDERFULLCONTENT
            )
            if rendered:
                break
            if attempt < SCREENSHOT_RETRIES - 1:
                time.sleep(SCREENSHOT_RETRY_DELAY_SECONDS)
        if rendered:
            # 从全窗口位图裁出客户区
            client_dc.BitBlt(
                (0, 0), (client_width, client_height),
                full_mem_dc, (offset_x, offset_y), win32con.SRCCOPY,
            )
            client_bitmap.SaveBitmapFile(client_dc, str(save_path))
            return save_path
        logger.warning("PrintWindow(全窗口) 失败，尝试仅客户区渲染")
        # 与主路径同一套几何：PrintWindow 以窗口左上角为原点，所以仍渲染到整窗位图后按偏移裁
        if ctypes.windll.user32.PrintWindow(hwnd, full_mem_dc.GetSafeHdc(), PW_CLIENTONLY):
            client_dc.BitBlt(
                (0, 0), (client_width, client_height),
                full_mem_dc, (offset_x, offset_y), win32con.SRCCOPY,
            )
            client_bitmap.SaveBitmapFile(client_dc, str(save_path))
            return save_path
        logger.warning("PrintWindow 失败，回退 BitBlt 全窗口截图")
        full_mem_dc.BitBlt(
            (0, 0), (window_width, window_height), full_dc, (0, 0), win32con.SRCCOPY
        )
        client_dc.BitBlt(
            (0, 0), (client_width, client_height),
            full_mem_dc, (offset_x, offset_y), win32con.SRCCOPY,
        )
        client_bitmap.SaveBitmapFile(client_dc, str(save_path))
        return save_path
    finally:
        win32gui.DeleteObject(client_bitmap.GetHandle())
        win32gui.DeleteObject(full_bitmap.GetHandle())
        client_dc.DeleteDC()
        full_mem_dc.DeleteDC()
        full_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)


def screenshot_path(base_dir: Path, now: datetime | None = None) -> Path:
    """生成 window_<时间戳>.png 路径（now 可注入便于测试）。"""
    return base_dir / f"window_{(now or datetime.now()):%Y%m%d%H%M%S}.png"


def diagnose_window(keyword: str, debug_dir: Path) -> DiagnosticResult:
    """查找→（权限不足先要求提权）→强制置前→截图。"""
    hwnd = find_window(keyword)
    if hwnd is None:
        return DiagnosticResult(f"未找到标题含“{keyword}”的窗口，请确认游戏已窗口化运行")
    title = win32gui.GetWindowText(hwnd)
    if not is_process_elevated() and is_window_elevated(hwnd) is True:
        # 权限不足：先请求提权，完全不触碰游戏窗口（避免恢复了窗口又被取消）
        return DiagnosticResult(
            f"游戏窗口“{title}”以管理员权限运行，本工具权限不足，无法置前/截图；"
            "请以管理员身份重启本工具后重试",
            needs_elevation=True,
        )
    denied = not bring_to_front(hwnd) and not is_process_elevated()
    if win32gui.IsIconic(hwnd):
        hint = "；游戏可能以管理员权限运行，请以管理员身份运行本工具后重试" if denied else ""
        return DiagnosticResult(
            f"窗口“{title}”仍处于最小化状态，无法截图（已尝试恢复置前{hint}）", denied
        )
    _, _, width, height = get_client_rect(hwnd)
    try:
        path = screenshot_client(hwnd, screenshot_path(debug_dir))
    except Exception as exc:
        logger.exception("截图失败")
        return DiagnosticResult(f"截图失败：{exc}（已尝试置前，请确认窗口可见）", denied)
    return DiagnosticResult(
        f"窗口诊断完成：hwnd={hwnd} 标题“{title}” 客户区 {width}x{height} 截图 {path}", denied
    )


def run_window_diagnostic(keyword: str, debug_dir: Path) -> str:
    """兼容封装：只返回诊断消息。"""
    return diagnose_window(keyword, debug_dir).message
