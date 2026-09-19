"""任务注册表：任务 ID → 任务类；内置占位任务 A。"""

from luoluotool.config.models import PlaceholderTaskParams
from luoluotool.core.task import BaseTask, TaskContext, TaskResult

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

    task_id = "placeholder_task_a"

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
