"""automation.vision 测试：模板匹配纯函数、模板加载、截图转数组（合成图像，不依赖游戏窗口）。"""

import numpy as np
import pytest

from luoluotool.automation import vision


def _pattern(height: int = 10, width: int = 20) -> np.ndarray:
    """造一个高对比度图案（BGR），便于稳定匹配。"""
    pattern = np.zeros((height, width, 3), dtype=np.uint8)
    pattern[:, : width // 2] = 255
    pattern[::3, :] = 128
    return pattern


def _haystack(height: int = 120, width: int = 200) -> np.ndarray:
    """造一张背景（带轻微纹理，避免全黑导致模板匹配退化）。"""
    canvas = np.full((height, width, 3), 40, dtype=np.uint8)
    canvas[::7, :] = 60
    canvas[:, ::11] = 55
    return canvas


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


# ---------------------------------------------------------------- 截图 → 数组


def test_capture_client_bgr_converts_bgra_bits(monkeypatch) -> None:
    """截图像素（BGRA 原始位）→ numpy 数组：形状/通道顺序/宽度补齐都要正确。"""
    width, height = 3, 2
    # 每行 4 字节对齐：3 像素 ×4 通道 = 12 字节（已是 4 的倍数）
    bits = bytes(
        [
            1, 2, 3, 0,     # 像素1 BGR
            4, 5, 6, 0,     # 像素2
            7, 8, 9, 0,     # 像素3
            10, 11, 12, 0, 13, 14, 15, 0, 16, 17, 18, 0,
        ]
    )
    monkeypatch.setattr(vision, "_render_client_bits", lambda hwnd: (width, height, bits))
    image = vision.capture_client_bgr(12345)
    assert image.shape == (height, width, 3)
    assert tuple(image[0, 0]) == (1, 2, 3)
    assert tuple(image[1, 2]) == (16, 17, 18)


def test_capture_client_bgr_handles_padding(monkeypatch) -> None:
    """宽度不是 4 的倍数时，行末可能有补齐字节，必须正确跳过。"""
    width, height = 1, 1
    bits = bytes([9, 8, 7, 0])      # 1 像素 + 3 字节补齐
    monkeypatch.setattr(vision, "_render_client_bits", lambda hwnd: (width, height, bits))
    image = vision.capture_client_bgr(1)
    assert tuple(image[0, 0]) == (9, 8, 7)


def test_capture_client_bgr_reports_render_failure(monkeypatch) -> None:
    """渲染失败（窗口已关闭/无权限）→ 可读错误，不返回空图。"""
    def boom(hwnd: int):
        raise vision.VisionError("截图失败：窗口已关闭")

    monkeypatch.setattr(vision, "_render_client_bits", boom)
    with pytest.raises(vision.VisionError):
        vision.capture_client_bgr(1)
