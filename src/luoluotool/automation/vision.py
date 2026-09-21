"""窗口客户区取景与可视化：抓客户区画面（含黑帧回退链）、画框、存图。

分层：automation 层（不 import PySide6），集中封装 GDI/窗口截图调用。

**本模块同时是「图像识别」的对外门面**（拆分后 2026-09-20）：
- 模板读取与匹配原语 → `automation.template_match`
- 多尺度（缩放）搜索 → `automation.multiscale`
- 这里只保留取景/渲染与可视化，并把上面两个模块的公共名字**再导出**，
  因此 `from luoluotool.automation.vision import locate_all_scaled, Match, capture_client_bgr`
  这类旧导入继续可用（本次拆分不改任何调用方）。

坐标语义：所有匹配结果都是**游戏窗口客户区坐标**；取景原点必须是客户区左上
（窗口 DC / PrintWindow 的原点都是窗口左上角，必须按 `window.client_area_offset` 校正）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from luoluotool.automation.multiscale import (          # 再导出（旧导入路径不变）
    DEFAULT_SCALE_RANGE,
    SCALE_FAST_MAX,
    locate_all_scaled,
    locate_best_scaled,
    scale_candidates,
)
from luoluotool.automation.template_match import (      # 再导出（旧导入路径不变）
    DEFAULT_MAX_RESULTS,
    DEFAULT_THRESHOLD,
    BLANK_MIN_PIXELS,
    BLANK_STD_THRESHOLD,
    MIN_TEMPLATE_SIDE,
    NMS_OVERLAP_RATIO,
    Match,
    VisionError,
    is_blank_frame,
    load_template,
    locate_all,
    locate_best,
    read_image_bgr,
)

logger = logging.getLogger(__name__)

PW_RENDERFULLCONTENT = 2
PW_CLIENTONLY = 1


# ---------------------------------------------------------------- 窗口截图




def capture_client_bgr(hwnd: int) -> np.ndarray:
    """把窗口客户区渲染成 BGR numpy 数组（识别用，不落盘）。

    取景顺序：PrintWindow(PW_RENDERFULLCONTENT) → 若得到纯色/黑帧**或抛异常**则自动换其它方式
    （PW_CLIENTONLY → BitBlt(窗口 DC) → 桌面屏幕 BitBlt，后者仅在窗口位于前台时使用）。
    全部失败时抛可读 `VisionError` 并给出「以管理员身份运行 / 让窗口保持可见」的指引
    —— 实测本作（GPU 渲染 + 管理员运行）会取到黑帧，若不判断就会出现"整帧纯黑 →
    匹配度 0 → 报告未识别到目标"这种误导性结论。

    评审 P2-7：主取景**抛异常**时也必须退到兜底链（GetWindowDC / CreateCompatibleBitmap
    在权限不足、窗口已关闭时会失败），不能在还有可用路径的情况下直接以异常收场。
    """
    primary_error: str = ""
    try:
        width, height, bits = _render_client_bits(hwnd)
        image = _bits_to_bgr(width, height, bits)
        if not is_blank_frame(image):
            return image
        logger.warning(
            "PrintWindow 取到纯色/黑帧（%dx%d，标准差 %.2f），改用其它取景方式",
            width, height, float(image.std()),
        )
    except VisionError as exc:
        primary_error = str(exc)
        logger.warning("主取景方式失败（%s），改用其它取景方式", exc)
    except Exception as exc:
        primary_error = str(exc)
        logger.warning("主取景方式异常（%s），改用其它取景方式", exc)

    fallback = _render_client_bgr_fallback(hwnd)
    if fallback is not None:
        return fallback
    hint = f"（主取景失败原因：{primary_error}）" if primary_error else ""
    raise VisionError(
        "取景失败：各种方式都只拿到纯色/黑帧或直接报错，无法识别。"
        f"{hint}请确认游戏窗口可见且在前台；若游戏以管理员身份运行，请以管理员身份重启本工具后再试。"
    )


def _bits_to_bgr(width: int, height: int, bits: bytes) -> np.ndarray:
    """BGRA 原始位 → BGR 数组（win32ui.GetBitmapBits(True) 的格式）。"""
    if width <= 0 or height <= 0:
        raise VisionError(f"窗口客户区尺寸异常（{width}x{height}），无法截图识别")
    expected = width * height * 4
    if len(bits) < expected:
        raise VisionError(
            f"截图数据不完整（期望 {expected} 字节，实际 {len(bits)} 字节），无法识别"
        )
    array = np.frombuffer(bits, dtype=np.uint8, count=expected).reshape((height, width, 4))
    return np.ascontiguousarray(array[:, :, :3])


def _render_client_bgr_fallback(hwnd: int) -> np.ndarray | None:
    """备用取景：返回有内容的帧；全部失败返回 None。"""
    try:
        import win32gui

        foreground = win32gui.GetForegroundWindow() == hwnd
    except Exception:                     # 拿不到前台信息就保守一点，不用屏幕取景
        foreground = False

    attempts: list[tuple[str, Callable[[], tuple[int, int, bytes]]]] = [
        ("PrintWindow(PW_CLIENTONLY)", lambda: _render_client_bits_printwindow(hwnd, PW_CLIENTONLY)),
        ("BitBlt(窗口DC)", lambda: _render_client_bits_bitblt(hwnd)),
    ]
    if foreground:                        # 屏幕取景要求窗口确实在前台可见，否则会抓到别的窗口内容
        attempts.append(("屏幕BitBlt(桌面DC)", lambda: _render_client_bits_screen(hwnd)))

    for name, render in attempts:
        try:
            width, height, bits = render()
            image = _bits_to_bgr(width, height, bits)
        except VisionError as exc:
            logger.info("取景方式 %s 失败：%s", name, exc)
            continue
        except Exception as exc:
            logger.warning("取景方式 %s 异常：%s", name, exc)
            continue
        if not is_blank_frame(image):
            logger.info("取景成功（备用方式：%s，%dx%d）", name, width, height)
            return image
        logger.info("取景方式 %s 同样是纯色/黑帧", name)
    return None


def _render_client_bits(hwnd: int) -> tuple[int, int, bytes]:
    """主取景方式：PrintWindow(PW_RENDERFULLCONTENT) —— 抽成独立函数便于测试注入。"""
    return _render_client_bits_printwindow(hwnd, PW_RENDERFULLCONTENT)


def _print_window(hwnd: int, hdc, flag: int) -> bool:
    """调用 User32 的 PrintWindow（抽成独立函数，便于测试注入）。"""
    import ctypes

    return bool(ctypes.windll.user32.PrintWindow(hwnd, hdc, flag))


def _render_client_bits_printwindow(hwnd: int, flag: int) -> tuple[int, int, bytes]:
    """用 PrintWindow 渲染客户区（flag=PW_RENDERFULLCONTENT 或 PW_CLIENTONLY）。

    **PrintWindow 画的是整个窗口**（含标题栏与边框），且目标 DC 的原点对应窗口左上角，
    因此必须：按**窗口尺寸**渲染 → 再按**客户区偏移**裁出客户区。
    直接按客户区尺寸渲染的话，抓到的第一行是标题栏、客户区底部缺"标题栏高度"那一截，
    识别坐标会整体偏下标题栏高度（2026-09-20 实测：本作窗口 1618x1070 / 客户区 1600x1024，
    偏移 (9, 37) —— 用户报的"坐标总是偏下"就是这个）。做法与 `window.screenshot_client` 一致。
    """
    import win32con
    import win32gui
    import win32ui

    from luoluotool.automation.window import client_area_offset, get_client_rect, get_window_size

    _, _, width, height = get_client_rect(hwnd)
    window_width, window_height = get_window_size(hwnd)
    if width <= 0 or height <= 0 or window_width <= 0 or window_height <= 0:
        raise VisionError(
            f"窗口客户区尺寸异常（客户区 {width}x{height}，窗口 {window_width}x{window_height}），"
            "无法截图识别"
        )
    offset_x, offset_y = client_area_offset(hwnd)
    logger.info(
        "取景(PrintWindow)：客户区在窗口内偏移 (%d, %d)（标题栏/边框），已按该偏移裁出客户区",
        offset_x, offset_y,
    )

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    try:
        window_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        full_dc = window_dc.CreateCompatibleDC()
        full_bitmap = win32ui.CreateBitmap()
        full_bitmap.CreateCompatibleBitmap(window_dc, window_width, window_height)
        full_dc.SelectObject(full_bitmap)
        client_dc = window_dc.CreateCompatibleDC()
        client_bitmap = win32ui.CreateBitmap()
        client_bitmap.CreateCompatibleBitmap(window_dc, width, height)
        client_dc.SelectObject(client_bitmap)
        try:
            _print_window(hwnd, full_dc.GetSafeHdc(), flag)
            client_dc.BitBlt(
                (0, 0), (width, height), full_dc, (offset_x, offset_y), win32con.SRCCOPY
            )
            bits = client_bitmap.GetBitmapBits(True)
        finally:
            win32gui.DeleteObject(client_bitmap.GetHandle())
            win32gui.DeleteObject(full_bitmap.GetHandle())
            client_dc.DeleteDC()
            full_dc.DeleteDC()
            window_dc.DeleteDC()
    finally:
        win32gui.ReleaseDC(hwnd, hwnd_dc)
    return width, height, bits


def _render_client_bits_bitblt(hwnd: int) -> tuple[int, int, bytes]:
    """备用：从窗口 DC 直接 BitBlt 客户区（部分窗口 PrintWindow 失败但 BitBlt 可用）。

    窗口 DC 的原点是**窗口左上角**（含标题栏/边框），所以源点必须用客户区偏移，
    不能写 (0, 0) —— 那会抓到"标题栏 + 客户区上半部分"，让坐标整体偏下标题栏高度
    （2026-09-20 实测本作偏移 (9, 37)，是本作实际生效的取景路径，用户报告的 bug 就在这）。
    """
    import win32con
    import win32gui
    import win32ui

    from luoluotool.automation.window import client_area_offset, get_client_rect

    _, _, width, height = get_client_rect(hwnd)
    if width <= 0 or height <= 0:
        raise VisionError(f"窗口客户区尺寸异常（{width}x{height}），无法截图识别")
    offset_x, offset_y = client_area_offset(hwnd)
    logger.info(
        "取景(BitBlt 窗口DC)：从客户区左上 (%d, %d) 抓取（窗口 DC 原点在标题栏，已跳过）",
        offset_x, offset_y,
    )

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    try:
        window_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        memory_dc = window_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(window_dc, width, height)
        memory_dc.SelectObject(bitmap)
        try:
            memory_dc.BitBlt(
                (0, 0), (width, height), window_dc, (offset_x, offset_y), win32con.SRCCOPY
            )
            bits = bitmap.GetBitmapBits(True)
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            memory_dc.DeleteDC()
            window_dc.DeleteDC()
    finally:
        win32gui.ReleaseDC(hwnd, hwnd_dc)
    return width, height, bits


def _render_client_bits_screen(hwnd: int) -> tuple[int, int, bytes]:
    """备用：从桌面屏幕 DC 抓窗口客户区所在区域。

    GPU 独占渲染的游戏（实测本作）用 PrintWindow/BitBlt 都拿不到画面，只剩这种方式；
    但它抓的是"屏幕上的内容"，因此只有窗口确实在前台可见时才有意义
    （调用方 `_render_client_bgr_fallback` 已用前台判断做门禁）。
    这一条**天然以客户区左上为原点**（源点取 `ClientToScreen(hwnd, (0, 0))`），
    不需要再按窗口偏移裁剪 —— 它是"取景原点应为客户区左上"的参照实现。
    """
    import win32con
    import win32gui
    import win32ui

    from luoluotool.automation.window import get_client_rect

    _, _, width, height = get_client_rect(hwnd)
    if width <= 0 or height <= 0:
        raise VisionError(f"窗口客户区尺寸异常（{width}x{height}），无法截图识别")
    origin_x, origin_y = win32gui.ClientToScreen(hwnd, (0, 0))

    screen_dc = win32gui.GetDC(0)
    try:
        source_dc = win32ui.CreateDCFromHandle(screen_dc)
        memory_dc = source_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source_dc, width, height)
        memory_dc.SelectObject(bitmap)
        try:
            memory_dc.BitBlt(
                (0, 0), (width, height), source_dc, (origin_x, origin_y), win32con.SRCCOPY
            )
            bits = bitmap.GetBitmapBits(True)
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            memory_dc.DeleteDC()
            source_dc.DeleteDC()
    finally:
        win32gui.ReleaseDC(0, screen_dc)
    return width, height, bits


# ---------------------------------------------------------------- 可视化


def annotate(image: np.ndarray, matches: list[Match] | tuple[Match, ...]) -> np.ndarray:
    """在截图上把命中位置画框（结果存盘供人工核对）。"""
    canvas = image.copy()
    for index, match in enumerate(matches, start=1):
        cv2.rectangle(
            canvas, (match.left, match.top), match.right_bottom, (0, 0, 255), 2
        )
        cv2.putText(
            canvas, f"#{index} {match.score:.2f}", (match.left, max(match.top - 6, 12)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA,
        )
    return canvas


def save_image(path: str | Path, image: np.ndarray) -> Path:
    """保存图片（用 imencode + tofile 以支持中文路径）。"""
    target = Path(path)
    ok, buffer = cv2.imencode(target.suffix or ".png", image)
    if not ok:
        raise VisionError(f"无法编码截图：{target}")
    buffer.tofile(str(target))
    return target
