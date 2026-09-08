"""core.runner 测试：执行顺序、循环、连续失败自停、急停、错误恢复（虚拟时间）。"""

import threading
import time

import pytest

from luoluotool.config.models import AppConfig, TaskConfig
from luoluotool.core.registry import register
from luoluotool.core.runner import Runner
from luoluotool.core.state import RunState
from luoluotool.core.task import BaseTask, TaskContext, TaskResult

EXECUTION_LOG: list[str] = []


@register
class _FakeTaskOne(BaseTask):
    task_id = "test_fake_one"

    def run(self, ctx: TaskContext) -> TaskResult:
        EXECUTION_LOG.append("one")
        return TaskResult(self.task_id, True)


@register
class _FakeTaskTwo(BaseTask):
    task_id = "test_fake_two"

    def run(self, ctx: TaskContext) -> TaskResult:
        EXECUTION_LOG.append("two")
        return TaskResult(self.task_id, True)


@register
class _FakeFailTask(BaseTask):
    task_id = "test_fake_fail"

    def run(self, ctx: TaskContext) -> TaskResult:
        EXECUTION_LOG.append("fail")
        return TaskResult(self.task_id, False, "模拟失败")


def _config(tasks: list[tuple[str, bool, int]], loop_enabled: bool = False,
            interval: int = 5, max_failures: int = 3) -> AppConfig:
    config = AppConfig.default()
    config.features.daily_tasks.tasks = {
        task_id: TaskConfig(enabled=enabled, order=order)
        for task_id, enabled, order in tasks
    }
    config.features.daily_tasks.loop.enabled = loop_enabled
    config.features.daily_tasks.loop.interval_seconds = interval
    config.automation.max_consecutive_failures = max_failures
    return config


@pytest.fixture(autouse=True)
def _clear_execution_log():
    EXECUTION_LOG.clear()
    yield
    EXECUTION_LOG.clear()


def _run_in_thread(runner: Runner, wait_for, timeout: float = 3.0) -> None:
    """在独立线程跑 start()，等待条件后请求停止并回收。"""
    thread = threading.Thread(target=runner.start)
    thread.start()
    deadline = time.time() + timeout
    while time.time() < deadline and not wait_for():
        time.sleep(0.01)
    runner.request_stop()
    thread.join(timeout)
    assert not thread.is_alive()


def test_runs_selected_tasks_in_order() -> None:
    runner = Runner(_config([("test_fake_two", True, 2), ("test_fake_one", True, 1)]))
    runner.start()
    assert EXECUTION_LOG == ["one", "two"]  # order 小的先执行
    assert runner.state is RunState.IDLE


def test_no_selected_tasks_returns_immediately() -> None:
    runner = Runner(_config([("test_fake_one", False, 1)]))
    runner.start()
    assert EXECUTION_LOG == []
    assert runner.state is RunState.IDLE


def test_loop_repeats_until_stop() -> None:
    config = _config([("test_fake_one", True, 1)], loop_enabled=True, interval=5)
    runner = Runner(config, sleep=lambda s: None)
    _run_in_thread(runner, lambda: len(EXECUTION_LOG) >= 4)
    assert len(EXECUTION_LOG) >= 4
    assert runner.state is RunState.IDLE


def test_consecutive_failures_auto_stop(caplog) -> None:
    """循环开启时，连续失败累计到上限后自动停止。"""
    config = _config([("test_fake_fail", True, 1)], loop_enabled=True, max_failures=3)
    runner = Runner(config)
    runner.start()
    assert EXECUTION_LOG.count("fail") == 3
    assert runner.state is RunState.IDLE
    assert "自动停止" in caplog.text


def test_success_resets_failure_count() -> None:
    """失败后紧跟成功会重置计数，不会触发自停。"""
    config = _config(
        [("test_fake_fail", True, 1), ("test_fake_one", True, 2)],
        loop_enabled=True,
        max_failures=3,
    )
    runner = Runner(config, sleep=lambda s: None)
    _run_in_thread(runner, lambda: EXECUTION_LOG.count("one") >= 4)
    assert EXECUTION_LOG.count("fail") >= 4
    assert runner.state is RunState.IDLE


def test_request_stop_interrupts_running_loop() -> None:
    config = _config([("test_fake_one", True, 1)], loop_enabled=True, interval=5)
    runner = Runner(config, sleep=lambda s: None)
    _run_in_thread(runner, lambda: bool(EXECUTION_LOG))
    assert runner.state is RunState.IDLE


def test_stop_before_start_returns_immediately() -> None:
    runner = Runner(_config([("test_fake_one", True, 1)]))
    assert runner.stop(timeout=1.0) is True
    assert runner.state is RunState.IDLE


def test_start_while_running_raises() -> None:
    config = _config([("test_fake_one", True, 1)], loop_enabled=True, interval=5)
    runner = Runner(config, sleep=lambda s: None)
    thread = threading.Thread(target=runner.start)
    thread.start()
    deadline = time.time() + 2
    while time.time() < deadline and runner.state is not RunState.RUNNING:
        time.sleep(0.01)
    with pytest.raises(RuntimeError):
        runner.start()
    runner.request_stop()
    thread.join(2)
    assert not thread.is_alive()


def test_unregistered_task_id_goes_error_and_recovers() -> None:
    config = _config([("no_such_task", True, 1)])
    runner = Runner(config)
    runner.start()
    assert runner.state is RunState.ERROR
    config.features.daily_tasks.tasks = {"test_fake_one": TaskConfig(enabled=True, order=1)}
    runner.start()  # ERROR 允许重新启动（内部先复位 IDLE）
    assert runner.state is RunState.IDLE
    assert EXECUTION_LOG == ["one"]
