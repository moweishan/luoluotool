"""config 迁移测试：schema v1 → v2 → v3 → v4。"""

from luoluotool.config.models import (
    INPUT_MODE_WINDOW_ALIGN,
    INPUT_MODE_WINDOW_MESSAGE,
    SCHEMA_VERSION,
)
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
    assert migrated["schema_version"] == SCHEMA_VERSION == 4  # 一次迁移到最新版本
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
    """v2 一路迁移到最新版本：v3 补上对齐开关，v4 再把该布尔升级为 input_mode 枚举。"""
    raw = v2_raw()
    raw["automation"]["click_interval_ms"] = 1500
    migrated = migrate(raw)
    assert migrated["schema_version"] == SCHEMA_VERSION == 4
    assert migrated["automation"]["input_mode"] == INPUT_MODE_WINDOW_MESSAGE
    assert "align_window_before_click" not in migrated["automation"]
    assert migrated["automation"]["restore_cursor_after_click"] is True
    assert migrated["automation"]["click_interval_ms"] == 1500
    assert migrated["automation"]["ask_elevation_on_start"] is False
    assert migrated["automation"]["dry_run"] is True


def test_migrate_v1_all_the_way_to_v4() -> None:
    """老配置必须能一次连跳三级（v1 → v2 → v3 → v4）。"""
    migrated = migrate(v1_raw())
    assert migrated["schema_version"] == SCHEMA_VERSION == 4
    assert migrated["automation"]["ask_elevation_on_start"] is True
    assert migrated["automation"]["input_mode"] == INPUT_MODE_WINDOW_MESSAGE


def test_migrate_v3_align_true_becomes_window_align_mode() -> None:
    """v3 里 align_window_before_click=true 的配置必须无损升级为 input_mode=window_align。"""
    raw = v2_raw()
    raw["schema_version"] = 3
    raw["automation"]["align_window_before_click"] = True
    migrated = migrate(raw)
    assert migrated["schema_version"] == 4
    assert migrated["automation"]["input_mode"] == INPUT_MODE_WINDOW_ALIGN
    assert "align_window_before_click" not in migrated["automation"]


def test_migrate_v3_align_false_becomes_window_message_mode() -> None:
    """v3 里 align_window_before_click=false → input_mode 保持默认 window_message。"""
    raw = v2_raw()
    raw["schema_version"] = 3
    raw["automation"]["align_window_before_click"] = False
    migrated = migrate(raw)
    assert migrated["automation"]["input_mode"] == INPUT_MODE_WINDOW_MESSAGE


def test_migrate_v3_to_v4_keeps_existing_input_mode() -> None:
    """已经是 v3 但已手工写了 input_mode 时，迁移不得覆盖用户取值。"""
    raw = v2_raw()
    raw["schema_version"] = 3
    raw["automation"]["input_mode"] = "real_input"
    assert migrate(raw)["automation"]["input_mode"] == "real_input"


def test_migrate_v2_to_v3_keeps_existing_align_value(monkeypatch) -> None:
    """v2 里已手工写了 v4 字段时同样不得被覆盖。"""
    raw = v2_raw()
    raw["automation"]["input_mode"] = "real_input"
    raw["automation"]["restore_cursor_after_click"] = False
    migrated = migrate(raw)
    assert migrated["automation"]["input_mode"] == "real_input"
    assert migrated["automation"]["restore_cursor_after_click"] is False
