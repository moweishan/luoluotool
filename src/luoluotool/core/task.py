"""任务协议与执行上下文（不依赖 PySide6/win32）。"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

DEFAULT_TASK_LOGGER_NAME = "luoluotool.core"


@dataclass
class TaskContext:
    """任务执行上下文：stop_event、dry_run、logger 与可注入 sleep。"""

    stop_event: threading.Event = field(default_factory=threading.Event)
    dry_run: bool = True
    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger(DEFAULT_TASK_LOGGER_NAME)
    )
    sleep: Callable[[float], None] = time.sleep

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
