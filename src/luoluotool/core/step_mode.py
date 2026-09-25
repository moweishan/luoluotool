"""单步运行（调试）：让脚本"点一次「下一步」才走一步"的控制器（与 Qt 无关）。

用户 2026-09-22 要求：开发者调试页最上方加「单步运行」开关，勾上后点「启动」时
**每点一次「下一步」脚本才走一步**；「上一步」回到上一步的运动状态，且**不执行**那一步的动作
（"只是调试方便"）。三个口径都是用户当场选的：

① **不存盘**：只在本次运行有效 —— 万一存盘后忘了关，下次点「启动」会"卡住不动"；
② **一个动作＝一步**：点击 / 滑动 / 按键各算一步（和 `registry.PlaceholderTaskA` 的步骤一一对应）；
③ **「上一步」＝指针回退 + 光标回到那一步的位置**：不重放任何点击/按键/滑动。

分工（谁在哪里跑）：

- **执行线程**（任务里）在每一步**执行前**调 `gate(...)`：单步模式下它在门口等，
  直到界面按「下一步」（`RUN`）、按「上一步」（`REWOUND`，此时把「回位目标」交回调用方去移光标）、
  急停（`STOPPED`）或单步开关被关掉（`RUN`，继续跑完，绝不把任务卡死）；
- **界面线程**调 `request_next()` / `request_previous()` —— 它们只改状态与唤醒等待者，
  **不做任何输入**；真正的"光标回位"由拿到 `REWOUND` 的执行线程用输入通道去做
  （真实键鼠只允许在 `automation` 层动，`core` 不碰 win32）；
- 单步**关闭**时所有方法都是空操作：`gate()` 立刻返回 `RUN`，一个字都不记
  （非单步路径的行为与开销必须和以前完全一样）。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

STEP_POLL_SECONDS = 0.1          # 等「下一步」时的轮询间隔（急停最迟 0.1 秒内生效）


class StepDecision:
    """执行线程在门口等到的结论（用字符串常量而不是 Enum，便于日志里直接打出来）。"""

    RUN = "run"                  # 放行：执行这一步
    REWOUND = "rewound"          # 指针被「上一步」挪走了：重新读指针，**不要**执行
    STOPPED = "stopped"          # 收到停止请求：收手


@dataclass(frozen=True)
class StepSnapshot:
    """给界面看的当前单步状态（正在等第几步、共几步、这一步叫什么）。"""

    index: int = 0
    total: int = 0
    label: str = ""
    waiting: bool = False


class StepController:
    """单步控制器：执行线程等门、界面按「下一步 / 上一步」（线程安全）。"""

    def __init__(self, *, on_change: Callable[[StepSnapshot], None] | None = None) -> None:
        self._cv = threading.Condition()
        self._enabled = False
        self._index = 0                       # 下一步要执行的序号（0 起）
        self._total = 0
        self._label = ""
        self._waiting = False                 # 执行线程是否正停在门口
        self._grants = 0                      # 「下一步」的放行票（一次只发一张）
        self._pending_restore: tuple[int, int] | None = None
        self._after: dict[int, tuple[int, int] | None] = {}
        # 回调来自**执行线程**：实现方（GUI 桥）必须自己转成 Qt 信号，别在这里碰界面
        self._on_change = on_change

    # ---------------------------------------------------------------- 开关
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        """界面开关。关掉时唤醒等在门口的线程（它按"继续跑"处理，任务不会被卡住）。"""
        with self._cv:
            if self._enabled == bool(value):
                return
            self._enabled = bool(value)
            self._grants = 0
            self._cv.notify_all()
            snapshot = self._snapshot()
        logger.info("单步运行：%s", "开启（点一次「下一步」走一步）" if self._enabled else "关闭")
        self._emit(snapshot)

    # ---------------------------------------------------------------- 运行边界
    def begin_run(self, initial_cursor: tuple[int, int] | None = None) -> None:
        """一轮运行开始：清空上一轮的游标与残留放行票，指针回到第一步。

        `initial_cursor` ＝"脚本开始前光标在哪"，记在 **0 号位**（指针停在第 0 步时的状态），
        供「上一步」退到第一步/最初状态时回位用。
        **不清 `enabled`**：开关是用户勾的，跨轮保留。
        """
        with self._cv:
            self._index = 0
            self._total = 0
            self._label = ""
            self._grants = 0
            self._pending_restore = None
            self._after = {0: initial_cursor}
            snapshot = self._snapshot()
        self._emit(snapshot)

    def end_run(self) -> None:
        """一轮运行结束：清掉"正在等"的显示状态（开关保持用户勾选的样子）。"""
        with self._cv:
            self._waiting = False
            self._grants = 0
            self._pending_restore = None
            snapshot = self._snapshot()
        self._emit(snapshot)

    # ---------------------------------------------------------------- 执行线程
    def gate(self, index: int, total: int, label: str,
             *, should_stop: Callable[[], bool]) -> tuple[str, tuple[int, int] | None]:
        """在第 `index` 步**执行前**调：返回 `(StepDecision, 回位目标)`。

        非单步模式：立刻返回 `(RUN, None)`，不记任何状态（行为与开销不变）。
        单步模式：阻塞直到「下一步」/「上一步」/急停/关开关。
        """
        if not self._enabled:
            return (StepDecision.RUN, None)
        with self._cv:
            self._total = int(total)
            self._label = str(label)
            self._waiting = True
            snapshot = self._snapshot()
        self._emit(snapshot)
        while True:
            with self._cv:
                if should_stop():
                    self._waiting = False
                    snapshot = self._snapshot()
                    self._emit(snapshot)
                    return (StepDecision.STOPPED, None)
                if not self._enabled:                  # 运行中关掉单步 → 立刻放行
                    self._waiting = False
                    snapshot = self._snapshot()
                    self._emit(snapshot)
                    return (StepDecision.RUN, None)
                if self._pending_restore is not None or self._index != index:
                    restore = self._pending_restore
                    self._pending_restore = None
                    self._waiting = False
                    snapshot = self._snapshot()
                    self._emit(snapshot)
                    return (StepDecision.REWOUND, restore)
                if self._grants > 0:
                    self._grants -= 1
                    self._waiting = False
                    snapshot = self._snapshot()
                    self._emit(snapshot)
                    return (StepDecision.RUN, None)
                self._cv.wait(STEP_POLL_SECONDS)

    def complete(self, index: int, cursor: tuple[int, int] | None) -> None:
        """第 `index` 步执行完：指针前进一格，并记下"指针到新位置时的光标在哪"。

        记的键是**前进之后的指针值**：`_after[k]` 就表示"指针停在第 k 步时光标在哪"，
        于是「上一步」退到第 k 步时直接取 `_after[k]` 就是那个运动状态（0 号位＝脚本开始前）。
        """
        if not self._enabled:
            return
        with self._cv:
            self._index = index + 1
            self._after[self._index] = cursor
            snapshot = self._snapshot()
        self._emit(snapshot)

    def index(self) -> int:
        with self._cv:
            return self._index

    # ---------------------------------------------------------------- 界面按钮
    def request_next(self) -> bool:
        """「下一步」：放行一步。**返回是否真的被接受**。

        两种不接受的清况（都给界面一个诚实的返回值，而不是静默吃掉一次点击）：
        ① 现在没人在门口等（比如还没点「启动」）—— 否则这张票会留到下一轮自动跑掉；
        ② 上一步的票**还没被消费**（用户连点了两下）—— 单步调试要的是一步一停，
           连点两下不该变成"跳过一步"。
        """
        with self._cv:
            if not self._waiting:
                logger.info("单步：现在没有停在门口，忽略「下一步」")
                return False
            if self._grants > 0:
                logger.info("单步：上一步还没走完（放行票未消费），忽略这次「下一步」")
                return False
            self._grants = 1
            self._cv.notify_all()
            return True

    def request_previous(self) -> tuple[int, tuple[int, int] | None]:
        """「上一步」：指针退一格 + 给出"那一步的运动状态"（光标位置）；**不放行、不执行**。

        指针已经指向第一步时不再后退，只把光标放回"脚本开始前"记录的位置。
        """
        with self._cv:
            target = max(0, self._index - 1)
            restore = self._after.get(target)      # "指针停在第 target 步时光标在哪"
            self._index = target
            self._pending_restore = restore
            self._grants = 0
            self._cv.notify_all()
            snapshot = self._snapshot()
        logger.info("单步：回到第 %d 步（不执行动作，光标回位到 %s）",
                    target + 1, restore if restore is not None else "原位（未记录）")
        self._emit(snapshot)
        return (target, restore)

    def snapshot(self) -> StepSnapshot:
        with self._cv:
            return self._snapshot()

    # ---------------------------------------------------------------- 内部
    def _snapshot(self) -> StepSnapshot:
        return StepSnapshot(
            index=self._index, total=self._total, label=self._label, waiting=self._waiting
        )

    def _emit(self, snapshot: StepSnapshot) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(snapshot)
        except Exception:                          # 界面回调不许把执行线程带崩
            logger.exception("单步状态回调异常（已忽略）")
