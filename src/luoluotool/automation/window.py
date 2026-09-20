"""窗口查找/置前/截图诊断（pywin32；不依赖 PySide6）。"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pywintypes
import win32con
import win32gui

from luoluotool.automation.elevation import is_process_elevated, is_window_elevated

logger = logging.getLogger(__name__)

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
    """截取客户区保存为**真正的 PNG** 并返回路径。

    评审 P2-9：旧实现自己走 PrintWindow/BitBlt 并用 `SaveBitmapFile` 落盘（那其实写的是 BMP，
    只是扩展名是 .png），而且**不判断结果是不是纯黑** —— 对 GPU 渲染的游戏会存出一张全黑图
    却上报"诊断完成"。现在复用识别链的 `capture_client_bgr`（黑帧检测 + PW_CLIENTONLY →
    BitBlt(窗口DC) → 屏幕 BitBlt 多级兜底 + 客户区偏移裁剪）与 `save_image`（imencode 写 PNG）：
    取不到画面时抛可读 `VisionError`，由 `diagnose_window` 转成提示，不再谎报成功。
    """
    from luoluotool.automation.vision import capture_client_bgr, save_image

    return save_image(save_path, capture_client_bgr(hwnd))


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
