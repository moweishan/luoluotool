"""config 迁移测试：schema v1 → v2 → v3。"""

from luoluotool.config.models import SCHEMA_VERSION
from luoluotool.config.validation import migrate


def v1_raw() -> dict:
    """一份合法的 schema v1 配置（不含 v2 新字段）。"""
    return {
        "schema_version": 1,
        "features": {
            "daily_tasks": {
                "enabled": False,
                "tasks": {"placeholder_task_a": {"enabled": False, "order": 1, "params": {}}},
                "loop": {"enabled": False, "interval_seconds": 3600},
            },
            "order_hold": {
                "enabled": False,
                "reserved_switch_1": False,
                "reserved_switch_2": False,
            },
            "feature_3": {"enabled": False},
            "feature_4": {"enabled": False},
        },
        "automation": {
            "dry_run": True,
            "window_title_keyword": "桃源深处有人家",
            "click_interval_ms": 800,
            "post_click_wait_ms": 500,
            "max_consecutive_failures": 3,
            "pause_on_window_focus_loss": True,
            "failsafe_hotkey": "F8",
        },
        "logging": {"level": "INFO", "max_file_mb": 2, "backup_count": 3},
    }


def test_migrate_v1_to_v2_adds_field_and_preserves_values() -> None:
    raw = v1_raw()
    raw["automation"]["click_interval_ms"] = 1234
    migrated = migrate(raw)
    assert migrated["schema_version"] == SCHEMA_VERSION == 3  # 一次迁移到最新版本
    assert migrated["automation"]["ask_elevation_on_start"] is True
    assert migrated["automation"]["click_interval_ms"] == 1234
    assert migrated["automation"]["dry_run"] is True
    assert migrated["features"]["order_hold"]["reserved_switch_1"] is False


def test_migrate_current_version_is_noop() -> None:
    raw = v1_raw()
    raw["schema_version"] = SCHEMA_VERSION
    raw["automation"]["ask_elevation_on_start"] = False
    assert migrate(raw) is raw


def test_migrate_unknown_version_returns_unchanged() -> None:
    raw = v1_raw()
    raw["schema_version"] = 99
    assert migrate(raw) is raw


def test_migrate_invalid_input_returns_unchanged() -> None:
    assert migrate([]) == []
    raw = v1_raw()
    del raw["schema_version"]
    assert migrate(raw) is raw


def v2_raw() -> dict:
    """一份合法的 schema v2 配置（不含 v3 新字段）。"""
    raw = v1_raw()
    raw["schema_version"] = 2
    raw["automation"]["ask_elevation_on_start"] = False
    return raw


def test_migrate_v2_to_v3_adds_align_window_flag() -> None:
    """v2 → v3：新增「点击前对齐游戏窗口」开关，默认关闭，其余取值保持不变。"""
    raw = v2_raw()
    raw["automation"]["click_interval_ms"] = 1500
    migrated = migrate(raw)
    assert migrated["schema_version"] == SCHEMA_VERSION == 3
    assert migrated["automation"]["align_window_before_click"] is False
    assert migrated["automation"]["click_interval_ms"] == 1500
    assert migrated["automation"]["ask_elevation_on_start"] is False
    assert migrated["automation"]["dry_run"] is True


def test_migrate_v1_all_the_way_to_v3() -> None:
    """老配置必须能一次连跳两级（v1 → v2 → v3）。"""
    migrated = migrate(v1_raw())
    assert migrated["schema_version"] == SCHEMA_VERSION == 3
    assert migrated["automation"]["ask_elevation_on_start"] is True
    assert migrated["automation"]["align_window_before_click"] is False


def test_migrate_v2_to_v3_keeps_existing_align_value() -> None:
    """已经是 v2 但已手工写了新字段时，迁移不得覆盖用户取值。"""
    raw = v2_raw()
    raw["automation"]["align_window_before_click"] = True
    assert migrate(raw)["automation"]["align_window_before_click"] is True
