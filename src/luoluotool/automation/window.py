"""窗口查找/置前/截图诊断（pywin32；不依赖 PySide6）。"""

import ctypes
import logging
from datetime import datetime
from pathlib import Path

import win32con
import win32gui
import win32ui

logger = logging.getLogger(__name__)

PRINT_WINDOW_FULL_CONTENT = 2


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
    """恢复并置前窗口（尽力而为，失败不抛异常）。"""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception as exc:
        logger.warning("置前窗口失败：%s", exc)


def get_client_rect(hwnd: int) -> tuple[int, int, int, int]:
    """返回客户区 (left, top, width, height)。"""
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    return left, top, right - left, bottom - top


def screenshot_client(hwnd: int, save_path: Path) -> Path:
    """截取客户区保存为 PNG 并返回路径；优先 PrintWindow，失败回退 BitBlt。"""
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    width, height = right - left, bottom - top
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)
    try:
        rendered = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PRINT_WINDOW_FULL_CONTENT)
        if not rendered:
            logger.warning("PrintWindow 失败，回退 BitBlt 截图")
            save_dc.BitBlt((0, 0), (width, height), mfc_dc, (left, top), win32con.SRCCOPY)
        bitmap.SaveBitmapFile(save_dc, str(save_path))
        return save_path
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)


def screenshot_path(base_dir: Path, now: datetime | None = None) -> Path:
    """生成 window_<时间戳>.png 路径（now 可注入便于测试）。"""
    return base_dir / f"window_{(now or datetime.now()):%Y%m%d%H%M%S}.png"


def run_window_diagnostic(keyword: str, debug_dir: Path) -> str:
    """查找→置前→截图；返回人读结果消息（未找到时给提示）。"""
    hwnd = find_window(keyword)
    if hwnd is None:
        return f"未找到标题含“{keyword}”的窗口，请确认游戏已窗口化运行"
    bring_to_front(hwnd)
    _, _, width, height = get_client_rect(hwnd)
    path = screenshot_client(hwnd, screenshot_path(debug_dir))
    title = win32gui.GetWindowText(hwnd)
    return f"窗口诊断完成：hwnd={hwnd} 标题“{title}” 客户区 {width}x{height} 截图 {path}"
