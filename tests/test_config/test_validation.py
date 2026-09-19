"""config.validation 测试：类型、枚举、上下限、schema 版本、任务条目。"""

import pytest

from luoluotool.config import models
from luoluotool.config.validation import validate


def _default_raw() -> dict:
    return models.AppConfig.default().to_dict()


def _set_path(raw: dict, path: str, value) -> None:
    """按 a.b.c 路径设置值。"""
    parts = path.split(".")
    node = raw
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def test_valid_default_passes() -> None:
    assert validate(_default_raw()) == []


def test_root_must_be_dict() -> None:
    assert validate([]) == ["配置根节点必须是对象"]


def test_schema_version_checks() -> None:
    raw = _default_raw()
    raw["schema_version"] = 9
    assert any("schema_version" in e for e in validate(raw))
    raw["schema_version"] = 0
    assert any("schema_version" in e for e in validate(raw))
    raw["schema_version"] = "8"
    assert any("schema_version" in e for e in validate(raw))
    del raw["schema_version"]
    assert any("schema_version" in e for e in validate(raw))


def test_missing_sections_reported() -> None:
    raw = _default_raw()
    del raw["automation"]
    errors = validate(raw)
    assert any("automation" in e for e in errors)
    assert validate({})


_BOOL_PATHS = (
    "features.daily_tasks.enabled",
    "features.daily_tasks.loop.enabled",
    "features.order_hold.enabled",
    "features.order_hold.reserved_switch_1",
    "features.order_hold.reserved_switch_2",
    "features.feature_3.enabled",
    "features.feature_4.enabled",
    "automation.dry_run",
        "automation.ask_elevation_on_start",
    "automation.restore_cursor_after_click",
    "automation.developer_mode",
)


@pytest.mark.parametrize("path", _BOOL_PATHS)
def test_bool_fields_reject_non_bool(path) -> None:
    raw = _default_raw()
    _set_path(raw, path, "yes")
    assert any(path in e for e in validate(raw))


_INT_BOUNDS = (
    ("automation.click_interval_ms", 100, 5000),
    ("automation.post_click_wait_ms", 0, 60000),
    ("automation.max_consecutive_failures", 1, 100),
    ("features.daily_tasks.loop.interval_seconds", 1, 86400),
    ("logging.max_file_mb", 1, 100),
    ("logging.backup_count", 0, 50),
)


@pytest.mark.parametrize("path,lo,hi", _INT_BOUNDS)
def test_int_bounds(path, lo, hi) -> None:
    for bad in (lo - 1, hi + 1, "10", 1.5, True):
        raw = _default_raw()
        _set_path(raw, path, bad)
        assert any(path in e for e in validate(raw))
    for ok in (lo, hi):
        raw = _default_raw()
        _set_path(raw, path, ok)
        assert validate(raw) == []


def test_string_fields_reject_empty_and_overlong() -> None:
    raw = _default_raw()
    _set_path(raw, "automation.window_title_keyword", "")
    assert any("window_title_keyword" in e for e in validate(raw))
    _set_path(raw, "automation.window_title_keyword", "x" * 101)
    assert any("window_title_keyword" in e for e in validate(raw))
    _set_path(raw, "automation.failsafe_hotkey", "")
    assert any("failsafe_hotkey" in e for e in validate(raw))


def test_log_level_enum() -> None:
    raw = _default_raw()
    _set_path(raw, "logging.level", "VERBOSE")
    assert any("logging.level" in e for e in validate(raw))
    _set_path(raw, "logging.level", "DEBUG")
    assert validate(raw) == []


def test_task_entries_validation() -> None:
    raw = _default_raw()
    tasks = raw["features"]["daily_tasks"]["tasks"]
    tasks["placeholder_task_a"]["enabled"] = "no"
    assert any("placeholder_task_a.enabled" in e for e in validate(raw))
    tasks["placeholder_task_a"] = {"enabled": True, "order": 0, "params": []}
    errors = validate(raw)
    assert any("order" in e for e in errors)
    assert any("params" in e for e in errors)
    tasks["placeholder_task_a"] = "bad"
    assert any("placeholder_task_a 必须是对象" in e for e in validate(raw))
    _set_path(raw, "features.daily_tasks.tasks", "bad")
    assert any("tasks 必须是对象" in e for e in validate(raw))


def test_task_params_structure_validation() -> None:
    """params 内容：缺省键合法；坐标数组与等待时间需符合结构。"""
    raw = _default_raw()
    tasks = raw["features"]["daily_tasks"]["tasks"]

    tasks["placeholder_task_a"]["params"] = {}
    assert validate(raw) == []  # 缺失键回落到默认值

    tasks["placeholder_task_a"]["params"] = {"click_points": [], "wait_after_ms": 0}
    assert validate(raw) == []  # 空坐标列表合法（不崩溃）

    tasks["placeholder_task_a"]["params"] = {"click_points": [[10, 20]], "wait_after_ms": 500}
    assert validate(raw) == []

    for bad_points in ("bad", [[10]], [[-1, 5]], [[1.5, 2]], [[True, 2]], [["a", "b"]], [10, 20]):
        tasks["placeholder_task_a"]["params"] = {"click_points": bad_points}
        errors = validate(raw)
        assert any("click_points" in e for e in errors), bad_points

    for bad_wait in (-1, 60001, "500", True):
        tasks["placeholder_task_a"]["params"] = {"wait_after_ms": bad_wait}
        errors = validate(raw)
        assert any("wait_after_ms" in e for e in errors), bad_wait


def test_task_keys_validation() -> None:
    """keys 结构校验：合法通过；非法结构/越界/超量都要报错。"""
    raw = _default_raw()
    tasks = raw["features"]["daily_tasks"]["tasks"]
    tasks["placeholder_task_a"]["params"] = {
        "click_points": [],
        "keys": [{"combo": "ctrl+s", "hold_ms": 0, "wait_after_ms": 300}],
    }
    assert validate(raw) == []

    for bad_keys in (
        "ctrl+s",                                             # 不是数组
        [{"combo": ""}],                                      # 空组合键
        [{"combo": "a" * 61}],                                # 超长
        [{"combo": "a", "hold_ms": -1}],                      # 越界
        [{"combo": "a", "hold_ms": True}],                    # 布尔
        [{"combo": "a", "wait_after_ms": 60001}],             # 越界
        [{"combo": "a"}] * 21,                                # 超量
        ["ctrl+s"],                                           # 元素不是对象
    ):
        tasks["placeholder_task_a"]["params"] = {"keys": bad_keys}
        errors = validate(raw)
        assert any("keys" in error for error in errors), bad_keys


def test_task_swipes_validation() -> None:
    """swipes 结构校验：合法通过；非法坐标/时长越界/超量都要报错。"""
    raw = _default_raw()
    tasks = raw["features"]["daily_tasks"]["tasks"]
    tasks["placeholder_task_a"]["params"] = {
        "click_points": [],
        "swipes": [{"from": [10, 10], "to": [400, 10], "duration_ms": 500, "wait_after_ms": 200}],
    }
    assert validate(raw) == []

    for bad_swipes in (
        "10,10 > 20,20",                                   # 不是数组
        [{"from": [10, 10]}],                              # 缺 to
        [{"from": [10], "to": [20, 20]}],                  # 坐标维度错
        [{"from": [-1, 0], "to": [20, 20]}],               # 负坐标
        [{"from": [0, 0], "to": [1, 1], "duration_ms": 10}],    # 时长过短
        [{"from": [0, 0], "to": [1, 1], "duration_ms": True}],  # 布尔
        [{"from": [0, 0], "to": [1, 1], "wait_after_ms": 60001}],  # 等待越界
        [{"from": [0, 0], "to": [1, 1]}] * 21,                   # 超量
        ["100,200 > 400,600"],                                   # 元素不是对象
    ):
        tasks["placeholder_task_a"]["params"] = {"swipes": bad_swipes}
        errors = validate(raw)
        assert any("swipes" in error for error in errors), bad_swipes
