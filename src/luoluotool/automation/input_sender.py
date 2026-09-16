"""后台窗口消息输入：PostMessage 到游戏窗口，**不接管真实鼠标键盘**。

真实模式通过向窗口句柄发送鼠标/键盘消息完成操作：
不移动真实光标、不抢占键盘焦点、不注入系统输入流，玩家可同时正常使用键鼠。
"""

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import win32gui

from luoluotool.automation import real_input, window_align
from luoluotool.automation.window import find_window
from luoluotool.config.models import INPUT_MODE_REAL_INPUT, INPUT_MODE_WINDOW_ALIGN, AppConfig

logger = logging.getLogger(__name__)

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MK_LBUTTON = 0x0001
READINESS_POLL_SECONDS = 0.2
SMTO_ABORTIFHUNG = 0x0002
SEND_MESSAGE_TIMEOUT_MS = 500
# 消息间隔：让游戏分帧处理“移动/按下/抬起”，避免同一帧内连发被忽略或用到旧的指针位置
MESSAGE_GAP_SECONDS = 0.05


class WindowUnavailableError(RuntimeError):
    """真实模式下游戏窗口不可用（未找到 / 最小化 / 不可见 / 已关闭）。"""


class InputSender(Protocol):
    """输入发送接口：干跑与真实实现共用同一契约。"""

    def move_to(self, x: int, y: int) -> None: ...

    def click(self, x: int, y: int) -> None: ...

    def click_at(self, x: int, y: int) -> None: ...

    def key_tap(self, vk: int) -> None: ...


def _pack_point(x: int, y: int) -> int:
    """按 MAKELPARAM 规则把客户区坐标打包进 lParam。"""
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


class DryRunSender:
    """干跑模式：只写日志，绝不产生任何输入。"""

    def __init__(self, log: logging.Logger | None = None) -> None:
        self._logger = log or logger

    def move_to(self, x: int, y: int) -> None:
        self._logger.info("干跑：移动到 (%d, %d)", x, y)

    def click(self, x: int, y: int) -> None:
        self._logger.info("干跑：模拟点击 (%d, %d)", x, y)

    def click_at(self, x: int, y: int) -> None:
        self._logger.info("干跑：模拟点击 (%d, %d)", x, y)

    def key_tap(self, vk: int) -> None:
        self._logger.info("干跑：模拟按键 (vk=%d)", vk)


def resolve_input_target(hwnd: int, point: tuple[int, int]) -> tuple[int, tuple[int, int]]:
    """把主窗口客户区坐标解析为「最深的子窗口 + 该窗口客户区坐标」。

    游戏常把渲染/输入放在子窗口上，直接向顶层窗口发消息可能被忽略；
    若无可用子窗口或换算失败，则回退为顶层窗口 + 原坐标。
    """
    if not window_exists(hwnd):
        raise WindowUnavailableError(f"游戏窗口已关闭（hwnd={hwnd}）")
    try:
        screen_point = win32gui.ClientToScreen(hwnd, point)
        target = win32gui.WindowFromPoint(screen_point)
    except Exception as exc:
        logger.warning("定位输入目标窗口失败，回退顶层窗口：%s", exc)
        return hwnd, point
    if not target or target == hwnd:
        return hwnd, point
    try:
        if not win32gui.IsChild(hwnd, target):
            return hwnd, point
        local = win32gui.ScreenToClient(target, screen_point)
    except Exception as exc:
        logger.warning("换算子窗口坐标失败，回退顶层窗口：%s", exc)
        return hwnd, point
    return target, local


class WindowMessageSender:
    """真实模式：向游戏窗口（或坐标处子窗口）发送窗口消息。

    不移动真实光标、不抢占键盘焦点、不注入系统输入流。
    """

    def __init__(
        self,
        hwnd: int,
        log: logging.Logger | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.hwnd = hwnd
        self._logger = log or logger
        self._sleep = sleep if sleep is not None else time.sleep

    def move_to(self, x: int, y: int) -> None:
        target, point = self._resolve(x, y)
        self._post(target, WM_MOUSEMOVE, 0, point)
        self._send(target, WM_MOUSEMOVE, 0, point)
        self._logger.info("已发送鼠标移动消息 (%d, %d)（目标 hwnd=%s）", x, y, target)

    def click(self, x: int, y: int) -> None:
        target, point = self._resolve(x, y)
        self._post(target, WM_MOUSEMOVE, 0, point)  # 异步：让游戏消息泵先看到悬停位置
        self._send(target, WM_MOUSEMOVE, 0, point)  # 同步：确保先处理移动再处理按下
        self._sleep(MESSAGE_GAP_SECONDS)
        self._send(target, WM_LBUTTONDOWN, MK_LBUTTON, point)
        self._sleep(MESSAGE_GAP_SECONDS)
        self._send(target, WM_LBUTTONUP, 0, point)
        self._logger.info("已发送点击消息 (%d, %d)（目标 hwnd=%s）", x, y, target)

    def click_at(self, x: int, y: int) -> None:
        self.click(x, y)

    def key_tap(self, vk: int) -> None:
        self._send(self.hwnd, WM_KEYDOWN, vk, 0)
        self._send(self.hwnd, WM_KEYUP, vk, 0)
        self._logger.info("已发送按键消息 (vk=%d)", vk)

    def _resolve(self, x: int, y: int) -> tuple[int, int]:
        target, local_point = resolve_input_target(self.hwnd, (x, y))
        return target, _pack_point(*local_point)

    def _post(self, target: int, message: int, wparam: int, lparam: int) -> None:
        if not ctypes.windll.user32.PostMessageW(target, message, wparam, lparam):
            raise WindowUnavailableError(
                f"向窗口投递消息失败（hwnd={target}，消息=0x{message:04X}），窗口可能已关闭"
            )

    def _send(self, target: int, message: int, wparam: int, lparam: int) -> None:
        """同步投递（带超时与防挂起标志），失败即视为窗口不可用。"""
        result = ctypes.c_size_t()
        ok = ctypes.windll.user32.SendMessageTimeoutW(
            target, message, wparam, lparam,
            SMTO_ABORTIFHUNG, SEND_MESSAGE_TIMEOUT_MS, ctypes.byref(result),
        )
        if not ok:
            raise WindowUnavailableError(
                f"向窗口同步发送消息失败（hwnd={target}，消息=0x{message:04X}），窗口可能无响应"
            )


class WindowAlignSender:
    """真实模式：先把游戏窗口对齐到静止光标下方，再发窗口消息点击。

    适用于**按真实光标位置决定点击落点**的游戏（本作实测结论，见 `PROJECT_SPEC.md` §5）：
    把「目标客户区坐标」搬到静止的真实光标底下（移动窗口，而不是移动光标），
    游戏按光标取点即命中目标，而真实光标全程不动、不消失。

    安全约束：
    - 只移动游戏窗口，绝不移动真实光标、绝不注入系统输入流；
    - 前置检查：窗口可用、未最大化（最大化窗口无法对齐 → 抛可读错误，绝不误点）；
    - 真实鼠标正在移动时不对齐、不点击（否则会点错位置）；
    - 无论成功失败都在 `finally` 里还原窗口位置。
    """

    def __init__(
        self,
        hwnd: int,
        log: logging.Logger | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.hwnd = hwnd
        self._logger = log or logger
        self._sleep = sleep if sleep is not None else time.sleep
        self._inner = WindowMessageSender(hwnd, log, sleep)

    def move_to(self, x: int, y: int) -> None:
        """悬停不影响落点，不做窗口对齐（避免无意义的窗口位移）。"""
        self._inner.move_to(x, y)

    def click(self, x: int, y: int) -> None:
        self.click_at(x, y)

    def click_at(self, x: int, y: int) -> None:
        if not is_window_ready(self.hwnd):
            raise WindowUnavailableError("游戏窗口已最小化或不可见，已取消本次点击")
        window_align.ensure_alignment_supported(self.hwnd)

        idle, speed = window_align.wait_cursor_idle(sleep=self._sleep)
        if not idle:
            raise WindowUnavailableError(
                f"真实鼠标正在移动（{speed:.0f} px/s），为避免点错位置已取消本次点击；"
                "请让鼠标静止或调大点击间隔后重试"
            )

        result = window_align.align_window(self.hwnd, x, y, sleep=self._sleep)
        if not result.aligned:
            self._restore_quietly(result.rect_before)
            raise WindowUnavailableError(f"窗口对齐失败：{result.reason}")

        try:
            self._inner.click(x, y)
        finally:
            restored = window_align.restore_window(self.hwnd, result.rect_before, sleep=self._sleep)
            if not restored:
                self._logger.error(
                    "窗口还原失败：请手动把游戏窗口移回对齐前位置 (%d, %d)",
                    result.rect_before[0], result.rect_before[1],
                )
        self._logger.info(
            "对齐点击完成：客户区 (%d, %d)，对齐误差=%s，尝试 %d 次，真实光标未移动且保持可见",
            x, y, result.error, result.attempts,
        )

    def key_tap(self, vk: int) -> None:
        """按键不需要对齐，直接走窗口消息通道。"""
        self._inner.key_tap(vk)

    def _restore_quietly(self, rect: tuple[int, int, int, int]) -> None:
        """对齐失败时尽力还原窗口（失败只记日志，不掩盖原始错误）。"""
        if not window_align.restore_window(self.hwnd, rect, sleep=self._sleep):
            self._logger.error("窗口还原失败：请手动把游戏窗口移回 (%d, %d)", rect[0], rect[1])


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
    ) -> None:
        self.hwnd = hwnd
        self.restore_cursor = restore_cursor
        self._logger = log or logger
        self._sleep = sleep if sleep is not None else time.sleep

    def move_to(self, x: int, y: int) -> None:
        """悬停不点击：真实输入通道下不做任何光标移动（避免无意义地干扰用户的鼠标）。"""
        self._logger.debug("真实输入通道不执行悬停，已忽略 move_to(%d, %d)", x, y)

    def click(self, x: int, y: int) -> None:
        self.click_at(x, y)

    def click_at(self, x: int, y: int) -> None:
        front = self._ensure_front_or_raise("点击")
        saved = real_input.get_cursor_pos()
        try:
            screen = real_input.client_to_screen(self.hwnd, (x, y))
            real_input.move_cursor_absolute(*screen)
            self._sleep(real_input.INPUT_SETTLE_SECONDS)
            if not real_input.send_left_click(self._sleep):
                raise WindowUnavailableError("真实鼠标点击注入失败（SendInput 未被系统接受）")
            self._logger.info(
                "真实点击完成：客户区 (%d, %d) → 屏幕 %s（已确保窗口在最顶层）", x, y, screen
            )
        finally:
            if self.restore_cursor:
                real_input.set_cursor_pos(*saved)
            self._release_topmost_if_needed(front)

    def key_tap(self, vk: int) -> None:
        front = self._ensure_front_or_raise("按键")
        try:
            if not real_input.send_key_tap(vk, self._sleep):
                raise WindowUnavailableError("真实按键注入失败（SendInput 未被系统接受）")
            self._logger.info("真实按键完成：vk=%d（已确保窗口在最顶层）", vk)
        finally:
            self._release_topmost_if_needed(front)

    def _ensure_front_or_raise(self, action: str) -> real_input.FrontResult:
        if not is_window_ready(self.hwnd):
            raise WindowUnavailableError("游戏窗口已最小化或不可见，已取消本次%s" % action)
        front = real_input.ensure_window_front(self.hwnd, self._logger, self._sleep)
        if not front.ok:
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


def is_window_foreground(hwnd: int) -> bool:
    """窗口是否为当前前台窗口。"""
    return win32gui.GetForegroundWindow() == hwnd


class WindowReadinessGate:
    """真实模式的窗口守卫：最小化/失焦时暂停等待，恢复后继续；停止请求随时生效。"""

    def __init__(
        self,
        hwnd: int,
        pause_on_focus_loss: bool,
        stop_event: threading.Event,
        sleep: Callable[[float], None],
        log: logging.Logger | None = None,
    ) -> None:
        self._hwnd = hwnd
        self._pause_on_focus_loss = pause_on_focus_loss
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
        if self._pause_on_focus_loss and not is_window_foreground(self._hwnd):
            self._logger.info("游戏窗口失焦，暂停执行（等待重新聚焦）")
            return self._wait_for(
                lambda: is_window_foreground(self._hwnd), "窗口已重新聚焦，继续执行"
            )
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


def build_channel(
    config: AppConfig,
    stop_event: threading.Event,
    sleep: Callable[[float], None],
    log: logging.Logger | None = None,
) -> InputChannel:
    """按 dry_run 与窗口状态构建输入通道；真实模式窗口不可用时抛可读错误。"""
    if config.automation.dry_run:
        return InputChannel(DryRunSender(log))
    keyword = config.automation.window_title_keyword
    hwnd = find_window(keyword)
    if hwnd is None:
        raise WindowUnavailableError(f"未找到标题含“{keyword}”的窗口，请确认游戏已窗口化运行")
    if not is_window_ready(hwnd):
        raise WindowUnavailableError("游戏窗口已最小化或不可见，请恢复窗口后重试")
    mode = config.automation.input_mode
    if mode == INPUT_MODE_REAL_INPUT:
        # 真实键鼠通道自己会在每次输入前抢前台；若再叠加"失焦暂停"会互相等待（暂停→不输入→永不复位）
        if config.automation.pause_on_window_focus_loss:
            (log or logger).info(
                "输入方式=真实鼠标键盘：已忽略「窗口失焦时暂停」（该通道每次输入前会自行把游戏窗口置前）"
            )
        gate = WindowReadinessGate(hwnd, False, stop_event, sleep, log)
        sender: InputSender = RealInputSender(
            hwnd, config.automation.restore_cursor_after_click, log, sleep
        )
    elif mode == INPUT_MODE_WINDOW_ALIGN:
        gate = WindowReadinessGate(
            hwnd, config.automation.pause_on_window_focus_loss, stop_event, sleep, log
        )
        sender = WindowAlignSender(hwnd, log, sleep)
    else:
        gate = WindowReadinessGate(
            hwnd, config.automation.pause_on_window_focus_loss, stop_event, sleep, log
        )
        sender = WindowMessageSender(hwnd, log, sleep)
    return InputChannel(sender, gate.wait_until_ready)
