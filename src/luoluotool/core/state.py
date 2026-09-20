"""运行状态枚举与状态机。"""

import threading
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
    # 评审 P3-1：STOPPING 也要允许转 ERROR —— worker 在"停止中"抛错时会 transition(ERROR)，
    # 旧表不允许会让异常处理分支二次抛出并掩盖原始异常。
    RunState.STOPPING: frozenset({RunState.IDLE, RunState.ERROR}),
    RunState.ERROR: frozenset({RunState.IDLE}),
}


class StateMachine:
    """运行状态机：拒绝非法转移（抛 ValueError）。

    评审 P3-1：加锁 + 提供 `try_transition`。主线程（停止按钮/急停）与 worker 线程会并发读写
    状态，旧实现是"先读 state 再 transition"的 check-then-act，可能命中非法转移并在 GUI 线程
    抛异常、使 `_stop()` 提前返回（跳过 wait）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = RunState.IDLE

    def transition(self, target: RunState) -> None:
        """转移状态；非法转移抛 `ValueError`（保持既有语义）。"""
        with self._lock:
            allowed = _ALLOWED_TRANSITIONS[self.state]
            if target not in allowed:
                raise ValueError(f"非法状态转移：{self.state.name} -> {target.name}")
            self.state = target

    def try_transition(self, target: RunState) -> bool:
        """尽力转移：非法转移返回 False 而不是抛异常（并发路径用）。"""
        with self._lock:
            if target not in _ALLOWED_TRANSITIONS[self.state]:
                return False
            self.state = target
            return True
