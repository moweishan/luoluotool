"""图像识别的业务编排：找窗口 → 校验就绪 → 截图 → 模板匹配 → 返回客户区坐标。

与 GUI 无关（可被调试页、命令行或后续任务复用）：本模块只依赖 automation 层，
不 import PySide6；失败一律转成 `RecognizeResult`（不把异常抛给 GUI 线程）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from luoluotool.automation.input_sender import is_window_ready
from luoluotool.automation.vision import (
    DEFAULT_MAX_RESULTS,
    DEFAULT_SCALE_RANGE,
    DEFAULT_THRESHOLD,
    MIN_TEMPLATE_SIDE,
    Match,
    VisionError,
    annotate,
    capture_client_bgr,
    load_template,
    locate_all,
    locate_all_scaled,
    save_image,
)
from luoluotool.automation.window import find_window
from luoluotool.config.models import AppConfig
from luoluotool.utils.paths import get_debug_dir

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecognizeResult:
    """识别结果：命中列表（客户区坐标）+ 人读消息 + 可选带框截图路径。

    - `matches` 是**一张模板**在图上的全部命中（同一张图出现在屏幕多个区域时全部列出，
      按匹配度降序，`matches[0]` 就是"默认使用值"）；
    - `matched_template` 记录是**哪张模板**命中的（多模板时给用户看是第几张）；
    - `tried_templates` 记录本次试过的模板与各自结果（全部未命中时写进消息）。
    """

    found: bool
    matches: tuple[Match, ...]
    message: str
    window_size: tuple[int, int] | None = None
    annotated_path: Path | None = None
    matched_template: Path | None = None
    tried_templates: tuple[str, ...] = ()


def _template_paths(image_path: str | Path | Sequence[str | Path]) -> list[Path]:
    """把"单个路径 / 路径列表"统一成路径列表（丢掉空项，保持用户给的顺序）。"""
    if isinstance(image_path, (str, Path)):
        raw: list[str | Path] = [image_path]
    else:
        raw = list(image_path)
    return [Path(item) for item in raw if str(item).strip()]


def recognize_in_window(
    config: AppConfig,
    image_path: str | Path | Sequence[str | Path],
    threshold: float = DEFAULT_THRESHOLD,
    max_results: int = DEFAULT_MAX_RESULTS,
    annotate_result: bool | None = None,
    capture: Callable[[int], np.ndarray] | None = None,
    allow_scale: bool = True,
    scale_range: tuple[float, float] = DEFAULT_SCALE_RANGE,
) -> RecognizeResult:
    """在当前游戏窗口客户区里查找模板图片，返回命中位置（客户区坐标）。

    **多张模板（`image_path` 传列表）**：按用户给的顺序逐张尝试，**第一张达到阈值的就直接
    采用它的结果**（后面的不再试，省时间）；某张图片读不出来或匹配报错就跳过它、继续下一张。
    全部未命中时，消息里逐张列出各自的结果（未命中 / 读不了的原因）。

    **一张模板命中多处（屏幕多个区域）**：全部返回（按匹配度降序，`max_results` 封顶），
    消息里逐处编号，并标出"默认使用值"（第 1 处＝匹配度最高）。

    - 窗口未找到 / 最小化 → 直接给可读结果，不截图；
    - `capture` 可注入（测试用）；默认走 `vision.capture_client_bgr`（内含黑帧兜底）；
    - 多张模板共用**同一张截图**（只截一次，保证各模板看到的是同一帧画面）；
    - `allow_scale=True`（默认）时做**多尺度匹配**：游戏画面放大/缩小时模板像素尺寸会变，
      1:1 匹配会失败（用户实测现象）；关闭后只按原始尺寸匹配（更快、更严格）；
    - `annotate_result=None`（默认）时看配置项 `automation.save_vision_annotations`
      （开发者调试页的「识别成功时保存带框截图」开关）；显式传 True/False 可覆盖配置。
      开启时把带框截图存到 `user_data/debug/vision_<时间戳>.png`（每处命中都画框编号）。
    """
    if annotate_result is None:
        annotate_result = bool(config.automation.save_vision_annotations)
    templates = _template_paths(image_path)
    if not templates:
        return RecognizeResult(
            False, (), "请先添加至少一张模板图片（调试页的模板列表，或 --recognize 参数）"
        )
    keyword = config.automation.window_title_keyword
    hwnd = find_window(keyword)
    if hwnd is None:
        return RecognizeResult(
            False, (), f"未找到标题含“{keyword}”的窗口，请确认游戏已窗口化运行"
        )
    if not is_window_ready(hwnd):
        return RecognizeResult(False, (), "游戏窗口已最小化或不可见，请恢复窗口后重试")

    capture_fn = capture or capture_client_bgr
    try:
        haystack = capture_fn(hwnd)
    except VisionError as exc:
        return RecognizeResult(False, (), str(exc))
    except Exception as exc:                       # 截图的 Win32 异常也要转成可读结果
        logger.exception("图像识别截图失败")
        return RecognizeResult(False, (), f"图像识别失败：{exc}")

    height, width = haystack.shape[:2]
    window_size = (int(width), int(height))
    mode = "多尺度" if allow_scale else "原始尺寸"
    tried: list[str] = []
    for index, path in enumerate(templates, start=1):
        try:
            template = load_template(path)
        except VisionError as exc:
            logger.warning("模板不可用，跳过继续试下一张：%s（%s）", path, exc)
            tried.append(f"{path.name}（{exc}）")
            continue
        try:
            if allow_scale:
                matches = tuple(
                    locate_all_scaled(
                        haystack, template, threshold,
                        max_results=max_results, scale_range=scale_range,
                    )
                )
            else:
                matches = tuple(locate_all(haystack, template, threshold, max_results=max_results))
        except VisionError as exc:
            logger.warning("模板匹配失败，跳过继续试下一张：%s（%s）", path, exc)
            tried.append(f"{path.name}（{exc}）")
            continue
        except Exception as exc:
            logger.exception("图像识别出错（模板 %s）", path)
            tried.append(f"{path.name}（匹配出错：{exc}）")
            continue
        if not matches:
            tried.append(f"{path.name}（未命中）")
            continue
        return _success_result(
            path, index, len(templates), matches, haystack, threshold, max_results,
            annotate_result=bool(annotate_result),
        )

    lines = [f"未识别到目标（阈值 {threshold:.2f}，截图 {width}x{height}，匹配方式：{mode}）"]
    if len(tried) == 1:
        lines.append(f"模板：{tried[0]}")
    else:
        lines.append(f"已试 {len(templates)} 张模板：")
        lines.extend(f"  {index}) {item}" for index, item in enumerate(tried, start=1))
    message = "\n".join(lines)
    logger.info("图像识别未命中：试过 %d 张模板", len(templates))
    return RecognizeResult(
        False, (), message, window_size=window_size, tried_templates=tuple(tried)
    )


def _success_result(
    path: Path,
    index: int,
    total: int,
    matches: tuple[Match, ...],
    haystack: np.ndarray,
    threshold: float,
    max_results: int,
    annotate_result: bool,
) -> RecognizeResult:
    """命中后组织消息（含"用的是哪张模板"与"默认使用哪一处"）。"""
    height, width = haystack.shape[:2]
    window_size = (int(width), int(height))
    annotated_path: Path | None = None
    if annotate_result:
        annotated_path = _save_annotated(haystack, matches)

    best = matches[0]
    scale_text = f"，缩放匹配 {best.scale:.2f}x" if abs(best.scale - 1.0) >= 1e-3 else ""
    lines = [
        f"识别成功：命中 {len(matches)} 处"
        f"（截图 {width}x{height}，阈值 {threshold:.2f}{scale_text}）",
        f"模板：{path.name}（第 {index}/{total} 张）" if total > 1 else f"模板：{path.name}",
    ]
    if len(matches) > 1:
        lines.append(f"使用值：第 1 处（匹配度最高，共 {len(matches)} 处）")
    if len(matches) >= max_results:
        lines.append(f"注意：已达上限 {max_results} 处，可能还有更多（可调大「最多列出」）")
    for number, match in enumerate(matches, start=1):
        lines.append(f"  {number}) 客户区 {match.describe()}")
    if annotated_path is not None:
        lines.append(f"带框截图：{annotated_path}")
    message = "\n".join(lines)
    logger.info(
        "图像识别完成：模板 %s 命中 %d 处，最佳 %s", path.name, len(matches), best.describe()
    )
    return RecognizeResult(
        True, matches, message, window_size=window_size,
        annotated_path=annotated_path, matched_template=path,
    )


def capture_window(
    config: AppConfig, capture: Callable[[int], np.ndarray] | None = None
) -> tuple[np.ndarray | None, str]:
    """截取当前游戏窗口客户区；返回 (图像, 错误消息)。成功时错误消息为空串。

    供「框选截图生成模板」等入口复用：统一做窗口存在性与就绪校验，失败一律转可读消息。
    """
    keyword = config.automation.window_title_keyword
    hwnd = find_window(keyword)
    if hwnd is None:
        return None, f"未找到标题含“{keyword}”的窗口，请确认游戏已窗口化运行"
    if not is_window_ready(hwnd):
        return None, "游戏窗口已最小化或不可见，请恢复窗口后重试"
    capture_fn = capture or capture_client_bgr
    try:
        return capture_fn(hwnd), ""
    except VisionError as exc:
        return None, str(exc)
    except Exception as exc:                       # 截图的 Win32 异常也要转成可读消息
        logger.exception("截取游戏窗口失败")
        return None, f"截取游戏窗口失败：{exc}"


def _save_annotated(image: np.ndarray, matches: tuple[Match, ...]) -> Path | None:
    """保存带框截图；保存失败只记日志（识别结果本身仍然有效）。"""
    try:
        debug_dir = get_debug_dir()
        path = debug_dir / f"vision_{datetime.now():%Y%m%d_%H%M%S}.png"
        return save_image(path, annotate(image, matches))
    except Exception as exc:
        logger.warning("保存识别结果截图失败：%s", exc)
        return None


# ------------------------------------------------- 「在本图试识别」（D1：框选弹窗自检）

PROBE_MAX_LISTED = 5          # 消息里最多列出几处位置（其余写"等 N 处"，图上的框全画）


@dataclass(frozen=True)
class TemplateProbeResult:
    """「把这块选区当模板、在同一张图上试识别」的结论。

    - `matches` 含**自己那一处**（模板就是从这张图裁的，分数必然接近 1.0），`self_index` 标出它的下标；
    - `duplicates`＝除自己以外的命中数 —— **这才是给用户看的数字**：0 表示这块区域在画面里独一无二，
      >0 表示还有别处长一样，真识别时可能选错地方；
    - `truncated` 表示触到了 `max_results` 上限（可能还有更多）。
    """

    region: tuple[int, int, int, int]
    matches: tuple[Match, ...]
    self_index: int
    threshold: float
    truncated: bool
    message: str

    @property
    def self_match(self) -> Match | None:
        """自己那一处（正常情况必有；异常时为 None）。"""
        if 0 <= self.self_index < len(self.matches):
            return self.matches[self.self_index]
        return None

    @property
    def others(self) -> tuple[Match, ...]:
        """除自己以外的命中（画在图上、列在消息里的就是这些）。"""
        return tuple(
            match for index, match in enumerate(self.matches) if index != self.self_index
        )

    @property
    def duplicates(self) -> int:
        return len(self.others)


def probe_region_on_image(
    image_bgr: np.ndarray,
    region: tuple[int, int, int, int],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> TemplateProbeResult:
    """把 `region` 那块当模板，在**同一张图**上匹配一次（用户 2026-09-20 勾选的 D1）。

    为什么需要它：光看截图，用户没法判断"这块区域在画面里是不是独一无二"；等到真识别时
    才发现有几处长得一样，就只能靠猜坐标。这里当场给出答案。

    只做 **1:1 匹配**：模板就是从这张图裁下来的，缩放搜索没有意义，还慢好几倍。
    选区非法（越界/太小）时抛可读 `VisionError`（调用方转成提示），绝不返回假结论。
    """
    image_height, image_width = image_bgr.shape[:2]
    x, y, width, height = (int(value) for value in region)
    if width < MIN_TEMPLATE_SIDE or height < MIN_TEMPLATE_SIDE:
        raise VisionError(
            f"选区太小（{width}x{height}），至少 {MIN_TEMPLATE_SIDE}x{MIN_TEMPLATE_SIDE} 像素才能试识别"
        )
    if x < 0 or y < 0 or x + width > image_width or y + height > image_height:
        raise VisionError(
            f"选区 ({x}, {y}, {width}, {height}) 超出截图范围（{image_width}x{image_height}）"
        )
    template = image_bgr[y : y + height, x : x + width]
    max_results = max(int(max_results), 1)
    matches = tuple(locate_all(image_bgr, template, threshold=threshold, max_results=max_results))

    self_index = -1
    for index, match in enumerate(matches):
        if abs(match.left - x) <= 1 and abs(match.top - y) <= 1:
            self_index = index
            break
    result = TemplateProbeResult(
        region=(x, y, width, height), matches=matches, self_index=self_index,
        threshold=float(threshold), truncated=len(matches) >= max_results, message="",
    )
    logger.info(
        "框选自检：选区 (%d, %d, %d, %d) 在 %dx%d 的画面上命中 %d 处（除自己 %d 处）",
        x, y, width, height, image_width, image_height, len(matches), result.duplicates,
    )
    return replace(result, message=_probe_message(result))


def _probe_message(result: TemplateProbeResult, max_listed: int = PROBE_MAX_LISTED) -> str:
    """组织「在本图试识别」的人读结论（分成：独一无二 / 有多处 / 异常零命中）。

    措辞必须**限定在这次试识别成立的条件上**（评审 P2-2）：试识别用的是 **1:1 匹配 + 当前阈值**，
    而正式识别还会搜缩放版本（0.3x–4.0x）且阈值可能被调低，两种差异都只会让正式识别**命中更多处**。
    因此这里只说"本图 1:1 匹配（阈值 …）下只命中你框的这一处"，**不许**写成"识别时不会认错"。
    """
    if not result.matches:
        return (
            "试识别异常：连你框的这块都没找到（模板就是从这张图裁下来的，正常情况下必然命中）——"
            "请把这次操作和日志一并反馈"
        )
    self_match = result.self_match
    best_score = self_match.score if self_match is not None else result.matches[0].score
    if result.duplicates == 0:
        return (
            f"试识别：本图 1:1 匹配（阈值 {result.threshold:.2f}）下只命中你框的这一处"
            f"（匹配度 {best_score:.3f}）—— 这块区域在这张图上没有重复；"
            f"正式识别还会搜缩放版本、阈值也可能更低，所以仍要挑画面里不会变的细节"
        )
    listed = "、".join(
        f"({match.center[0]}, {match.center[1]})" for match in result.others[:max_listed]
    )
    if result.duplicates > max_listed:
        remaining = result.duplicates - max_listed
        listed += f" 等（另有 {remaining} 处未列出）"
    head = (
        f"试识别：本图 1:1 匹配（阈值 {result.threshold:.2f}）共 {len(result.matches)} 处相似，"
        f"除你框的还有 {result.duplicates} 处：{listed}"
    )
    lines = [
        head,
        "⚠ 识别时可能选中其中任意一处：建议把选区改小到只包含独特细节（例如数字/图标），或改用更靠得住的特征",
    ]
    if result.truncated:
        lines.append(f"注意：已达上限 {len(result.matches)} 处，可能还有更多")
    return "\n".join(lines)
