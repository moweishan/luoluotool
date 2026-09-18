"""配置模型：PROJECT_SPEC.md 第 9 节 schema v5（dataclass 实现）。"""

from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = 5


@dataclass
class TaskConfig:
    """单个任务配置。"""

    enabled: bool = False
    order: int = 1
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "order": self.order, "params": self.params}

    @classmethod
    def from_dict(cls, data: dict) -> TaskConfig:
        return cls(data.get("enabled", False), data.get("order", 1), data.get("params", {}))


@dataclass
class LoopConfig:
    """循环执行配置。"""

    enabled: bool = False
    interval_seconds: int = 3600

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "interval_seconds": self.interval_seconds}

    @classmethod
    def from_dict(cls, data: dict) -> LoopConfig:
        return cls(data.get("enabled", False), data.get("interval_seconds", 3600))


@dataclass
class PlaceholderTaskParams:
    """placeholder_task_a 的私有参数（params 内容，缺省键回落默认值）。"""

    click_points: list[list[int]] = field(default_factory=list)
    wait_after_ms: int = 500

    def to_dict(self) -> dict:
        return {
            "click_points": [list(point) for point in self.click_points],
            "wait_after_ms": self.wait_after_ms,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> PlaceholderTaskParams:
        raw = data or {}
        points = [list(point) for point in (raw.get("click_points") or [])]
        return cls(points, raw.get("wait_after_ms", 500))


@dataclass
class DailyTasksConfig:
    """功能一：日常任务。"""

    enabled: bool = False
    tasks: dict[str, TaskConfig] = field(default_factory=dict)
    loop: LoopConfig = field(default_factory=LoopConfig)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "tasks": {task_id: task.to_dict() for task_id, task in self.tasks.items()},
            "loop": self.loop.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> DailyTasksConfig:
        return cls(
            data.get("enabled", False),
            {task_id: TaskConfig.from_dict(item) for task_id, item in data.get("tasks", {}).items()},
            LoopConfig.from_dict(data.get("loop", {})),
        )


@dataclass
class OrderHoldConfig:
    """功能二：卡订单（两个预留开关仅占位）。"""

    enabled: bool = False
    reserved_switch_1: bool = False
    reserved_switch_2: bool = False

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "reserved_switch_1": self.reserved_switch_1,
            "reserved_switch_2": self.reserved_switch_2,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OrderHoldConfig:
        return cls(
            data.get("enabled", False),
            data.get("reserved_switch_1", False),
            data.get("reserved_switch_2", False),
        )


@dataclass
class FeatureConfig:
    """功能三/四：预留配置页。"""

    enabled: bool = False

    def to_dict(self) -> dict:
        return {"enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: dict) -> FeatureConfig:
        return cls(data.get("enabled", False))


@dataclass
class AutomationConfig:
    """自动化参数。"""

    dry_run: bool = True
    window_title_keyword: str = "桃源深处有人家"
    click_interval_ms: int = 800
    post_click_wait_ms: int = 500
    max_consecutive_failures: int = 3
    failsafe_hotkey: str = "F8"
    ask_elevation_on_start: bool = True
    # 输入实现方式固定为「真实鼠标键盘（SendInput）」，故不再有 input_mode 选项；
    # 该通道每次输入前会自行把游戏窗口置顶/置前，因此也没有"失焦暂停"开关。
    # 每次点击后是否把真实光标移回原位（用户要求"动作后还原光标"可配置）
    restore_cursor_after_click: bool = True

    def to_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "window_title_keyword": self.window_title_keyword,
            "click_interval_ms": self.click_interval_ms,
            "post_click_wait_ms": self.post_click_wait_ms,
            "max_consecutive_failures": self.max_consecutive_failures,
            "failsafe_hotkey": self.failsafe_hotkey,
            "ask_elevation_on_start": self.ask_elevation_on_start,
            "restore_cursor_after_click": self.restore_cursor_after_click,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AutomationConfig:
        return cls(
            data.get("dry_run", True),
            data.get("window_title_keyword", "桃源深处有人家"),
            data.get("click_interval_ms", 800),
            data.get("post_click_wait_ms", 500),
            data.get("max_consecutive_failures", 3),
            data.get("failsafe_hotkey", "F8"),
            data.get("ask_elevation_on_start", True),
            data.get("restore_cursor_after_click", True),
        )


@dataclass
class LoggingConfig:
    """日志配置。"""

    level: str = "INFO"
    max_file_mb: int = 2
    backup_count: int = 3

    def to_dict(self) -> dict:
        return {"level": self.level, "max_file_mb": self.max_file_mb, "backup_count": self.backup_count}

    @classmethod
    def from_dict(cls, data: dict) -> LoggingConfig:
        return cls(data.get("level", "INFO"), data.get("max_file_mb", 2), data.get("backup_count", 3))


@dataclass
class FeaturesConfig:
    """四大功能开关集合。"""

    daily_tasks: DailyTasksConfig = field(default_factory=DailyTasksConfig)
    order_hold: OrderHoldConfig = field(default_factory=OrderHoldConfig)
    feature_3: FeatureConfig = field(default_factory=FeatureConfig)
    feature_4: FeatureConfig = field(default_factory=FeatureConfig)

    def to_dict(self) -> dict:
        return {
            "daily_tasks": self.daily_tasks.to_dict(),
            "order_hold": self.order_hold.to_dict(),
            "feature_3": self.feature_3.to_dict(),
            "feature_4": self.feature_4.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> FeaturesConfig:
        return cls(
            DailyTasksConfig.from_dict(data.get("daily_tasks", {})),
            OrderHoldConfig.from_dict(data.get("order_hold", {})),
            FeatureConfig.from_dict(data.get("feature_3", {})),
            FeatureConfig.from_dict(data.get("feature_4", {})),
        )


@dataclass
class AppConfig:
    """根配置：schema v1 全部字段。"""

    schema_version: int = SCHEMA_VERSION
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    automation: AutomationConfig = field(default_factory=AutomationConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def default(cls) -> AppConfig:
        """返回出厂默认配置（含占位任务 A 及其 params 结构）。"""
        config = cls()
        config.features.daily_tasks.tasks["placeholder_task_a"] = TaskConfig(
            params=PlaceholderTaskParams().to_dict()
        )
        return config

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "features": self.features.to_dict(),
            "automation": self.automation.to_dict(),
            "logging": self.logging.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> AppConfig:
        return cls(
            data.get("schema_version", SCHEMA_VERSION),
            FeaturesConfig.from_dict(data.get("features", {})),
            AutomationConfig.from_dict(data.get("automation", {})),
            LoggingConfig.from_dict(data.get("logging", {})),
        )
