"""配置校验与 schema 迁移：返回错误列表而非抛异常。"""

import logging

from luoluotool.config.models import SCHEMA_VERSION

logger = logging.getLogger(__name__)

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
    "automation.pause_on_window_focus_loss",
    "automation.ask_elevation_on_start",
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


def _validate_task_params(task_id: str, params: object, errors: list[str]) -> None:
    """校验任务私有参数结构（缺省键合法，回落默认值）。"""
    prefix = f"features.daily_tasks.tasks.{task_id}.params"
    if not isinstance(params, dict):
        errors.append(f"{prefix} 必须是对象")
        return
    points = params.get("click_points", [])
    if not isinstance(points, list) or not all(_is_point(point) for point in points):
        errors.append(f"{prefix}.click_points 必须是 [[x, y], ...] 形式的非负整数坐标数组")
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


_MIGRATIONS = {1: _migrate_v1_to_v2}


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
