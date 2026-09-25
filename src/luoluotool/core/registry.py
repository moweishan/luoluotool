"""任务注册表：任务 ID → 任务类；内置占位任务 A 与三个预留功能占位任务。"""

from collections.abc import Callable

from luoluotool.config.models import PlaceholderTaskParams
from luoluotool.core.step_mode import StepDecision
from luoluotool.core.task import BaseTask, TaskContext, TaskResult

# 任务 ID 常量（runner 编排与注册表共用，避免两处硬编码不一致）
PLACEHOLDER_TASK_A_ID = "placeholder_task_a"
ORDER_HOLD_TASK_ID = "order_hold"
FEATURE_3_TASK_ID = "feature_3"
FEATURE_4_TASK_ID = "feature_4"

_PLANNED_MESSAGE = "该功能尚未实现真实逻辑（规划中）"

_REGISTRY: dict[str, type[BaseTask]] = {}


def register(task_class: type[BaseTask]) -> type[BaseTask]:
    """注册任务类（以 task_id 为键）；空 ID 或重复 ID 抛 ValueError。"""
    task_id = getattr(task_class, "task_id", "")
    if not task_id:
        raise ValueError(f"任务类 {task_class.__name__} 缺少非空 task_id")
    if task_id in _REGISTRY:
        raise ValueError(f"任务 ID 已注册：{task_id}")
    _REGISTRY[task_id] = task_class
    return task_class


def get(task_id: str) -> type[BaseTask]:
    """按 ID 返回任务类；未注册抛 KeyError。"""
    return _REGISTRY[task_id]


def registered_ids() -> list[str]:
    """返回已注册任务 ID（排序）。"""
    return sorted(_REGISTRY)


@register
class PlaceholderTaskA(BaseTask):
    """占位任务 A：依次执行 params.click_points（点击）→ params.swipes（鼠标滑动）→ params.keys（按键）。

    按键步骤支持组合键（`ctrl+s`）与长按（`{"combo": "w", "hold_ms": 800}`）；
    滑动步骤为按住左键从 from 分帧移动到 to（`{"from": [x, y], "to": [x, y], "duration_ms": 500}`）。
    真实/干跑由输入层决定：干跑模式只写日志，绝不产生真实输入。
    """

    task_id = PLACEHOLDER_TASK_A_ID

    def run(self, ctx: TaskContext) -> TaskResult:
        params = PlaceholderTaskParams.from_dict(ctx.params)
        click_total = len(params.click_points)
        swipe_total = len(params.swipes)
        key_total = len(params.keys)
        total = click_total + swipe_total + key_total
        if total == 0:
            ctx.logger.warning(
                "占位任务 A 未配置任何步骤（params.click_points / params.swipes / params.keys 均为空），"
                "本轮无操作；示例："
                '"params": {"click_points": [[100, 100]], '
                '"swipes": [{"from": [300, 300], "to": [600, 300], "duration_ms": 500}], '
                '"keys": [{"combo": "ctrl+s"}], "wait_after_ms": 500}'
            )
            return TaskResult(self.task_id, True, "未配置任何步骤，跳过")
        # 把三类参数摊平成**有序步骤表**（点击 → 滑动 → 按键，与旧实现完全同序）：
        # 单步运行（用户 2026-09-22）需要"一个动作＝一步"的粒度，并且要能被「上一步」退回。
        steps = self._build_steps(params, ctx)
        index = 0
        while index < total:
            if not ctx.wait_until_ready():
                return TaskResult(self.task_id, True, f"第 {index + 1} 步前收到停止请求")
            label, action, wait_after_ms = steps[index]
            decision, restore_to = ctx.step_gate(index, total, label)
            if decision == StepDecision.STOPPED:
                return TaskResult(self.task_id, True, f"第 {index + 1} 步前收到停止请求")
            if decision == StepDecision.REWOUND:
                # 「上一步」：指针退回去了 —— **不执行这一步**，只把光标放回那一步的位置
                if restore_to is not None:
                    ctx.sender.move_cursor(int(restore_to[0]), int(restore_to[1]))
                index = ctx.stepper.index() if ctx.stepper is not None else index
                continue
            ctx.logger.info("步骤 %d/%d：%s", index + 1, total, label)
            action()
            ctx.step_done(index)
            index += 1
            ctx.interruptible_sleep(wait_after_ms / 1000)
        return TaskResult(
            self.task_id, True,
            f"完成 {total} 步（点击 {click_total}，滑动 {swipe_total}，按键 {key_total}）",
        )

    @staticmethod
    def _build_steps(
        params: PlaceholderTaskParams, ctx: TaskContext
    ) -> list[tuple[str, Callable[[], None], int]]:
        """把参数摊平成步骤表：`(日志文案, 动作, 该步之后的等待毫秒数)`。

        顺序与旧实现一字不差：先全部点击、再全部滑动、最后全部按键；
        文案也与旧日志保持一致（单步运行时它就是"这一步在干什么"的显示文案）。
        """
        steps: list[tuple[str, Callable[[], None], int]] = []
        for point in params.click_points:
            x, y = int(point[0]), int(point[1])
            steps.append((
                f"点击 ({x}, {y})",
                lambda x=x, y=y: ctx.sender.click_at(x, y),
                params.wait_after_ms,
            ))
        for swipe in params.swipes:
            from_point = (int(swipe.from_point[0]), int(swipe.from_point[1]))
            to_point = (int(swipe.to_point[0]), int(swipe.to_point[1]))
            seconds = swipe.duration_ms / 1000
            steps.append((
                f"滑动 ({from_point[0]}, {from_point[1]}) → ({to_point[0]}, {to_point[1]})"
                f" 用时 {swipe.duration_ms} ms",
                lambda f=from_point, t=to_point, s=seconds: ctx.sender.drag(f, t, s),
                swipe.wait_after_ms,
            ))
        for item in params.keys:
            if item.hold_ms > 0:
                seconds = item.hold_ms / 1000
                steps.append((
                    f"长按 {item.combo} 持续 {item.hold_ms} ms",
                    lambda c=item.combo, s=seconds: ctx.sender.key_hold(c, s),
                    item.wait_after_ms,
                ))
            else:
                steps.append((
                    f"按键 {item.combo}",
                    lambda c=item.combo: ctx.sender.key_combo(c),
                    item.wait_after_ms,
                ))
        return steps


class PlaceholderFeatureTask(BaseTask):
    """Phase 6 预留功能占位任务：**只写「进入日志 + 心跳日志」并响应停止**。

    严格边界（用户要求）：不产生任何输入、不读 params、不含任何推测性业务逻辑；
    卡订单的两个预留开关同样不参与行为（只存/读/显示）。真实功能由后续阶段实现。
    """

    feature_label = ""

    def run(self, ctx: TaskContext) -> TaskResult:
        if ctx.should_stop():
            return TaskResult(self.task_id, True, "收到停止请求，未执行")
        ctx.logger.info(
            "进入 %s（%s）：%s", self.task_id, self.feature_label, _PLANNED_MESSAGE
        )
        ctx.logger.info("%s 心跳：本轮无实际操作，等待后续阶段实现（规划中）", self.task_id)
        return TaskResult(self.task_id, True, "规划中：本轮无实际动作")


@register
class OrderHoldTask(PlaceholderFeatureTask):
    """功能二：卡订单（占位；两个预留开关不触发任何行为）。"""

    task_id = ORDER_HOLD_TASK_ID
    feature_label = "功能二：卡订单"


@register
class Feature3Task(PlaceholderFeatureTask):
    """功能三（占位）。"""

    task_id = FEATURE_3_TASK_ID
    feature_label = "功能三"


@register
class Feature4Task(PlaceholderFeatureTask):
    """功能四（占位）。"""

    task_id = FEATURE_4_TASK_ID
    feature_label = "功能四"
