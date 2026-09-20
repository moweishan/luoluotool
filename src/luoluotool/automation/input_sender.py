"""输入通道：干跑（只写日志）与真实鼠标键盘（`SendInput`）。

用户 2026-09-16 选定：**只保留「真实移动鼠标 + 模拟真实键盘」一种实现方式**
（其它通道——窗口消息、合成指针、对齐窗口——已按用户要求删除；如需回退可从 git 历史取回）。

真实通道的硬规则（用户明确要求）：**每一次鼠标点击与键盘输入之前都必须校验游戏窗口是否在最顶层，
不在最顶层时先置顶再输入**；无法确保窗口在最前时**绝不输入**。具体实现见 `automation/real_input.py`。
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import win32gui

from luoluotool.automation import real_input
from luoluotool.automation.window import find_window, get_client_rect
from luoluotool.config.models import AppConfig

logger = logging.getLogger(__name__)

READINESS_POLL_SECONDS = 0.2
CLICK_CURSOR_TOLERANCE_PX = 4        # 点击前允许的光标落点偏差；超过就跳过本次点击
CLICK_MOVE_STEP_SECONDS = 0.03       # 两步移动光标之间的间隔（给游戏一帧建立 hover）
CLICK_RESTORE_DELAY_SECONDS = 0.35   # 松手后到"还原光标"的延迟（让游戏先处理完这次点击）


class WindowUnavailableError(RuntimeError):
    """真实模式下游戏窗口不可用（未找到 / 最小化 / 不可见 / 已关闭 / 无法置前）。"""


class InputSender(Protocol):
    """输入发送接口：干跑与真实实现共用同一契约。"""

    def move_to(self, x: int, y: int) -> None: ...

    def click(self, x: int, y: int, hold_seconds: float | None = None) -> None: ...

    def click_at(self, x: int, y: int, hold_seconds: float | None = None) -> None: ...

    def key_tap(self, vk: int) -> None: ...

    def drag(self, from_xy: tuple[int, int], to_xy: tuple[int, int], duration_seconds: float) -> None: ...

    def key_combo(self, combo: str) -> None: ...

    def key_hold(self, combo: str, seconds: float) -> None: ...


class DryRunSender:
    """干跑模式：只写日志，绝不产生任何输入。

    `bounds` 可选注入「(x, y) → (是否在窗口内, 说明)」的越界校验回调：干跑时若能查到
    游戏窗口，越界点击同样会被跳过并写日志（与真实模式行为一致，便于提前发现配置错误）。
    """

    def __init__(
        self,
        log: logging.Logger | None = None,
        bounds: Callable[[int, int], tuple[bool, str]] | None = None,
    ) -> None:
        self._logger = log or logger
        self._bounds = bounds

    def _skip_if_out_of_bounds(self, descriptions: list[tuple[str, tuple[int, int]]]) -> bool:
        """越界则写提示日志并返回 True（调用方据此跳过本次输入）。

        `descriptions` 是「人读标签 + 客户区坐标」列表，例如点击一个点、滑动起终点两个点。
        """
        if self._bounds is None:
            return False
        offenders, detail = check_points_in_bounds(descriptions, self._bounds)
        if not offenders:
            return False
        self._logger.warning("干跑：%s 不在游戏窗口内（%s），已跳过", "、".join(offenders), detail)
        return True

    def move_to(self, x: int, y: int) -> None:
        self._logger.info("干跑：移动到 (%d, %d)", x, y)

    def click(self, x: int, y: int, hold_seconds: float | None = None) -> None:
        self.click_at(x, y, hold_seconds)

    def click_at(self, x: int, y: int, hold_seconds: float | None = None) -> None:
        if self._skip_if_out_of_bounds([(f"点击坐标 ({x}, {y})", (x, y))]):
            return
        if hold_seconds is None:
            self._logger.info("干跑：模拟点击 (%d, %d)", x, y)
            return
        self._logger.info(
            "干跑：模拟点击 (%d, %d) 点击时长 %.0f ms（按住后再松开）", x, y, hold_seconds * 1000
        )

    def key_tap(self, vk: int) -> None:
        self._logger.info("干跑：模拟按键 (vk=%d)", vk)

    def drag(self, from_xy: tuple[int, int], to_xy: tuple[int, int], duration_seconds: float) -> None:
        if self._skip_if_out_of_bounds(
            [(f"滑动起点 {tuple(from_xy)}", from_xy), (f"滑动终点 {tuple(to_xy)}", to_xy)]
        ):
            return
        self._logger.info(
            "干跑：模拟滑动 (%d, %d) → (%d, %d) 用时 %.2fs",
            from_xy[0], from_xy[1], to_xy[0], to_xy[1], duration_seconds,
        )

    def key_combo(self, combo: str) -> None:
        self._logger.info("干跑：模拟按键组合 %s", combo)

    def key_hold(self, combo: str, seconds: float) -> None:
        self._logger.info("干跑：模拟长按 %s 持续 %.2fs", combo, seconds)


class RealInputSender:
    """真实键鼠输入通道（`SendInput`）：真实移动光标 + 模拟真实鼠标/键盘。

    硬规则（用户 2026-09-16 指定，**每次**点击/按键前都执行）：校验游戏窗口是否在最顶层，
    不在则先置顶再置前；无法确保窗口在最前时**绝不输入**（抛可读错误）。
    每次点击后按配置把真实光标移回原位；输入结束取消由我们设置的 TOPMOST。

    代价（用户已知情并选择）：输入期间会抢前台，因此运行时不宜同时操作其它软件。
    """

    def __init__(
        self,
        hwnd: int,
        restore_cursor: bool = True,
        log: logging.Logger | None = None,
        sleep: Callable[[float], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.hwnd = hwnd
        self.restore_cursor = restore_cursor
        self._logger = log or logger
        self._sleep = sleep if sleep is not None else time.sleep
        # 用于长按期间响应急停（切片检查），None 表示不检查
        self._stop_event = stop_event

    def move_to(self, x: int, y: int) -> None:
        """悬停不点击：真实输入通道下不做任何光标移动（避免无意义地干扰用户的鼠标）。"""
        self._logger.debug("真实输入通道不执行悬停，已忽略 move_to(%d, %d)", x, y)

    def click(self, x: int, y: int, hold_seconds: float | None = None) -> None:
        self.click_at(x, y, hold_seconds)

    def click_at(self, x: int, y: int, hold_seconds: float | None = None) -> None:
        """点击客户区 (x, y)；`hold_seconds` 为按住时长（None＝引擎默认 40ms，0＝瞬时）。

        硬规则（2026-09-19 用户要求）：点击位置必须在游戏窗口客户区内，越界不点击。
        点击时长用于游戏吞掉瞬时点击的情况（按住一会儿再松开），期间可被急停打断。
        """
        # 硬规则（2026-09-19 用户要求）：点击位置必须在游戏窗口客户区内，越界不点击
        inside, detail = point_in_client_area(self.hwnd, x, y)
        if not inside:
            self._logger.warning(
                "点击坐标 (%d, %d) 不在游戏窗口内（%s），已跳过本次点击", x, y, detail
            )
            return
        front = self._ensure_front_or_raise("点击")
        saved: tuple[int, int] | None = None
        clicked = False
        try:
            # 光标位置必须在 try 内读取：万一这里抛异常，finally 仍要取消我们设置的置顶
            saved = real_input.get_cursor_pos()
            screen = real_input.client_to_screen(self.hwnd, (x, y))
            self._move_cursor_for_click(saved, screen)
            self._sleep(real_input.INPUT_SETTLE_SECONDS)
            if not self._verify_before_press(x, y, screen):
                return
            if not real_input.send_left_click(
                self._sleep, hold_seconds=hold_seconds, stop_event=self._stop_event
            ):
                raise WindowUnavailableError("真实鼠标点击注入失败（SendInput 未被系统接受）")
            clicked = True
            hold_text = "" if hold_seconds is None else f"，点击时长 {hold_seconds * 1000:.0f} ms"
            self._logger.info(
                "真实点击完成：客户区 (%d, %d) → 屏幕 %s%s（已确保窗口在最顶层）",
                x, y, screen, hold_text,
            )
        finally:
            if self.restore_cursor and saved is not None:
                self._restore_cursor_after_click(saved, clicked=clicked)
            self._release_topmost_if_needed(front)

    def _restore_cursor_after_click(self, saved: tuple[int, int], clicked: bool) -> None:
        """点击后把真实光标移回 `saved`：**先延迟**（让游戏处理完这次点击）**再分帧小步移回**。

        为什么不能一次 `SetCursorPos` 跳回（2026-09-20 用户实测确认的根因）：游戏（Unity）按帧
        采样指针位置 —— 松手后立刻把光标跳到另一个显示器，游戏处理这次点击的那一帧看到的是
        "指针已不在窗口内"，于是这次点击被丢弃。用户实测「关掉还原鼠标原位置就能点动」正好反证。
        分帧小步 + 延迟（`CLICK_RESTORE_DELAY_SECONDS`）能保证"游戏先处理点击，再看到指针离开"。
        与滑动路径的 `_restore_cursor_after_drag` 同一套做法；被跳过/未点击时不额外等待。
        """
        if clicked:
            try:
                self._sleep(CLICK_RESTORE_DELAY_SECONDS)
            except Exception as exc:        # 等待被中断（例如急停）也必须继续还原光标
                self._logger.warning("还原光标前的等待被中断（继续还原）：%s", exc)
        if real_input.restore_cursor_smooth(saved, self._sleep):
            self._logger.info("真实光标已移回点击前的位置 (%d, %d)", saved[0], saved[1])
        else:
            self._logger.warning("真实光标可能未完全移回点击前的位置 (%d, %d)", saved[0], saved[1])

    def _move_cursor_for_click(self, start: tuple[int, int] | None, target: tuple[int, int]) -> None:
        """把光标移到点击目标；分两步走（先到中途点），让游戏先收到"指针移进来/hover"再收到按下。

        为什么（2026-09-20 用户实测"某页能点、另一页点不动"）：一次绝对跳跃只产生一条移动事件，
        Unity 的 UI 模块按帧采样指针位置与 hover 状态；两步移动多产生一条移动事件并留出
        `CLICK_MOVE_STEP_SECONDS`，让游戏先在当前帧建立 hover 再处理按下。
        光标本来就在目标上时不发多余移动。
        """
        if start is not None:
            middle = ((int(start[0]) + int(target[0])) // 2, (int(start[1]) + int(target[1])) // 2)
            if middle != (int(target[0]), int(target[1])):
                real_input.move_cursor_absolute(*middle)
                self._sleep(CLICK_MOVE_STEP_SECONDS)
        real_input.move_cursor_absolute(*target)

    def _verify_before_press(self, x: int, y: int, screen: tuple[int, int]) -> bool:
        """按下左键前核对"事实"，返回是否继续点击。

        为什么需要（2026-09-20 实测）：用户报"同一坐标在某个页面能点、另一个页面点不动"，而日志两边
        都只写"完成" —— 真实输入"成功"只代表 `SendInput` 被系统接受，不代表游戏真的收到并处理了。
        这里把可核对的事实一次记全，下一次就能一眼区分"没送到"与"送对了但游戏不认"：
        客户区尺寸（窗口是否被改过大小）、目标屏幕点、**实测光标位置**、前台/置顶状态、光标处窗口。

        `SendInput` 被接受但光标没到位（例如被系统/权限钳制）时**不点击**：那样会点到别的控件上，
        在游戏里可能误触其它按钮 —— 宁可跳过并写 WARNING。
        """
        try:
            _, _, width, height = get_client_rect(self.hwnd)
        except Exception:
            width = height = -1
        try:
            actual = real_input.get_cursor_pos()
        except Exception as exc:                       # 读不到就只记日志，不据此拒绝点击
            self._logger.warning("点击前核对：读不到当前光标位置（%s），按原样继续", exc)
            actual = screen
        drift = max(abs(actual[0] - screen[0]), abs(actual[1] - screen[1]))
        under = real_input.window_under_point(*screen)
        self._logger.info(
            "点击前核对：客户区 %dx%d，目标客户区 (%d, %d) → 屏幕 %s，实测光标 %s（偏差 %dpx），"
            "前台是否本窗口 %s，置顶 %s，光标处窗口 %s，光标处就是本窗口 %s",
            width, height, x, y, screen, actual, drift,
            real_input.is_foreground(self.hwnd), real_input.is_topmost(self.hwnd),
            real_input.describe_window(under), under == self.hwnd,
        )
        if drift > CLICK_CURSOR_TOLERANCE_PX:
            self._logger.warning(
                "光标实测 (%d, %d) 未到达目标 %s（偏差 %d px），已跳过本次点击（宁可跳过也不用错误位置点击）",
                actual[0], actual[1], screen, drift,
            )
            return False
        if under and under != self.hwnd:
            self._logger.warning(
                "光标处窗口不是本窗口（%s）：若游戏收不到点击，多半是这里被别的窗口挡住",
                real_input.describe_window(under),
            )
        return True

    def key_tap(self, vk: int) -> None:
        front = self._ensure_front_or_raise("按键")
        try:
            if not real_input.send_key_tap(vk, self._sleep):
                raise WindowUnavailableError("真实按键注入失败（SendInput 未被系统接受）")
            self._logger.info("真实按键完成：vk=%d（已确保窗口在最顶层）", vk)
        finally:
            self._release_topmost_if_needed(front)

    def drag(self, from_xy: tuple[int, int], to_xy: tuple[int, int], duration_seconds: float) -> None:
        """真实鼠标滑动：按住左键从 A 分帧移动到 B 后松开。

        与点击同样：**每次滑动前**校验并确保游戏窗口在最顶层，无法确保时绝不输入；
        滑动可被急停打断，且任何情况下都会校验并释放左键（松开后复查，未松开则补发）。
        **起点与终点都必须落在游戏窗口客户区内**（2026-09-19 用户要求，与点击同一规则）：
        任一端越界或读不到客户区就整段跳过并写 WARNING。
        结束后按 `restore_cursor_after_click` 把真实光标移回原位，但**先延迟再分帧
        小步移回**（`_restore_cursor_after_drag`）：一次跳回会被残留的拖拽状态算成
        巨大位移，表现为画面乱飘。
        """
        offenders, detail = check_points_in_bounds(
            [(f"起点 {tuple(from_xy)}", from_xy), (f"终点 {tuple(to_xy)}", to_xy)],
            lambda x, y: point_in_client_area(self.hwnd, x, y),
        )
        if offenders:
            self._logger.warning(
                "滑动%s 不在游戏窗口内（%s），已跳过本次滑动", "、".join(offenders), detail
            )
            return
        front = self._ensure_front_or_raise("滑动")
        saved: tuple[int, int] | None = None
        try:
            # 必须在 try 内读取：万一这里抛异常，finally 仍要取消我们设置的置顶
            saved = real_input.get_cursor_pos()
            start = real_input.client_to_screen(self.hwnd, from_xy)
            end = real_input.client_to_screen(self.hwnd, to_xy)
            ok, interrupted = real_input.send_left_drag(
                start, end, duration_seconds, self._sleep, self._stop_event
            )
            if not ok:
                raise WindowUnavailableError(
                    "真实鼠标滑动注入失败（SendInput 未被系统接受，或左键未能释放；"
                    "请手动点击一次左键确认鼠标已松开）"
                )
            if interrupted:
                self._logger.warning(
                    "滑动 (%d, %d) → (%d, %d) 被停止请求中断（已释放左键）",
                    from_xy[0], from_xy[1], to_xy[0], to_xy[1],
                )
            else:
                self._logger.info(
                    "真实滑动完成：客户区 (%d, %d) → (%d, %d) 用时 %.2fs（已确保窗口在最顶层）",
                    from_xy[0], from_xy[1], to_xy[0], to_xy[1], duration_seconds,
                )
        finally:
            if self.restore_cursor and saved is not None:
                self._restore_cursor_after_drag(saved)
            self._release_topmost_if_needed(front)

    def _restore_cursor_after_drag(self, saved: tuple[int, int]) -> None:
        """滑动结束后把真实光标移回 `saved`：先延迟（等引擎处理完"抬起"）再分帧移回。"""
        try:
            self._sleep(real_input.DRAG_RESTORE_DELAY_SECONDS)
        except Exception as exc:        # 等待被中断（例如急停）也必须继续还原光标
            self._logger.warning("还原光标前的等待被中断（继续还原）：%s", exc)
        if real_input.restore_cursor_smooth(saved, self._sleep):
            self._logger.info("真实光标已移回滑动前的位置 (%d, %d)", saved[0], saved[1])
        else:
            self._logger.warning("真实光标可能未完全移回滑动前的位置 (%d, %d)", saved[0], saved[1])

    def key_combo(self, combo: str) -> None:
        """发送组合键（如 `ctrl+s`）：每次按键前同样会校验并确保窗口在最顶层。"""
        front = self._ensure_front_or_raise("按键")
        try:
            self._validate_combo(combo)
            if not real_input.send_key_combo(combo, self._sleep):
                raise WindowUnavailableError(f"按键注入失败（SendInput 未被系统接受）：{combo}")
            self._logger.info("真实按键完成：%s（已确保窗口在最顶层）", combo)
        finally:
            self._release_topmost_if_needed(front)

    def key_hold(self, combo: str, seconds: float) -> None:
        """长按组合键 `seconds` 秒：可被急停打断，且无论何种情况都会释放按键（不卡键）。"""
        front = self._ensure_front_or_raise("按键")
        try:
            self._validate_combo(combo)
            ok, interrupted = real_input.send_key_hold(
                combo, seconds, self._sleep, self._stop_event
            )
            if not ok:
                raise WindowUnavailableError(f"长按注入失败（SendInput 未被系统接受）：{combo}")
            if interrupted:
                self._logger.warning("长按 %s 被停止请求中断（已释放按键）", combo)
            else:
                self._logger.info(
                    "真实长按完成：%s 持续 %.2fs（已确保窗口在最顶层）", combo, seconds
                )
        finally:
            self._release_topmost_if_needed(front)

    def _validate_combo(self, combo: str) -> None:
        """提前解析按键文本，把"未知键名"变成可读错误（不进入注入流程）。"""
        try:
            real_input.parse_combo(combo)
        except ValueError as exc:
            raise WindowUnavailableError(f"按键组合无法解析：{exc}") from exc

    def _ensure_front_or_raise(self, action: str) -> real_input.FrontResult:
        if not is_window_ready(self.hwnd):
            raise WindowUnavailableError(f"游戏窗口已最小化或不可见，已取消本次{action}")
        front = real_input.ensure_window_front(self.hwnd, self._logger, self._sleep)
        if not front.ok:
            # 评审 P1-3：置前失败时**本次由我们设置的置顶必须立刻取消**再抛 ——
            # 旧实现直接抛出并把 FrontResult 丢掉，调用方的 finally 永远走不到，
            # 于是窗口长期浮在所有窗口之上（AGENTS/PROJECT_SPEC §4.2.3 的"收拾现场"硬规则）。
            if front.set_topmost:
                if real_input.release_topmost(self.hwnd):
                    self._logger.warning("置前失败，已取消本次由我们设置的置顶（避免窗口长期浮在最上层）")
                else:
                    self._logger.warning("置前失败且取消置顶也失败：游戏窗口可能仍浮在最上层")
            raise WindowUnavailableError(
                f"无法把游戏窗口置于最前，已取消本次{action}（真实键鼠输入只能送到最前窗口）：{front.reason}"
            )
        return front

    def _release_topmost_if_needed(self, front: real_input.FrontResult) -> None:
        """只取消"本次由我们设置的"置顶，避免改变用户原本的窗口层级。"""
        if front.set_topmost and not real_input.release_topmost(self.hwnd):
            self._logger.warning("取消窗口置顶失败：游戏窗口可能仍浮在所有窗口之上")


def window_exists(hwnd: int) -> bool:
    """窗口句柄是否仍然有效。"""
    return bool(win32gui.IsWindow(hwnd))


def is_window_ready(hwnd: int) -> bool:
    """窗口存在、可见且未最小化。"""
    return (
        window_exists(hwnd)
        and bool(win32gui.IsWindowVisible(hwnd))
        and not win32gui.IsIconic(hwnd)
    )


class WindowReadinessGate:
    """真实模式的窗口守卫：窗口被关闭/最小化/不可见时暂停等待，恢复后继续；停止请求随时生效。

    注：真实键鼠通道会在每次输入前自行把游戏窗口置顶/置前，因此这里不再做"失焦暂停"
    （原 `pause_on_window_focus_loss` 配置与之冲突，已随本次精简移除）。
    """

    def __init__(
        self,
        hwnd: int,
        stop_event: threading.Event,
        sleep: Callable[[float], None],
        log: logging.Logger | None = None,
    ) -> None:
        self._hwnd = hwnd
        self._stop_event = stop_event
        self._sleep = sleep
        self._logger = log or logger

    def wait_until_ready(self) -> bool:
        """返回 True 表示可继续；False 表示收到停止请求（应优雅结束）。"""
        if self._stop_event.is_set():
            return False
        if not window_exists(self._hwnd):
            raise WindowUnavailableError("游戏窗口已关闭，无法继续执行")
        if not is_window_ready(self._hwnd):
            self._logger.warning("游戏窗口已最小化或不可见，暂停执行（等待窗口恢复）")
            return self._wait_for(lambda: is_window_ready(self._hwnd), "窗口已恢复，继续执行")
        return True

    def _wait_for(self, condition: Callable[[], bool], resume_message: str) -> bool:
        while not self._stop_event.is_set():
            if condition():
                self._logger.info(resume_message)
                return True
            self._sleep(READINESS_POLL_SECONDS)
        self._logger.info("暂停期间收到停止请求，结束本次执行")
        return False


@dataclass
class InputChannel:
    """输入通道：sender 与可选的就绪检查（仅真实模式提供）。"""

    sender: InputSender
    readiness: Callable[[], bool] | None = None


def point_in_client_area(hwnd: int, x: int, y: int) -> tuple[bool, str]:
    """判断客户区坐标 (x, y) 是否落在窗口客户区内；返回 (是否在内, 说明文字)。

    边界语义：客户区为 `[0, width) × [0, height)`（右下边界点算越界）。
    读取失败（窗口已关闭、权限不足等）按**越界**处理——宁可不点击。
    """
    try:
        _, _, width, height = get_client_rect(hwnd)
    except Exception as exc:
        logger.warning("读取窗口客户区失败（hwnd=%s）：%s", hwnd, exc)
        return False, f"无法读取窗口客户区（{exc}）"
    inside = 0 <= int(x) < int(width) and 0 <= int(y) < int(height)
    return inside, f"客户区 {int(width)}x{int(height)}"


def check_points_in_bounds(
    points: list[tuple[str, tuple[int, int]]],
    check: Callable[[int, int], tuple[bool, str]],
) -> tuple[tuple[str, ...], str]:
    """逐个判定若干客户区点，返回 (越界点的标签, 客户区说明)。

    点击只传一个点，滑动传起点与终点——这样"滑动任意一端出界就不滑动"与点击共用同一份判定。
    """
    offenders: list[str] = []
    detail = ""
    for label, (x, y) in points:
        inside, detail = check(int(x), int(y))
        if not inside:
            offenders.append(label)
    return tuple(offenders), detail


def _dry_run_bounds(
    keyword: str, log: logging.Logger | None = None
) -> Callable[[int, int], tuple[bool, str]]:
    """干跑用的惰性越界校验（点击时才查窗口；查不到就不校验）。

    惰性是刻意的：干跑模式下 `build_channel` **不得**查询窗口（有测试守卫：干跑无需游戏在运行），
    因此窗口查找推迟到第一次点击时。
    """
    target_logger = log or logger

    def bounds(x: int, y: int) -> tuple[bool, str]:
        try:
            hwnd = find_window(keyword)
        except Exception as exc:
            target_logger.warning("干跑：查找游戏窗口失败，跳过点击越界校验：%s", exc)
            return True, "查找窗口失败"
        if hwnd is None:
            target_logger.info(
                "干跑：未找到标题含“%s”的窗口，跳过点击越界校验（(%d, %d) 直接模拟）",
                keyword, x, y,
            )
            return True, "未找到游戏窗口"
        return point_in_client_area(hwnd, x, y)

    return bounds


def build_channel(
    config: AppConfig,
    stop_event: threading.Event,
    sleep: Callable[[float], None],
    log: logging.Logger | None = None,
) -> InputChannel:
    """构建输入通道：干跑用 DryRunSender，真实模式用真实鼠标键盘（SendInput）。

    真实模式窗口不可用时抛可读错误（不执行任何输入）。
    """
    if config.automation.dry_run:
        return InputChannel(
            DryRunSender(log, _dry_run_bounds(config.automation.window_title_keyword, log))
        )
    keyword = config.automation.window_title_keyword
    hwnd = find_window(keyword)
    if hwnd is None:
        raise WindowUnavailableError(f"未找到标题含“{keyword}”的窗口，请确认游戏已窗口化运行")
    if not is_window_ready(hwnd):
        raise WindowUnavailableError("游戏窗口已最小化或不可见，请恢复窗口后重试")
    gate = WindowReadinessGate(hwnd, stop_event, sleep, log)
    sender = RealInputSender(
        hwnd, config.automation.restore_cursor_after_click, log, sleep, stop_event
    )
    return InputChannel(sender, gate.wait_until_ready)
