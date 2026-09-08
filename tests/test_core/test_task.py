"""core.task 测试：TaskContext、TaskResult、BaseTask。"""

import pytest

from luoluotool.core.task import BaseTask, TaskContext, TaskResult


def test_should_stop_reflects_event() -> None:
    ctx = TaskContext()
    assert ctx.should_stop() is False
    ctx.stop_event.set()
    assert ctx.should_stop() is True


def test_interruptible_sleep_chunks_and_accumulates() -> None:
    calls: list[float] = []
    ctx = TaskContext(sleep=calls.append)
    ctx.interruptible_sleep(1.0)
    assert len(calls) == 10
    assert max(calls) <= 0.1
    assert sum(calls) == pytest.approx(1.0)


def test_interruptible_sleep_stops_immediately_when_stop_set() -> None:
    calls: list[float] = []
    ctx = TaskContext(sleep=calls.append)
    ctx.stop_event.set()
    ctx.interruptible_sleep(5.0)
    assert calls == []


def test_interruptible_sleep_stops_midway() -> None:
    calls: list[float] = []
    ctx = TaskContext()

    def fake_sleep(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) >= 3:
            ctx.stop_event.set()

    ctx.sleep = fake_sleep
    ctx.interruptible_sleep(5.0)
    assert calls == [0.1] * 3


def test_base_task_run_raises() -> None:
    with pytest.raises(NotImplementedError):
        BaseTask().run(TaskContext())


def test_task_result_fields() -> None:
    result = TaskResult("t1", True, "ok")
    assert (result.task_id, result.success, result.message) == ("t1", True, "ok")
    assert TaskResult("t2", False).message == ""
