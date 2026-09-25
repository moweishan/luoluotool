"""单步运行（调试）测试：控制器语义 + 任务按步执行 + 主循环接线。

用户 2026-09-22 要求：开发者调试页最上方加「单步运行」开关，勾上后点「启动」时
**每点一次「下一步」脚本才走一步**；「上一步」回到上一步的运动状态，且**不执行**那一步的脚本动作。
三个口径都按用户当场选的：① 开关**不存盘**（只在本次运行有效）；② **一个动作＝一步**
（点击 / 滑动 / 按键各算一步）；③ 「上一步」＝**指针回退 + 光标回到那一步的位置**。

这里只测核心层（不碰 Qt）：`core/step_mode.StepController`、`core/registry` 的按步执行、
`core/runner` 的挂接。界面部分在 `tests/test_gui_step_mode.py`。
"""

import threading
import time

from luoluotool.config.models import AppConfig
from luoluotool.core.registry import PlaceholderTaskA
from luoluotool.core.runner import Runner
from luoluotool.core.step_mode import StepDecision, StepController, StepSnapshot
from luoluotool.core.task import TaskContext


class _FakeSender:
    """记录调用的假输入通道（**零真实输入**）；光标位置由脚本决定，便于断言"回位"。"""

    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []
        self.keys: list[str] = []
        self.drags: list[tuple] = []
        self.moves: list[tuple[int, int]] = []
        self.cursor: tuple[int, int] | None = (5, 5)

    def move_to(self, x: int, y: int) -> None:
        return None

    def click(self, x: int, y: int, hold_seconds: float | None = None) -> None:
        self.click_at(x, y, hold_seconds)

    def click_at(self, x: int, y: int, hold_seconds: float | None = None) -> None:
        self.clicks.append((x, y))
        self.cursor = (x, y)                     # 点完光标就停在那儿

    def key_tap(self, vk: int) -> None:
        return None

    def drag(self, from_xy, to_xy, duration_seconds: float) -> None:
        self.drags.append((tuple(from_xy), tuple(to_xy)))
        self.cursor = (int(to_xy[0]), int(to_xy[1]))

    def key_combo(self, combo: str) -> None:
        self.keys.append(combo)

    def key_hold(self, combo: str, seconds: float) -> None:
        self.keys.append(f"{combo}*{int(seconds * 1000)}")

    # ---- 单步专用 ----
    def cursor_position(self) -> tuple[int, int] | None:
        return self.cursor

    def move_cursor(self, x: int, y: int) -> None:
        self.moves.append((int(x), int(y)))
        self.cursor = (int(x), int(y))


def _ctx(stepper: StepController, sender: _FakeSender) -> TaskContext:
    return TaskContext(
        stop_event=threading.Event(), dry_run=True, sender=sender,
        sleep=lambda _seconds: None, stepper=stepper,
    )


def _task_params(**overrides) -> dict:
    params = {"click_points": [[10, 20], [30, 40]], "keys": [{"combo": "ctrl+s"}],
              "wait_after_ms": 0}
    params.update(overrides)
    return params


def _press_next(stepper: StepController, index: int, timeout: float = 5.0) -> None:
    """等执行线程停在**第 index 步**的门口再按「下一步」。

    只看 `waiting` 不够：上一张放行票被消费之前 `waiting` 一直是 True，按早了会被控制器
    （有意地）忽略，于是测试会偶发地"少按一次"。这里按门牌号等，消除这个竞态。
    """
    assert _wait_until(
        lambda: stepper.snapshot().waiting and stepper.snapshot().index == index, timeout
    ), f"执行线程没停在第 {index + 1} 步门口：{stepper.snapshot()}"
    assert stepper.request_next() is True


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


# ------------------------------------------------------------------ 控制器
def test_controller_is_a_no_op_when_step_mode_is_off() -> None:
    """没勾单步：`gate` 立即放行、不记游标 —— 非单步路径的开销与行为不许变。"""
    stepper = StepController()

    decision, restore = stepper.gate(0, 3, "点击 (1, 2)", should_stop=lambda: False)

    assert stepper.enabled() is False
    assert (decision, restore) == (StepDecision.RUN, None)
    assert stepper.snapshot() == StepSnapshot(index=0, total=0, label="", waiting=False)


def test_gate_waits_until_next_step_is_requested() -> None:
    """勾上单步：`gate` 会一直等到「下一步」—— 这就是"点一次走一步"的落点。"""
    stepper = StepController()
    stepper.set_enabled(True)
    stepper.begin_run()
    results: list[str] = []

    worker = threading.Thread(
        target=lambda: results.append(
            stepper.gate(0, 2, "点击 (10, 20)", should_stop=lambda: False)[0]
        )
    )
    worker.start()

    assert _wait_until(lambda: stepper.snapshot().waiting), "执行线程应停在第一步门口"
    assert stepper.snapshot().index == 0 and stepper.snapshot().total == 2
    assert stepper.snapshot().label == "点击 (10, 20)"
    assert results == []                                   # 没点「下一步」之前一步都不走

    assert stepper.request_next() is True
    worker.join(timeout=5)
    assert results == [StepDecision.RUN]


def test_previous_rewinds_the_pointer_and_returns_the_recorded_cursor() -> None:
    """「上一步」：指针退一格 + 给出"上一步跑完时"的光标位置；**不放行任何一步**。

    场景＝用户已经点了两次「下一步」（第 1、2 步都跑完了），现在停在第三步门口。
    """
    stepper = StepController()
    stepper.set_enabled(True)
    stepper.begin_run(initial_cursor=(5, 5))               # 脚本开始前光标在 (5,5)
    stepper.complete(0, (10, 20))                          # 第 1 步（点击 10,20）跑完了
    stepper.complete(1, (30, 40))                          # 第 2 步跑完了 → 指针＝2
    decisions: list[tuple] = []

    worker = threading.Thread(
        target=lambda: decisions.append(
            stepper.gate(2, 3, "按键 ctrl+s", should_stop=lambda: False)
        )
    )
    worker.start()
    assert _wait_until(lambda: stepper.snapshot().waiting)

    rewind = stepper.request_previous()

    assert rewind == (1, (10, 20))                    # 退回第 2 步、光标回到"第 1 步跑完"的位置
    assert stepper.index() == 1
    worker.join(timeout=5)
    assert decisions == [(StepDecision.REWOUND, (10, 20))]  # 执行方只"重新读指针"，不执行动作

    # 真实执行方拿到新指针后会**重新等门**（任务循环里就是这么做的），再点「下一步」才继续
    again: list[tuple] = []
    worker2 = threading.Thread(daemon=True, target=lambda: again.append(
        stepper.gate(1, 3, "点击 (30, 40)", should_stop=lambda: False)
    ))
    worker2.start()
    assert _wait_until(lambda: stepper.snapshot().waiting)
    assert stepper.request_next() is True
    worker2.join(timeout=5)
    assert again == [(StepDecision.RUN, None)]


def test_previous_at_the_first_step_goes_back_to_the_pre_script_cursor() -> None:
    """已经在第一步：指针不再后退，只把光标放回"脚本开始前"的位置（不执行任何动作）。"""
    stepper = StepController()
    stepper.set_enabled(True)
    stepper.begin_run(initial_cursor=(5, 5))
    decisions: list[tuple] = []
    worker = threading.Thread(
        target=lambda: decisions.append(
            stepper.gate(0, 3, "点击 (10, 20)", should_stop=lambda: False)
        )
    )
    worker.start()
    assert _wait_until(lambda: stepper.snapshot().waiting)

    rewind = stepper.request_previous()

    assert rewind == (0, (5, 5))
    assert stepper.index() == 0
    worker.join(timeout=5)
    assert decisions == [(StepDecision.REWOUND, (5, 5))]   # 仍然不执行这一步

    again: list[tuple] = []
    worker2 = threading.Thread(daemon=True, target=lambda: again.append(
        stepper.gate(0, 3, "点击 (10, 20)", should_stop=lambda: False)
    ))
    worker2.start()
    assert _wait_until(lambda: stepper.snapshot().waiting)
    assert stepper.request_next() is True
    worker2.join(timeout=5)
    assert again == [(StepDecision.RUN, None)]


def test_previous_without_a_recorded_cursor_only_moves_the_pointer() -> None:
    """开始前读不到光标（干跑/读失败）：指针照回退，回位目标为 None（调用方跳过回位）。"""
    stepper = StepController()
    stepper.set_enabled(True)
    stepper.begin_run()                                    # 没有初始光标
    stepper.complete(0, None)

    assert stepper.request_previous() == (0, None)
    assert stepper.index() == 0


def test_disabling_step_mode_releases_a_waiting_executor() -> None:
    """运行中把单步开关关掉：等在门口的线程立刻继续（不能把任务卡死）。"""
    stepper = StepController()
    stepper.set_enabled(True)
    stepper.begin_run()
    decisions: list[str] = []
    worker = threading.Thread(
        target=lambda: decisions.append(
            stepper.gate(0, 1, "点击 (1, 1)", should_stop=lambda: False)[0]
        )
    )
    worker.start()
    assert _wait_until(lambda: stepper.snapshot().waiting)

    stepper.set_enabled(False)
    worker.join(timeout=5)

    assert decisions == [StepDecision.RUN]


def test_stop_request_releases_a_waiting_executor() -> None:
    """急停：等在门口也要收手（返回 STOPPED，由任务返回"第 N 步前收到停止请求"）。"""
    stepper = StepController()
    stepper.set_enabled(True)
    stepper.begin_run()
    stop = threading.Event()
    decisions: list[str] = []
    worker = threading.Thread(
        target=lambda: decisions.append(
            stepper.gate(0, 1, "点击 (1, 1)", should_stop=stop.is_set)[0]
        )
    )
    worker.start()
    assert _wait_until(lambda: stepper.snapshot().waiting)

    stop.set()
    worker.join(timeout=5)

    assert decisions == [StepDecision.STOPPED]


def test_next_pressed_before_the_run_starts_does_not_leak_into_it() -> None:
    """「下一步」在没人等的时候按下去不算数：新的一轮仍然老老实实等第一步。"""
    stepper = StepController()
    stepper.set_enabled(True)

    assert stepper.request_next() is False                 # 没有人在等 → 不接受
    stepper.begin_run()
    assert stepper.index() == 0
    assert stepper.snapshot().waiting is False


# ------------------------------------------------------------------ 任务按步执行
def test_task_runs_one_action_per_next_press() -> None:
    """勾上单步：点一次「下一步」只走一个动作；不点就一直停着。"""
    stepper = StepController()
    stepper.set_enabled(True)
    sender = _FakeSender()
    ctx = _ctx(stepper, sender)
    ctx.params = _task_params()
    results = []

    worker = threading.Thread(daemon=True, target=lambda: results.append(PlaceholderTaskA().run(ctx)))
    worker.start()

    assert _wait_until(lambda: stepper.snapshot().waiting)
    assert sender.clicks == []                             # 第 1 步还没被放行

    stepper.request_next()
    assert _wait_until(lambda: sender.clicks == [(10, 20)])
    assert stepper.index() == 1                            # 停在第二步门口
    assert sender.keys == []                               # 后面的步骤一步都没走

    stepper.request_next()
    assert _wait_until(lambda: sender.clicks == [(10, 20), (30, 40)])
    stepper.request_next()
    assert _wait_until(lambda: sender.keys == ["ctrl+s"])
    worker.join(timeout=5)

    assert results and results[0].message == "完成 3 步（点击 2，滑动 0，按键 1）"
    assert (stepper.index(), stepper.snapshot().waiting) == (3, False)


def test_previous_does_not_execute_the_step_again() -> None:
    """「上一步」**不执行**上一步的脚本动作：只把光标移回那一步的位置，点击次数不增加。"""
    stepper = StepController()
    stepper.set_enabled(True)
    sender = _FakeSender()
    stepper.begin_run(initial_cursor=sender.cursor_position())  # Runner 启动时会做的第一件事
    ctx = _ctx(stepper, sender)
    ctx.params = _task_params()
    results = []

    worker = threading.Thread(daemon=True, target=lambda: results.append(PlaceholderTaskA().run(ctx)))
    worker.start()
    assert _wait_until(lambda: stepper.snapshot().waiting)
    stepper.request_next()
    assert _wait_until(lambda: sender.clicks == [(10, 20)])   # 走完第 1 步
    assert _wait_until(lambda: stepper.snapshot().waiting)    # 停在第二步门口

    stepper.request_previous()

    assert _wait_until(lambda: sender.moves == [(5, 5)])      # 光标回位到"脚本开始前"
    assert sender.clicks == [(10, 20)]                        # 点击**没有**再来一次
    assert stepper.index() == 0

    _press_next(stepper, 0)                                   # 回到第 1 步后可以重跑它
    assert _wait_until(lambda: sender.clicks == [(10, 20), (10, 20)])
    _press_next(stepper, 1)                                   # 第 2 步
    _press_next(stepper, 2)                                   # 第 3 步
    worker.join(timeout=5)
    assert results, "任务应当能跑完（回退不影响收尾）"
    assert results[0].message == "完成 3 步（点击 2，滑动 0，按键 1）"


def test_task_keeps_the_old_behaviour_when_step_mode_is_off() -> None:
    """没勾单步：一次跑完（回归：非单步路径的日志与结果文案一字不变）。"""
    stepper = StepController()                                # enabled=False
    sender = _FakeSender()
    ctx = _ctx(stepper, sender)
    ctx.params = _task_params()

    result = PlaceholderTaskA().run(ctx)

    assert sender.clicks == [(10, 20), (30, 40)] and sender.keys == ["ctrl+s"]
    assert result.message == "完成 3 步（点击 2，滑动 0，按键 1）"


def test_task_reports_the_step_it_stopped_before() -> None:
    """单步模式下按急停：停在门口 → 任务返回"第 N 步前收到停止请求"，不执行那一步。"""
    stepper = StepController()
    stepper.set_enabled(True)
    stepper.begin_run()
    sender = _FakeSender()
    ctx = _ctx(stepper, sender)
    ctx.params = _task_params(click_points=[[10, 20]])

    stop = threading.Event()
    ctx.stop_event = stop
    results = []
    worker = threading.Thread(daemon=True, target=lambda: results.append(PlaceholderTaskA().run(ctx)))
    worker.start()
    assert _wait_until(lambda: stepper.snapshot().waiting)

    stop.set()
    worker.join(timeout=5)

    assert sender.clicks == []
    assert results and "第 1 步前收到停止请求" in results[0].message


# ------------------------------------------------------------------ 主循环接线
def test_runner_passes_the_stepper_into_the_task_context() -> None:
    """`Runner` 把单步控制器交给任务上下文，并在运行前后开会话（清掉上一轮残留的放行）。"""
    stepper = StepController()
    stepper.set_enabled(True)
    sender = _FakeSender()

    class _Channel:
        def __init__(self) -> None:
            self.sender = sender

        def readiness(self) -> bool:
            return True

    config = AppConfig.default()
    config.features.daily_tasks.enabled = True
    config.features.daily_tasks.tasks["placeholder_task_a"].enabled = True
    config.features.daily_tasks.tasks["placeholder_task_a"].params = _task_params()
    runner = Runner(config, sleep=lambda _s: None,
                    channel_factory=lambda *args: _Channel(), stepper=stepper)

    worker = threading.Thread(daemon=True, target=runner.start)
    worker.start()
    assert _wait_until(lambda: stepper.snapshot().waiting)
    assert sender.clicks == []

    stepper.request_next()
    assert _wait_until(lambda: sender.clicks == [(10, 20)])

    runner.request_stop()
    worker.join(timeout=5)

    assert sender.clicks == [(10, 20)]                    # 停在第二步就被急停收手了
    assert stepper.snapshot().waiting is False            # 运行结束后不再显示"正在等"


def test_runner_attaches_the_stepper_later_too() -> None:
    """GUI 的 runner 工厂只吃 config，所以也支持启动前把控制器挂上去。"""
    runner = Runner(AppConfig.default(), sleep=lambda _s: None)

    assert runner.stepper is None
    stepper = StepController()
    runner.stepper = stepper
    assert runner.stepper is stepper
