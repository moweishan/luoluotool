"""core.state 测试：状态机合法/非法转移。"""

import pytest

from luoluotool.core.state import RunState, StateMachine


def test_initial_state_is_idle() -> None:
    assert StateMachine().state is RunState.IDLE


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
