"""运行状态枚举与状态机。"""

from enum import Enum, auto


class RunState(Enum):
    """运行状态。"""

    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    ERROR = auto()


_ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.IDLE: frozenset({RunState.RUNNING}),
    RunState.RUNNING: frozenset({RunState.STOPPING, RunState.ERROR, RunState.IDLE}),
    RunState.STOPPING: frozenset({RunState.IDLE}),
    RunState.ERROR: frozenset({RunState.IDLE}),
}


class StateMachine:
    """运行状态机：拒绝非法转移（抛 ValueError）。"""

    def __init__(self) -> None:
        self.state = RunState.IDLE

    def transition(self, target: RunState) -> None:
        allowed = _ALLOWED_TRANSITIONS[self.state]
        if target not in allowed:
            raise ValueError(f"非法状态转移：{self.state.name} -> {target.name}")
        self.state = target
