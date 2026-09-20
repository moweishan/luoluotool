"""真实键鼠输入通道（SendInput）测试。

硬规则（用户 2026-09-16 指定）：**每次鼠标点击与键盘输入前都必须校验游戏窗口是否在最顶层，
不在最顶层时先置顶再输入**；无法确保窗口在最前时绝不输入。

全部注入假 user32：单测**零真实输入**（不会真的移动光标、不会真的按键）。

按被测对象拆分（2026-09-20，原 1229 行超出 AGENTS.md 的 600 行硬线；纯搬运，未改一行测试函数体）：
本文件保留**注入原语与坐标 / 窗口状态**（`_set_window_pos` 包装、`ensure_window_front`、
`release_topmost`、`normalize_absolute`、`move_cursor_absolute`、`set_cursor_pos`、
`restore_cursor_smooth`）以及通道构建与架构约束；点击、滑动、键盘的用例分别见同目录
`test_real_input_click.py` / `test_real_input_drag.py` / `test_real_input_keys.py`，
共享夹具见 `real_input_helpers.py`。
"""

from luoluotool.automation import input_sender, real_input
from luoluotool.automation.input_sender import RealInputSender

from test_automation.real_input_helpers import _capture_logs, user32


def test_set_window_pos_wrapper_treats_pywin32_none_as_success(monkeypatch) -> None:
    """回归：pywin32 的 SetWindowPos 成功返回 None、失败抛异常，不能按返回值判成败。"""
    calls: list[tuple] = []

    def fake(hwnd, insert_after, x, y, cx, cy, flags):
        calls.append((hwnd, insert_after, flags))
        return None

    monkeypatch.setattr(real_input.win32gui, "SetWindowPos", fake)
    assert real_input._set_window_pos(555, real_input.HWND_TOPMOST, real_input.TOP_FLAGS) is True
    assert calls == [(555, real_input.HWND_TOPMOST, real_input.TOP_FLAGS)]


def test_set_window_pos_wrapper_reports_exception_as_failure(monkeypatch) -> None:
    """pywin32 抛异常（句柄失效/拒绝访问）时必须返回 False。"""

    def boom(*args, **kwargs):
        raise OSError("拒绝访问（5）")

    monkeypatch.setattr(real_input.win32gui, "SetWindowPos", boom)
    assert real_input._set_window_pos(555, real_input.HWND_TOPMOST, real_input.TOP_FLAGS) is False


# --------------------------------------------------------- ensure_window_front


def test_ensure_window_front_sets_topmost_and_foreground_when_not_front(user32) -> None:
    """不在最前/最顶层时：先恢复（若最小化）→ 置顶 → 置前，并报告"本次是我们置的顶"。"""
    user32.foreground = 999  # 别的窗口在前台
    result = real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert result.ok is True
    assert result.set_topmost is True
    kinds = [call[0] for call in user32.calls]
    assert "SetWindowPos" in kinds and "SetForegroundWindow" in kinds
    assert kinds.index("SetWindowPos") < kinds.index("SetForegroundWindow")


def test_ensure_window_front_restores_minimized_window_first(user32) -> None:
    """最小化的窗口无法接收输入：必须先 SW_RESTORE。"""
    user32.minimized = True
    user32.foreground = 999
    real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert ("ShowWindow", 555, real_input.SW_RESTORE) in user32.calls


def test_ensure_window_front_is_noop_when_already_front_and_topmost(user32) -> None:
    """已经在前台且已置顶：不再做任何窗口操作（不打扰用户）。"""
    user32.foreground = 555
    user32.topmost_style = real_input.WS_EX_TOPMOST
    result = real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert result.ok is True
    assert result.set_topmost is False
    kinds = [call[0] for call in user32.calls]
    assert "SetWindowPos" not in kinds
    assert "SetForegroundWindow" not in kinds


def test_ensure_window_front_sets_foreground_when_only_topmost(user32) -> None:
    """已置顶但不在前台（键盘收不到）：仍需置前。"""
    user32.foreground = 999
    user32.topmost_style = real_input.WS_EX_TOPMOST
    result = real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert result.ok is True
    assert result.set_topmost is False  # 顶层本来就是它，不需要我们改
    assert ("SetForegroundWindow", 555) in user32.calls


def test_ensure_window_front_uses_attach_thread_input_fallback(user32) -> None:
    """前台锁定导致 SetForegroundWindow 无效时，用 AttachThreadInput 兜底。"""
    user32.foreground = 999
    user32.set_foreground_result = 0  # 直接置前失败

    real_calls: list[str] = []
    original_attach = user32.AttachThreadInput

    def attach_and_report(source, target, attach):
        if attach:  # 只统计"附加"这一次（解除附加不该计数）
            real_calls.append("attach")
            user32.foreground = 555  # 兜底成功
        return original_attach(source, target, attach)

    user32.AttachThreadInput = attach_and_report
    result = real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert result.ok is True
    assert real_calls == ["attach"]


def test_ensure_window_front_fails_with_readable_reason(user32) -> None:
    """无法把窗口置前时必须报告失败（调用方据此拒绝输入），而不是硬着头皮点。"""
    user32.foreground = 999
    user32.set_foreground_result = 0
    result = real_input.ensure_window_front(555, sleep=lambda _s: None)
    assert result.ok is False
    assert "置前" in result.reason or "最前" in result.reason


def test_release_topmost_clears_flag(user32) -> None:
    """输入结束后取消 TOPMOST，避免游戏窗口长期浮在所有窗口之上。"""
    user32.topmost_style = real_input.WS_EX_TOPMOST
    assert real_input.release_topmost(555) is True
    assert user32.topmost_style == 0


def test_release_topmost_skips_when_not_topmost(user32) -> None:
    """本来就不是 TOPMOST：不做任何窗口操作。"""
    user32.topmost_style = 0
    real_input.release_topmost(555)
    assert ("SetWindowPos", 555, real_input.HWND_NOTOPMOST, real_input.TOP_FLAGS) not in user32.calls


# --------------------------------------------------------------- 输入原语


def test_normalize_absolute_maps_virtual_desktop() -> None:
    """绝对坐标归一化：0..65535 对应虚拟桌面范围。"""
    assert real_input.normalize_absolute(0, 0, (0, 0, 1920, 1080)) == (0, 0)
    assert real_input.normalize_absolute(1919, 1079, (0, 0, 1920, 1080)) == (65535, 65535)
    # 多显示器（虚拟桌面以负坐标起始）也要正确
    nx, ny = real_input.normalize_absolute(0, 0, (-1920, 0, 3840, 1080))
    assert 32000 < nx < 33500 and ny == 0


def test_move_cursor_absolute_sends_single_move_event(user32) -> None:
    """移动真实光标：一次 MOUSEEVENTF_MOVE|ABSOLUTE|VIRTUALDESK，不带按键。"""
    real_input.move_cursor_absolute(700, 500)
    assert len(user32.sent) == 1
    event = user32.sent[0]
    assert event["flags"] & real_input.MOUSEEVENTF_MOVE
    assert event["flags"] & real_input.MOUSEEVENTF_ABSOLUTE
    assert event["flags"] & real_input.MOUSEEVENTF_VIRTUALDESK
    assert not event["flags"] & real_input.MOUSEEVENTF_LEFTDOWN


def test_set_cursor_pos_clamps_into_virtual_desktop(user32) -> None:
    """还原光标位置：直接 SetCursorPos（不需要按下抬起语义）。"""
    real_input.set_cursor_pos(321, 654)
    assert ("SetCursorPos", 321, 654) in user32.calls


def test_restore_cursor_smooth_moves_in_small_steps(user32, monkeypatch) -> None:
    """平滑还原光标：分帧小步移回（不是一次跳跃），末点精确落在目标位置。"""
    moves: list[tuple[int, int]] = []
    monkeypatch.setattr(real_input, "get_cursor_pos", lambda: (800, 600))
    monkeypatch.setattr(real_input, "move_cursor_absolute",
                        lambda x, y: (moves.append((x, y)), True)[1])
    assert real_input.restore_cursor_smooth((100, 300), sleep=lambda _s: None) is True
    assert len(moves) == real_input.DRAG_RESTORE_MAX_STEPS >= 4   # 多步，不是一次跳跃
    assert moves[0] != (100, 300)                                 # 第一步不跳到位
    assert moves[-1] == (100, 300)                                # 末点精确
    assert all(call[0] != "SetCursorPos" for call in user32.calls)  # 不用跳跃式复位


def test_restore_cursor_smooth_skips_when_already_at_target(user32, monkeypatch) -> None:
    """光标已经在目标位置：不产生任何移动。"""
    moves: list[tuple[int, int]] = []
    monkeypatch.setattr(real_input, "get_cursor_pos", lambda: (100, 300))
    monkeypatch.setattr(real_input, "move_cursor_absolute",
                        lambda x, y: moves.append((x, y)) or True)
    assert real_input.restore_cursor_smooth((100, 300), sleep=lambda _s: None) is True
    assert moves == []


def test_restore_cursor_smooth_survives_sleep_interruption(user32, monkeypatch) -> None:
    """还原过程中的等待抛异常（例如急停）：仍要把光标送回去。"""
    moves: list[tuple[int, int]] = []
    monkeypatch.setattr(real_input, "get_cursor_pos", lambda: (800, 600))
    monkeypatch.setattr(real_input, "move_cursor_absolute",
                        lambda x, y: moves.append((x, y)) or True)

    def boom(_seconds: float) -> None:
        raise RuntimeError("停止请求")

    assert real_input.restore_cursor_smooth((100, 300), sleep=boom) is True
    assert moves[-1] == (100, 300)


def test_restore_cursor_smooth_falls_back_when_read_fails(user32, monkeypatch) -> None:
    """读光标位置失败：退回 `SetCursorPos` 直接复位（不静默什么都不做）。"""
    def boom() -> tuple[int, int]:
        raise RuntimeError("读不到光标")

    monkeypatch.setattr(real_input, "get_cursor_pos", boom)
    assert real_input.restore_cursor_smooth((444, 555), sleep=lambda _s: None) is True
    assert ("SetCursorPos", 444, 555) in user32.calls


# --------------------------------------------------- 通道构建与架构约束


def test_build_channel_uses_real_input_in_real_mode(monkeypatch) -> None:
    """真实模式（dry_run=False）下通道固定使用 RealInputSender（唯一保留的实现方式）。"""
    import threading

    from luoluotool.config.models import AppConfig

    monkeypatch.setattr(input_sender, "find_window", lambda keyword: 777)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    config = AppConfig.default()
    config.automation.dry_run = False
    config.automation.restore_cursor_after_click = False
    channel = input_sender.build_channel(config, threading.Event(), lambda _s: None)
    assert isinstance(channel.sender, RealInputSender)
    assert channel.sender.restore_cursor is False
    assert channel.readiness is not None


def test_sendinput_is_confined_to_real_input_module() -> None:
    """架构约束：输入注入 API 只能出现在 real_input 模块里（便于审计与回归）。"""
    import pathlib

    src_root = pathlib.Path(real_input.__file__).resolve().parents[1]  # src/luoluotool
    offenders = []
    for path in src_root.rglob("*.py"):
        if path.name == "real_input.py":
            continue
        text = path.read_text(encoding="utf-8")
        for token in ("SendInput(", "SetCursorPos(", "mouse_event(", "keybd_event("):
            if token in text:
                offenders.append(f"{path.name}:{token}")
    assert offenders == [], f"这些模块不应直接调用输入注入 API：{offenders}"
