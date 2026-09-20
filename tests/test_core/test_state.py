"""core.state 测试：状态机合法/非法转移（含评审 P3-1 的并发加固）。"""

import threading

import pytest

from luoluotool.core.state import RunState, StateMachine


def test_initial_state_is_idle() -> None:
    assert StateMachine().state is RunState.IDLE


def test_stopping_can_go_to_error() -> None:
    """回归（评审 P3-1）：STOPPING → ERROR 必须合法 —— 停止过程中抛错要走 ERROR，
    旧表不允许会让异常处理分支二次抛出、掩盖原始异常。"""
    machine = StateMachine()
    machine.state = RunState.STOPPING
    machine.transition(RunState.ERROR)
    assert machine.state is RunState.ERROR


def test_try_transition_never_raises() -> None:
    """`try_transition`：非法转移返回 False（并发路径用），合法转移返回 True。"""
    machine = StateMachine()
    assert machine.try_transition(RunState.STOPPING) is False      # IDLE → STOPPING 非法
    assert machine.state is RunState.IDLE
    assert machine.try_transition(RunState.RUNNING) is True
    assert machine.try_transition(RunState.IDLE) is True


def test_concurrent_stop_requests_do_not_raise() -> None:
    """回归（评审 P3-1）：多线程同时请求停止不得抛异常（旧实现是 check-then-act）。"""
    machine = StateMachine()
    machine.transition(RunState.RUNNING)
    errors: list[Exception] = []

    def worker() -> None:
        try:
            for _ in range(200):
                machine.try_transition(RunState.STOPPING)
                machine.try_transition(RunState.IDLE)     # 模拟 worker 收尾
        except Exception as exc:                          # pragma: no cover - 只在回归时触发
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []


@pytest.mark.parametrize(
    "source,target",
    [
        (RunState.IDLE, RunState.RUNNING),
        (RunState.RUNNING, RunState.STOPPING),
        (RunState.RUNNING, RunState.ERROR),
        (RunState.RUNNING, RunState.IDLE),
        (RunState.STOPPING, RunState.IDLE),
        (RunState.ERROR, RunState.IDLE),
    ],
)
def test_legal_transitions(source, target) -> None:
    machine = StateMachine()
    machine.state = source
    machine.transition(target)
    assert machine.state is target


@pytest.mark.parametrize(
    "source,target",
    [
        (RunState.IDLE, RunState.STOPPING),
        (RunState.IDLE, RunState.ERROR),
        (RunState.STOPPING, RunState.RUNNING),
        (RunState.ERROR, RunState.RUNNING),
        (RunState.RUNNING, RunState.RUNNING),
    ],
)
def test_illegal_transitions_raise(source, target) -> None:
    machine = StateMachine()
    machine.state = source
    with pytest.raises(ValueError):
        machine.transition(target)
