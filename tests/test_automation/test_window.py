"""automation.window 测试：路径/时间戳纯逻辑 + 注入假 win32 的查找/诊断流程。"""

from datetime import datetime
from pathlib import Path

import pytest

from luoluotool.automation import window


def test_screenshot_path_timestamp_naming(tmp_path) -> None:
    now = datetime(2026, 9, 8, 12, 34, 56)
    path = window.screenshot_path(tmp_path, now=now)
    assert path == tmp_path / "window_20260908123456.png"
    assert window.screenshot_path(tmp_path, now=now).name.startswith("window_")


def test_get_client_rect_computes_size(monkeypatch) -> None:
    monkeypatch.setattr(window.win32gui, "GetClientRect", lambda hwnd: (1, 2, 101, 52))
    assert window.get_client_rect(123) == (1, 2, 100, 50)


@pytest.fixture
def fake_enum(monkeypatch):
    """注入假 EnumWindows/GetWindowText/IsWindowVisible。"""

    def _apply(windows: list[tuple[int, str, bool]]) -> None:
        monkeypatch.setattr(
            window.win32gui, "EnumWindows",
            lambda cb, lp: [cb(h, None) for h, _, _ in windows],
        )
        monkeypatch.setattr(
            window.win32gui, "GetWindowText",
            lambda h: next(t for hw, t, _ in windows if hw == h),
        )
        monkeypatch.setattr(
            window.win32gui, "IsWindowVisible",
            lambda h: next(v for hw, _, v in windows if hw == h),
        )

    return _apply


def test_find_window_matches_visible_keyword(fake_enum) -> None:
    fake_enum([(10, "桃源深处有人家 客户端", True), (20, "记事本", True)])
    assert window.find_window("桃源") == 10


def test_find_window_skips_invisible(fake_enum) -> None:
    fake_enum([(10, "桃源深处有人家", False)])
    assert window.find_window("桃源") is None


def test_find_window_no_match_returns_none(fake_enum) -> None:
    fake_enum([(10, "记事本", True)])
    assert window.find_window("桃源") is None


def test_find_window_multiple_uses_first(caplog, fake_enum) -> None:
    fake_enum([(10, "桃源A", True), (20, "桃源B", True)])
    assert window.find_window("桃源") == 10
    assert "2 个匹配" in caplog.text


def test_diagnostic_not_found_message() -> None:
    """真实 EnumWindows 下不存在该窗口：返回明确提示（集成冒烟）。"""
    message = window.run_window_diagnostic("__luoluotool_不存在的窗口__", Path("."))
    assert "未找到" in message


def test_diagnostic_success_flow(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(window, "find_window", lambda keyword: 123)
    monkeypatch.setattr(window, "bring_to_front", lambda hwnd: calls.append("front"))
    monkeypatch.setattr(window, "get_client_rect", lambda hwnd: (0, 0, 800, 600))
    monkeypatch.setattr(window, "screenshot_client", lambda hwnd, p: calls.append("shot") or p)
    monkeypatch.setattr(window.win32gui, "GetWindowText", lambda hwnd: "游戏")
    message = window.run_window_diagnostic("桃源", tmp_path)
    assert calls == ["front", "shot"]
    assert "hwnd=123" in message
    assert "800x600" in message
    assert str(tmp_path) in message
