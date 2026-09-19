"""图像识别（模板匹配）：在窗口客户区截图里查找模板图，返回**客户区坐标**。

分层：本模块属于 automation 层（不 import PySide6），集中封装 OpenCV 调用；
窗口查找与就绪判断由上层（`core.vision`）负责，本模块只做「截图 → 匹配 → 坐标」。

坐标语义：`Match` 的 left/top/center 全部是**游戏窗口客户区坐标**，
可直接喂给 `InputSender.click_at()` / `drag()`（它们收的也是客户区坐标）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.85
DEFAULT_MAX_RESULTS = 20
NMS_OVERLAP_RATIO = 0.3          # 重叠超过该比例视为同一目标（保留高分那个）
PW_RENDERFULLCONTENT = 2
PW_CLIENTONLY = 1


class VisionError(RuntimeError):
    """图像识别失败（模板读取失败、模板比截图大、截图渲染失败等）。"""


@dataclass(frozen=True)
class Match:
    """一次命中；坐标均为**游戏窗口客户区坐标**。"""

    left: int
    top: int
    width: int
    height: int
    score: float

    @property
    def center(self) -> tuple[int, int]:
        """命中区域中心（推荐用这个坐标去点击）。"""
        return self.left + self.width // 2, self.top + self.height // 2

    @property
    def right_bottom(self) -> tuple[int, int]:
        return self.left + self.width, self.top + self.height

    def describe(self) -> str:
        """人读描述（日志/界面共用）。"""
        return (
            f"中心 {self.center} 左上 ({self.left}, {self.top}) "
            f"尺寸 {self.width}x{self.height} 匹配度 {self.score:.3f}"
        )


# ---------------------------------------------------------------- 模板与匹配


def load_template(path: str | Path) -> np.ndarray:
    """读取模板图片（BGR 三通道）。

    用 `np.fromfile` + `cv2.imdecode` 而不是 `cv2.imread`：后者在 Windows 上
    对中文/含空格路径会静默失败（返回 None）。
    """
    template_path = Path(path)
    if not template_path.is_file():
        raise VisionError(f"无法读取模板图片：文件不存在 {template_path}")
    try:
        buffer = np.fromfile(str(template_path), dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR) if buffer.size else None
    except Exception as exc:                      # 权限/编码等异常统一转可读错误
        raise VisionError(f"无法读取模板图片 {template_path}：{exc}") from exc
    if image is None or image.size == 0:
        raise VisionError(f"无法解析模板图片（不是有效图片？）：{template_path}")
    return image


def _prepare(image: np.ndarray, grayscale: bool) -> np.ndarray:
    """按匹配需要准备图像：灰度化（默认）或保持 BGR；灰度输入原样返回。"""
    if not grayscale:
        return image
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def locate_all(
    haystack: np.ndarray,
    template: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
    grayscale: bool = True,
    max_results: int = DEFAULT_MAX_RESULTS,
    overlap_ratio: float = NMS_OVERLAP_RATIO,
) -> list[Match]:
    """在 `haystack`（窗口截图）里查找所有匹配度 ≥ `threshold` 的 `template`。

    - 匹配算法：`TM_CCOEFF_NORMED`（对亮度变化不敏感，返回 0–1 相似度）；
    - 结果按匹配度降序，并用 NMS 去掉互相重叠的重复命中（同一个目标只留一个）；
    - 模板比截图还大时抛 `VisionError`（这种调用没有意义，容易掩盖配置错误）。
    """
    source = _prepare(haystack, grayscale)
    target = _prepare(template, grayscale)
    source_h, source_w = source.shape[:2]
    target_h, target_w = target.shape[:2]
    if target_h > source_h or target_w > source_w:
        raise VisionError(
            f"模板比截图还大（模板 {target_w}x{target_h}，截图 {source_w}x{source_h}），无法匹配"
        )
    result = cv2.matchTemplate(source, target, cv2.TM_CCOEFF_NORMED)
    rows, cols = np.where(result >= float(threshold))
    candidates = sorted(
        (
            Match(int(x), int(y), target_w, target_h, float(result[y, x]))
            for y, x in zip(rows.tolist(), cols.tolist())
        ),
        key=lambda match: match.score,
        reverse=True,
    )
    kept: list[Match] = []
    for candidate in candidates:
        if all(_overlap_ratio(candidate, chosen) <= overlap_ratio for chosen in kept):
            kept.append(candidate)
        if len(kept) >= max(int(max_results), 1):
            break
    return kept


def locate_best(
    haystack: np.ndarray,
    template: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
    grayscale: bool = True,
) -> Match | None:
    """只取最佳命中；没有达到阈值的目标时返回 None。"""
    matches = locate_all(haystack, template, threshold, grayscale, max_results=1)
    return matches[0] if matches else None


def _overlap_ratio(first: Match, second: Match) -> float:
    """两个矩形的重叠面积 / 两者中较小的面积（0–1）。"""
    left = max(first.left, second.left)
    top = max(first.top, second.top)
    right = min(first.right_bottom[0], second.right_bottom[0])
    bottom = min(first.right_bottom[1], second.right_bottom[1])
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    smaller = min(first.width * first.height, second.width * second.height)
    return intersection / smaller if smaller else 0.0


# ---------------------------------------------------------------- 窗口截图


def capture_client_bgr(hwnd: int) -> np.ndarray:
    """把窗口客户区渲染成 BGR numpy 数组（识别用，不落盘）。

    渲染方式与 `automation.window.screenshot_client` 一致（PrintWindow 优先，
    游戏多为 GPU 渲染，需要 PW_RENDERFULLCONTENT；失败再回退），只是结果直接给数组。
    """
    width, height, bits = _render_client_bits(hwnd)
    if width <= 0 or height <= 0:
        raise VisionError(f"窗口客户区尺寸异常（{width}x{height}），无法截图识别")
    expected = width * height * 4
    if len(bits) < expected:
        raise VisionError(
            f"截图数据不完整（期望 {expected} 字节，实际 {len(bits)} 字节），无法识别"
        )
    # win32ui.GetBitmapBits(True) 返回 BGRA（每行 4 字节对齐）
    array = np.frombuffer(bits, dtype=np.uint8, count=expected).reshape((height, width, 4))
    return np.ascontiguousarray(array[:, :, :3])


def _render_client_bits(hwnd: int) -> tuple[int, int, bytes]:
    """渲染窗口客户区并返回 (宽, 高, BGRA 原始位)。实现细节抽出来便于测试注入。"""
    import ctypes

    import win32con
    import win32gui
    import win32ui

    from luoluotool.automation.window import get_client_rect

    _, _, width, height = get_client_rect(hwnd)
    if width <= 0 or height <= 0:
        raise VisionError(f"窗口客户区尺寸异常（{width}x{height}），无法截图识别")

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    try:
        window_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        memory_dc = window_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(window_dc, width, height)
        memory_dc.SelectObject(bitmap)
        try:
            if not ctypes.windll.user32.PrintWindow(hwnd, memory_dc.GetSafeHdc(), PW_RENDERFULLCONTENT):
                logger.debug("PrintWindow(全窗口) 未成功，回退 BitBlt 客户区渲染")
                memory_dc.BitBlt(
                    (0, 0), (width, height), window_dc, (0, 0), win32con.SRCCOPY
                )
            bits = bitmap.GetBitmapBits(True)
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            memory_dc.DeleteDC()
            window_dc.DeleteDC()
    finally:
        win32gui.ReleaseDC(hwnd, hwnd_dc)
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
