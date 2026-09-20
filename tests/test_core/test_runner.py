"""core.runner 测试：执行顺序、循环、连续失败自停、急停、错误恢复（虚拟时间）。"""

import logging
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


@register
class _FakeCrashTask(BaseTask):
    task_id = "test_fake_crash"

    def run(self, ctx: TaskContext) -> TaskResult:
        EXECUTION_LOG.append("crash")
        raise RuntimeError("模拟任务内异常")


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


def test_task_exception_counts_as_failure_and_auto_stops(caplog) -> None:
    """任务内抛异常：按失败计数处理（不整体 ERROR），达到上限自动停止。"""
    config = _config([("test_fake_crash", True, 1)], loop_enabled=True, max_failures=3)
    runner = Runner(config, sleep=lambda s: None)
    runner.start()
    assert EXECUTION_LOG.count("crash") == 3
    assert runner.state is RunState.IDLE
    assert "执行异常" in caplog.text
    assert "自动停止" in caplog.text


def test_real_mode_without_window_goes_error(monkeypatch, caplog) -> None:
    """真实模式找不到游戏窗口：给出可读错误并以 ERROR 结束（不发任何输入）。"""
    from luoluotool.automation import input_sender

    monkeypatch.setattr(input_sender, "find_window", lambda keyword: None)
    config = _config([("test_fake_one", True, 1)])
    config.automation.dry_run = False
    runner = Runner(config)
    runner.start()
    assert runner.state is RunState.ERROR
    assert "未找到" in caplog.text


def test_channel_factory_is_used_for_sender(monkeypatch) -> None:
    """Runner 通过注入的通道工厂构建 sender（测试注入假 sender 的入口）。"""
    from luoluotool.automation.input_sender import DryRunSender, InputChannel

    created: list[str] = []

    def fake_factory(config, stop_event, sleep, log):
        created.append("built")
        return InputChannel(DryRunSender())

    config = _config([("test_fake_one", True, 1)])
    runner = Runner(config, channel_factory=fake_factory)
    runner.start()
    assert created == ["built"]
    assert EXECUTION_LOG == ["one"]


# ------------------------------------------- Phase 6：多来源任务编排（日常组 + 单功能组）


def _with_features(config: AppConfig, order_hold=False, feature_3=False, feature_4=False) -> AppConfig:
    config.features.order_hold.enabled = order_hold
    config.features.feature_3.enabled = feature_3
    config.features.feature_4.enabled = feature_4
    return config


def test_queue_merges_daily_group_then_single_feature_group() -> None:
    """编排规则：日常任务组（按 order 升序）→ 单功能组（卡订单 → 功能三 → 功能四）。"""
    config = _with_features(
        _config([("test_fake_two", True, 2), ("test_fake_one", True, 1), ("test_fake_off", False, 0)]),
        order_hold=True, feature_3=True,
    )
    runner = Runner(config)
    assert runner.queued_tasks() == ["test_fake_one", "test_fake_two", "order_hold", "feature_3"]
    assert "test_fake_off" not in runner.queued_tasks()


def test_queue_order_is_deterministic_for_equal_orders() -> None:
    """相同 order 时按任务 ID 字典序，保证每次运行的顺序完全一致。"""
    config = _config([("test_fake_two", True, 1), ("test_fake_one", True, 1)])
    assert Runner(config).queued_tasks() == ["test_fake_one", "test_fake_two"]


def test_single_feature_switch_off_keeps_task_out() -> None:
    """单功能组由功能主开关决定：开关关闭时不入队（默认全部关闭 → 空队列）。"""
    config = _config([("test_fake_one", True, 1)])
    assert Runner(config).queued_tasks() == ["test_fake_one"]
    assert Runner(_with_features(_config([]))).queued_tasks() == []


def test_queue_deduplicates_single_feature_tasks(caplog) -> None:
    """回归（评审 P3-4）：单功能组任务若已出现在日常任务组里，不得被重复入队。"""
    config = _with_features(_config([("order_hold", True, 1)]), order_hold=True)
    runner = Runner(config)

    queued = runner.queued_tasks()

    assert queued == ["order_hold"]                       # 只出现一次
    assert "跳过单功能组的重复入队" in caplog.text


def test_reserved_switches_never_affect_queue() -> None:
    """卡订单两个预留开关是纯占位：任意组合都不改变运行任务集合（零行为）。"""
    expected: list[str] | None = None
    for switch_1 in (False, True):
        for switch_2 in (False, True):
            config = _with_features(_config([("test_fake_one", True, 1)]), order_hold=True)
            config.features.order_hold.reserved_switch_1 = switch_1
            config.features.order_hold.reserved_switch_2 = switch_2
            queue = Runner(config).queued_tasks()
            expected = expected if expected is not None else queue
            assert queue == expected == ["test_fake_one", "order_hold"]


def test_daily_group_switch_does_not_affect_queue() -> None:
    """`daily_tasks.enabled`（启用日常任务）保持「存/读/显示」：不参与编排（既有语义）。"""
    config = _config([("test_fake_one", True, 1)])
    assert config.features.daily_tasks.enabled is False
    assert Runner(config).queued_tasks() == ["test_fake_one"]
    config.features.daily_tasks.enabled = True
    assert Runner(config).queued_tasks() == ["test_fake_one"]


def test_placeholder_feature_tasks_run_in_queue_order_with_planned_logs(caplog) -> None:
    """端到端：主开关开启的功能任务按队列顺序执行，日志中出现"规划中"记录。"""
    caplog.set_level(logging.INFO)
    config = _with_features(_config([("test_fake_one", True, 1)]), order_hold=True, feature_3=True,
                            feature_4=True)
    Runner(config).start()
    planned = [record.message for record in caplog.records if "尚未实现" in record.message]
    assert len(planned) == 3
    for message, task_id in zip(planned, ("order_hold", "feature_3", "feature_4")):
        assert message.startswith(f"进入 {task_id}") and "规划中" in message
    assert "任务队列（4 个）：test_fake_one → order_hold → feature_3 → feature_4" in caplog.text
    assert EXECUTION_LOG == ["one"]


def test_feature_tasks_only_log_and_never_produce_input(monkeypatch, caplog) -> None:
    """占位功能任务零输入：即使真实模式通道被注入，也不会调用任何输入原语。"""
    from luoluotool.automation.input_sender import DryRunSender, InputChannel

    caplog.set_level(logging.INFO)
    calls: list[str] = []

    class _RecordingChannelSender(DryRunSender):
        def click_at(self, x: int, y: int) -> None:
            calls.append("click_at")

        def key_combo(self, combo: str) -> None:
            calls.append("key_combo")

        def drag(self, from_xy, to_xy, duration_seconds: float) -> None:
            calls.append("drag")

    config = _with_features(_config([]), order_hold=True, feature_3=True, feature_4=True)
    runner = Runner(
        config,
        channel_factory=lambda *_args: InputChannel(_RecordingChannelSender()),
    )
    runner.start()
    assert calls == []
    assert caplog.text.count("规划中") >= 6   # 三个任务各一条进入 + 一条心跳


def test_feature_task_loop_repeats_and_stops(caplog) -> None:
    """循环开启时占位功能任务按轮重复执行（尊重循环间隔），停止请求可立即中断。"""
    caplog.set_level(logging.INFO)
    config = _with_features(_config([], loop_enabled=True, interval=5), order_hold=True)
    runner = Runner(config, sleep=lambda _s: None)

    def heartbeat_count() -> int:
        return sum(1 for record in caplog.records if "心跳" in record.message)

    _run_in_thread(runner, lambda: heartbeat_count() >= 3)
    assert heartbeat_count() >= 3
    assert runner.state is RunState.IDLE
    assert "自动停止" not in caplog.text   # 停止是正常路径，不算失败自停
