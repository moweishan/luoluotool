"""框选弹窗「在本图试识别」（D1）的业务编排用例。

它要做的事：把**当前选区**当模板，在**同一张截图**上匹配一次，回答两个问题 ——
① 画面里除了你框的这块，还有没有别处长一样（有 → 真识别时可能选错地方）；
② 匹配度是多少（太低说明这块本身不稳）。

设计要点（写进测试就是不变量）：
- 模板就是从这张图裁下来的，所以**必然**命中"自己那一处"，它由 `self_index` 标出来，
  结论只按"除自己以外还有几处"给 —— 否则每块区域都会显示"命中 1 处"，等于没说；
- 只做 1:1 匹配（同图同尺寸，缩放搜索没有意义且慢好几倍）；
- 选区非法（越界 / 太小 / 空）抛可读 `VisionError`，由 GUI 转成提示，不静默给假结论。
"""

from __future__ import annotations

import numpy as np
import pytest

from luoluotool.automation.template_match import VisionError
from luoluotool.core import vision as vision_actions
from luoluotool.core.vision import TemplateProbeResult, probe_region_on_image

STAMP_SIZE = (40, 30)          # 图章（要测的那块）的宽高
STAMP_POSITIONS = [(40, 30), (150, 120), (300, 200)]


def _scene(positions: list[tuple[int, int]] | None = None, size: tuple[int, int] = (400, 300)) -> np.ndarray:
    """造一张有纹理的画面，并在指定位置贴上同一枚"图章"（同一枚 → 应该被认成同一件东西）。"""
    width, height = size
    rng = np.random.default_rng(20260921)
    scene = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
    stamp = rng.integers(0, 255, (STAMP_SIZE[1], STAMP_SIZE[0], 3), dtype=np.uint8)
    for x, y in positions or [STAMP_POSITIONS[0]]:
        scene[y : y + STAMP_SIZE[1], x : x + STAMP_SIZE[0]] = stamp
    return scene


def _region(position: tuple[int, int]) -> tuple[int, int, int, int]:
    return position[0], position[1], STAMP_SIZE[0], STAMP_SIZE[1]


def test_unique_region_reports_only_itself() -> None:
    """画面里只有这一枚图章：结论必须是"只命中你框的这一处"。"""
    scene = _scene([STAMP_POSITIONS[0]])

    result = probe_region_on_image(scene, _region(STAMP_POSITIONS[0]))

    assert isinstance(result, TemplateProbeResult)
    assert len(result.matches) == 1
    assert result.self_index == 0
    assert result.duplicates == 0
    assert result.matches[0].score > 0.99
    assert "1 处" in result.message or "只有" in result.message or "只命中" in result.message
    assert result.truncated is False


def test_duplicate_positions_are_all_listed() -> None:
    """同一枚图章贴了 3 处：三处都要报出来，"自己那一处"要被标出来。"""
    scene = _scene(STAMP_POSITIONS)

    result = probe_region_on_image(scene, _region(STAMP_POSITIONS[1]))

    assert len(result.matches) == 3
    assert result.duplicates == 2
    assert result.self_index >= 0
    self_match = result.matches[result.self_index]
    assert (self_match.left, self_match.top) == STAMP_POSITIONS[1]
    assert {(m.left, m.top) for m in result.matches} == set(STAMP_POSITIONS)
    assert "3 处" in result.message
    assert "可能" in result.message                      # 提醒"可能选错地方"


def test_duplicate_lines_do_not_exceed_the_limit() -> None:
    """触到 `max_results` 上限：结果里标记 `truncated`，消息里提示可能还有更多。"""
    scene = _scene(STAMP_POSITIONS)

    result = probe_region_on_image(scene, _region(STAMP_POSITIONS[1]), max_results=1)

    assert len(result.matches) == 1
    assert result.truncated is True
    assert "还有更多" in result.message


def test_message_lists_the_other_positions() -> None:
    """消息里要给出"另外几处"的位置（客户区中心坐标，用户能照着找过去）。"""
    scene = _scene(STAMP_POSITIONS)

    result = probe_region_on_image(scene, _region(STAMP_POSITIONS[0]))

    others = {position for position in STAMP_POSITIONS if position != STAMP_POSITIONS[0]}
    for x, y in others:
        center = (x + STAMP_SIZE[0] // 2, y + STAMP_SIZE[1] // 2)
        assert f"({center[0]}, {center[1]})" in result.message


def test_region_outside_the_image_is_rejected() -> None:
    """选区越界：抛可读 VisionError，不给"未命中"这种误导结论。"""
    scene = _scene()

    with pytest.raises(VisionError, match="选区"):
        probe_region_on_image(scene, (380, 280, 60, 60))


def test_too_small_region_is_rejected() -> None:
    """选区太小（<4 像素）：同样拒绝，别给出没有意义的匹配度。"""
    scene = _scene()

    with pytest.raises(VisionError, match="选区"):
        probe_region_on_image(scene, (10, 10, 3, 3))


def test_no_match_at_all_is_reported_as_abnormal(monkeypatch) -> None:
    """理论上"零命中"不该发生（模板就是从这张图裁的）——真发生时要说清是异常，而不是"没找到"。"""
    scene = _scene()
    monkeypatch.setattr(vision_actions, "locate_all", lambda *args, **kwargs: [])

    result = probe_region_on_image(scene, _region(STAMP_POSITIONS[0]))

    assert result.matches == ()
    assert result.self_index == -1
    assert "异常" in result.message or "没找到" in result.message
