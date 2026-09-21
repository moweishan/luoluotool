"""模板区域质量评估（保存前的"可辨识度"检查）用例。

背景（用户 2026-09-21 勾选的 C3 + D2）：纯色/几乎没有明暗变化的区域当模板，
在真实画面上会刷出一堆"匹配度 1.000"的假坐标（实测一张纯色 260x260 命中 20 处）。
`load_template` 只在**纯色**时拒绝，介于"纯色"和"有纹理"之间的低对比度区域照样会存下来害人，
所以保存前要按**同一套判据 + 结构（边缘占比）**再检查一次。

阈值是拿真实素材标定的：`assets/templates/` 两张人工整理的模板与
`assets/anchors/` 里可用的框选产物，对比度（灰度标准差）≥ 11.3、边缘占比 ≥ 0.065；
而纯色/轻噪声是 ≤ 2.7 / 0.000 —— 两组之间留了很宽的安全带。
"""

import numpy as np
import pytest

from luoluotool.automation.template_match import (
    QUALITY_LOW_EDGE_RATIO,
    QUALITY_LOW_STD,
    RegionQuality,
    assess_region_quality,
)


def _flat(size: int = 60, value: int = 128) -> np.ndarray:
    return np.full((size, size, 3), value, dtype=np.uint8)


def _noise(size: int = 60, amplitude: int = 1, seed: int = 0) -> np.ndarray:
    """纯色 + ±amplitude 的均匀噪声（模拟"看着像纯色、其实有一点噪点"的区域）。"""
    rng = np.random.default_rng(seed)
    base = _flat(size).astype(np.int16)
    return (base + rng.integers(-amplitude, amplitude + 1, base.shape)).clip(0, 255).astype(np.uint8)


def _texture(width: int = 120, height: int = 60) -> np.ndarray:
    """斜条纹纹理（对比度与结构都够）。"""
    column = (np.arange(width) % 16 * 16).astype(np.uint8)
    return np.repeat(column[None, :, None], 3, axis=2).repeat(height, axis=0)


def _glyph(size: int = 60) -> np.ndarray:
    """纯色底上写一个字符：对比度够高、但边缘占比很低（真实模板常这样）。"""
    import cv2

    image = _flat(size)
    cv2.putText(image, "7", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
    return image


def _gradient(width: int = 120, height: int = 60) -> np.ndarray:
    """平滑横向渐变：对比度很高，但**几乎没有边缘**（结构太少）。"""
    column = np.linspace(20, 235, width).astype(np.uint8)
    return np.repeat(column[None, :, None], 3, axis=2).repeat(height, axis=0)


def test_pure_color_region_is_unusable() -> None:
    """纯色区域：判为 flat（不许当模板保存）。"""
    quality = assess_region_quality(_flat())

    assert quality.level == "flat"
    assert quality.is_usable is False
    assert quality.std == 0.0
    assert quality.message                             # 有可读原因（文案不锁死，只锁级别）


def test_light_noise_region_is_unusable() -> None:
    """±1 噪点（标准差 0.6）：肉眼是纯色，判 flat（不许当模板）。"""
    quality = assess_region_quality(_noise(amplitude=1))

    assert quality.level == "flat"
    assert quality.is_usable is False


def test_flat_region_with_small_noise_is_flagged_but_allowed() -> None:
    """±5 噪点：标准差约 2.1（**刚好越过** `is_blank_frame` 的 2.0 判据）、边缘占比 0。

    两个信号都弱 → 提示必须说清"几乎没有可辨识的细节"，
    但**不硬拦**：它至少还能被 `load_template` 读进来，低对比度有时是用户有意为之。
    """
    image = _noise(amplitude=5)
    assert float(image.std()) > 2.0                   # 守卫：确实越过了纯色判据

    quality = assess_region_quality(image)

    assert quality.level == "low"
    assert quality.is_usable is True
    assert quality.edge_ratio == 0.0
    assert "几乎没有" in quality.message               # 两个信号都弱 → 用更重的措辞


def test_large_noisy_flat_region_is_flagged_but_allowed() -> None:
    """大面积噪声（1600x1024）：抽样评估也要判得出来（大图不能因此漏过）。"""
    rng = np.random.default_rng(7)
    base = np.full((1024, 1600, 3), 128, dtype=np.float32)
    image = (base + rng.normal(0, 4, base.shape)).clip(0, 255).astype(np.uint8)

    quality = assess_region_quality(image)

    assert quality.level == "low"
    assert "几乎没有" in quality.message
    assert quality.width == 1600 and quality.height == 1024


def test_fine_stripes_are_not_misjudged_by_the_sampling(monkeypatch) -> None:
    """评审 P3-4：抽样可能把细周期纹理抽成"平" —— 判"纯色"时要用**全分辨率复核**一次。

    构造一幅 1 像素周期的黑白条纹大图，并把取样边长压到 8（步长 8 的抽样会把条纹抽成同一列、
    看起来像纯色）；复核后应当按真实结构判为可用，而不是误拦用户的模板。
    """
    from luoluotool.automation import template_match

    stripes = np.zeros((64, 64, 3), dtype=np.uint8)
    stripes[::2, :, :] = 255                     # 1 像素周期黑白条纹
    monkeypatch.setattr(template_match, "QUALITY_SAMPLE_PX", 8)   # 强制步长 > 1

    quality = assess_region_quality(stripes)

    assert quality.level == "ok", quality.message          # 复核后按真实结构判，不误拦
    assert quality.edge_ratio > 0


def test_textured_region_is_usable() -> None:
    """斜条纹（对比度和结构都够）：判为 ok。"""
    quality = assess_region_quality(_texture())
    assert quality.level == "ok"
    assert quality.is_usable is True
    assert quality.std >= QUALITY_LOW_STD
    assert quality.edge_ratio >= QUALITY_LOW_EDGE_RATIO


def test_single_glyph_region_is_usable() -> None:
    """纯底 + 一个字符：边缘占比低但对比度够 —— 属于**可用**模板，不能误报。"""
    quality = assess_region_quality(_glyph())

    assert quality.level == "ok"


def test_smooth_gradient_is_reported_as_low_not_flat() -> None:
    """平滑渐变：对比度够、结构几乎没有 —— 判 low（只提示、仍允许保存），不能判 flat。"""
    quality = assess_region_quality(_gradient())

    assert quality.std >= QUALITY_LOW_STD                          # 对比度是够的
    assert quality.edge_ratio < QUALITY_LOW_EDGE_RATIO             # 但几乎没有结构
    assert quality.level == "low"
    assert quality.is_usable is True


def test_real_templates_are_all_rated_usable() -> None:
    """标定守卫：`assets/templates/` 里人工整理的模板必须全部判为 ok。

    阈值一旦调得过高，这条会先红 —— 免得"防误匹配"的检查反过来拦住用户自己的好模板。
    """
    from pathlib import Path

    from luoluotool.automation.template_match import load_template

    templates = sorted((Path(__file__).resolve().parents[2] / "assets/templates").glob("*.png"))
    if not templates:
        pytest.skip("assets/templates 里还没有人工整理的模板")

    ratings = {path.name: assess_region_quality(load_template(path)).level for path in templates}

    assert set(ratings.values()) == {"ok"}, ratings


def test_report_carries_size_and_metrics() -> None:
    """评估结果要带上尺寸与两个指标（界面提示要用它们说明原因）。"""
    quality = assess_region_quality(_texture(width=100, height=40))

    assert isinstance(quality, RegionQuality)
    assert (quality.width, quality.height) == (100, 40)
    assert quality.std > 0 and 0.0 <= quality.edge_ratio <= 1.0
    assert quality.message                              # 人读说明非空
