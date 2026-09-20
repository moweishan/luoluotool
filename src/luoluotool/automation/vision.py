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
    source = _prepare(haystack, grayscale)
    target = _prepare(template, grayscale)

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


# ---------------------------------------------------------------- 窗口截图


def is_blank_frame(image: np.ndarray) -> bool:
    """判断是否为纯色/黑帧（PrintWindow 对 GPU 独占渲染的游戏常返回黑帧）。

    像素太少（< `BLANK_MIN_PIXELS`）时无法判断，一律返回 False。
    """
    if image.size == 0 or image.shape[0] * image.shape[1] < BLANK_MIN_PIXELS:
        return False
    return float(image.std()) < BLANK_STD_THRESHOLD


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
