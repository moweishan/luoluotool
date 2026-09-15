"""任务协议与执行上下文（不依赖 PySide6/win32；输入经自动化层注入）。"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from luoluotool.automation.input_sender import DryRunSender, InputSender

DEFAULT_TASK_LOGGER_NAME = "luoluotool.core"


@dataclass
class TaskContext:
    """任务执行上下文：stop_event、dry_run、logger、可注入 sleep/sender/params。"""

    stop_event: threading.Event = field(default_factory=threading.Event)
    dry_run: bool = True
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(DEFAULT_TASK_LOGGER_NAME)
    )
    sleep: Callable[[float], None] = time.sleep
    params: dict = field(default_factory=dict)
    sender: InputSender = field(default_factory=DryRunSender)
    readiness_check: Callable[[], bool] | None = None

    def should_stop(self) -> bool:
        """是否已收到停止请求。"""
        return self.stop_event.is_set()

    def interruptible_sleep(self, seconds: float) -> None:
        """分段睡眠：停止请求后最迟 0.1 秒内返回。"""
        remaining = seconds
        while remaining > 1e-9 and not self.stop_event.is_set():
            chunk = min(0.1, remaining)
            self.sleep(chunk)
            remaining -= chunk

    def wait_until_ready(self) -> bool:
        """检查停止请求与窗口就绪（真实模式失焦时内部暂停等待）。

        返回 False 表示应终止本次任务（停止请求或窗口不可用）。
        """
        if self.should_stop():
            return False
        if self.readiness_check is None:
            return True
        return self.readiness_check()


@dataclass
class TaskResult:
    """单次任务执行结果。"""

    task_id: str
    success: bool
    message: str = ""


class BaseTask:
    """任务协议：子类定义 task_id 并实现 run(ctx) -> TaskResult。"""

    task_id: str = ""

    def run(self, ctx: TaskContext) -> TaskResult:
        raise NotImplementedError(f"{type(self).__name__} 未实现 run()")
