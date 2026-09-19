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


def test_client_area_offset_is_title_bar_plus_border(monkeypatch) -> None:
    """客户区相对窗口左上角的偏移 = 标题栏高度 + 边框（实测本作 (9, 37)）。

    取景必须按这个偏移抓，否则抓到的是"标题栏 + 客户区上半部分"，
    导致坐标整体偏下"标题栏高度"（2026-09-20 用户实测 bug）。
    """
    monkeypatch.setattr(window.win32gui, "GetWindowRect", lambda hwnd: (86, 0, 1704, 1070))
    monkeypatch.setattr(window.win32gui, "ClientToScreen", lambda hwnd, point: (95, 37))
    assert window.client_area_offset(123) == (9, 37)


def test_client_area_offset_is_zero_for_borderless_window(monkeypatch) -> None:
    """无边框全屏窗口：客户区就在窗口左上角，偏移必须是 (0, 0)（不能凭空加偏移）。"""
    monkeypatch.setattr(window.win32gui, "GetWindowRect", lambda hwnd: (0, 0, 1920, 1080))
    monkeypatch.setattr(window.win32gui, "ClientToScreen", lambda hwnd, point: (0, 0))
    assert window.client_area_offset(123) == (0, 0)


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
    monkeypatch.setattr(window, "bring_to_front", lambda hwnd: calls.append("front") or True)
    monkeypatch.setattr(window, "get_client_rect", lambda hwnd: (0, 0, 800, 600))
    monkeypatch.setattr(window, "screenshot_client", lambda hwnd, p: calls.append("shot") or p)
    monkeypatch.setattr(window.win32gui, "GetWindowText", lambda hwnd: "游戏")
    monkeypatch.setattr(window.win32gui, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(window, "is_window_elevated", lambda hwnd: None)
    message = window.run_window_diagnostic("桃源", tmp_path)
    assert calls == ["front", "shot"]
    assert "hwnd=123" in message
    assert "800x600" in message
    assert str(tmp_path) in message


def test_diagnostic_minimized_window_returns_hint(monkeypatch, tmp_path) -> None:
    """恢复置前后仍处于最小化：返回明确提示且不截图。"""
    calls: list[str] = []
    monkeypatch.setattr(window, "find_window", lambda keyword: 123)
    monkeypatch.setattr(window, "bring_to_front", lambda hwnd: calls.append("front") or True)
    monkeypatch.setattr(window, "screenshot_client", lambda hwnd, p: calls.append("shot") or p)
    monkeypatch.setattr(window.win32gui, "GetWindowText", lambda hwnd: "游戏")
    monkeypatch.setattr(window.win32gui, "IsIconic", lambda hwnd: True)
    monkeypatch.setattr(window, "is_process_elevated", lambda: True)
    monkeypatch.setattr(window, "is_window_elevated", lambda hwnd: True)
    message = window.run_window_diagnostic("桃源", tmp_path)
    assert calls == ["front"]
    assert "最小化" in message
    assert "截图" in message


def test_diagnostic_minimized_without_elevation_hints_admin(monkeypatch, tmp_path) -> None:
    """置前被拒（UIPI）且本进程未提权：提示以管理员身份运行。"""
    monkeypatch.setattr(window, "find_window", lambda keyword: 123)
    monkeypatch.setattr(window, "bring_to_front", lambda hwnd: False)
    monkeypatch.setattr(window, "screenshot_client", lambda hwnd, p: p)
    monkeypatch.setattr(window.win32gui, "GetWindowText", lambda hwnd: "游戏")
    monkeypatch.setattr(window.win32gui, "IsIconic", lambda hwnd: True)
    monkeypatch.setattr(window, "is_process_elevated", lambda: False)
    monkeypatch.setattr(window, "is_window_elevated", lambda hwnd: None)
    message = window.run_window_diagnostic("桃源", tmp_path)
    assert "最小化" in message
    assert "管理员" in message


def test_diagnose_window_requires_elevation_without_touching_window(monkeypatch, tmp_path) -> None:
    """权限不足时先要求提权，且完全不触碰游戏窗口（不恢复/不置前/不截图）。"""
    calls: list[str] = []
    monkeypatch.setattr(window, "find_window", lambda keyword: 123)
    monkeypatch.setattr(window, "is_process_elevated", lambda: False)
    monkeypatch.setattr(window, "is_window_elevated", lambda hwnd: True)
    monkeypatch.setattr(window, "bring_to_front", lambda hwnd: calls.append("front") or True)
    monkeypatch.setattr(window, "screenshot_client", lambda hwnd, p: calls.append("shot") or p)
    monkeypatch.setattr(window.win32gui, "GetWindowText", lambda hwnd: "游戏")
    result = window.diagnose_window("桃源", tmp_path)
    assert calls == []
    assert result.needs_elevation is True
    assert "管理员" in result.message


def test_diagnose_window_elevated_process_runs_full_flow(monkeypatch, tmp_path) -> None:
    """本进程已提权：正常执行置前与截图，即使游戏窗口也是管理员权限。"""
    calls: list[str] = []
    monkeypatch.setattr(window, "find_window", lambda keyword: 123)
    monkeypatch.setattr(window, "is_process_elevated", lambda: True)
    monkeypatch.setattr(window, "is_window_elevated", lambda hwnd: True)
    monkeypatch.setattr(window, "bring_to_front", lambda hwnd: calls.append("front") or True)
    monkeypatch.setattr(window, "get_client_rect", lambda hwnd: (0, 0, 800, 600))
    monkeypatch.setattr(window, "screenshot_client", lambda hwnd, p: calls.append("shot") or p)
    monkeypatch.setattr(window.win32gui, "GetWindowText", lambda hwnd: "游戏")
    monkeypatch.setattr(window.win32gui, "IsIconic", lambda hwnd: False)
    result = window.diagnose_window("桃源", tmp_path)
    assert calls == ["front", "shot"]
    assert result.needs_elevation is False


def test_diagnose_window_reports_needs_elevation(monkeypatch, tmp_path) -> None:
    """置前被拒（UIPI）且权限未知：结果标记需要提权。"""
    monkeypatch.setattr(window, "find_window", lambda keyword: 123)
    monkeypatch.setattr(window, "is_process_elevated", lambda: False)
    monkeypatch.setattr(window, "is_window_elevated", lambda hwnd: None)
    monkeypatch.setattr(window, "bring_to_front", lambda hwnd: False)
    monkeypatch.setattr(window.win32gui, "GetWindowText", lambda hwnd: "游戏")
    monkeypatch.setattr(window.win32gui, "IsIconic", lambda hwnd: True)
    result = window.diagnose_window("桃源", tmp_path)
    assert result.needs_elevation is True
    assert "管理员" in result.message


def test_bring_to_front_restores_and_tops(monkeypatch) -> None:
    """置前：恢复最小化 → 显示 → SetForegroundWindow → z 序置顶；成功返回 True。"""
    calls: list[tuple] = []
    monkeypatch.setattr(window.win32gui, "ShowWindow", lambda hwnd, cmd: calls.append(("show", cmd)))
    monkeypatch.setattr(window.win32gui, "SetForegroundWindow", lambda hwnd: calls.append(("fg", hwnd)))
    monkeypatch.setattr(
        window.win32gui, "SetWindowPos",
        lambda hwnd, after, x, y, w, h, flags: calls.append(("pos", after, flags)),
    )
    assert window.bring_to_front(123) is True
    assert ("show", window.win32con.SW_RESTORE) in calls
    assert ("show", window.win32con.SW_SHOW) in calls
    assert ("fg", 123) in calls
    assert any(call[0] == "pos" and call[1] == window.win32con.HWND_TOP for call in calls)


def test_bring_to_front_access_denied_returns_false(monkeypatch) -> None:
    """高权限窗口（UIPI）：置前被拒时返回 False 而非崩溃。"""
    import pywintypes

    def deny(hwnd, cmd):
        raise pywintypes.error(5, "ShowWindow", "拒绝访问。")

    monkeypatch.setattr(window.win32gui, "ShowWindow", deny)
    assert window.bring_to_front(123) is False
