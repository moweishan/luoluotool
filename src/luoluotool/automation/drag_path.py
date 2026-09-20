"""滑动（拖拽）路径几何：缓出曲线 + 分帧插值 + 末尾静止保持帧（纯函数，不产生任何输入）。

分层：automation 层（不 import PySide6）。本模块只算坐标，不碰 `SendInput`：
逐帧发送在 `automation.real_input.send_left_drag`，它把这里算出的点依次发出去。

为什么必须「缓出 + 末尾静止」（2026-09-20 用户实测）：瞬移式路径会被引擎当成甩动，
松手后画面继续飘；末尾在终点静止若干帧再松手可消除惯性（规则见 AGENTS.md 滑动硬规则）。

拆分说明（2026-09-20）：本模块由 `automation/real_input.py` 原样搬出（行为零变化），
`real_input` 仍再导出这里的名字，`real_input.build_drag_path(...)` 等旧用法继续可用。
"""

from __future__ import annotations

from collections.abc import Callable

DRAG_STEP_SECONDS = 0.016   # 滑动插值步长（≈60Hz）
DRAG_MIN_STEPS = 4
DRAG_TAIL_HOLD_STEPS = 4    # 松手前在终点保持静止的帧数（消除「甩动惯性」导致的画面继续飘）


def ease_out_quad(t: float) -> float:
    """缓出曲线（纯函数）：`1 - (1 - t)²`，先快后慢、终点速度为 0。"""
    return 1 - (1 - float(t)) ** 2


def interpolate_points(
    start: tuple[int, int],
    end: tuple[int, int],
    steps: int,
    easing: Callable[[float], float] | None = None,
) -> list[tuple[int, int]]:
    """纯函数：在起点与终点之间插值出 `steps` 个中间点（不含起点、含终点）。

    真实鼠标滑动必须分帧移动：一次跳跃式移动会被很多游戏识别为瞬移而不是拖拽。
    `easing` 为 None 时线性；给定时按 `easing(进度)` 采样（拖动用缓出曲线）。
    """
    count = max(int(steps), 1)
    sx, sy = int(start[0]), int(start[1])
    ex, ey = int(end[0]), int(end[1])
    points: list[tuple[int, int]] = []
    for index in range(1, count + 1):
        progress = index / count
        fraction = easing(progress) if easing is not None else progress
        points.append((round(sx + (ex - sx) * fraction), round(sy + (ey - sy) * fraction)))
    return points


def build_drag_path(
    start: tuple[int, int],
    end: tuple[int, int],
    steps: int,
    tail_hold_steps: int = DRAG_TAIL_HOLD_STEPS,
) -> list[tuple[int, int]]:
    """生成拖动轨迹（纯函数）：**缓出采样** + 末尾在终点保持静止若干帧。

    为什么要缓出 + 末尾静止：很多游戏把"匀速甩到底再松手"识别成 flick，
    松手后镜头/画面会带着惯性继续飘。减速到静止再松手，引擎才会判定为"停住后松手"。
    """
    ex, ey = int(end[0]), int(end[1])
    path = interpolate_points(start, end, max(int(steps), DRAG_MIN_STEPS), easing=ease_out_quad)
    if path:
        path[-1] = (ex, ey)             # 保证末点精确落在终点
    hold = max(int(tail_hold_steps), 0)
    path.extend([(ex, ey)] * hold)      # 末尾静止保持（松手前的"停住"）
    return path
