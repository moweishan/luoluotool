"""任务注册表：任务 ID → 任务类；内置占位任务 A。"""

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
    """占位任务 A：每秒输出一条模拟点击日志；尊重停止请求。"""

    task_id = "placeholder_task_a"
    steps: int = 3
    step_interval_seconds: float = 1.0
    click_point: tuple[int, int] = (100, 100)

    def run(self, ctx: TaskContext) -> TaskResult:
        for step in range(1, self.steps + 1):
            if ctx.should_stop():
                return TaskResult(self.task_id, True, f"第 {step} 步前收到停止请求")
            ctx.logger.info("模拟点击 (%d, %d)（第 %d 步）", *self.click_point, step)
            ctx.interruptible_sleep(self.step_interval_seconds)
        return TaskResult(self.task_id, True, f"完成 {self.steps} 步模拟")
