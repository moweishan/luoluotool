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

    def drag(self, from_xy: tuple[int, int], to_xy: tuple[int, int], duration_seconds: float) -> None:
        self.calls.append(("drag", from_xy, to_xy, round(duration_seconds, 3)))

    def key_combo(self, combo: str) -> None:
        self.calls.append(("key_combo", combo))

    def key_hold(self, combo: str, seconds: float) -> None:
        self.calls.append(("key_hold", combo, round(seconds, 3)))


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
    assert "未配置任何步骤" in caplog.text


def test_placeholder_respects_readiness_gate() -> None:
    sender = _RecordingSender()
    ctx = TaskContext(
        sender=sender, readiness_check=lambda: False, params={"click_points": [[1, 1]]}
    )
    result = PlaceholderTaskA().run(ctx)
    assert "停止" in result.message
    assert sender.calls == []


def test_placeholder_runs_keys_after_clicks(caplog) -> None:
    """按键序列在点击之后按顺序执行：普通组合键走 key_combo，长按走 key_hold。"""
    sender = _RecordingSender()
    ctx = TaskContext(
        sender=sender,
        sleep=lambda _s: None,
        params={
            "click_points": [[5, 6]],
            "keys": [
                {"combo": "ctrl+s", "hold_ms": 0, "wait_after_ms": 0},
                {"combo": "w", "hold_ms": 800, "wait_after_ms": 0},
            ],
            "wait_after_ms": 0,
        },
    )
    result = PlaceholderTaskA().run(ctx)
    assert result.success is True
    assert sender.calls == [
        ("click_at", 5, 6),
        ("key_combo", "ctrl+s"),
        ("key_hold", "w", 0.8),
    ]
    assert "步骤 1/3：点击 (5, 6)" in caplog.text
    assert "步骤 2/3：按键 ctrl+s" in caplog.text
    assert "步骤 3/3：长按 w 持续 800 ms" in caplog.text
    assert "点击 1，滑动 0，按键 2" in result.message


def test_placeholder_with_only_keys_does_not_warn(caplog) -> None:
    """只配置按键（没有点击坐标）时应正常执行，不再像以前那样判为"未配置"。"""
    sender = _RecordingSender()
    ctx = TaskContext(
        sender=sender, sleep=lambda _s: None,
        params={"click_points": [], "keys": [{"combo": "enter"}], "wait_after_ms": 0},
    )
    result = PlaceholderTaskA().run(ctx)
    assert result.success is True
    assert sender.calls == [("key_combo", "enter")]
    assert "未配置" not in caplog.text


def test_placeholder_without_any_steps_only_logs(caplog) -> None:
    """点击与按键都为空时才提示未配置，且不产生任何输入。"""
    sender = _RecordingSender()
    ctx = TaskContext(sender=sender, sleep=lambda _s: None, params={})
    result = PlaceholderTaskA().run(ctx)
    assert result.success is True
    assert sender.calls == []
    assert "未配置任何步骤" in caplog.text


def test_placeholder_stops_between_key_steps() -> None:
    """按键步骤之间也要响应停止请求（不继续发送后续按键）。"""
    sender = _RecordingSender()
    ctx = TaskContext(
        sender=sender,
        params={
            "keys": [
                {"combo": "a", "wait_after_ms": 500},
                {"combo": "b", "wait_after_ms": 500},
            ]
        },
    )

    def fake_sleep(seconds: float) -> None:
        ctx.stop_event.set()

    ctx.sleep = fake_sleep
    result = PlaceholderTaskA().run(ctx)
    assert result.success is True
    assert "停止" in result.message
    assert sender.calls == [("key_combo", "a")]


def test_placeholder_runs_swipes_between_clicks_and_keys(caplog) -> None:
    """执行顺序：点击 → 滑动 → 按键，日志给出每步序号。"""
    sender = _RecordingSender()
    ctx = TaskContext(
        sender=sender,
        sleep=lambda _s: None,
        params={
            "click_points": [[5, 6]],
            "swipes": [{"from": [100, 100], "to": [400, 100], "duration_ms": 500,
                        "wait_after_ms": 0}],
            "keys": [{"combo": "enter", "wait_after_ms": 0}],
            "wait_after_ms": 0,
        },
    )
    result = PlaceholderTaskA().run(ctx)
    assert result.success is True
    assert sender.calls == [
        ("click_at", 5, 6),
        ("drag", (100, 100), (400, 100), 0.5),
        ("key_combo", "enter"),
    ]
    assert "步骤 1/3：点击 (5, 6)" in caplog.text
    assert "步骤 2/3：滑动 (100, 100) → (400, 100) 用时 500 ms" in caplog.text
    assert "步骤 3/3：按键 enter" in caplog.text
    assert "点击 1，滑动 1，按键 1" in result.message


def test_placeholder_stops_between_swipes() -> None:
    """滑动步骤之间响应停止请求。"""
    sender = _RecordingSender()
    ctx = TaskContext(
        sender=sender,
        params={"swipes": [
            {"from": [0, 0], "to": [10, 10], "wait_after_ms": 500},
            {"from": [10, 10], "to": [20, 20], "wait_after_ms": 500},
        ]},
    )

    def fake_sleep(seconds: float) -> None:
        ctx.stop_event.set()

    ctx.sleep = fake_sleep
    result = PlaceholderTaskA().run(ctx)
    assert result.success is True
    assert "停止" in result.message
    assert sender.calls == [("drag", (0, 0), (10, 10), 0.4)]


# --------------------------------------------------- Phase 6：三个预留功能占位任务


PLANNED_MESSAGE = "该功能尚未实现真实逻辑（规划中）"


def test_three_placeholder_feature_tasks_are_registered() -> None:
    """Phase 6：卡订单/功能三/功能四三个占位任务已注册，任务 ID 与功能模块对应。"""
    from luoluotool.core.registry import (
        FEATURE_3_TASK_ID,
        FEATURE_4_TASK_ID,
        ORDER_HOLD_TASK_ID,
        Feature3Task,
        Feature4Task,
        OrderHoldTask,
    )

    assert (ORDER_HOLD_TASK_ID, FEATURE_3_TASK_ID, FEATURE_4_TASK_ID) == (
        "order_hold", "feature_3", "feature_4",
    )
    for task_id, task_class in (
        (ORDER_HOLD_TASK_ID, OrderHoldTask),
        (FEATURE_3_TASK_ID, Feature3Task),
        (FEATURE_4_TASK_ID, Feature4Task),
    ):
        assert task_id in registered_ids()
        assert get(task_id) is task_class


@pytest.mark.parametrize("task_id", ["order_hold", "feature_3", "feature_4"])
def test_placeholder_feature_task_logs_entry_and_heartbeat(task_id, caplog) -> None:
    """占位任务只允许「进入日志 + 心跳日志」：两条 INFO，且不产生任何输入。"""
    sender = _RecordingSender()
    ctx = TaskContext(sender=sender, sleep=lambda _s: None, params={"anything": 1})
    result = get(task_id)().run(ctx)

    assert result.success is True
    assert result.task_id == task_id
    assert "规划中" in result.message
    messages = [record.message for record in caplog.records]
    assert any(task_id in text and PLANNED_MESSAGE in text for text in messages)   # 进入日志
    assert any(task_id in text and "心跳" in text for text in messages)            # 心跳日志
    assert len([text for text in messages if task_id in text]) == 2                # 只有这两条
    assert sender.calls == []                    # 绝不产生任何输入
    assert ctx.params == {"anything": 1}         # 不读参数、不做任何推测性逻辑


@pytest.mark.parametrize("task_id", ["order_hold", "feature_3", "feature_4"])
def test_placeholder_feature_task_respects_stop(task_id, caplog) -> None:
    """占位任务响应停止请求：已请求停止时直接返回，不写进入/心跳日志。"""
    ctx = TaskContext(params={})
    ctx.stop_event.set()
    result = get(task_id)().run(ctx)
    assert result.success is True
    assert "停止" in result.message
    assert [record.message for record in caplog.records] == []


def test_placeholder_feature_tasks_do_not_touch_input_protocol() -> None:
    """三个占位任务不得调用任何输入原语（只有日志与停止检查）。"""
    sender = _RecordingSender()
    ctx = TaskContext(sender=sender, sleep=lambda _s: None, params={})
    for task_id in ("order_hold", "feature_3", "feature_4"):
        get(task_id)().run(ctx)
    assert sender.calls == []
