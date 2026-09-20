"""模板读取与匹配原语：读模板（中文路径 + 纯色拒绝）→ 在截图里按原尺寸匹配 → 客户区坐标。

分层：automation 层（不 import PySide6）。本模块只做「图 × 图」，不碰窗口与取景：
多尺度（缩放）搜索在 `automation.multiscale`，窗口取景在 `automation.vision`。

坐标语义：`Match` 的 left/top/center 全部是**游戏窗口客户区坐标**，可直接喂给
`InputSender.click_at()` / `drag()`。

拆分说明（2026-09-20）：本模块由 `automation/vision.py` 原样搬出（行为零变化），
`vision.py` 仍再导出这里的所有公共名字，旧的 `from ...automation.vision import Match` 继续可用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.85
DEFAULT_MAX_RESULTS = 20
NMS_OVERLAP_RATIO = 0.3          # 重叠超过该比例视为同一目标（保留高分那个）
BLANK_MIN_PIXELS = 64            # 少于该像素数不做"纯色帧"判断（1x1 之类无法判断）
BLANK_STD_THRESHOLD = 2.0        # 标准差低于该值视为纯色/黑帧
MIN_TEMPLATE_SIDE = 4            # 缩放后模板每边至少这么多像素（再小没有匹配意义）


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
    scale: float = 1.0            # 命中所用的缩放比例（1.0 = 原始尺寸）

    @property
    def center(self) -> tuple[int, int]:
        """命中区域中心（推荐用这个坐标去点击）。"""
        return self.left + self.width // 2, self.top + self.height // 2

    @property
    def right_bottom(self) -> tuple[int, int]:
        return self.left + self.width, self.top + self.height

    def describe(self) -> str:
        """人读描述（日志/界面共用）；非原始尺寸时带上缩放比例。"""
        scale_text = "" if abs(self.scale - 1.0) < 1e-3 else f" 缩放 {self.scale:.2f}x"
        return (
            f"中心 {self.center} 左上 ({self.left}, {self.top}) "
            f"尺寸 {self.width}x{self.height} 匹配度 {self.score:.3f}{scale_text}"
        )


def is_blank_frame(image: np.ndarray) -> bool:
    """判断是否为纯色/黑帧（PrintWindow 对 GPU 独占渲染的游戏常返回黑帧）。

    像素太少（< `BLANK_MIN_PIXELS`）时无法判断，一律返回 False。
    """
    if image.size == 0 or image.shape[0] * image.shape[1] < BLANK_MIN_PIXELS:
        return False
    return float(image.std()) < BLANK_STD_THRESHOLD


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
    if is_blank_frame(image):
        # 纯色模板会让任何平坦区域都拿到满分（实测：一张纯色 260x260 在真实游戏画面上
        # 刷出 20 处"匹配度 1.000"），必须在读取阶段就拒绝，而不是给用户一堆假坐标。
        raise VisionError(
            f"模板图片几乎是纯色（标准差 {float(image.std()):.2f}，没有可匹配的纹理）："
            f"{template_path}；请框选包含细节的区域重新生成模板"
        )
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
