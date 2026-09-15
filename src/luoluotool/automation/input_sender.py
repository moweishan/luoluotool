"""后台窗口消息输入：PostMessage 到游戏窗口，**不接管真实鼠标键盘**。

真实模式通过向窗口句柄发送鼠标/键盘消息完成操作：
不移动真实光标、不抢占键盘焦点、不注入系统输入流，玩家可同时正常使用键鼠。
"""

import ctypes
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import win32gui

from luoluotool.automation.window import find_window
from luoluotool.config.models import AppConfig

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

    def __init__(self, hwnd: int, log: logging.Logger | None = None) -> None:
        self.hwnd = hwnd
        self._logger = log or logger

    def move_to(self, x: int, y: int) -> None:
        target, point = self._resolve(x, y)
        self._post(target, WM_MOUSEMOVE, 0, point)
        self._send(target, WM_MOUSEMOVE, 0, point)
        self._logger.info("已发送鼠标移动消息 (%d, %d)（目标 hwnd=%s）", x, y, target)

    def click(self, x: int, y: int) -> None:
        target, point = self._resolve(x, y)
        self._post(target, WM_MOUSEMOVE, 0, point)  # 异步：让游戏消息泵先看到悬停位置
        self._send(target, WM_MOUSEMOVE, 0, point)  # 同步：确保先处理移动再处理按下
        self._send(target, WM_LBUTTONDOWN, MK_LBUTTON, point)
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
    gate = WindowReadinessGate(
        hwnd, config.automation.pause_on_window_focus_loss, stop_event, sleep, log
    )
    return InputChannel(WindowMessageSender(hwnd, log), gate.wait_until_ready)
