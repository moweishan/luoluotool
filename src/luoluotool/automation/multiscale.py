"""多尺度（缩放）模板匹配：画面放大/缩小时按比例搜索模板，返回客户区坐标。

分层：automation 层（不 import PySide6）。匹配原语与 `Match` 来自 `automation.template_match`。

两档搜索（用户 2026-09-19 要求，规则见 AGENTS.md）：先搜 0.3x–2.0x，**没命中才**扩到 0.3x–4.0x；
每档内部都是"粗搜比例 → 在最佳比例附近精修（步长 0.02）→ 在该比例下取全部命中"。
阈值必须在精修之后判断，粗搜必须"越过峰值回落"才停（否则实测真值 3.50x 会被截断成 3.36x）。

拆分说明（2026-09-20）：本模块由 `automation/vision.py` 原样搬出（行为零变化），
`vision.py` 仍再导出这里的公共名字，`from ...automation.vision import locate_all_scaled` 继续可用。
"""

from __future__ import annotations

import cv2
import numpy as np

from luoluotool.automation.template_match import (
    DEFAULT_MAX_RESULTS,
    DEFAULT_THRESHOLD,
    MIN_TEMPLATE_SIDE,
    Match,
    locate_all,
    prepare_for_match,
)


# 多尺度（缩放）匹配：游戏画面放大/缩小时模板的像素尺寸会变，必须按比例搜索
DEFAULT_SCALE_RANGE = (0.30, 4.00)   # 完整搜索范围（第二档会用到上界 4.0x）
SCALE_FAST_MAX = 2.00                # 第一档（快搜）上界：先只搜到这里，档位少、命中率高
DEFAULT_SCALE_STEP = 0.10        # 粗搜步长
SCALE_REFINE_STEP = 0.02         # 在最佳比例附近精修的步长
SCALE_REFINE_SPAN = 0.06
SCALE_TIE_TOLERANCE = 0.01       # 分数接近时优先接近 1.0x 的缩放（减少误报）
SCALE_STRONG_MARGIN = 0.05       # 分数比阈值高出这么多 → 视为"比较像了"，允许在越过峰值后结束粗搜
SCALE_PEAK_DROP = 0.02           # 越过峰值后分数回落这么多 → 认定已经过了峰值，可以结束粗搜
SCALE_STRONG_AREA_RATIO = 0.30   # 终止粗搜的条件之一：候选模板面积 ≥ 原模板面积的该比例
                                 # （过小的缩放会给出虚高分数——实测 9x4 像素能"匹配"到 0.96）
SCALE_REFINE_MARGIN = 0.20       # 粗搜分数低于「阈值 - 该值」时不再精修（明显没有目标，省时间）


# ---------------------------------------------------------------- 多尺度匹配


def scale_candidates(scale_range: tuple[float, float], step: float) -> list[float]:
    """生成缩放候选（从小到大、去重、含端点）。"""
    low, high = float(min(scale_range)), float(max(scale_range))
    step = max(float(step), 0.001)
    scales: list[float] = []
    value = low
    while value <= high + 1e-9:
        scales.append(round(value, 4))
        value += step
    if scales and abs(scales[-1] - high) > 1e-9:
        scales.append(round(high, 4))
    return sorted(set(scales))


def _resize_template(template: np.ndarray, scale: float) -> np.ndarray | None:
    """按比例缩放模板；尺寸小到无意义或超出画面时返回 None。"""
    height, width = template.shape[:2]
    target_w = int(round(width * scale))
    target_h = int(round(height * scale))
    if target_w < MIN_TEMPLATE_SIDE or target_h < MIN_TEMPLATE_SIDE:
        return None
    if target_w == width and target_h == height:
        return template
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    return cv2.resize(template, (target_w, target_h), interpolation=interpolation)


def _best_score(source: np.ndarray, template: np.ndarray) -> float:
    """某尺寸模板在画面里的最佳匹配度（不取位置）。"""
    if template.shape[0] > source.shape[0] or template.shape[1] > source.shape[1]:
        return -1.0
    result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, _ = cv2.minMaxLoc(result)
    return float(score)


def _better_scale(current: tuple[float, float] | None, scale: float, score: float) -> bool:
    """判断新候选是否更优：分数更高（或接近时更贴近 1.0x）。"""
    if current is None:
        return True
    best_scale, best_score = current
    if score > best_score + SCALE_TIE_TOLERANCE:
        return True
    if abs(score - best_score) <= SCALE_TIE_TOLERANCE and abs(scale - 1.0) < abs(best_scale - 1.0):
        return True
    return False


def _is_substantial(resized: np.ndarray, original: np.ndarray) -> bool:
    """候选模板是否"足够大"（面积不少于原模板的 `SCALE_STRONG_AREA_RATIO`）。

    用途：只有足够大的候选才允许提前结束粗搜——把模板缩得很小时，几个像素就能凑出很高的
    相关系数（实测 9x4 像素匹配出 0.96），若据此提前结束就会停在完全错误的比例上。
    """
    original_area = float(original.shape[0] * original.shape[1])
    resized_area = float(resized.shape[0] * resized.shape[1])
    return original_area <= 0 or resized_area >= original_area * SCALE_STRONG_AREA_RATIO


def _scale_tiers(scale_range: tuple[float, float]) -> list[tuple[float, float]]:
    """把搜索范围拆成"先窄后宽"的档位（用户要求：先 0.3x–2.0x，找不到再扩到 0.3x–4.0x）。

    窄档档位少、绝大多数情况一次就命中；只有窄档确实找不到时才付第二档的代价。
    范围本来就落在窄档之内（或整段都在窄档上界之上）时只有一档。
    """
    low, high = float(min(scale_range)), float(max(scale_range))
    if high <= SCALE_FAST_MAX + 1e-9 or low >= SCALE_FAST_MAX - 1e-9:
        return [(low, high)]
    return [(low, SCALE_FAST_MAX), (low, high)]


def _scan_coarse(
    source: np.ndarray,
    target: np.ndarray,
    scales: list[float],
    best: tuple[float, float] | None,
    best_substantial: bool,
    strong_score: float,
) -> tuple[tuple[float, float] | None, bool]:
    """在给定档位上做粗搜，沿用"最佳候选 + 越过峰值回落才停"的状态（可跨档继续）。

    结束粗搜的条件：已经有了"够强且足够大"的最佳候选，且当前分数明显从峰值回落
    —— 后面只会更差。**不能**改成"第一个够强的候选就停"：分数是在真实缩放附近缓慢爬升
    的，3.50x 的真值在 3.30x 就有 0.9018（高于阈值+0.05），一旦就此停住，±0.06 的
    精修窗口够不到真值，实测会报成 3.36x（框比目标小一圈）。见 test_..._after_peak。
    """
    for scale in scales:
        resized = _resize_template(target, scale)
        if resized is None:
            continue
        score = _best_score(source, resized)
        if (
            best is not None
            and best_substantial
            and best[1] >= strong_score
            and score < best[1] - SCALE_PEAK_DROP
        ):
            break
        if _better_scale(best, scale, score):
            best = (scale, score)
            best_substantial = _is_substantial(resized, target)
    return best, best_substantial


def _refine_scale(
    source: np.ndarray, target: np.ndarray, best: tuple[float, float]
) -> tuple[float, float]:
    """在最佳比例附近精修（只接受**严格更好**的分数）。

    不能再用"贴近 1.0x"的平局规则，否则会把真实比例（例如 1.40x）掰成更靠近 1.0 的邻居（1.38x）。
    """
    best_scale, best_score = best
    for scale in scale_candidates(
        (best_scale - SCALE_REFINE_SPAN, best_scale + SCALE_REFINE_SPAN), SCALE_REFINE_STEP
    ):
        resized = _resize_template(target, scale)
        if resized is None:
            continue
        score = _best_score(source, resized)
        if score > best_score + 1e-9:
            best_scale, best_score = scale, score
    return best_scale, best_score


def locate_all_scaled(
    haystack: np.ndarray,
    template: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
    max_results: int = DEFAULT_MAX_RESULTS,
    grayscale: bool = True,
    scale_range: tuple[float, float] = DEFAULT_SCALE_RANGE,
    scale_step: float = DEFAULT_SCALE_STEP,
) -> list[Match]:
    """**多尺度**模板匹配：按档粗搜缩放比例 → 在最佳比例附近精修 → 在该比例上取全部命中。

    为什么需要它：游戏画面放大/缩小时，模板的像素尺寸会跟着变，
    1:1 匹配（`locate_all`）就再也对不上（用户实测的现象）。
    搜索分两档（`_scale_tiers`）：先 0.3x–2.0x 快搜，**没命中才**把范围扩到 0.3x–4.0x 继续搜；
    第二档不重复扫第一档的档位。返回的 `Match.scale` 是命中时用的缩放比例，坐标仍是**客户区坐标**。
    """
    source = prepare_for_match(haystack, grayscale)
    target = prepare_for_match(template, grayscale)

    strong_score = float(threshold) + SCALE_STRONG_MARGIN
    best: tuple[float, float] | None = None
    best_substantial = False                          # best 对应的模板是否"足够大"（见 _is_substantial）
    scanned: set[float] = set()                       # 已经粗搜过的档位（第二档不重复扫）
    matched: tuple[float, float] | None = None
    for low, high in _scale_tiers(scale_range):
        pending = [s for s in scale_candidates((low, high), scale_step) if s not in scanned]
        scanned.update(pending)
        best, best_substantial = _scan_coarse(
            source, target, pending, best, best_substantial, strong_score
        )
        if best is None or best[1] < float(threshold) - SCALE_REFINE_MARGIN:
            continue                                  # 这一档连像样的候选都没有，换下一档
        # 阈值必须在**精修之后**判断：真实缩放常常落在粗搜两档之间
        # （例如 0.75x 落在 0.70/0.80 之间，粗搜只有 0.83，精修到 0.74x 是 0.95 —— 实测踩到）
        refined = _refine_scale(source, target, best)
        if refined[1] >= float(threshold):
            matched = refined                          # 这一档找到了
            break
        if refined[1] > best[1]:
            best = refined                             # 精修更好就带进下一档继续比

    if matched is None:
        return []
    best_scale = matched[0]
    resized = _resize_template(target, best_scale)
    if resized is None:
        return []
    matches = locate_all(
        source, resized, threshold, grayscale=False, max_results=max_results
    )
    # 把缩放比例写进命中结果（Match 是 frozen，用 replace 复制）
    from dataclasses import replace

    return [replace(match, scale=float(best_scale)) for match in matches]


def locate_best_scaled(
    haystack: np.ndarray,
    template: np.ndarray,
    threshold: float = DEFAULT_THRESHOLD,
    grayscale: bool = True,
    scale_range: tuple[float, float] = DEFAULT_SCALE_RANGE,
    scale_step: float = DEFAULT_SCALE_STEP,
) -> Match | None:
    """多尺度匹配只取最佳命中；没有达到阈值的目标时返回 None。"""
    matches = locate_all_scaled(
        haystack, template, threshold, max_results=1, grayscale=grayscale,
        scale_range=scale_range, scale_step=scale_step,
    )
    return matches[0] if matches else None
