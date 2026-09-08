"""core.registry 测试：注册表与占位任务 A。"""

import pytest

from luoluotool.core.registry import PlaceholderTaskA, get, register, registered_ids
from luoluotool.core.task import BaseTask, TaskContext


def test_placeholder_task_a_is_registered() -> None:
    assert "placeholder_task_a" in registered_ids()
    assert get("placeholder_task_a") is PlaceholderTaskA


def test_get_unknown_raises_key_error() -> None:
    with pytest.raises(KeyError):
        get("no_such_task")


def test_register_duplicate_id_raises() -> None:
    class DupTask(BaseTask):
        task_id = "placeholder_task_a"

    with pytest.raises(ValueError):
        register(DupTask)


def test_register_missing_id_raises() -> None:
    class NoIdTask(BaseTask):
        pass

    with pytest.raises(ValueError):
        register(NoIdTask)


def test_placeholder_runs_steps_and_logs() -> None:
    record_logs: list[str] = []

    class FakeLogger:
        def info(self, msg, *args) -> None:
            record_logs.append(msg % args)

    ctx = TaskContext(sleep=lambda s: None, logger=FakeLogger())
    result = PlaceholderTaskA().run(ctx)
    assert result.success is True
    assert len(record_logs) == 3
    assert "模拟点击" in record_logs[0]
    assert "第 1 步" in record_logs[0]


def test_placeholder_stops_on_request() -> None:
    sleep_count = {"n": 0}
    ctx = TaskContext()

    def fake_sleep(seconds: float) -> None:
        sleep_count["n"] += 1
        ctx.stop_event.set()

    ctx.sleep = fake_sleep
    result = PlaceholderTaskA().run(ctx)
    assert result.success is True
    assert "停止" in result.message
    assert sleep_count["n"] == 1
