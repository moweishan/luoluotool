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
    """占位任务 A：按 params.click_points 依次点击。

    真实/干跑由输入层决定：干跑模式只写日志，绝不产生真实输入。
    """

    task_id = "placeholder_task_a"

    def run(self, ctx: TaskContext) -> TaskResult:
        params = PlaceholderTaskParams.from_dict(ctx.params)
        total = len(params.click_points)
        if total == 0:
            ctx.logger.warning(
                "占位任务 A 未配置点击坐标（params.click_points 为空），本轮无操作；"
                '示例："params": {"click_points": [[100, 100]], "wait_after_ms": 500}'
            )
            return TaskResult(self.task_id, True, "未配置点击坐标，跳过")
        for index, point in enumerate(params.click_points, start=1):
            if not ctx.wait_until_ready():
                return TaskResult(self.task_id, True, f"第 {index} 步前收到停止请求")
            x, y = int(point[0]), int(point[1])
            ctx.logger.info("步骤 %d/%d：点击 (%d, %d)", index, total, x, y)
            ctx.sender.click_at(x, y)
            ctx.interruptible_sleep(params.wait_after_ms / 1000)
        return TaskResult(self.task_id, True, f"完成 {total} 步点击")
