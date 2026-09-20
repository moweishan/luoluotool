"""开发者调试动作：鼠标单点/连点、屏幕滑动、键盘按键测试。

与正式任务共用同一输入通道（`build_channel`），因此**规则完全一致**：

- 干跑模式（`automation.dry_run`）下只写日志，零真实输入；
- 真实模式下每次输入前校验并把游戏窗口置于最顶层，无法确保时抛可读错误、不输入；
- 滑动可被停止请求打断且始终释放左键；连点/连续按键在每次动作之间检查停止请求。

这些函数只做编排（参数校验 + 调用 sender + 汇总结果），不含任何 GUI 代码，便于单测。
"""

import logging
import threading
import time
from collections.abc import Callable

from luoluotool.automation.input_sender import build_channel
from luoluotool.config.models import AppConfig
from luoluotool.utils.keys import parse_combo

logger = logging.getLogger(__name__)

MAX_REPEAT = 200
INTERVAL_RANGE_MS = (50, 5000)
COORDINATE_MAX = 10000
DURATION_RANGE_MS = (50, 10000)
CLICK_HOLD_RANGE_MS = (0, 5000)      # 「点击时长」上限：0＝瞬时，5000＝按住 5 秒
DEFAULT_CLICK_HOLD_MS = 40           # 与 real_input.CLICK_HOLD_SECONDS 对齐（调试页默认值）


def _validate_point(x: int, y: int) -> tuple[int, int]:
    """客户区坐标必须是非负整数且不超过上限（防止误输入一个巨大的值）。"""
    for name, value in (("x", x), ("y", y)):
        if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= COORDINATE_MAX):
            raise ValueError(f"{name} 必须是 0–{COORDINATE_MAX} 之间的整数（实际 {value!r}）")
    return int(x), int(y)


def _validate_repeat(count: int, interval_ms: int) -> tuple[int, int]:
    if isinstance(count, bool) or not isinstance(count, int) or not (1 <= count <= MAX_REPEAT):
        raise ValueError(f"次数必须是 1–{MAX_REPEAT} 之间的整数（实际 {count!r}）")
    low, high = INTERVAL_RANGE_MS
    if isinstance(interval_ms, bool) or not isinstance(interval_ms, int) or not (low <= interval_ms <= high):
        raise ValueError(f"间隔必须是 {low}–{high} 毫秒之间的整数（实际 {interval_ms!r}）")
    return int(count), int(interval_ms)


def _validate_duration(duration_ms: int) -> int:
    low, high = DURATION_RANGE_MS
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or not (low <= duration_ms <= high):
        raise ValueError(f"滑动用时必须是 {low}–{high} 毫秒之间的整数（实际 {duration_ms!r}）")
    return int(duration_ms)


def _validate_click_hold(hold_ms: int | None) -> int | None:
    """点击时长校验：`None`＝用引擎默认；否则必须是 0–`CLICK_HOLD_RANGE_MS` 的整数。"""
    if hold_ms is None:
        return None
    low, high = CLICK_HOLD_RANGE_MS
    if isinstance(hold_ms, bool) or not isinstance(hold_ms, int) or not (low <= hold_ms <= high):
        raise ValueError(f"点击时长必须是 {low}–{high} 毫秒之间的整数（实际 {hold_ms!r}）")
    return int(hold_ms)


def _open_sender(config: AppConfig, stop_event: threading.Event, log: logging.Logger | None):
    """按配置构建输入通道并返回 (sender, readiness)。干跑时 sender 只会写日志。"""
    channel = build_channel(config, stop_event, time.sleep, log)
    return channel.sender, channel.readiness


def _ready(readiness: Callable[[], bool] | None, stop_event: threading.Event) -> bool:
    """动作前的就绪检查（真实模式下会等待窗口恢复；返回 False 表示应中止）。"""
    if stop_event.is_set():
        return False
    if readiness is None:
        return True
    return bool(readiness())


def run_single_click(
    config: AppConfig, x: int, y: int,
    log: logging.Logger | None = None, stop_event: threading.Event | None = None,
    hold_ms: int | None = None,
) -> str:
    """鼠标单点测试：在客户区 (x, y) 点击一次。

    `hold_ms` 是**点击时长**（按下左键后保持多久再松开）：
    `None`（默认）＝不指定，用引擎默认时长（`real_input.CLICK_HOLD_SECONDS`＝40 ms）；
    `0`＝瞬时点击；正数＝按住这么多毫秒（游戏吞掉瞬时点击时调大，例如 100–300）。
    """
    x, y = _validate_point(x, y)
    hold_ms = _validate_click_hold(hold_ms)
    stop_event = stop_event or threading.Event()
    sender, readiness = _open_sender(config, stop_event, log)
    if not _ready(readiness, stop_event):
        return "单点测试已取消（收到停止请求）"
    hold_text = f"点击时长 {hold_ms} ms" if hold_ms is not None else "点击时长＝引擎默认"
    (log or logger).info("调试：鼠标单点测试 → 客户区 (%d, %d)（%s）", x, y, hold_text)
    if hold_ms is None:
        sender.click_at(x, y)
    else:
        sender.click_at(x, y, hold_seconds=hold_ms / 1000)
    return f"单点测试完成：(x={x}, y={y}) 1 次，{hold_text}"


def run_repeat_click(
    config: AppConfig, x: int, y: int, count: int, interval_ms: int,
    log: logging.Logger | None = None, stop_event: threading.Event | None = None,
) -> str:
    """鼠标连点测试：在 (x, y) 连点 `count` 次，每次间隔 `interval_ms`。"""
    x, y = _validate_point(x, y)
    count, interval_ms = _validate_repeat(count, interval_ms)
    stop_event = stop_event or threading.Event()
    sender, readiness = _open_sender(config, stop_event, log)
    done = 0
    for index in range(1, count + 1):
        if not _ready(readiness, stop_event):
            break
        (log or logger).info("调试：连点测试 第 %d/%d 次 → 客户区 (%d, %d)", index, count, x, y)
        sender.click_at(x, y)
        done += 1
        if index < count:
            time.sleep(interval_ms / 1000)
    if done == count:
        return f"连点测试完成：(x={x}, y={y}) {done} 次，间隔 {interval_ms} ms"
    return f"连点测试中断：已完成 {done}/{count} 次（停止请求或窗口不可用）"


def run_swipe(
    config: AppConfig, from_xy: tuple[int, int], to_xy: tuple[int, int], duration_ms: int,
    log: logging.Logger | None = None, stop_event: threading.Event | None = None,
) -> str:
    """鼠标屏幕滑动测试：从 `from_xy` 拖拽到 `to_xy`（客户区坐标）。"""
    fx, fy = _validate_point(from_xy[0], from_xy[1])
    tx, ty = _validate_point(to_xy[0], to_xy[1])
    duration_ms = _validate_duration(duration_ms)
    stop_event = stop_event or threading.Event()
    sender, readiness = _open_sender(config, stop_event, log)
    if not _ready(readiness, stop_event):
        return "滑动测试已取消（收到停止请求）"
    (log or logger).info(
        "调试：滑动测试 → 客户区 (%d, %d) 到 (%d, %d)，用时 %d ms", fx, fy, tx, ty, duration_ms
    )
    sender.drag((fx, fy), (tx, ty), duration_ms / 1000)
    return f"滑动测试完成：({fx}, {fy}) → ({tx}, {ty})，用时 {duration_ms} ms"


def run_key(
    config: AppConfig, combo: str, count: int = 1, interval_ms: int = 300,
    log: logging.Logger | None = None, stop_event: threading.Event | None = None,
) -> str:
    """键盘点击测试：发送组合键/按键 `count` 次（如 `a`、`ctrl+s`、`f5`）。"""
    text = (combo or "").strip()
    if not text:
        raise ValueError("按键不能为空（示例：a、enter、ctrl+s）")
    parse_combo(text)   # 未知键名在这里就以可读错误拒绝
    count, interval_ms = _validate_repeat(count, interval_ms)
    stop_event = stop_event or threading.Event()
    sender, readiness = _open_sender(config, stop_event, log)
    done = 0
    for index in range(1, count + 1):
        if not _ready(readiness, stop_event):
            break
        (log or logger).info("调试：键盘测试 第 %d/%d 次 → %s", index, count, text)
        sender.key_combo(text)
        done += 1
        if index < count:
            time.sleep(interval_ms / 1000)
    if done == count:
        return f"键盘测试完成：{text} {done} 次，间隔 {interval_ms} ms"
    return f"键盘测试中断：已完成 {done}/{count} 次（停止请求或窗口不可用）"
