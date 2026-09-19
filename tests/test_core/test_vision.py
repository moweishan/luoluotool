"""core.vision 测试：找窗口 → 截图 → 匹配 → 坐标结果的编排（注入假截图/假窗口，零真实操作）。"""

import numpy as np
import pytest

from luoluotool.automation import vision as automation_vision
from luoluotool.config.models import AppConfig
from luoluotool.core import vision as core_vision


def _pattern(height: int = 10, width: int = 20) -> np.ndarray:
    pattern = np.zeros((height, width, 3), dtype=np.uint8)
    pattern[:, : width // 2] = 255
    pattern[::3, :] = 128
    return pattern


def _haystack(height: int = 120, width: int = 200) -> np.ndarray:
    canvas = np.full((height, width, 3), 40, dtype=np.uint8)
    canvas[::7, :] = 60
    canvas[:, ::11] = 55
    return canvas


@pytest.fixture
def template_file(tmp_path):
    """写一张模板图片文件（真实存在，走 load_template）。

    用 imencode + tofile 写盘：`cv2.imwrite` 在 Windows 上不支持中文路径。
    """
    import cv2

    pattern = _pattern()
    path = tmp_path / "template.png"
    ok, buffer = cv2.imencode(".png", pattern)
    assert ok
    buffer.tofile(str(path))
    return path, pattern


def _patch_window(monkeypatch, hwnd=555, ready=True):
    monkeypatch.setattr(core_vision, "find_window", lambda keyword: hwnd)
    monkeypatch.setattr(core_vision, "is_window_ready", lambda h: ready)


def test_recognize_returns_client_coordinates(monkeypatch, template_file, tmp_path) -> None:
    """正常识别：返回客户区坐标（中心/左上/尺寸）与匹配度，并保存带框截图。"""
    template_path, pattern = template_file
    canvas = _haystack()
    canvas[30 : 30 + pattern.shape[0], 50 : 50 + pattern.shape[1]] = pattern
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    result = core_vision.recognize_in_window(
        AppConfig.default(), template_path, capture=lambda hwnd: canvas
    )
    assert result.found is True
    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.center == (60, 35)
    assert (match.left, match.top) == (50, 30)
    assert match.score > 0.99
    assert result.window_size == (200, 120)
    assert "识别成功" in result.message and "(60, 35)" in result.message
    assert result.annotated_path is not None and result.annotated_path.is_file()


def test_recognize_reports_not_found(monkeypatch, template_file, tmp_path) -> None:
    """没找到目标：found=False + 说明阈值，且不产生带框截图。"""
    template_path, _ = template_file
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    result = core_vision.recognize_in_window(
        AppConfig.default(), template_path, threshold=0.95, capture=lambda hwnd: _haystack()
    )
    assert result.found is False
    assert result.matches == ()
    assert "未识别到目标" in result.message and "0.95" in result.message
    assert result.annotated_path is None


def test_recognize_without_window(monkeypatch, template_file) -> None:
    """找不到游戏窗口：给出可读提示，不尝试截图。"""
    template_path, _ = template_file
    monkeypatch.setattr(core_vision, "find_window", lambda keyword: None)

    def forbidden(hwnd):                       # 不应被调用
        raise AssertionError("窗口不存在时不应截图")

    result = core_vision.recognize_in_window(AppConfig.default(), template_path, capture=forbidden)
    assert result.found is False
    assert "未找到标题含" in result.message


def test_recognize_when_window_minimized(monkeypatch, template_file) -> None:
    """窗口最小化/不可见：拒绝识别并提示先恢复窗口。"""
    template_path, _ = template_file
    _patch_window(monkeypatch, ready=False)
    result = core_vision.recognize_in_window(
        AppConfig.default(), template_path, capture=lambda hwnd: _haystack()
    )
    assert result.found is False
    assert "最小化" in result.message or "不可见" in result.message


def test_recognize_reports_bad_template(monkeypatch, tmp_path) -> None:
    """模板文件不可用时给出可读错误（不抛异常给 GUI 线程）。"""
    _patch_window(monkeypatch)
    result = core_vision.recognize_in_window(
        AppConfig.default(), tmp_path / "缺失.png", capture=lambda hwnd: _haystack()
    )
    assert result.found is False
    assert "无法读取模板图片" in result.message


def test_recognize_reports_capture_failure(monkeypatch, template_file) -> None:
    """截图失败（窗口关闭/权限不足）也要转成可读结果。"""
    template_path, _ = template_file
    _patch_window(monkeypatch)

    def boom(hwnd):
        raise automation_vision.VisionError("截图失败：窗口已关闭")

    result = core_vision.recognize_in_window(AppConfig.default(), template_path, capture=boom)
    assert result.found is False
    assert "截图失败" in result.message


def test_recognize_can_skip_annotation(monkeypatch, template_file, tmp_path) -> None:
    """annotate_result=False 时不写截图文件（调试页里可选，避免刷盘）。"""
    template_path, pattern = template_file
    canvas = _haystack()
    canvas[10 : 10 + pattern.shape[0], 10 : 10 + pattern.shape[1]] = pattern
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    result = core_vision.recognize_in_window(
        AppConfig.default(), template_path, annotate_result=False, capture=lambda hwnd: canvas
    )
    assert result.found is True
    assert result.annotated_path is None
    assert list(tmp_path.glob("vision_*.png")) == []


def test_recognize_finds_multiple_targets(monkeypatch, template_file, tmp_path) -> None:
    """多处命中：全部返回（按匹配度降序），消息里给出命中数量。"""
    template_path, pattern = template_file
    canvas = _haystack(120, 300)
    canvas[20 : 20 + pattern.shape[0], 20 : 20 + pattern.shape[1]] = pattern
    canvas[70 : 70 + pattern.shape[0], 200 : 200 + pattern.shape[1]] = pattern
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    result = core_vision.recognize_in_window(
        AppConfig.default(), template_path, capture=lambda hwnd: canvas
    )
    assert result.found is True
    assert len(result.matches) == 2
    assert {(m.center) for m in result.matches} == {(30, 25), (210, 75)}
    assert "命中 2 处" in result.message


def test_recognize_annotation_follows_config_option(monkeypatch, template_file, tmp_path) -> None:
    """默认（annotate_result=None）时按配置 `automation.save_vision_annotations` 决定是否存带框截图。"""
    template_path, pattern = template_file
    canvas = _haystack()
    canvas[30 : 30 + pattern.shape[0], 50 : 50 + pattern.shape[1]] = pattern
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    config = AppConfig.default()
    config.automation.save_vision_annotations = True
    result = core_vision.recognize_in_window(config, template_path, capture=lambda hwnd: canvas)
    assert result.found is True and result.annotated_path is not None

    config.automation.save_vision_annotations = False
    result2 = core_vision.recognize_in_window(config, template_path, capture=lambda hwnd: canvas)
    assert result2.found is True and result2.annotated_path is None
    assert "带框截图" not in result2.message
    assert len(list(tmp_path.glob("vision_*.png"))) == 1      # 只有第一次留下文件


def test_recognize_explicit_annotate_overrides_config(monkeypatch, template_file, tmp_path) -> None:
    """显式传 annotate_result 时优先于配置（CLI 的 --no-annotate 走这条）。"""
    template_path, pattern = template_file
    canvas = _haystack()
    canvas[5 : 5 + pattern.shape[0], 5 : 5 + pattern.shape[1]] = pattern
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    config = AppConfig.default()
    config.automation.save_vision_annotations = True
    result = core_vision.recognize_in_window(
        config, template_path, annotate_result=False, capture=lambda hwnd: canvas
    )
    assert result.annotated_path is None
    assert list(tmp_path.glob("vision_*.png")) == []


def test_cli_recognize_follows_config_annotation_option(monkeypatch, template_file, tmp_path, capsys) -> None:
    """`--recognize` 不带 --no-annotate 时，跟随配置里的带框截图开关。"""
    from luoluotool.__main__ import main
    from luoluotool.config import store

    template_path, pattern = template_file
    canvas = _haystack()
    canvas[10 : 10 + pattern.shape[0], 10 : 10 + pattern.shape[1]] = pattern
    _patched_cli_env(monkeypatch, canvas, tmp_path)

    config = AppConfig.default()
    config.automation.save_vision_annotations = False
    config_path = tmp_path / "config.json"
    store.save(config, config_path)

    code = main(["--recognize", str(template_path), "--config", str(config_path)])
    out = capsys.readouterr().out
    assert code == 0 and "识别成功" in out
    assert "带框截图" not in out
    assert list(tmp_path.glob("vision_*.png")) == []


# ---------------------------------------------------------------- 命令行入口


def _patched_cli_env(monkeypatch, canvas, tmp_path) -> None:
    """让 CLI 走注入的假截图（不碰真实窗口），并把带框截图写到 tmp。"""
    monkeypatch.setattr(core_vision, "find_window", lambda keyword: 555)
    monkeypatch.setattr(core_vision, "is_window_ready", lambda hwnd: True)
    monkeypatch.setattr(core_vision, "capture_client_bgr", lambda hwnd: canvas)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)


def test_cli_recognize_prints_coordinates(monkeypatch, template_file, tmp_path, capsys) -> None:
    """`--recognize` 命中时打印客户区坐标并返回退出码 0。"""
    from luoluotool.__main__ import main

    template_path, pattern = template_file
    canvas = _haystack()
    canvas[30 : 30 + pattern.shape[0], 50 : 50 + pattern.shape[1]] = pattern
    _patched_cli_env(monkeypatch, canvas, tmp_path)

    code = main(["--recognize", str(template_path), "--config", str(tmp_path / "none.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "识别成功" in out
    assert "中心 (60, 35)" in out
    assert "带框截图" in out


def test_cli_recognize_returns_1_when_not_found(monkeypatch, template_file, tmp_path, capsys) -> None:
    """没命中时退出码 1（便于脚本判断），并说明阈值。"""
    from luoluotool.__main__ import main

    template_path, _ = template_file
    _patched_cli_env(monkeypatch, _haystack(), tmp_path)

    code = main([
        "--recognize", str(template_path), "--threshold", "0.95",
        "--config", str(tmp_path / "none.json"),
    ])
    out = capsys.readouterr().out
    assert code == 1
    assert "未识别到目标" in out and "0.95" in out


def test_cli_recognize_can_skip_annotate(monkeypatch, template_file, tmp_path, capsys) -> None:
    """`--no-annotate` 时不写带框截图。"""
    from luoluotool.__main__ import main

    template_path, pattern = template_file
    canvas = _haystack()
    canvas[5 : 5 + pattern.shape[0], 5 : 5 + pattern.shape[1]] = pattern
    _patched_cli_env(monkeypatch, canvas, tmp_path)

    code = main([
        "--recognize", str(template_path), "--no-annotate", "--config", str(tmp_path / "none.json"),
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "带框截图" not in out
    assert list(tmp_path.glob("vision_*.png")) == []


def test_cli_recognize_rejects_bad_threshold(tmp_path, capsys) -> None:
    """阈值必须在 (0, 1]：非法值直接退出码 2，不进入识别流程。"""
    from luoluotool.__main__ import main

    code = main(["--recognize", str(tmp_path / "x.png"), "--threshold", "1.5"])
    assert code == 2
    assert "阈值必须大于 0 且不超过 1" in capsys.readouterr().out


# ------------------------------------------------- 截图给「框选生成模板」用


def test_capture_window_returns_image(monkeypatch) -> None:
    """正常情况：返回截图数组与空消息（不含任何输入）。"""
    _patch_window(monkeypatch)
    image, message = core_vision.capture_window(
        AppConfig.default(), capture=lambda hwnd: _haystack()
    )
    assert image is not None and image.shape == (120, 200, 3)
    assert message == ""


def test_capture_window_without_window(monkeypatch) -> None:
    """找不到窗口：不截图，返回可读消息。"""
    monkeypatch.setattr(core_vision, "find_window", lambda keyword: None)

    def forbidden(hwnd):
        raise AssertionError("窗口不存在时不应截图")

    image, message = core_vision.capture_window(AppConfig.default(), capture=forbidden)
    assert image is None and "未找到标题含" in message


def test_capture_window_when_minimized(monkeypatch) -> None:
    """窗口最小化：拒绝截图并提示恢复窗口。"""
    _patch_window(monkeypatch, ready=False)
    image, message = core_vision.capture_window(
        AppConfig.default(), capture=lambda hwnd: _haystack()
    )
    assert image is None and ("最小化" in message or "不可见" in message)


def test_capture_window_reports_capture_failure(monkeypatch) -> None:
    """截图抛错：转成可读消息，不向上抛。"""
    _patch_window(monkeypatch)

    def boom(hwnd):
        raise automation_vision.VisionError("截图失败：窗口已关闭")

    image, message = core_vision.capture_window(AppConfig.default(), capture=boom)
    assert image is None and "截图失败" in message


# ------------------------------------------------ 多张模板（任一张命中即用它的值）


def _pattern_b(height: int = 16, width: int = 16) -> np.ndarray:
    """第二张模板用的图案（与 `_pattern` 结构差异大，避免互相误匹配）。"""
    pattern = np.full((height, width, 3), 30, dtype=np.uint8)
    pattern[4:12, 4:12] = 240
    pattern[::2, ::2] = 90
    return pattern


def _write_png(path, pattern) -> None:
    import cv2

    ok, buffer = cv2.imencode(".png", pattern)
    assert ok
    buffer.tofile(str(path))


@pytest.fixture
def two_templates(tmp_path):
    """写两张模板图片：t1 = 条纹图案，t2 = 方块图案。"""
    first = tmp_path / "t1.png"
    second = tmp_path / "t2.png"
    _write_png(first, _pattern())
    _write_png(second, _pattern_b())
    return (first, second), (_pattern(), _pattern_b())


def test_recognize_uses_first_template_that_matches(monkeypatch, two_templates, tmp_path) -> None:
    """多张模板：按顺序试，第一张命中就用它的结果（后面的不再试）。"""
    (first, second), (pattern_a, _) = two_templates
    canvas = _haystack(160, 300)
    canvas[20 : 20 + pattern_a.shape[0], 20 : 20 + pattern_a.shape[1]] = pattern_a
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    result = core_vision.recognize_in_window(
        AppConfig.default(), [first, second], capture=lambda hwnd: canvas
    )
    assert result.found is True
    assert result.matched_template == first
    assert result.matches[0].center == (30, 25)
    assert "t1.png" in result.message and "第 1/2 张" in result.message


def test_recognize_falls_through_to_second_template(monkeypatch, two_templates, tmp_path) -> None:
    """第一张模板在画面里没有时，自动改用第二张（并报告用的是哪一张）。

    这里把阈值提到 0.9：实测 t1（条纹）缩到 0.5x 时会"蹭"上 t2 的亮块区拿到 0.883，
    按默认 0.85 就算第一张命中了。这正是"先用先命中"策略的固有权衡——模板之间若互相
    形似，应把阈值调高（或让模板更有辨识度）。
    """
    (first, second), (_, pattern_b) = two_templates
    canvas = _haystack(160, 300)
    canvas[90 : 90 + pattern_b.shape[0], 240 : 240 + pattern_b.shape[1]] = pattern_b
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    result = core_vision.recognize_in_window(
        AppConfig.default(), [first, second], threshold=0.9, capture=lambda hwnd: canvas
    )
    assert result.found is True
    assert result.matched_template == second
    assert result.matches[0].center == (248, 98)
    assert "t2.png" in result.message and "第 2/2 张" in result.message
    assert "t1.png" not in result.message          # 未命中的那张不写成"命中模板"


def test_recognize_reports_all_templates_when_none_match(monkeypatch, two_templates, tmp_path) -> None:
    """全部模板都没命中：一条可读消息里列出试过的每张模板及各自结果。"""
    (first, second), _ = two_templates
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    result = core_vision.recognize_in_window(
        AppConfig.default(), [first, second], threshold=0.95, capture=lambda hwnd: _haystack()
    )
    assert result.found is False and result.matches == ()
    assert "未识别到目标" in result.message and "已试 2 张模板" in result.message
    assert "t1.png" in result.message and "t2.png" in result.message
    assert "未命中" in result.message


def test_recognize_skips_unreadable_template(monkeypatch, two_templates, tmp_path) -> None:
    """列表里有读不出来的图片时跳过它，继续用后面的模板（不整体失败）。"""
    (first, second), (_, pattern_b) = two_templates
    canvas = _haystack(160, 300)
    canvas[40 : 40 + pattern_b.shape[0], 40 : 40 + pattern_b.shape[1]] = pattern_b
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    result = core_vision.recognize_in_window(
        AppConfig.default(), [tmp_path / "缺失.png", second, first], capture=lambda hwnd: canvas
    )
    assert result.found is True and result.matched_template == second


def test_recognize_skips_flat_template(monkeypatch, tmp_path) -> None:
    """纯色模板会被跳过（会在平坦区域刷满分），消息里给出原因而不是一堆假坐标。"""
    flat = tmp_path / "flat.png"
    _write_png(flat, np.full((40, 40, 3), 180, dtype=np.uint8))
    _patch_window(monkeypatch)

    result = core_vision.recognize_in_window(
        AppConfig.default(), [flat], capture=lambda hwnd: _haystack()
    )
    assert result.found is False
    assert "纯色" in result.message and "flat.png" in result.message


def test_recognize_reports_broken_template_with_reason(monkeypatch, tmp_path) -> None:
    """只有坏图片时：消息里带上"无法读取模板图片"的原因（给用户可操作的提示）。"""
    _patch_window(monkeypatch)
    result = core_vision.recognize_in_window(
        AppConfig.default(),
        [tmp_path / "缺失.png", tmp_path / "也没有.png"],
        capture=lambda hwnd: _haystack(),
    )
    assert result.found is False
    assert "无法读取模板图片" in result.message
    assert "缺失.png" in result.message and "也没有.png" in result.message


def test_recognize_requires_at_least_one_template(monkeypatch) -> None:
    """模板列表为空：直接给可读提示，不截图、不识别。"""
    _patch_window(monkeypatch)

    def forbidden(hwnd):
        raise AssertionError("没有模板时不应截图")

    result = core_vision.recognize_in_window(AppConfig.default(), [], capture=forbidden)
    assert result.found is False
    assert "至少一张模板" in result.message


def test_recognize_captures_only_once_for_many_templates(monkeypatch, two_templates, tmp_path) -> None:
    """多张模板共用同一张截图（避免每张模板各截一次，也保证结果一致）。"""
    (first, second), (_, pattern_b) = two_templates
    canvas = _haystack(160, 300)
    canvas[60 : 60 + pattern_b.shape[0], 60 : 60 + pattern_b.shape[1]] = pattern_b
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    captures: list[int] = []

    def counting(hwnd):
        captures.append(hwnd)
        return canvas

    result = core_vision.recognize_in_window(AppConfig.default(), [first, second], capture=counting)
    assert result.found is True
    assert len(captures) == 1


# ------------------------------------------------ 一张模板命中多处（屏幕多个区域）


def test_recognize_lists_every_region_for_one_template(monkeypatch, template_file, tmp_path) -> None:
    """一张模板在屏幕上出现多次：全部列出，并指明默认使用哪一处（第 1 处＝匹配度最高）。"""
    template_path, pattern = template_file
    canvas = _haystack(160, 400)
    for x, y in ((20, 20), (150, 40), (300, 110)):
        canvas[y : y + pattern.shape[0], x : x + pattern.shape[1]] = pattern
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    result = core_vision.recognize_in_window(
        AppConfig.default(), template_path, capture=lambda hwnd: canvas
    )
    assert result.found is True
    assert len(result.matches) == 3
    assert "命中 3 处" in result.message
    assert "使用值" in result.message
    indexed = [line for line in result.message.splitlines() if line.strip().startswith(("1)", "2)", "3)"))]
    assert len(indexed) == 3


def test_recognize_region_count_follows_max_results(monkeypatch, template_file, tmp_path) -> None:
    """最多列出多少处：受 `max_results` 限制，触顶时消息里给出提示。"""
    template_path, pattern = template_file
    canvas = _haystack(160, 400)
    for x, y in ((20, 20), (150, 40), (300, 110)):
        canvas[y : y + pattern.shape[0], x : x + pattern.shape[1]] = pattern
    _patch_window(monkeypatch)
    monkeypatch.setattr(core_vision, "get_debug_dir", lambda: tmp_path)

    result = core_vision.recognize_in_window(
        AppConfig.default(), template_path, max_results=2, capture=lambda hwnd: canvas
    )
    assert result.found is True
    assert len(result.matches) == 2
    assert "已达上限 2" in result.message


# ------------------------------------------------ 命令行：多张模板 / 多区域上限


def test_cli_recognize_accepts_multiple_templates(
    monkeypatch, two_templates, tmp_path, capsys
) -> None:
    """`--recognize a.png b.png`：按顺序试，第二张命中时退出码 0 且打印它的结果。

    阈值用 0.9：条纹模板缩到 0.5x 会"蹭"上第二张的亮块区拿到 0.883（见上面同款测试的说明）。
    """
    from luoluotool.__main__ import main

    (first, second), (_, pattern_b) = two_templates
    canvas = _haystack(160, 300)
    canvas[70 : 70 + pattern_b.shape[0], 120 : 120 + pattern_b.shape[1]] = pattern_b
    _patched_cli_env(monkeypatch, canvas, tmp_path)

    code = main([
        "--recognize", str(first), str(second), "--threshold", "0.9",
        "--no-annotate", "--config", str(tmp_path / "none.json"),
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "识别成功" in out and "t2.png" in out and "第 2/2 张" in out
    assert "中心 (128, 78)" in out


def test_cli_recognize_max_results_limits_regions(
    monkeypatch, template_file, tmp_path, capsys
) -> None:
    """`--max-results 1`：一张模板命中多处时只列出 1 处（便于脚本取唯一坐标）。"""
    from luoluotool.__main__ import main

    template_path, pattern = template_file
    canvas = _haystack(160, 400)
    for x, y in ((20, 20), (150, 40), (300, 110)):
        canvas[y : y + pattern.shape[0], x : x + pattern.shape[1]] = pattern
    _patched_cli_env(monkeypatch, canvas, tmp_path)

    code = main([
        "--recognize", str(template_path), "--max-results", "1",
        "--no-annotate", "--config", str(tmp_path / "none.json"),
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "命中 1 处" in out
    assert "2)" not in out


def test_cli_recognize_rejects_bad_max_results(tmp_path, capsys) -> None:
    """`--max-results` 必须 ≥1：非法值退出码 2，不进入识别流程。"""
    from luoluotool.__main__ import main

    code = main(["--recognize", str(tmp_path / "x.png"), "--max-results", "0"])
    assert code == 2
    assert "max-results" in capsys.readouterr().out

