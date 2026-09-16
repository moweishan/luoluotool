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
    raw["schema_version"] = 5
    assert any("schema_version" in e for e in validate(raw))
    raw["schema_version"] = 0
    assert any("schema_version" in e for e in validate(raw))
    raw["schema_version"] = "4"
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
    "automation.pause_on_window_focus_loss",
    "automation.ask_elevation_on_start",
    "automation.restore_cursor_after_click",
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
