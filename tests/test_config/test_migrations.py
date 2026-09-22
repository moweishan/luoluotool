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
    assert migrated["schema_version"] == SCHEMA_VERSION
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
    assert migrated["schema_version"] == SCHEMA_VERSION
    assert "align_window_before_click" not in migrated["automation"]
    assert migrated["automation"]["restore_cursor_after_click"] is True


def test_migrate_v4_drops_input_mode_and_focus_pause() -> None:
    """v4 → v5：输入实现方式已固定，input_mode 与失焦暂停开关都必须移除。"""
    migrated = migrate(v4_raw())
    assert migrated["schema_version"] == SCHEMA_VERSION
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


def test_migrate_v5_adds_keys_and_swipes_defaults() -> None:
    """v5 起：任务参数依次补上 `keys: []` 与 `swipes: []`（默认不按键、不滑动），已有取值不变。"""
    raw = v4_raw()
    raw["schema_version"] = 5
    raw["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["params"] = {
        "click_points": [[11, 22]],
        "wait_after_ms": 700,
    }
    migrated = migrate(raw)
    assert migrated["schema_version"] == SCHEMA_VERSION
    params = migrated["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["params"]
    assert params["keys"] == []
    assert params["swipes"] == []
    assert params["click_points"] == [[11, 22]]
    assert params["wait_after_ms"] == 700


def test_migrate_v5_keeps_existing_keys() -> None:
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


def test_migrate_v6_to_v7_adds_empty_swipe_sequence() -> None:
    """v6 → v7：任务参数补上 `swipes: []`，已有 keys 保持不变。"""
    raw = v4_raw()
    raw["schema_version"] = 6
    raw["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["params"] = {
        "click_points": [],
        "keys": [{"combo": "ctrl+s"}],
        "wait_after_ms": 500,
    }
    migrated = migrate(raw)
    assert migrated["schema_version"] == SCHEMA_VERSION
    params = migrated["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["params"]
    assert params["swipes"] == []
    assert params["keys"][0]["combo"] == "ctrl+s"


def test_migrate_v6_to_v7_keeps_existing_swipes() -> None:
    """已经手工配好 swipes 的 v6 配置不得被覆盖。"""
    raw = v4_raw()
    raw["schema_version"] = 6
    raw["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["params"] = {
        "click_points": [],
        "swipes": [{"from": [10, 10], "to": [20, 20], "duration_ms": 800}],
    }
    params = migrate(raw)["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["params"]
    assert params["swipes"][0]["duration_ms"] == 800


def test_migrate_v7_to_v8_adds_developer_mode() -> None:
    """v7 → v8：新增 automation.developer_mode（默认 false = 不显示开发者调试页）。"""
    raw = v4_raw()
    raw["schema_version"] = 7
    raw["automation"]["restore_cursor_after_click"] = True
    migrated = migrate(raw)
    assert migrated["schema_version"] == SCHEMA_VERSION
    assert migrated["automation"]["developer_mode"] is False


def test_migrate_v7_to_v8_keeps_existing_developer_mode() -> None:
    """已手工开启开发者模式的配置不得被覆盖。"""
    raw = v4_raw()
    raw["schema_version"] = 7
    raw["automation"]["developer_mode"] = True
    assert migrate(raw)["automation"]["developer_mode"] is True


def test_migrate_v8_to_v9_adds_save_vision_annotations() -> None:
    """v8 → v9：新增 `automation.save_vision_annotations`（默认 true = 识别成功仍存带框截图）。"""
    raw = v4_raw()
    raw["schema_version"] = 8
    raw["automation"].pop("save_vision_annotations", None)
    migrated = migrate(raw)
    assert migrated["schema_version"] == SCHEMA_VERSION
    assert migrated["automation"]["save_vision_annotations"] is True


def test_migrate_v8_to_v9_keeps_existing_value() -> None:
    """用户已把带框截图关掉的配置不得被迁移覆盖回 true。"""
    raw = v4_raw()
    raw["schema_version"] = 8
    raw["automation"]["save_vision_annotations"] = False
    assert migrate(raw)["automation"]["save_vision_annotations"] is False


def _v9_daily_raw() -> dict:
    """一份 schema v9 配置（还没有日常任务页那批新字段）。"""
    raw = v4_raw()
    raw["schema_version"] = 9
    raw["automation"]["restore_cursor_after_click"] = True
    raw["automation"]["developer_mode"] = False
    raw["automation"]["save_vision_annotations"] = True
    return raw


def test_migrate_v9_to_v10_adds_daily_page_defaults() -> None:
    """v9 → v10：补上日常任务页那批字段，默认值＝"一个建筑都没配"（岛屿 1、路径空、开关关）。"""
    migrated = migrate(_v9_daily_raw())
    assert migrated["schema_version"] == SCHEMA_VERSION
    daily = migrated["features"]["daily_tasks"]
    assert daily["coop_island"] == 1
    assert daily["land_island"] == 1
    assert daily["aqua_island"] == 1
    # 参考图在 v10 里是空串，v11 起是空列表 —— 这里断言的是**整条迁移链的最终形态**
    assert daily["coop_island_ref_image"] == []
    assert daily["land_ref_image"] == []
    assert daily["aqua_ref_image"] == []
    assert daily["auto_produce_least"] is False


def test_migrate_v9_to_v10_keeps_every_existing_value() -> None:
    """老配置升级后**原有字段一个都不许变**（含队列、循环秒数、自动化节）。"""
    raw = _v9_daily_raw()
    raw["features"]["daily_tasks"]["enabled"] = True
    raw["features"]["daily_tasks"]["loop"] = {"enabled": True, "interval_seconds": 1234}
    raw["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["enabled"] = True
    raw["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]["order"] = 7
    raw["automation"]["click_interval_ms"] = 1500
    migrated = migrate(raw)

    daily = migrated["features"]["daily_tasks"]
    assert daily["enabled"] is True
    assert daily["loop"] == {"enabled": True, "interval_seconds": 1234}
    task = daily["tasks"]["placeholder_task_a"]
    assert task["enabled"] is True and task["order"] == 7
    assert migrated["automation"]["click_interval_ms"] == 1500


def _v10_daily_raw() -> dict:
    """一份 schema v10 配置（参考图还是**单个路径字符串**）。"""
    raw = _v9_daily_raw()
    raw["schema_version"] = 10
    raw["features"]["daily_tasks"].update({
        "coop_island": 1,
        "land_island": 1,
        "aqua_island": 1,
        "coop_island_ref_image": "",
        "land_ref_image": "",
        "aqua_ref_image": "",
        "auto_produce_least": False,
    })
    return raw


def test_migrate_v10_to_v11_turns_single_paths_into_lists() -> None:
    """v10 → v11：参考图从"单个路径字符串"改成路径列表（用户 2026-09-22 要求可多选）。

    单张 → 单元素列表；空串 → 空数组（＝还没选）。
    """
    raw = _v10_daily_raw()
    daily = raw["features"]["daily_tasks"]
    daily["coop_island_ref_image"] = "assets/templates/鸡舍_1.png"
    daily["land_ref_image"] = ""
    daily["aqua_ref_image"] = "assets/anchors/水产_x.png"

    migrated = migrate(raw)

    assert migrated["schema_version"] == SCHEMA_VERSION
    daily = migrated["features"]["daily_tasks"]
    assert daily["coop_island_ref_image"] == ["assets/templates/鸡舍_1.png"]
    assert daily["land_ref_image"] == []
    assert daily["aqua_ref_image"] == ["assets/anchors/水产_x.png"]


def test_migrate_v10_to_v11_keeps_existing_lists_and_other_fields() -> None:
    """已经是列表的值不动（去重前只丢空项），其它字段也一律保持原样。"""
    raw = _v10_daily_raw()
    daily = raw["features"]["daily_tasks"]
    daily["coop_island_ref_image"] = ["a.png", "b.png"]
    daily["coop_island"] = 7
    daily["auto_produce_least"] = True
    daily["loop"] = {"enabled": True, "interval_seconds": 1234}
    raw["automation"]["click_interval_ms"] = 1500

    migrated = migrate(raw)

    daily = migrated["features"]["daily_tasks"]
    assert daily["coop_island_ref_image"] == ["a.png", "b.png"]
    assert daily["coop_island"] == 7 and daily["auto_produce_least"] is True
    assert daily["loop"] == {"enabled": True, "interval_seconds": 1234}
    assert migrated["automation"]["click_interval_ms"] == 1500


def test_migrate_v9_to_v10_keeps_already_filled_daily_page_values() -> None:
    """已经手工填过（或从新版本降级回来）的值不得被默认值覆盖。"""
    raw = _v9_daily_raw()
    daily = raw["features"]["daily_tasks"]
    daily["coop_island"] = 7
    daily["aqua_island"] = 5
    daily["land_ref_image"] = "assets/templates/土地.png"
    daily["auto_produce_least"] = True
    migrated = migrate(raw)["features"]["daily_tasks"]
    assert migrated["coop_island"] == 7
    assert migrated["aqua_island"] == 5
    assert migrated["land_ref_image"] == ["assets/templates/土地.png"]  # v11 起是列表
    assert migrated["auto_produce_least"] is True
