"""automation.vision 测试：模板加载、匹配原语与多尺度（缩放）搜索。

全部用例只用合成图像，不依赖真实游戏窗口。
取景 / 渲染路径（假 GDI、黑帧兜底、客户区原点几何）的用例见同目录 test_vision_capture.py。
"""

import numpy as np
import pytest

from luoluotool.automation import multiscale, vision

from test_automation.vision_helpers import _haystack


def _pattern(height: int = 10, width: int = 20) -> np.ndarray:
    """造一个高对比度图案（BGR），便于稳定匹配。"""
    pattern = np.zeros((height, width, 3), dtype=np.uint8)
    pattern[:, : width // 2] = 255
    pattern[::3, :] = 128
    return pattern


def _paste(canvas: np.ndarray, pattern: np.ndarray, x: int, y: int) -> None:
    canvas[y : y + pattern.shape[0], x : x + pattern.shape[1]] = pattern


# ---------------------------------------------------------------- 模板加载


def test_load_template_reads_png_with_chinese_path(tmp_path) -> None:
    """模板文件用 imdecode 读取，支持中文/空格路径（imread/imwrite 在 Windows 上会失败）。

    注意：写测试文件也不能用 `cv2.imwrite`（同样不支持中文路径），要用 imencode + tofile。
    """
    import cv2

    path = tmp_path / "锚点 图.png"
    canvas = _haystack(40, 60)
    ok, buffer = cv2.imencode(".png", canvas)
    assert ok
    buffer.tofile(str(path))
    assert path.is_file()

    loaded = vision.load_template(path)
    assert loaded.shape == canvas.shape
    assert loaded.dtype == np.uint8


def test_load_template_missing_file_raises_readable(tmp_path) -> None:
    with pytest.raises(vision.VisionError) as excinfo:
        vision.load_template(tmp_path / "不存在.png")
    assert "无法读取模板图片" in str(excinfo.value)


def test_load_template_rejects_flat_image(tmp_path) -> None:
    """纯色模板必须被拒绝：平坦区域会给它满分（实测纯色 260x260 刷出 20 处 1.000）。"""
    import cv2

    path = tmp_path / "flat.png"
    ok, buffer = cv2.imencode(".png", np.full((60, 80, 3), 200, dtype=np.uint8))
    assert ok
    buffer.tofile(str(path))

    with pytest.raises(vision.VisionError) as excinfo:
        vision.load_template(path)
    assert "纯色" in str(excinfo.value)
    assert "flat.png" in str(excinfo.value)


def test_load_template_invalid_image_raises_readable(tmp_path) -> None:
    path = tmp_path / "bad.png"
    path.write_bytes(b"not an image")
    with pytest.raises(vision.VisionError) as excinfo:
        vision.load_template(path)
    assert "无法解析" in str(excinfo.value)


# ---------------------------------------------------------------- 单目标匹配


def test_locate_best_returns_known_position() -> None:
    """在已知位置贴图案 → 命中位置与匹配度必须正确。"""
    canvas = _haystack()
    pattern = _pattern()
    _paste(canvas, pattern, 50, 30)

    match = vision.locate_best(canvas, pattern)
    assert match is not None
    assert (match.left, match.top) == (50, 30)
    assert (match.width, match.height) == (20, 10)
    assert match.center == (60, 35)
    assert match.right_bottom == (70, 40)
    assert match.score > 0.99


def test_locate_returns_empty_when_absent() -> None:
    """图案不在画面里 → 返回空列表（阈值足够高时）。"""
    canvas = _haystack()
    pattern = _pattern()
    assert vision.locate_all(canvas, pattern, threshold=0.9) == []
    assert vision.locate_best(canvas, pattern, threshold=0.9) is None


def test_locate_threshold_is_respected() -> None:
    """轻微改动的图案：低阈值能命中、高阈值不能。"""
    canvas = _haystack()
    pattern = _pattern()
    _paste(canvas, pattern, 20, 40)
    noisy = pattern.copy()
    noisy[0:2, :] = 0          # 改动一小部分像素
    low = vision.locate_all(canvas, noisy, threshold=0.5)
    high = vision.locate_all(canvas, noisy, threshold=0.999)
    assert len(low) == 1
    assert high == []


def test_locate_works_on_color_haystack() -> None:
    """grayscale=False 时直接按彩色匹配，坐标语义不变。"""
    canvas = _haystack()
    pattern = _pattern()
    _paste(canvas, pattern, 5, 5)
    match = vision.locate_best(canvas, pattern, grayscale=False)
    assert match is not None and (match.left, match.top) == (5, 5)


def test_locate_accepts_grayscale_input() -> None:
    """输入为单通道灰度图时也能匹配（不做不必要的转换）。"""
    import cv2

    canvas = cv2.cvtColor(_haystack(), cv2.COLOR_BGR2GRAY)
    pattern = cv2.cvtColor(_pattern(), cv2.COLOR_BGR2GRAY)
    canvas[25 : 25 + pattern.shape[0], 15 : 15 + pattern.shape[1]] = pattern
    match = vision.locate_best(canvas, pattern)
    assert match is not None and match.center == (25, 30)


# ---------------------------------------------------------------- 多目标与去重


def test_locate_multiple_matches_sorted_by_score() -> None:
    """同一图案出现两次 → 两处命中，按匹配度降序；NMS 不会把相邻处合并掉。"""
    canvas = _haystack(120, 260)
    pattern = _pattern()
    _paste(canvas, pattern, 10, 20)      # 完全一致 → 分数 1.0
    _paste(canvas, pattern, 160, 60)     # 与背景略有叠加 → 分数略低

    matches = vision.locate_all(canvas, pattern, threshold=0.8)
    assert len(matches) == 2
    assert matches[0].score >= matches[1].score
    assert {(m.left, m.top) for m in matches} == {(10, 20), (160, 60)}


def test_locate_suppresses_overlapping_duplicates() -> None:
    """同一目标附近的重复命中会被 NMS 去掉（只保留最佳的 1 处）。"""
    canvas = _haystack()
    pattern = _pattern()
    _paste(canvas, pattern, 60, 50)
    matches = vision.locate_all(canvas, pattern, threshold=0.5)
    assert len(matches) == 1
    assert (matches[0].left, matches[0].top) == (60, 50)


def test_locate_respects_max_results() -> None:
    """max_results 限制返回条数（从高分到低分截断）。"""
    canvas = _haystack(200, 400)
    pattern = _pattern()
    for index in range(4):
        _paste(canvas, pattern, 20 + index * 90, 30)
    all_matches = vision.locate_all(canvas, pattern, threshold=0.8, max_results=10)
    assert len(all_matches) == 4
    limited = vision.locate_all(canvas, pattern, threshold=0.8, max_results=2)
    assert len(limited) == 2
    assert [m.score for m in limited] == sorted((m.score for m in all_matches), reverse=True)[:2]


def test_locate_rejects_template_larger_than_haystack() -> None:
    """模板比画面还大：给出可读错误（而不是毫无意义的匹配结果）。"""
    canvas = _haystack(40, 40)
    pattern = _pattern(60, 80)
    with pytest.raises(vision.VisionError) as excinfo:
        vision.locate_all(canvas, pattern)
    assert "模板比截图还大" in str(excinfo.value)


def test_match_describe_is_human_readable() -> None:
    match = vision.Match(left=10, top=20, width=20, height=10, score=0.987654)
    text = match.describe()
    assert "中心 (20, 25)" in text and "0.988" in text


# ---------------------------------------------------------------- 多尺度（缩放）匹配


def _rich_pattern(height: int = 40, width: int = 64) -> np.ndarray:
    """造一个"有信息量"的图案（多区块 + 斜纹 + 圆点）。

    多尺度测试必须用这种图案：20x10 那种小图案在任意缩放下都能"像"别的区域，
    缩放判断本身就没有唯一解（模板匹配的固有限制），拿它测多尺度没有意义。
    """
    import cv2

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    canvas[:, : width // 2] = 210
    canvas[: height // 2, :] = 120
    for index in range(0, height, 6):                     # 斜纹
        canvas[index : index + 2, :] = 60
    cv2.circle(canvas, (width // 2, height // 2), min(height, width) // 4, (255, 255, 255), -1)
    cv2.rectangle(canvas, (width - 12, 4), (width - 4, height - 4), (30, 30, 30), -1)
    return canvas


def _scaled(pattern: np.ndarray, scale: float) -> np.ndarray:
    import cv2

    height, width = pattern.shape[:2]
    return cv2.resize(
        pattern, (int(round(width * scale)), int(round(height * scale))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
    )


def test_locate_scaled_finds_enlarged_template() -> None:
    """画面被放大（模板需要放大后才匹配）：多尺度搜索必须找到，并报出缩放比例。"""
    canvas = _haystack(300, 500)
    pattern = _scaled(_rich_pattern(), 1.4)
    _paste(canvas, pattern, 60, 40)

    match = vision.locate_best_scaled(canvas, _rich_pattern(), threshold=0.9)
    assert match is not None
    assert abs(match.scale - 1.4) <= 0.03
    assert abs(match.left - 60) <= 3 and abs(match.top - 40) <= 3
    assert "缩放" in match.describe()


def test_locate_scaled_finds_shrunk_template() -> None:
    """画面被缩小（模板需要缩小后才匹配）同样要能找到。"""
    canvas = _haystack(300, 500)
    pattern = _scaled(_rich_pattern(), 0.6)
    _paste(canvas, pattern, 100, 80)

    match = vision.locate_best_scaled(canvas, _rich_pattern(), threshold=0.9)
    assert match is not None
    assert abs(match.scale - 0.6) <= 0.03
    assert abs(match.left - 100) <= 3 and abs(match.top - 80) <= 3


def test_locate_scaled_reports_scale_one_for_exact_match() -> None:
    """原始尺寸就匹配时，缩放应识别为 1.0x（不要瞎报缩放）。"""
    canvas = _haystack(300, 500)
    pattern = _rich_pattern()
    _paste(canvas, pattern, 50, 30)

    match = vision.locate_best_scaled(canvas, pattern, threshold=0.9)
    assert match is not None and abs(match.scale - 1.0) <= 0.03
    assert (match.left, match.top) == (50, 30)


def test_locate_scaled_finds_scale_between_coarse_steps() -> None:
    """回归：真实缩放落在粗搜两档之间（0.75x）也必须命中 —— 阈值必须在精修之后再判。

    实测过：0.70x 粗搜只有 0.83（低于 0.85），若在精修前就用阈值返回，就会漏掉
    精修后 0.74x 的 0.95 命中。
    """
    canvas = _haystack(300, 500)
    pattern = _scaled(_rich_pattern(), 0.75)
    _paste(canvas, pattern, 120, 90)

    match = vision.locate_best_scaled(canvas, _rich_pattern(), threshold=0.85)
    assert match is not None
    assert abs(match.scale - 0.75) <= 0.03
    assert abs(match.left - 120) <= 3 and abs(match.top - 90) <= 3


def test_locate_scaled_returns_empty_when_absent() -> None:
    """画面里没有目标时返回空（多尺度不能凭空匹配出来）。"""
    assert vision.locate_all_scaled(_haystack(), _rich_pattern(), threshold=0.9) == []
    assert vision.locate_best_scaled(_haystack(), _rich_pattern(), threshold=0.9) is None


def test_locate_scaled_multiple_targets_at_same_scale() -> None:
    """同一缩放下有多个目标：全部返回（NMS 不误合并）。"""
    canvas = _haystack(240, 560)
    pattern = _scaled(_rich_pattern(), 1.2)
    _paste(canvas, pattern, 20, 30)
    _paste(canvas, pattern, 300, 130)

    matches = vision.locate_all_scaled(canvas, _rich_pattern(), threshold=0.9)
    assert len(matches) == 2
    assert {m.center for m in matches} == {
        (20 + pattern.shape[1] // 2, 30 + pattern.shape[0] // 2),
        (300 + pattern.shape[1] // 2, 130 + pattern.shape[0] // 2),
    }
    assert all(abs(m.scale - 1.2) <= 0.03 for m in matches)


def test_locate_scaled_respects_scale_range() -> None:
    """限定缩放范围时，范围外的尺寸不会被匹配到。"""
    canvas = _haystack(300, 500)
    _paste(canvas, _scaled(_rich_pattern(), 1.8), 50, 50)
    assert vision.locate_best_scaled(
        canvas, _rich_pattern(), threshold=0.9, scale_range=(0.8, 1.2)
    ) is None
    assert vision.locate_best_scaled(
        canvas, _rich_pattern(), threshold=0.9, scale_range=(1.5, 2.0)
    ) is not None


def test_default_scale_range_is_fast_then_extended() -> None:
    """默认范围 0.3x–4.0x，且必须**分两档**搜：先 0.3x–2.0x 快搜，找不到才扩到 0.3x–4.0x。"""
    assert vision.DEFAULT_SCALE_RANGE == (0.30, 4.00)
    assert vision.SCALE_FAST_MAX == 2.00
    # 拆分后（2026-09-20）多尺度搜索在 automation.multiscale，vision 只再导出公共名字
    assert multiscale._scale_tiers(multiscale.DEFAULT_SCALE_RANGE) == [(0.30, 2.00), (0.30, 4.00)]
    assert multiscale._scale_tiers((0.8, 1.2)) == [(0.8, 1.2)]        # 范围本来就窄：只有一档
    assert multiscale._scale_tiers((2.5, 3.0)) == [(2.5, 3.0)]        # 整段都在快搜上界之上：也一档
    assert multiscale._scale_tiers((1.0, 2.5)) == [(1.0, 2.00), (1.0, 2.5)]


def _record_scales(monkeypatch, original: np.ndarray) -> list[float]:
    """记录多尺度搜索实际评估过的缩放比例（由候选模板宽度反推）。"""
    real_score = multiscale._best_score
    seen: list[float] = []

    def recording(source: np.ndarray, template: np.ndarray) -> float:
        seen.append(round(template.shape[1] / original.shape[1], 3))
        return real_score(source, template)

    monkeypatch.setattr(multiscale, "_best_score", recording)
    return seen


def test_locate_scaled_fast_pass_does_not_touch_extended_range(monkeypatch) -> None:
    """第一档（快搜）：目标在 0.3x–2.0x 内时，绝不评估 2.0x 以上的档位。"""
    canvas = _haystack(600, 800)
    pattern = _scaled(_rich_pattern(), 1.6)
    _paste(canvas, pattern, 300, 180)

    evaluated = _record_scales(monkeypatch, _rich_pattern())
    match = vision.locate_best_scaled(canvas, _rich_pattern(), threshold=0.9)
    assert match is not None
    assert abs(match.scale - 1.6) <= 0.03
    assert max(evaluated) <= vision.SCALE_FAST_MAX + 0.07


def test_locate_scaled_extended_pass_runs_when_fast_pass_misses(monkeypatch) -> None:
    """第二档（扩展）：快搜找不到时，必须把范围扩到 4.0x 继续搜。"""
    canvas = _haystack(600, 800)
    pattern = _scaled(_rich_pattern(), 3.5)
    _paste(canvas, pattern, 400, 250)

    evaluated = _record_scales(monkeypatch, _rich_pattern())
    match = vision.locate_best_scaled(canvas, _rich_pattern(), threshold=0.9)
    assert match is not None
    assert abs(match.scale - 3.5) <= 0.03
    assert max(evaluated) > vision.SCALE_FAST_MAX            # 证明第二档真的跑了


def test_locate_scaled_finds_three_tenths_scale() -> None:
    """下界放宽到 0.3x：画面被缩小到 0.3 倍也要能识别。"""
    canvas = _haystack(600, 800)
    pattern = _scaled(_rich_pattern(), 0.30)
    _paste(canvas, pattern, 300, 180)

    match = vision.locate_best_scaled(canvas, _rich_pattern(), threshold=0.9)
    assert match is not None
    assert abs(match.scale - 0.30) <= 0.03
    assert abs(match.left - 300) <= 3 and abs(match.top - 180) <= 3


def test_locate_scaled_finds_two_and_a_half_times_zoom() -> None:
    """画面放大到 2.5 倍也要能识别（放宽范围前 2.0x 是上界，超出就一律认不出）。"""
    canvas = _haystack(600, 800)
    pattern = _scaled(_rich_pattern(), 2.5)
    _paste(canvas, pattern, 300, 180)

    match = vision.locate_best_scaled(canvas, _rich_pattern(), threshold=0.9)
    assert match is not None
    assert abs(match.scale - 2.5) <= 0.03
    assert abs(match.left - 300) <= 4 and abs(match.top - 180) <= 4


def test_locate_scaled_stops_coarse_search_only_after_peak() -> None:
    """回归：粗搜不能"第一个够强的候选就停"，必须等分数越过峰值回落才停。

    实测踩到（真值 3.50x）：粗搜走到 3.30x 时分数 0.9018 已高于「阈值+0.05」，
    旧逻辑立刻结束粗搜，而精修窗口只有 ±0.06，够不到真值 3.50x（那里分数是 1.000）
    —— 结果报成 3.36x（0.933），框比目标小一圈。
    """
    canvas = _haystack(600, 800)
    pattern = _scaled(_rich_pattern(), 3.5)
    _paste(canvas, pattern, 400, 250)

    match = vision.locate_best_scaled(canvas, _rich_pattern(), threshold=0.9)
    assert match is not None
    assert abs(match.scale - 3.5) <= 0.03
    assert abs(match.left - 400) <= 4 and abs(match.top - 250) <= 4


def test_locate_scaled_handles_candidates_larger_than_canvas() -> None:
    """范围上界放到 4.0x 后，很多档位的模板会大于画面 —— 必须安全跳过，不是抛异常。"""
    canvas = _haystack(120, 200)
    assert vision.locate_all_scaled(canvas, _rich_pattern(), threshold=0.9) == []


def test_scale_candidates_are_sorted_and_deduplicated() -> None:
    """缩放候选列表：从小到大、去重、往返包含端点。"""
    scales = vision.scale_candidates((0.8, 1.2), 0.2)
    assert scales == [0.8, 1.0, 1.2]
    assert vision.scale_candidates((1.1, 0.9), 0.1) == [0.9, 1.0, 1.1]
    assert vision.scale_candidates((1.0, 1.0), 0.1) == [1.0]
