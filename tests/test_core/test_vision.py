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
