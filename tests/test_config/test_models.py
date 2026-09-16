"""config.models 测试：默认值、序列化往返、schema 键完整性。"""

from luoluotool.config import models


def test_defaults_are_safe() -> None:
    """出厂默认：开关全关，dry_run 开启，schema_version=4。"""
    config = models.AppConfig.default()
    assert config.schema_version == models.SCHEMA_VERSION == 4
    assert config.automation.dry_run is True
    assert config.automation.pause_on_window_focus_loss is True
    assert config.features.daily_tasks.enabled is False
    assert config.features.daily_tasks.loop.enabled is False
    assert config.features.order_hold.enabled is False
    assert config.features.order_hold.reserved_switch_1 is False
    assert config.features.order_hold.reserved_switch_2 is False
    assert config.features.feature_3.enabled is False
    assert config.features.feature_4.enabled is False
    assert config.automation.click_interval_ms == 800
    assert config.automation.post_click_wait_ms == 500
    assert config.automation.max_consecutive_failures == 3
    assert config.automation.window_title_keyword == "桃源深处有人家"
    assert config.automation.failsafe_hotkey == "F8"
    assert config.automation.ask_elevation_on_start is True
    assert config.logging.level == "INFO"
    assert config.logging.max_file_mb == 2
    assert config.logging.backup_count == 3


def test_default_contains_placeholder_task_a() -> None:
    """默认配置含占位任务 A：关、order=1、params 为新的坐标结构默认值。"""
    config = models.AppConfig.default()
    assert set(config.features.daily_tasks.tasks) == {"placeholder_task_a"}
    task = config.features.daily_tasks.tasks["placeholder_task_a"]
    assert task.enabled is False
    assert task.order == 1
    assert task.params == {"click_points": [], "wait_after_ms": 500}


def test_placeholder_params_defaults_and_roundtrip() -> None:
    """params 结构：缺失键回落默认值，往返一致。"""
    assert models.PlaceholderTaskParams.from_dict({}).to_dict() == {
        "click_points": [],
        "wait_after_ms": 500,
    }
    params = models.PlaceholderTaskParams.from_dict(
        {"click_points": [[10, 20], [30, 40]], "wait_after_ms": 800}
    )
    assert params.click_points == [[10, 20], [30, 40]]
    assert params.to_dict() == {"click_points": [[10, 20], [30, 40]], "wait_after_ms": 800}
    assert models.PlaceholderTaskParams.from_dict(None).wait_after_ms == 500


def test_to_dict_from_dict_roundtrip() -> None:
    """修改若干字段后 to_dict→from_dict 往返一致。"""
    config = models.AppConfig.default()
    config.features.daily_tasks.enabled = True
    config.features.order_hold.reserved_switch_1 = True
    config.automation.click_interval_ms = 1234
    config.automation.ask_elevation_on_start = False
    restored = models.AppConfig.from_dict(config.to_dict())
    assert restored.to_dict() == config.to_dict()


def test_from_dict_partial_uses_defaults() -> None:
    """缺失的节/字段回落到默认值。"""
    config = models.AppConfig.from_dict(
        {"schema_version": 1, "features": {}, "automation": {}, "logging": {}}
    )
    assert config.automation.dry_run is True
    assert config.features.daily_tasks.enabled is False
    assert config.features.daily_tasks.tasks == {}
    assert config.logging.level == "INFO"


def test_to_dict_keys_match_schema_v1() -> None:
    """序列化键与 PROJECT_SPEC 第 9 节完全一致，不多不少。"""
    data = models.AppConfig.default().to_dict()
    assert set(data) == {"schema_version", "features", "automation", "logging"}
    assert set(data["features"]) == {"daily_tasks", "order_hold", "feature_3", "feature_4"}
    assert set(data["features"]["daily_tasks"]) == {"enabled", "tasks", "loop"}
    assert set(data["features"]["daily_tasks"]["loop"]) == {"enabled", "interval_seconds"}
    assert set(data["features"]["order_hold"]) == {"enabled", "reserved_switch_1", "reserved_switch_2"}
    assert set(data["features"]["feature_3"]) == {"enabled"}
    assert set(data["features"]["feature_4"]) == {"enabled"}
    assert set(data["automation"]) == {
        "dry_run",
        "window_title_keyword",
        "click_interval_ms",
        "post_click_wait_ms",
        "max_consecutive_failures",
        "pause_on_window_focus_loss",
        "failsafe_hotkey",
        "ask_elevation_on_start",
        "input_mode",
        "restore_cursor_after_click",
    }
    assert set(data["logging"]) == {"level", "max_file_mb", "backup_count"}
    task = data["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]
    assert set(task) == {"enabled", "order", "params"}
