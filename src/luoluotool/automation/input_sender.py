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
from luoluotool.automation.window import find_window
from luoluotool.config.models import AppConfig

logger = logging.getLogger(__name__)

READINESS_POLL_SECONDS = 0.2


class WindowUnavailableError(RuntimeError):
    """真实模式下游戏窗口不可用（未找到 / 最小化 / 不可见 / 已关闭 / 无法置前）。"""


class InputSender(Protocol):
    """输入发送接口：干跑与真实实现共用同一契约。"""

    def move_to(self, x: int, y: int) -> None: ...

    def click(self, x: int, y: int) -> None: ...

    def click_at(self, x: int, y: int) -> None: ...

    def key_tap(self, vk: int) -> None: ...


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
        saved: tuple[int, int] | None = None
        try:
            # 光标位置必须在 try 内读取：万一这里抛异常，finally 仍要取消我们设置的置顶
            saved = real_input.get_cursor_pos()
            screen = real_input.client_to_screen(self.hwnd, (x, y))
            real_input.move_cursor_absolute(*screen)
            self._sleep(real_input.INPUT_SETTLE_SECONDS)
            if not real_input.send_left_click(self._sleep):
                raise WindowUnavailableError("真实鼠标点击注入失败（SendInput 未被系统接受）")
            self._logger.info(
                "真实点击完成：客户区 (%d, %d) → 屏幕 %s（已确保窗口在最顶层）", x, y, screen
            )
        finally:
            if self.restore_cursor and saved is not None:
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
            raise WindowUnavailableError(f"游戏窗口已最小化或不可见，已取消本次{action}")
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
        return InputChannel(DryRunSender(log))
    keyword = config.automation.window_title_keyword
    hwnd = find_window(keyword)
    if hwnd is None:
        raise WindowUnavailableError(f"未找到标题含“{keyword}”的窗口，请确认游戏已窗口化运行")
    if not is_window_ready(hwnd):
        raise WindowUnavailableError("游戏窗口已最小化或不可见，请恢复窗口后重试")
    gate = WindowReadinessGate(hwnd, stop_event, sleep, log)
    sender = RealInputSender(hwnd, config.automation.restore_cursor_after_click, log, sleep)
    return InputChannel(sender, gate.wait_until_ready)
