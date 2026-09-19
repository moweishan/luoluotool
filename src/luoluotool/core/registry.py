"""任务注册表：任务 ID → 任务类；内置占位任务 A 与三个预留功能占位任务。"""

from luoluotool.config.models import PlaceholderTaskParams
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
        step = 0
        for point in params.click_points:
            if not ctx.wait_until_ready():
                return TaskResult(self.task_id, True, f"第 {step + 1} 步前收到停止请求")
            step += 1
            x, y = int(point[0]), int(point[1])
            ctx.logger.info("步骤 %d/%d：点击 (%d, %d)", step, total, x, y)
            ctx.sender.click_at(x, y)
            ctx.interruptible_sleep(params.wait_after_ms / 1000)
        for swipe in params.swipes:
            if not ctx.wait_until_ready():
                return TaskResult(self.task_id, True, f"第 {step + 1} 步前收到停止请求")
            step += 1
            ctx.logger.info(
                "步骤 %d/%d：滑动 (%d, %d) → (%d, %d) 用时 %d ms",
                step, total, swipe.from_point[0], swipe.from_point[1],
                swipe.to_point[0], swipe.to_point[1], swipe.duration_ms,
            )
            ctx.sender.drag(
                (int(swipe.from_point[0]), int(swipe.from_point[1])),
                (int(swipe.to_point[0]), int(swipe.to_point[1])),
                swipe.duration_ms / 1000,
            )
            ctx.interruptible_sleep(swipe.wait_after_ms / 1000)
        for item in params.keys:
            if not ctx.wait_until_ready():
                return TaskResult(self.task_id, True, f"第 {step + 1} 步前收到停止请求")
            step += 1
            if item.hold_ms > 0:
                ctx.logger.info(
                    "步骤 %d/%d：长按 %s 持续 %d ms", step, total, item.combo, item.hold_ms
                )
                ctx.sender.key_hold(item.combo, item.hold_ms / 1000)
            else:
                ctx.logger.info("步骤 %d/%d：按键 %s", step, total, item.combo)
                ctx.sender.key_combo(item.combo)
            ctx.interruptible_sleep(item.wait_after_ms / 1000)
        return TaskResult(
            self.task_id, True,
            f"完成 {total} 步（点击 {click_total}，滑动 {swipe_total}，按键 {key_total}）",
        )


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
