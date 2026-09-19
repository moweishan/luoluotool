"""图像识别的业务编排：找窗口 → 校验就绪 → 截图 → 模板匹配 → 返回客户区坐标。

与 GUI 无关（可被调试页、命令行或后续任务复用）：本模块只依赖 automation 层，
不 import PySide6；失败一律转成 `RecognizeResult`（不把异常抛给 GUI 线程）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from luoluotool.automation.input_sender import is_window_ready
from luoluotool.automation.vision import (
    DEFAULT_MAX_RESULTS,
    DEFAULT_THRESHOLD,
    Match,
    VisionError,
    annotate,
    capture_client_bgr,
    load_template,
    locate_all,
    save_image,
)
from luoluotool.automation.window import find_window
from luoluotool.config.models import AppConfig
from luoluotool.utils.paths import get_debug_dir

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecognizeResult:
    """识别结果：命中列表（客户区坐标）+ 人读消息 + 可选带框截图路径。"""

    found: bool
    matches: tuple[Match, ...]
    message: str
    window_size: tuple[int, int] | None = None
    annotated_path: Path | None = None


def recognize_in_window(
    config: AppConfig,
    image_path: str | Path,
    threshold: float = DEFAULT_THRESHOLD,
    max_results: int = DEFAULT_MAX_RESULTS,
    annotate_result: bool = True,
    capture: Callable[[int], np.ndarray] | None = None,
) -> RecognizeResult:
    """在当前游戏窗口客户区里查找 `image_path`，返回命中位置（客户区坐标）。

    - 窗口未找到 / 最小化 → 直接给可读结果，不截图；
    - `capture` 可注入（测试用）；默认走 `vision.capture_client_bgr`；
    - `annotate_result=True` 时把带框截图存到 `user_data/debug/vision_<时间戳>.png` 便于人工核对。
    """
    keyword = config.automation.window_title_keyword
    hwnd = find_window(keyword)
    if hwnd is None:
        return RecognizeResult(
            False, (), f"未找到标题含“{keyword}”的窗口，请确认游戏已窗口化运行"
        )
    if not is_window_ready(hwnd):
        return RecognizeResult(False, (), "游戏窗口已最小化或不可见，请恢复窗口后重试")

    try:
        template = load_template(image_path)
    except VisionError as exc:
        return RecognizeResult(False, (), str(exc))

    capture_fn = capture or capture_client_bgr
    try:
        haystack = capture_fn(hwnd)
        matches = tuple(locate_all(haystack, template, threshold, max_results=max_results))
    except VisionError as exc:
        return RecognizeResult(False, (), str(exc))
    except Exception as exc:                       # 截图的 Win32 异常也要转成可读结果
        logger.exception("图像识别失败")
        return RecognizeResult(False, (), f"图像识别失败：{exc}")

    height, width = haystack.shape[:2]
    window_size = (int(width), int(height))
    if not matches:
        return RecognizeResult(
            False, (), f"未识别到目标（阈值 {threshold:.2f}，截图 {width}x{height}）",
            window_size=window_size,
        )

    annotated_path: Path | None = None
    if annotate_result:
        annotated_path = _save_annotated(haystack, matches)

    best = matches[0]
    lines = [
        f"识别成功：命中 {len(matches)} 处（截图 {width}x{height}，阈值 {threshold:.2f}）"
    ]
    for index, match in enumerate(matches, start=1):
        lines.append(f"  {index}) 客户区 {match.describe()}")
    if annotated_path is not None:
        lines.append(f"带框截图：{annotated_path}")
    message = "\n".join(lines)
    logger.info("图像识别完成：命中 %d 处，最佳 %s", len(matches), best.describe())
    return RecognizeResult(True, matches, message, window_size=window_size,
                           annotated_path=annotated_path)


def _save_annotated(image: np.ndarray, matches: tuple[Match, ...]) -> Path | None:
    """保存带框截图；保存失败只记日志（识别结果本身仍然有效）。"""
    try:
        debug_dir = get_debug_dir()
        path = debug_dir / f"vision_{datetime.now():%Y%m%d_%H%M%S}.png"
        return save_image(path, annotate(image, matches))
    except Exception as exc:
        logger.warning("保存识别结果截图失败：%s", exc)
        return None


def format_matches_for_cli(result: RecognizeResult) -> str:
    """命令行输出（把 message 转成纯文本行，便于 `--recognize` 打印）。"""
    return result.message
