"""config 迁移测试：schema v1 → v2 → v3 → v4 → v5 → v6。

v1 加 `ask_elevation_on_start`；v2→v3 加 `align_window_before_click`；
v3→v4 去掉该布尔并加 `restore_cursor_after_click`；
v4→v5 因输入实现方式固定为「真实鼠标键盘」而移除 `input_mode` 与已失效的 `pause_on_window_focus_loss`；
v5→v6 任务参数新增按键序列 `params.keys`。
"""

from luoluotool.config.models import SCHEMA_VERSION
from luoluotool.config.validation import migrate


def v1_raw() -> dict:
    """一份合法的 schema v1 配置（不含后续版本的新字段）。"""
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


def v2_raw() -> dict:
    """v2：已有 ask_elevation_on_start，但还没有 v3/v4/v5 的字段。"""
    raw = v1_raw()
    raw["schema_version"] = 2
    raw["automation"]["ask_elevation_on_start"] = False
    return raw


def v4_raw() -> dict:
    """v4：含 input_mode 与失焦暂停开关（v5 将移除它们）。"""
    raw = v2_raw()
    raw["schema_version"] = 4
    raw["automation"]["input_mode"] = "real_input"
    raw["automation"]["restore_cursor_after_click"] = False
    return raw


def test_migrate_v1_to_latest_adds_fields_and_preserves_values() -> None:
    raw = v1_raw()
    raw["automation"]["click_interval_ms"] = 1234
    migrated = migrate(raw)
    assert migrated["schema_version"] == SCHEMA_VERSION == 6
    assert migrated["automation"]["ask_elevation_on_start"] is True
    assert migrated["automation"]["restore_cursor_after_click"] is True
    assert migrated["automation"]["click_interval_ms"] == 1234
    assert migrated["automation"]["dry_run"] is True
    assert migrated["features"]["order_hold"]["reserved_switch_1"] is False


def test_migrate_drops_removed_fields_everywhere_in_the_chain() -> None:
    """v1 里的 pause_on_window_focus_loss、v3 里的 align_window_before_click 最终都不应残留。"""
    migrated = migrate(v1_raw())
    automation = migrated["automation"]
    assert "pause_on_window_focus_loss" not in automation
    assert "align_window_before_click" not in automation
    assert "input_mode" not in automation


def test_migrate_current_version_is_noop() -> None:
    raw = v1_raw()
    raw["schema_version"] = SCHEMA_VERSION
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


def test_migrate_v3_drops_align_flag_and_adds_restore_cursor() -> None:
    """v3 的 align_window_before_click 属于已删除的对齐通道：迁移后必须被移除。"""
    raw = v2_raw()
    raw["schema_version"] = 3
    raw["automation"]["align_window_before_click"] = True
    migrated = migrate(raw)
    assert migrated["schema_version"] == 6
    assert "align_window_before_click" not in migrated["automation"]
    assert migrated["automation"]["restore_cursor_after_click"] is True


def test_migrate_v4_drops_input_mode_and_focus_pause() -> None:
    """v4 → v5：输入实现方式已固定，input_mode 与失焦暂停开关都必须移除。"""
    migrated = migrate(v4_raw())
    assert migrated["schema_version"] == 6
    automation = migrated["automation"]
    assert "input_mode" not in automation
    assert "pause_on_window_focus_loss" not in automation
    # 用户显式设置过的还原光标开关必须保留
    assert automation["restore_cursor_after_click"] is False


def test_migrate_v4_also_drops_stale_align_flag() -> None:
    """即使配置标成 v4 却残留了 v3 时代的 align_window_before_click，也要被清掉。

    （回归：v4→v5 迁移原先只 pop input_mode / pause_on_window_focus_loss，
    残留的 align_window_before_click 会被写回并长期留在配置里。）
    """
    raw = v4_raw()
    raw["automation"]["align_window_before_click"] = True
    migrated = migrate(raw)
    assert "align_window_before_click" not in migrated["automation"]


def test_migrate_v5_to_v6_adds_empty_key_sequence() -> None:
    """v5 → v6：任务参数补上 `keys: []`（默认不发送任何按键），已有 click_points 保持不变。"""
    raw = v4_raw()
    raw["schema_version"] = 5
    raw["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["params"] = {
        "click_points": [[11, 22]],
        "wait_after_ms": 700,
    }
    migrated = migrate(raw)
    assert migrated["schema_version"] == 6
    params = migrated["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["params"]
    assert params["keys"] == []
    assert params["click_points"] == [[11, 22]]
    assert params["wait_after_ms"] == 700


def test_migrate_v5_to_v6_keeps_existing_keys() -> None:
    """已经手工配好 keys 的 v5 配置不得被覆盖。"""
    raw = v4_raw()
    raw["schema_version"] = 5
    raw["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["params"] = {
        "click_points": [],
        "keys": [{"combo": "ctrl+s", "hold_ms": 0, "wait_after_ms": 300}],
        "wait_after_ms": 500,
    }
    params = migrate(raw)["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["params"]
    assert params["keys"][0]["combo"] == "ctrl+s"


def test_migrate_v4_keeps_other_user_values() -> None:
    raw = v4_raw()
    raw["automation"]["click_interval_ms"] = 1500
    raw["automation"]["failsafe_hotkey"] = "F9"
    migrated = migrate(raw)
    assert migrated["automation"]["click_interval_ms"] == 1500
    assert migrated["automation"]["failsafe_hotkey"] == "F9"
    assert migrated["automation"]["ask_elevation_on_start"] is False
