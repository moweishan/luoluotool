"""任务执行调度器：顺序执行、循环间隔、连续失败自停、可急停（与 GUI 无关）。"""

import logging
import threading
import time
from collections.abc import Callable

from luoluotool.automation.input_sender import (
    InputChannel,
    WindowUnavailableError,
    build_channel,
)
from luoluotool.config.models import AppConfig, TaskConfig
from luoluotool.core.registry import (
    FEATURE_3_TASK_ID,
    FEATURE_4_TASK_ID,
    ORDER_HOLD_TASK_ID,
    get,
)
from luoluotool.core.state import RunState, StateMachine
from luoluotool.core.task import TaskContext, TaskResult

logger = logging.getLogger(__name__)

SLEEP_CHUNK_SECONDS = 0.1


class Runner:
    """按配置顺序执行勾选任务；阻塞主循环由 GUI 层放入工作线程调用。"""

    def __init__(
        self,
        config: AppConfig,
        sleep: Callable[[float], None] | None = None,
        channel_factory: Callable[
            [AppConfig, threading.Event, Callable[[float], None], logging.Logger], InputChannel
        ]
        | None = None,
    ) -> None:
        self._config = config
        self._sleep = sleep if sleep is not None else time.sleep
        # 运行时解析默认工厂：便于测试注入假 sender（不在导入时绑定）
        self._channel_factory = channel_factory if channel_factory is not None else build_channel
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
        try:
            channel = self._channel_factory(self._config, self._stop_event, self._sleep, logger)
            self._context = TaskContext(
                stop_event=self._stop_event,
                dry_run=self._config.automation.dry_run,
                logger=logger,
                sleep=self._sleep,
                sender=channel.sender,
                readiness_check=channel.readiness,
            )
            self._run_loop()
        except WindowUnavailableError as exc:
            logger.error("无法执行：%s", exc)
            self._state_machine.transition(RunState.ERROR)
        except Exception:
            logger.exception("任务执行出现异常")
            self._state_machine.transition(RunState.ERROR)
        finally:
            if self._state_machine.state in (RunState.RUNNING, RunState.STOPPING):
                self._state_machine.transition(RunState.IDLE)
            self._finished_event.set()

    def _run_loop(self) -> None:
        selected = self._selected_tasks()
        if not selected:
            logger.info("未选择任何任务，不执行")
            return
        logger.info(
            "任务队列（%d 个）：%s",
            len(selected), " → ".join(task_id for task_id, _ in selected),
        )
        failures = 0
        max_failures = self._config.automation.max_consecutive_failures
        while not self._stop_event.is_set():
            for task_id, task_config in selected:
                if self._stop_event.is_set():
                    break
                result = self._run_one(task_id, task_config)
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

    def queued_tasks(self) -> list[str]:
        """返回本次运行的任务队列（按执行顺序）；供日志与测试查询编排结果。"""
        return [task_id for task_id, _ in self._selected_tasks()]

    def _selected_tasks(self) -> list[tuple[str, TaskConfig]]:
        """任务编排（Phase 6）：**日常任务组 → 单功能组**，统一顺序执行、统一失败计数。

        规则：
        1. 日常任务组：`features.daily_tasks.tasks[id].enabled == true` 的任务入队，
           按 `order` 升序、同 `order` 按任务 ID 字典序（保证每次运行顺序完全一致）；
        2. 单功能组：功能主开关开启即入队，固定顺序 **卡订单 → 功能三 → 功能四**；
        3. `features.daily_tasks.enabled`（启用日常任务）与卡订单两个预留开关
           **不参与编排**（保持「存/读/显示」的既有语义）。
        """
        selected: list[tuple[str, TaskConfig]] = [
            (task_id, cfg)
            for task_id, cfg in self._config.features.daily_tasks.tasks.items()
            if cfg.enabled
        ]
        selected.sort(key=lambda item: (item[1].order, item[0]))
        for task_id, enabled in self._single_feature_tasks():
            if enabled:
                selected.append((task_id, TaskConfig(enabled=True, params={})))
        return selected

    def _single_feature_tasks(self) -> tuple[tuple[str, bool], ...]:
        """单功能组：功能主开关 → 任务 ID（顺序固定：卡订单 → 功能三 → 功能四）。"""
        features = self._config.features
        return (
            (ORDER_HOLD_TASK_ID, bool(features.order_hold.enabled)),
            (FEATURE_3_TASK_ID, bool(features.feature_3.enabled)),
            (FEATURE_4_TASK_ID, bool(features.feature_4.enabled)),
        )

    def _run_one(self, task_id: str, task_config: TaskConfig) -> TaskResult:
        task_class = get(task_id)  # 未注册任务仍走整体 ERROR（保持既有语义）
        self._context.params = dict(task_config.params)
        logger.info("开始执行任务：%s", task_id)
        try:
            return task_class().run(self._context)
        except WindowUnavailableError as exc:
            logger.error("任务 %s 因窗口不可用中止：%s", task_id, exc)
            return TaskResult(task_id, False, str(exc))
        except Exception as exc:
            logger.exception("任务 %s 执行异常", task_id)
            return TaskResult(task_id, False, f"执行异常：{exc}")
