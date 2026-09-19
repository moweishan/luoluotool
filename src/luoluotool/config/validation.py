"""配置校验与 schema 迁移：返回错误列表而非抛异常。"""

import logging

from luoluotool.config.models import SCHEMA_VERSION
from luoluotool.utils.keys import parse_combo

logger = logging.getLogger(__name__)

MAX_KEY_STEPS = 20

_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_SECTIONS = (
    "features.daily_tasks",
    "features.daily_tasks.loop",
    "features.order_hold",
    "features.feature_3",
    "features.feature_4",
    "automation",
    "logging",
)
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
    "automation.save_vision_annotations",
)
_INT_BOUNDS = (
    ("automation.click_interval_ms", 100, 5000),
    ("automation.post_click_wait_ms", 0, 60000),
    ("automation.max_consecutive_failures", 1, 100),
    ("features.daily_tasks.loop.interval_seconds", 1, 86400),
    ("logging.max_file_mb", 1, 100),
    ("logging.backup_count", 0, 50),
)
_STR_LIMITS = (
    ("automation.window_title_keyword", 100),
    ("automation.failsafe_hotkey", 20),
)


class _Missing:
    """缺失标记（与 None 区分）。"""


_MISSING = _Missing()


def _get(raw: dict, path: str):
    """按 a.b.c 路径取值；路径上任何一节缺失返回 _MISSING。"""
    current = raw
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _skipped(path: str, missing: list[str]) -> bool:
    """所在配置节缺失时跳过该字段检查（已报告"缺少配置节"）。"""
    return any(path.startswith(section) for section in missing)


def _validate_version(raw: dict, errors: list[str]) -> None:
    version = raw.get("schema_version", _MISSING)
    if version is _MISSING:
        errors.append("缺少 schema_version")
    elif isinstance(version, bool) or not isinstance(version, int):
        errors.append("schema_version 必须是整数")
    elif version != SCHEMA_VERSION:
        errors.append(f"不支持的 schema_version：{version}（当前支持 {SCHEMA_VERSION}）")


def _is_point(value: object) -> bool:
    """判断是否为 [x, y] 形式的非负整数坐标。"""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return False
    return all(
        isinstance(item, int) and not isinstance(item, bool) and item >= 0 for item in value
    )


def _validate_key_steps(prefix: str, steps: object, errors: list[str]) -> None:
    """校验按键步骤列表：`[{"combo": "ctrl+s", "hold_ms": 0, "wait_after_ms": 500}, ...]`。"""
    if not isinstance(steps, list):
        errors.append(f"{prefix}.keys 必须是数组")
        return
    if len(steps) > MAX_KEY_STEPS:
        errors.append(f"{prefix}.keys 最多 {MAX_KEY_STEPS} 步")
    for index, step in enumerate(steps):
        item_prefix = f"{prefix}.keys[{index}]"
        if not isinstance(step, dict):
            errors.append(f"{item_prefix} 必须是对象")
            continue
        combo = step.get("combo")
        if not isinstance(combo, str) or not combo.strip() or len(combo) > 60:
            errors.append(f"{item_prefix}.combo 必须是非空字符串（最长 60）")
        else:
            try:
                parse_combo(combo)
            except ValueError as exc:
                errors.append(f"{item_prefix}.combo 非法：{exc}")
        hold = step.get("hold_ms", 0)
        if isinstance(hold, bool) or not isinstance(hold, int) or not (0 <= hold <= 60000):
            errors.append(f"{item_prefix}.hold_ms 必须是 0–60000 之间的整数")
        wait = step.get("wait_after_ms", 500)
        if isinstance(wait, bool) or not isinstance(wait, int) or not (0 <= wait <= 60000):
            errors.append(f"{item_prefix}.wait_after_ms 必须是 0–60000 之间的整数")


def _is_xy(value: object) -> bool:
    """`[x, y]` 形式的非负整数坐标。"""
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(not isinstance(item, bool) and isinstance(item, int) and item >= 0 for item in value)
    )


def _validate_swipes(prefix: str, swipes: object, errors: list[str]) -> None:
    """校验滑动步骤列表：`[{"from": [x, y], "to": [x, y], "duration_ms": 400, "wait_after_ms": 500}, ...]`。"""
    if not isinstance(swipes, list):
        errors.append(f"{prefix}.swipes 必须是数组")
        return
    if len(swipes) > MAX_KEY_STEPS:
        errors.append(f"{prefix}.swipes 最多 {MAX_KEY_STEPS} 步")
    for index, step in enumerate(swipes):
        item_prefix = f"{prefix}.swipes[{index}]"
        if not isinstance(step, dict):
            errors.append(f"{item_prefix} 必须是对象")
            continue
        if not _is_xy(step.get("from")) or not _is_xy(step.get("to")):
            errors.append(f"{item_prefix}.from/.to 必须是 [x, y] 形式的非负整数坐标")
        duration = step.get("duration_ms", 400)
        if isinstance(duration, bool) or not isinstance(duration, int) or not (50 <= duration <= 10000):
            errors.append(f"{item_prefix}.duration_ms 必须是 50–10000 之间的整数")
        wait = step.get("wait_after_ms", 500)
        if isinstance(wait, bool) or not isinstance(wait, int) or not (0 <= wait <= 60000):
            errors.append(f"{item_prefix}.wait_after_ms 必须是 0–60000 之间的整数")


def _validate_task_params(task_id: str, params: object, errors: list[str]) -> None:
    """校验任务私有参数结构（缺省键合法，回落默认值）。"""
    prefix = f"features.daily_tasks.tasks.{task_id}.params"
    if not isinstance(params, dict):
        errors.append(f"{prefix} 必须是对象")
        return
    points = params.get("click_points", [])
    if not isinstance(points, list) or not all(_is_point(point) for point in points):
        errors.append(f"{prefix}.click_points 必须是 [[x, y], ...] 形式的非负整数坐标数组")
    _validate_key_steps(prefix, params.get("keys", []), errors)
    _validate_swipes(prefix, params.get("swipes", []), errors)
    wait = params.get("wait_after_ms", 500)
    if isinstance(wait, bool) or not isinstance(wait, int) or not (0 <= wait <= 60000):
        errors.append(f"{prefix}.wait_after_ms 必须是 0–60000 之间的整数")


def _validate_tasks(raw: dict, errors: list[str]) -> None:
    tasks = _get(raw, "features.daily_tasks.tasks")
    if not isinstance(tasks, dict):
        errors.append("features.daily_tasks.tasks 必须是对象")
        return
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            errors.append(f"features.daily_tasks.tasks.{task_id} 必须是对象")
            continue
        if not isinstance(task.get("enabled"), bool):
            errors.append(f"features.daily_tasks.tasks.{task_id}.enabled 必须是布尔值")
        order = task.get("order")
        if isinstance(order, bool) or not isinstance(order, int) or not (1 <= order <= 999):
            errors.append(f"features.daily_tasks.tasks.{task_id}.order 必须是 1–999 之间的整数")
        _validate_task_params(task_id, task.get("params"), errors)


def _migrate_v1_to_v2(raw: dict) -> dict:
    """v1 → v2：新增 automation.ask_elevation_on_start（默认 true = 启动时询问提权）。"""
    automation = dict(raw.get("automation") or {})
    automation.setdefault("ask_elevation_on_start", True)
    migrated = dict(raw)
    migrated["automation"] = automation
    return migrated


def _migrate_v2_to_v3(raw: dict) -> dict:
    """v2 → v3：新增 automation.align_window_before_click（默认 false = 不移动窗口）。"""
    automation = dict(raw.get("automation") or {})
    automation.setdefault("align_window_before_click", False)
    migrated = dict(raw)
    migrated["automation"] = automation
    return migrated


def _migrate_v3_to_v4(raw: dict) -> dict:
    """v3 → v4：移除已废弃的 `align_window_before_click`（对齐窗口通道已按用户要求删除），
    并新增「点击后还原真实光标」开关。

    历史说明：v4 曾把该布尔升级成 `input_mode` 枚举（窗口消息/对齐窗口/真实键鼠三选一）；
    2026-09-16 用户确定只保留真实鼠标键盘实现后，`input_mode` 已在 v5 移除。
    """
    automation = dict(raw.get("automation") or {})
    automation.pop("align_window_before_click", None)
    automation.setdefault("restore_cursor_after_click", True)
    migrated = dict(raw)
    migrated["automation"] = automation
    return migrated


def _migrate_v4_to_v5(raw: dict) -> dict:
    """v4 → v5：输入实现方式固定为「真实鼠标键盘」，移除 input_mode 与已失效的失焦暂停开关。"""
    automation = dict(raw.get("automation") or {})
    automation.pop("input_mode", None)
    automation.pop("pause_on_window_focus_loss", None)
    # 对齐窗口通道已删除：旧配置里可能残留该布尔，一并清除（不依赖迁移链是否从 v3 起跳）
    automation.pop("align_window_before_click", None)
    automation.setdefault("restore_cursor_after_click", True)
    migrated = dict(raw)
    migrated["automation"] = automation
    return migrated


def _migrate_v5_to_v6(raw: dict) -> dict:
    """v5 → v6：任务参数新增按键序列 `params.keys`（默认空数组 = 不发送任何按键）。"""
    migrated = dict(raw)
    features = dict(migrated.get("features") or {})
    daily = dict(features.get("daily_tasks") or {})
    tasks = {}
    for task_id, task in (daily.get("tasks") or {}).items():
        if isinstance(task, dict):
            item = dict(task)
            params = dict(item.get("params") or {})
            params.setdefault("keys", [])
            item["params"] = params
            tasks[task_id] = item
        else:
            tasks[task_id] = task
    daily["tasks"] = tasks
    features["daily_tasks"] = daily
    migrated["features"] = features
    return migrated


def _migrate_v6_to_v7(raw: dict) -> dict:
    """v6 → v7：任务参数新增鼠标滑动序列 `params.swipes`（默认空数组 = 不滑动）。"""
    migrated = dict(raw)
    features = dict(migrated.get("features") or {})
    daily = dict(features.get("daily_tasks") or {})
    tasks = {}
    for task_id, task in (daily.get("tasks") or {}).items():
        if isinstance(task, dict):
            item = dict(task)
            params = dict(item.get("params") or {})
            params.setdefault("swipes", [])
            item["params"] = params
            tasks[task_id] = item
        else:
            tasks[task_id] = task
    daily["tasks"] = tasks
    features["daily_tasks"] = daily
    migrated["features"] = features
    return migrated


def _migrate_v7_to_v8(raw: dict) -> dict:
    """v7 → v8：新增 `automation.developer_mode`（默认 false = 不显示开发者调试页）。"""
    automation = dict(raw.get("automation") or {})
    automation.setdefault("developer_mode", False)
    migrated = dict(raw)
    migrated["automation"] = automation
    return migrated


def _migrate_v8_to_v9(raw: dict) -> dict:
    """v8 → v9：新增 `automation.save_vision_annotations`（默认 true = 识别成功仍存带框截图）。"""
    automation = dict(raw.get("automation") or {})
    automation.setdefault("save_vision_annotations", True)
    migrated = dict(raw)
    migrated["automation"] = automation
    return migrated


_MIGRATIONS = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
    3: _migrate_v3_to_v4,
    4: _migrate_v4_to_v5,
    5: _migrate_v5_to_v6,
    6: _migrate_v6_to_v7,
    7: _migrate_v7_to_v8,
    8: _migrate_v8_to_v9,
}


def migrate(raw: object) -> object:
    """按 schema_version 逐级迁移到当前版本。

    已是当前版本、版本未知或输入非法时原样返回（交由校验报错）。
    """
    if not isinstance(raw, dict):
        return raw
    version = raw.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        return raw
    if version >= SCHEMA_VERSION:
        return raw
    migrated = dict(raw)
    while version < SCHEMA_VERSION:
        step = _MIGRATIONS.get(version)
        if step is None:
            return raw
        migrated = step(migrated)
        version += 1
        migrated["schema_version"] = version
    logger.info("配置已从 schema v%s 迁移到 v%d", raw.get("schema_version"), version)
    return migrated


def validate(raw: object) -> list[str]:
    """校验原始配置；返回错误列表（空列表表示通过）。"""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return ["配置根节点必须是对象"]
    _validate_version(raw, errors)
    missing = [section for section in _SECTIONS if not isinstance(_get(raw, section), dict)]
    for section in missing:
        errors.append(f"缺少配置节 {section}")
    for path in _BOOL_PATHS:
        if _skipped(path, missing):
            continue
        if not isinstance(_get(raw, path), bool):
            errors.append(f"{path} 必须是布尔值")
    for path, lo, hi in _INT_BOUNDS:
        if _skipped(path, missing):
            continue
        value = _get(raw, path)
        if isinstance(value, bool) or not isinstance(value, int) or not (lo <= value <= hi):
            errors.append(f"{path} 必须是 {lo}–{hi} 之间的整数")
    for path, max_len in _STR_LIMITS:
        if _skipped(path, missing):
            continue
        value = _get(raw, path)
        if not isinstance(value, str) or not value or len(value) > max_len:
            errors.append(f"{path} 必须是非空字符串（最长 {max_len}）")
    if "logging" not in missing:
        level = _get(raw, "logging.level")
        if not isinstance(level, str) or level not in _LOG_LEVELS:
            errors.append(f"logging.level 必须是 {'/'.join(sorted(_LOG_LEVELS))} 之一")
    if "features.daily_tasks" not in missing:
        _validate_tasks(raw, errors)
    return errors
