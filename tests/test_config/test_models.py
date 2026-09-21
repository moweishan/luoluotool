import pytest

"""config.models 测试：默认值、序列化往返、schema 键完整性。"""

from luoluotool.config import models


@pytest.mark.real_defaults
def test_defaults_are_safe() -> None:
    """出厂默认：开关全关，**dry_run 关闭**（2026-09-19 用户要求，首次启动即真实模式），
    schema_version=8。"""
    config = models.AppConfig.default()
    assert config.schema_version == models.SCHEMA_VERSION
    assert config.automation.dry_run is False
    assert config.features.daily_tasks.enabled is False
    assert config.features.daily_tasks.loop.enabled is False
    # 日常任务页那批字段（schema v10）：默认＝"一个建筑都没配"
    assert config.features.daily_tasks.coop_island == 1
    assert config.features.daily_tasks.land_island == 1
    assert config.features.daily_tasks.aqua_island == 1
    assert config.features.daily_tasks.coop_island_ref_image == ""
    assert config.features.daily_tasks.land_ref_image == ""
    assert config.features.daily_tasks.aqua_ref_image == ""
    assert config.features.daily_tasks.auto_produce_least is False
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
    assert config.automation.save_vision_annotations is True   # 识别成功仍默认存带框截图
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
    assert task.params == {"click_points": [], "keys": [], "swipes": [], "wait_after_ms": 500}


def test_placeholder_params_defaults_and_roundtrip() -> None:
    """params 结构：缺失键回落默认值，往返一致。"""
    assert models.PlaceholderTaskParams.from_dict({}).to_dict() == {
        "click_points": [],
        "keys": [],
        "swipes": [],
        "wait_after_ms": 500,
    }
    params = models.PlaceholderTaskParams.from_dict(
        {"click_points": [[10, 20], [30, 40]], "wait_after_ms": 800}
    )
    assert params.click_points == [[10, 20], [30, 40]]
    assert params.to_dict() == {
        "click_points": [[10, 20], [30, 40]], "keys": [], "swipes": [], "wait_after_ms": 800
    }
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


@pytest.mark.real_defaults
def test_from_dict_partial_uses_defaults() -> None:
    """缺失的节/字段回落到默认值（含 dry_run 的生产默认：false = 首次启动即真实模式）。"""
    config = models.AppConfig.from_dict(
        {"schema_version": 1, "features": {}, "automation": {}, "logging": {}}
    )
    assert config.automation.dry_run is False
    assert models.AutomationConfig().dry_run is False
    assert config.features.daily_tasks.enabled is False
    assert config.features.daily_tasks.tasks == {}
    assert config.logging.level == "INFO"


def test_to_dict_keys_match_schema_v1() -> None:
    """序列化键与 PROJECT_SPEC 第 9 节完全一致，不多不少。"""
    data = models.AppConfig.default().to_dict()
    assert set(data) == {"schema_version", "features", "automation", "logging"}
    assert set(data["features"]) == {"daily_tasks", "order_hold", "feature_3", "feature_4"}
    assert set(data["features"]["daily_tasks"]) == {
        "enabled",
        "tasks",
        "loop",
        "coop_island",
        "land_island",
        "aqua_island",
        "coop_island_ref_image",
        "land_ref_image",
        "aqua_ref_image",
        "auto_produce_least",
    }
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
        "failsafe_hotkey",
        "ask_elevation_on_start",
        "restore_cursor_after_click",
        "developer_mode",
        "save_vision_annotations",
    }
    assert set(data["logging"]) == {"level", "max_file_mb", "backup_count"}
    task = data["features"]["daily_tasks"]["tasks"]["placeholder_task_a"]
    assert set(task) == {"enabled", "order", "params"}


def test_loop_interval_minutes_and_seconds_convert_both_ways() -> None:
    """循环间隔在界面用**分钟**、配置里存**秒**：两个方向都要一致（A2 用户选的口径）。"""
    assert models.loop_minutes_to_seconds(30) == 1800
    assert models.loop_minutes_to_seconds(1) == 60
    assert models.loop_seconds_to_minutes(1800) == 30
    for minutes in (1, 2, 30, 719, 720):
        assert models.loop_seconds_to_minutes(models.loop_minutes_to_seconds(minutes)) == minutes


def test_loop_seconds_to_minutes_rounds_and_clamps_for_display() -> None:
    """读配置时的口径：四舍五入到分钟，并夹在界面范围 1–720 内（**只影响显示**）。"""
    assert models.loop_seconds_to_minutes(90) == 2        # 1.5 分钟 → 2
    assert models.loop_seconds_to_minutes(89) == 1
    assert models.loop_seconds_to_minutes(30) == 1        # 不足 1 分钟 → 显示 1（不许显示 0）
    assert models.loop_seconds_to_minutes(1) == 1
    assert models.loop_seconds_to_minutes(86400) == 720   # 24 小时 → 顶到界面上限
    assert models.loop_seconds_to_minutes(60 * 720) == 720


def test_key_step_text_roundtrip() -> None:
    """按键步骤文本语法：`ctrl+s`、`w*800`，解析与格式化互逆。"""
    steps = models.parse_keys_text("ctrl+s, w*800, enter")
    assert [(step.combo, step.hold_ms) for step in steps] == [
        ("ctrl+s", 0), ("w", 800), ("enter", 0)
    ]
    assert models.format_keys_text(steps) == "ctrl+s, w*800, enter"
    # 中英文逗号与换行都当分隔符；空片段忽略
    assert len(models.parse_keys_text("a，b\nc, , ")) == 3


def test_key_step_text_rejects_bad_input() -> None:
    """非法文本必须抛可读错误（未知键名/格式错/长按超限）；空文本表示"清空序列"。"""
    assert models.parse_keys_text("") == []      # 清空输入框 = 不发送任何按键
    assert models.parse_keys_text("   ") == []
    for bad in ("ctrl+", "*800", "w*abc", "*", "ctrl+nosuchkey", "w*60001"):
        with pytest.raises(ValueError):
            models.parse_keys_text(bad)


def test_placeholder_params_roundtrip_with_keys() -> None:
    """params 含 keys 时 to_dict → from_dict 必须一致。"""
    params = models.PlaceholderTaskParams(
        click_points=[[1, 2]],
        keys=[models.KeyStepParams("ctrl+s", 0, 300), models.KeyStepParams("w", 800, 200)],
        wait_after_ms=600,
    )
    restored = models.PlaceholderTaskParams.from_dict(params.to_dict())
    assert restored.to_dict() == params.to_dict()
    assert restored.keys[1].hold_ms == 800


def test_swipe_step_text_roundtrip() -> None:
    """滑动文本语法：`100,200 > 400,600`（默认 400ms）、`...*800`（指定时长）。"""
    steps = models.parse_swipes_text("100,200 > 400,600; 10,10 > 20,20*800")
    assert [(s.from_point, s.to_point, s.duration_ms) for s in steps] == [
        ([100, 200], [400, 600], 400),
        ([10, 10], [20, 20], 800),
    ]
    assert models.format_swipes_text(steps) == "100,200 > 400,600; 10,10 > 20,20*800"
    assert models.parse_swipes_text("") == []


def test_swipe_step_text_rejects_bad_input() -> None:
    """非法滑动文本必须抛可读错误（GUI 据此回退、校验据此报错）。"""
    for bad in ("*800", "100,200", "100 > 200,300", "a,b > c,d", "100,200 > 400,600*abc",
                "100,200 > 400,600*60001"):
        with pytest.raises(ValueError):
            models.parse_swipes_text(bad)


def test_step_text_enforces_step_limits() -> None:
    """步数上限（`MAX_KEY_STEPS`/`MAX_SWIPE_STEPS`＝20）在**解析阶段**就挡住；正好 20 步可以通过。

    这条原来挂在日常任务页的两个输入框测试上（评审 P1-2/P3-2 的回归）；2026-09-21 该页按用户
    设计稿整页替换、不再有这两个文本框，于是把覆盖移到 config 层 —— 上限本来就是配置模型的规则，
    界面只是它的一个入口。
    """
    ok_keys = ", ".join(["w"] * models.MAX_KEY_STEPS)
    assert len(models.parse_keys_text(ok_keys)) == models.MAX_KEY_STEPS
    with pytest.raises(ValueError, match="最多"):
        models.parse_keys_text(", ".join(["w"] * (models.MAX_KEY_STEPS + 1)))

    ok_swipes = "; ".join(["1,1 > 2,2"] * models.MAX_SWIPE_STEPS)
    assert len(models.parse_swipes_text(ok_swipes)) == models.MAX_SWIPE_STEPS
    with pytest.raises(ValueError, match="最多"):
        models.parse_swipes_text("; ".join(["1,1 > 2,2"] * (models.MAX_SWIPE_STEPS + 1)))


def test_placeholder_params_roundtrip_with_swipes() -> None:
    """params 含 swipes 时 to_dict → from_dict 必须一致。"""
    params = models.PlaceholderTaskParams(
        click_points=[], keys=[],
        swipes=[models.SwipeStepParams([1, 2], [30, 40], 800, 200)],
        wait_after_ms=600,
    )
    restored = models.PlaceholderTaskParams.from_dict(params.to_dict())
    assert restored.to_dict() == params.to_dict()
    assert restored.swipes[0].duration_ms == 800
