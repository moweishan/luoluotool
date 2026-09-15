"""core.registry 测试：注册表与占位任务 A。"""

import logging

import pytest

from luoluotool.core.registry import PlaceholderTaskA, get, register, registered_ids
from luoluotool.core.task import BaseTask, TaskContext


@pytest.fixture(autouse=True)
def _capture_info_logs(caplog):
    caplog.set_level(logging.INFO)


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


class _RecordingSender:
    """假 sender：只记录调用，绝不产生真实输入。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def move_to(self, x: int, y: int) -> None:
        self.calls.append(("move_to", x, y))

    def click(self, x: int, y: int) -> None:
        self.calls.append(("click", x, y))

    def click_at(self, x: int, y: int) -> None:
        self.calls.append(("click_at", x, y))

    def key_tap(self, vk: int) -> None:
        self.calls.append(("key_tap", vk))


def test_placeholder_clicks_configured_points_in_order(caplog) -> None:
    sender = _RecordingSender()
    sleeps: list[float] = []
    ctx = TaskContext(
        sender=sender,
        sleep=sleeps.append,
        params={"click_points": [[10, 20], [30, 40]], "wait_after_ms": 800},
    )
    result = PlaceholderTaskA().run(ctx)
    assert result.success is True
    assert sender.calls == [("click_at", 10, 20), ("click_at", 30, 40)]
    assert len(sleeps) == 16  # 两步各 0.8s，按 0.1s 分片
    assert "步骤 1/2" in caplog.text
    assert "步骤 2/2" in caplog.text


def test_placeholder_stops_before_second_point() -> None:
    sender = _RecordingSender()
    ctx = TaskContext(sender=sender, params={"click_points": [[1, 1], [2, 2]], "wait_after_ms": 500})

    def fake_sleep(seconds: float) -> None:
        ctx.stop_event.set()

    ctx.sleep = fake_sleep
    result = PlaceholderTaskA().run(ctx)
    assert result.success is True
    assert "停止" in result.message
    assert sender.calls == [("click_at", 1, 1)]


def test_placeholder_without_points_only_logs(caplog) -> None:
    sender = _RecordingSender()
    ctx = TaskContext(sender=sender, params={"click_points": []})
    result = PlaceholderTaskA().run(ctx)
    assert result.success is True
    assert sender.calls == []
    assert "未配置点击坐标" in caplog.text


def test_placeholder_respects_readiness_gate() -> None:
    sender = _RecordingSender()
    ctx = TaskContext(
        sender=sender, readiness_check=lambda: False, params={"click_points": [[1, 1]]}
    )
    result = PlaceholderTaskA().run(ctx)
    assert "停止" in result.message
    assert sender.calls == []
