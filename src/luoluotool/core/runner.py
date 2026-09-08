"""任务执行调度器：顺序执行、循环间隔、连续失败自停、可急停（与 GUI 无关）。"""

import logging
import threading
import time
from collections.abc import Callable

from luoluotool.config.models import AppConfig, TaskConfig
from luoluotool.core.registry import get
from luoluotool.core.state import RunState, StateMachine
from luoluotool.core.task import TaskContext, TaskResult

logger = logging.getLogger(__name__)

SLEEP_CHUNK_SECONDS = 0.1


class Runner:
    """按配置顺序执行勾选任务；阻塞主循环由 GUI 层放入工作线程调用。"""

    def __init__(self, config: AppConfig, sleep: Callable[[float], None] | None = None) -> None:
        self._config = config
        self._sleep = sleep if sleep is not None else time.sleep
        self._state_machine = StateMachine()
        self._stop_event = threading.Event()
        self._finished_event = threading.Event()
        self._finished_event.set()
        self._context: TaskContext | None = None

    @property
    def state(self) -> RunState:
        return self._state_machine.state

    def request_stop(self) -> None:
        """请求停止（非阻塞）；主循环在最近检查点退出。"""
        self._stop_event.set()
        if self._state_machine.state is RunState.RUNNING:
            self._state_machine.transition(RunState.STOPPING)

    def stop(self, timeout: float | None = 5.0) -> bool:
        """请求停止并等待主循环退出；返回是否在超时内退出。"""
        self.request_stop()
        return self._finished_event.wait(timeout)

    def start(self) -> None:
        """阻塞执行任务主循环（应在工作线程中调用）。"""
        if self._state_machine.state is RunState.ERROR:
            self._state_machine.transition(RunState.IDLE)
        if self._state_machine.state is not RunState.IDLE:
            raise RuntimeError(f"Runner 状态不是 IDLE，无法启动：{self._state_machine.state.name}")
        self._stop_event.clear()
        self._finished_event.clear()
        self._state_machine.transition(RunState.RUNNING)
        self._context = TaskContext(
            stop_event=self._stop_event,
            dry_run=self._config.automation.dry_run,
            logger=logger,
            sleep=self._sleep,
        )
        try:
            self._run_loop()
        except Exception:
            logger.exception("任务执行出现异常")
            self._state_machine.transition(RunState.ERROR)
        finally:
            if self._state_machine.state in (RunState.RUNNING, RunState.STOPPING):
                self._state_machine.transition(RunState.IDLE)
            self._finished_event.set()

    def _run_loop(self) -> None:
        task_ids = self._selected_tasks()
        if not task_ids:
            logger.info("未选择任何任务，不执行")
            return
        failures = 0
        max_failures = self._config.automation.max_consecutive_failures
        while not self._stop_event.is_set():
            for task_id in task_ids:
                if self._stop_event.is_set():
                    break
                result = self._run_one(task_id)
                if result.success:
                    failures = 0
                else:
                    failures += 1
                    logger.warning(
                        "任务 %s 失败（连续失败 %d/%d）：%s",
                        task_id, failures, max_failures, result.message,
                    )
                    if failures >= max_failures:
                        logger.error("连续失败达到上限，自动停止")
                        return
            if self._stop_event.is_set() or not self._config.features.daily_tasks.loop.enabled:
                break
            self._context.interruptible_sleep(
                self._config.features.daily_tasks.loop.interval_seconds
            )

    def _selected_tasks(self) -> list[str]:
        """返回勾选任务 ID，按 order 升序。"""
        selected: list[tuple[str, TaskConfig]] = [
            (task_id, cfg)
            for task_id, cfg in self._config.features.daily_tasks.tasks.items()
            if cfg.enabled
        ]
        selected.sort(key=lambda item: item[1].order)
        return [task_id for task_id, _ in selected]

    def _run_one(self, task_id: str) -> TaskResult:
        logger.info("开始执行任务：%s", task_id)
        return get(task_id)().run(self._context)
