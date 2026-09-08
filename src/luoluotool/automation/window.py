"""窗口查找/置前/截图诊断（pywin32；不依赖 PySide6）。"""

import ctypes
import logging
import time
from datetime import datetime
from pathlib import Path

import win32con
import win32gui
import win32ui

logger = logging.getLogger(__name__)

PW_RENDERFULLCONTENT = 2
SCREENSHOT_RETRIES = 3
SCREENSHOT_RETRY_DELAY_SECONDS = 0.5


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


def bring_to_front(hwnd: int) -> None:
    """恢复最小化、显示并置前窗口（z 序置顶；尽力而为，失败仅告警）。"""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
        )
    except Exception as exc:
        logger.warning("置前窗口失败：%s", exc)


def get_client_rect(hwnd: int) -> tuple[int, int, int, int]:
    """返回客户区 (left, top, width, height)。"""
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    return left, top, right - left, bottom - top


def screenshot_client(hwnd: int, save_path: Path) -> Path:
    """截取客户区保存为 PNG 并返回路径。

    游戏窗口多为 GPU 渲染，BitBlt/PW_CLIENTONLY 会得到黑图；
    这里用 PW_RENDERFULLCONTENT 按窗口整体尺寸渲染（DWM 通道），
    再按客户区偏移裁出游戏画面，避免标题栏偏移与底部裁剪。
    """
    wx, wy, w_right, w_bottom = win32gui.GetWindowRect(hwnd)
    window_width, window_height = w_right - wx, w_bottom - wy
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    client_width, client_height = right - left, bottom - top
    client_screen_x, client_screen_y = win32gui.ClientToScreen(hwnd, (0, 0))
    offset_x, offset_y = client_screen_x - wx, client_screen_y - wy

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
        if not rendered:
            logger.warning("PrintWindow 失败，回退 BitBlt 全窗口截图")
            full_mem_dc.BitBlt(
                (0, 0), (window_width, window_height), full_dc, (0, 0), win32con.SRCCOPY
            )
        # 从全窗口位图裁出客户区
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


def run_window_diagnostic(keyword: str, debug_dir: Path) -> str:
    """查找→强制置前（恢复最小化）→截图；返回人读结果消息。"""
    hwnd = find_window(keyword)
    if hwnd is None:
        return f"未找到标题含“{keyword}”的窗口，请确认游戏已窗口化运行"
    bring_to_front(hwnd)
    if win32gui.IsIconic(hwnd):
        return f"窗口“{win32gui.GetWindowText(hwnd)}”仍处于最小化状态，无法截图（已尝试恢复置前）"
    _, _, width, height = get_client_rect(hwnd)
    try:
        path = screenshot_client(hwnd, screenshot_path(debug_dir))
    except Exception as exc:
        logger.exception("截图失败")
        return f"截图失败：{exc}（已尝试置前，请确认窗口可见）"
    title = win32gui.GetWindowText(hwnd)
    return f"窗口诊断完成：hwnd={hwnd} 标题“{title}” 客户区 {width}x{height} 截图 {path}"
