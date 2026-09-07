"""配置校验：字段级检查，返回错误列表而非抛异常。"""

from luoluotool.config.models import SCHEMA_VERSION

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
        if not isinstance(task.get("params"), dict):
            errors.append(f"features.daily_tasks.tasks.{task_id}.params 必须是对象")


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
