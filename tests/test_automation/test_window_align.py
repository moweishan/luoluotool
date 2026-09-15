"""对齐窗口点击的纯逻辑与守卫测试（全部注入假实现，不产生任何真实输入）。

原理：游戏按真实光标位置决定点击落点，因此把「目标客户区坐标」搬到静止光标底下
（移动窗口、不移动光标），再投递窗口消息即可点在正确位置。
"""

import pytest

from luoluotool.automation import window_align


def test_compute_window_origin_puts_target_under_cursor() -> None:
    """纯数学：算出的窗口左上角必须让目标客户区点正好落在光标处。"""
    cursor = (800, 600)
    target = (100, 50)
    frame_offset = (8, 31)  # 客户区原点相对窗口左上角的偏移（边框+标题栏）
    left, top = window_align.compute_window_origin(cursor, target, frame_offset)
    assert (left, top) == (800 - 100 - 8, 600 - 50 - 31)
    # 反算校验：新客户区原点 + 目标客户区点 == 光标
    client_origin = (left + frame_offset[0], top + frame_offset[1])
    assert (client_origin[0] + target[0], client_origin[1] + target[1]) == cursor


def test_compute_window_origin_handles_negative_offsets() -> None:
    """目标点比光标更靠右下时，窗口左上角应落在光标左侧/上方（可为负坐标）。"""
    left, top = window_align.compute_window_origin((100, 100), (300, 400), (0, 0))
    assert (left, top) == (-200, -300)


class _FakeDesktop:
    """假桌面：窗口矩形、客户区原点、光标位置都可脚本化。"""

    def __init__(self, left: int = 0, top: int = 0, frame: tuple[int, int] = (8, 31)) -> None:
        self.left = left
        self.top = top
        self.width, self.height = 1470, 863
        self.frame = frame
        self.cursor: tuple[int, int] = (800, 600)
        self.move_calls: list[tuple[int, int]] = []
        self.move_result = True
        self.cursor_after_align: tuple[int, int] | None = None

    def rect(self, hwnd: int) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.left + self.width, self.top + self.height)

    def origin(self, hwnd: int) -> tuple[int, int]:
        return (self.left + self.frame[0], self.top + self.frame[1])

    def move(self, hwnd: int, left: int, top: int) -> bool:
        self.move_calls.append((left, top))
        if self.move_result:
            self.left, self.top = left, top
            if self.cursor_after_align is not None:
                self.cursor = self.cursor_after_align
        return self.move_result


@pytest.fixture
def desktop(monkeypatch):
    fake = _FakeDesktop()
    monkeypatch.setattr(window_align, "get_cursor_pos", lambda: fake.cursor)
    monkeypatch.setattr(window_align, "window_rect", fake.rect)
    monkeypatch.setattr(window_align, "client_origin", fake.origin)
    monkeypatch.setattr(window_align, "_move_window", fake.move)
    return fake


def test_align_window_moves_window_and_reports_zero_error(desktop) -> None:
    """对齐成功后：窗口被搬到正确位置、误差为 0、记录了原矩形。"""
    before = desktop.rect(555)
    result = window_align.align_window(555, 100, 50, sleep=lambda _s: None)
    assert result.aligned is True
    assert result.error == (0, 0)
    assert result.cursor == (800, 600)
    assert result.rect_before == before
    assert desktop.move_calls == [(800 - 100 - 8, 600 - 50 - 31)]


def test_align_window_reports_mismatch_error(desktop, monkeypatch) -> None:
    """窗口没能真正移动（SetWindowPos 失败）→ 不得报告成功，且给出原因。"""
    desktop.move_result = False
    result = window_align.align_window(555, 100, 50, sleep=lambda _s: None)
    assert result.aligned is False
    assert "SetWindowPos" in result.reason
    assert result.rect_before == desktop.rect(555)


def test_align_window_realigns_when_cursor_drifted(desktop) -> None:
    """对齐期间光标被用户移动 → 必须按新的光标位置重新对齐，而不是点在错位置。"""
    desktop.cursor = (800, 600)
    desktop.cursor_after_align = (900, 700)  # 第一次对齐后光标跳走
    result = window_align.align_window(555, 100, 50, sleep=lambda _s: None)
    assert result.aligned is True
    assert len(desktop.move_calls) == 2, "应在光标漂移后重新对齐"
    # 最终窗口位置以「漂移后的光标」为准
    assert desktop.move_calls[-1] == (900 - 100 - 8, 700 - 50 - 31)
    assert result.cursor == (900, 700)


def test_align_window_gives_up_after_max_attempts(desktop, monkeypatch) -> None:
    """光标持续漂移时不能无限重试（有次数上限）并如实报告未对齐。"""
    calls = {"n": 0}

    def drifting_move(hwnd: int, left: int, top: int) -> bool:
        calls["n"] += 1
        desktop.left, desktop.top = left, top
        desktop.cursor = (1000 * calls["n"], 0)  # 每次移动后光标又跑到别处
        return True

    monkeypatch.setattr(window_align, "_move_window", drifting_move)
    result = window_align.align_window(555, 100, 50, sleep=lambda _s: None, attempts=2)
    assert result.aligned is False
    assert calls["n"] == 2


def test_restore_window_moves_back_and_verifies(desktop) -> None:
    """还原窗口位置：回到原坐标即为成功。"""
    window_align.align_window(555, 100, 50, sleep=lambda _s: None)
    before = desktop.rect(555)
    desktop.left, desktop.top = 0, 0
    window_align.align_window(555, 100, 50, sleep=lambda _s: None)
    assert window_align.restore_window(555, before, sleep=lambda _s: None) is True
    assert desktop.rect(555)[:2] == before[:2]


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_wait_cursor_idle_true_when_cursor_still(monkeypatch) -> None:
    """光标静止（位移 0）→ 立即返回静止。"""
    clock = _FakeClock()
    monkeypatch.setattr(window_align, "get_cursor_pos", lambda: (500, 400))
    idle, speed = window_align.wait_cursor_idle(sleep=clock.sleep, clock=clock.time)
    assert idle is True
    assert speed == 0.0


def test_wait_cursor_idle_false_when_cursor_keeps_moving(monkeypatch) -> None:
    """光标持续快速移动 → 超时后返回「未静止」，并给出实测速度。"""
    clock = _FakeClock()
    state = {"x": 0}

    def moving_cursor() -> tuple[int, int]:
        state["x"] += 500  # 每次采样都移动 500px
        return (state["x"], 0)

    monkeypatch.setattr(window_align, "get_cursor_pos", moving_cursor)
    idle, speed = window_align.wait_cursor_idle(timeout=0.4, sleep=clock.sleep, clock=clock.time)
    assert idle is False
    assert speed > window_align.CURSOR_IDLE_SPEED_PX_S


def test_wait_cursor_idle_true_when_cursor_slows_down(monkeypatch) -> None:
    """先快后停：静止后应立即返回 True。"""
    clock = _FakeClock()
    positions = iter([(0, 0), (500, 0), (500, 0), (500, 0)])
    monkeypatch.setattr(window_align, "get_cursor_pos", lambda: next(positions, (500, 0)))
    idle, _speed = window_align.wait_cursor_idle(timeout=1.0, sleep=clock.sleep, clock=clock.time)
    assert idle is True


def test_is_maximized_reflects_window_placement(monkeypatch) -> None:
    """最大化检测：SetWindowPos 对最大化窗口无效，必须能识别出来。"""
    import win32con

    maximized = (0, win32con.SW_SHOWMAXIMIZED, (0, 0), (0, 0), (0, 0, 100, 100))
    normal = (0, win32con.SW_SHOWNORMAL, (0, 0), (0, 0), (0, 0, 100, 100))
    monkeypatch.setattr(window_align.win32gui, "GetWindowPlacement", lambda hwnd: maximized)
    assert window_align.is_maximized(555) is True
    monkeypatch.setattr(window_align.win32gui, "GetWindowPlacement", lambda hwnd: normal)
    assert window_align.is_maximized(555) is False


def test_is_maximized_returns_false_when_query_fails(monkeypatch) -> None:
    """窗口已关闭等查询失败场景：返回 False（由上层按「窗口不可用」处理），不抛异常。"""

    def boom(hwnd):
        raise OSError("窗口已关闭")

    monkeypatch.setattr(window_align.win32gui, "GetWindowPlacement", boom)
    assert window_align.is_maximized(555) is False


def test_align_flags_avoid_stealing_focus_or_repaint() -> None:
    """对齐用的 SetWindowPos 标志：不得激活窗口、不得改变 z 序、不得改尺寸/重绘。"""
    for flag in (
        window_align.SWP_NOREDRAW,
        window_align.SWP_NOACTIVATE,
        window_align.SWP_NOZORDER,
        window_align.SWP_NOSIZE,
        window_align.SWP_NOCOPYBITS,
        window_align.SWP_NOSENDCHANGING,
    ):
        assert window_align.ALIGN_FLAGS & flag == flag, f"ALIGN_FLAGS 缺少 0x{flag:04X}"


def test_module_never_moves_the_real_cursor() -> None:
    """红线：本模块源码中不得出现任何移动真实光标的 API。"""
    source = (window_align.__file__ or "")
    with open(source, encoding="utf-8") as fp:
        text = fp.read()
    for forbidden in ("SetCursorPos", "mouse_event", "SendInput", "InjectSyntheticPointerInput"):
        assert forbidden not in text, f"window_align 不应使用 {forbidden}"
