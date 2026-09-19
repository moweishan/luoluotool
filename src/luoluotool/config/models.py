"""配置模型：PROJECT_SPEC.md 第 9 节 schema v8（dataclass 实现）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from luoluotool.utils.keys import parse_combo

SCHEMA_VERSION = 8


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
class KeyStepParams:
    """一个按键步骤：组合键文本 + 可选长按毫秒 + 步骤后等待毫秒。

    文本语法（GUI 单行输入也用它；解析/格式化为纯函数，见 `parse_keys_text`）：
    `ctrl+s`（组合键）、`w*800`（长按 800ms）、`enter`（普通按键）。
    """

    combo: str = ""
    hold_ms: int = 0
    wait_after_ms: int = 500

    def to_dict(self) -> dict:
        return {"combo": self.combo, "hold_ms": self.hold_ms, "wait_after_ms": self.wait_after_ms}

    @classmethod
    def from_dict(cls, data: dict | None) -> KeyStepParams:
        raw = data or {}
        return cls(
            str(raw.get("combo", "")),
            int(raw.get("hold_ms", 0) or 0),
            int(raw.get("wait_after_ms", 500)),
        )

    def to_text(self) -> str:
        """还原为单行文本（长按为 0 时省略 `*ms`）。"""
        return f"{self.combo}*{self.hold_ms}" if self.hold_ms else self.combo

    @classmethod
    def from_text(cls, text: str, wait_after_ms: int = 500) -> KeyStepParams:
        """解析单个步骤文本：`ctrl+s` 或 `w*800`；键名非法时抛可读 `ValueError`。"""
        raw = (text or "").strip()
        if not raw:
            raise ValueError("按键步骤不能为空")
        if "*" in raw:
            combo, _, hold = raw.rpartition("*")
            hold = hold.strip()
            if not combo.strip() or not hold.isdigit():
                raise ValueError(f"按键步骤格式非法（应为 按键 或 按键*长按毫秒）：{text!r}")
            step = cls(combo.strip(), int(hold), wait_after_ms)
        else:
            step = cls(raw, 0, wait_after_ms)
        parse_combo(step.combo)   # 校验键名/修饰键（未知键名在这里就报错）
        if step.hold_ms > 60000:
            raise ValueError(f"长按时间过长（0–60000 毫秒）：{text!r}")
        return step


def parse_keys_text(text: str, wait_after_ms: int = 500) -> list[KeyStepParams]:
    """把 `"ctrl+s, w*800, enter"` 解析为按键步骤列表（分隔符支持中英文逗号与换行）。"""
    steps: list[KeyStepParams] = []
    for chunk in (text or "").replace("，", ",").replace("\n", ",").split(","):
        if chunk.strip():
            steps.append(KeyStepParams.from_text(chunk, wait_after_ms))
    return steps


def format_keys_text(steps: list[KeyStepParams]) -> str:
    """把按键步骤列表格式化回单行文本（与 `parse_keys_text` 互逆）。"""
    return ", ".join(step.to_text() for step in steps)


@dataclass
class SwipeStepParams:
    """一个鼠标滑动步骤：从 from 按住左键分帧移动到 to，再松开。

    文本语法（GUI 单行输入也用它）：`100,200 > 400,600`（默认 400ms）、
    `100,200 > 400,600*800`（用时 800ms）。
    """

    from_point: list[int] = field(default_factory=lambda: [0, 0])
    to_point: list[int] = field(default_factory=lambda: [0, 0])
    duration_ms: int = 400
    wait_after_ms: int = 500

    def to_dict(self) -> dict:
        return {
            "from": [int(self.from_point[0]), int(self.from_point[1])],
            "to": [int(self.to_point[0]), int(self.to_point[1])],
            "duration_ms": self.duration_ms,
            "wait_after_ms": self.wait_after_ms,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> SwipeStepParams:
        raw = data or {}
        return cls(
            [int(value) for value in (raw.get("from") or [0, 0])],
            [int(value) for value in (raw.get("to") or [0, 0])],
            int(raw.get("duration_ms", 400) or 400),
            int(raw.get("wait_after_ms", 500)),
        )

    def to_text(self) -> str:
        base = f"{self.from_point[0]},{self.from_point[1]} > {self.to_point[0]},{self.to_point[1]}"
        return f"{base}*{self.duration_ms}" if self.duration_ms != 400 else base

    @classmethod
    def from_text(cls, text: str, wait_after_ms: int = 500) -> SwipeStepParams:
        """解析单个滑动步骤文本；非法时抛可读 `ValueError`。"""
        raw = (text or "").strip()
        if not raw:
            raise ValueError("滑动步骤不能为空")
        duration = 400
        if "*" in raw:
            raw, _, duration_text = raw.rpartition("*")
            duration_text = duration_text.strip()
            if not duration_text.isdigit():
                raise ValueError(f"滑动时长格式非法（应为 *毫秒）：{text!r}")
            duration = int(duration_text)
        if ">" not in raw:
            raise ValueError(f"滑动步骤缺少 '>'（应形如 100,200 > 400,600）：{text!r}")
        left, _, right = raw.partition(">")
        if not 50 <= duration <= 10000:
            raise ValueError(f"滑动时长必须在 50–10000 毫秒之间：{text!r}")
        return cls(_parse_point(left, text), _parse_point(right, text), duration, wait_after_ms)


def _parse_point(text: str, origin: str) -> list[int]:
    """解析 `x,y` 形式的客户区坐标点。"""
    parts = [part.strip() for part in (text or "").split(",")]
    if len(parts) != 2 or not all(part.lstrip("-").isdigit() for part in parts):
        raise ValueError(f"滑动坐标格式非法（应为 x,y，且为非负整数）：{origin!r}")
    x, y = int(parts[0]), int(parts[1])
    if x < 0 or y < 0:
        raise ValueError(f"滑动坐标必须为非负整数：{origin!r}")
    return [x, y]


def parse_swipes_text(text: str, wait_after_ms: int = 500) -> list[SwipeStepParams]:
    """把 `"100,200 > 400,600, 10,10 > 20,20*800"` 解析为滑动步骤列表。"""
    steps: list[SwipeStepParams] = []
    for chunk in (text or "").replace("，", ",").replace("\n", ";").replace(", ", ";").split(";"):
        if chunk.strip():
            steps.append(SwipeStepParams.from_text(chunk, wait_after_ms))
    return steps


def format_swipes_text(steps: list[SwipeStepParams]) -> str:
    """把滑动步骤列表格式化回单行文本（与 `parse_swipes_text` 互逆）。"""
    return "; ".join(step.to_text() for step in steps)


@dataclass
class PlaceholderTaskParams:
    """placeholder_task_a 的私有参数（params 内容，缺省键回落默认值）。"""

    click_points: list[list[int]] = field(default_factory=list)
    keys: list[KeyStepParams] = field(default_factory=list)
    swipes: list[SwipeStepParams] = field(default_factory=list)
    wait_after_ms: int = 500

    def to_dict(self) -> dict:
        return {
            "click_points": [list(point) for point in self.click_points],
            "keys": [step.to_dict() for step in self.keys],
            "swipes": [step.to_dict() for step in self.swipes],
            "wait_after_ms": self.wait_after_ms,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> PlaceholderTaskParams:
        raw = data or {}
        points = [list(point) for point in (raw.get("click_points") or [])]
        keys = [KeyStepParams.from_dict(item) for item in (raw.get("keys") or [])]
        swipes = [SwipeStepParams.from_dict(item) for item in (raw.get("swipes") or [])]
        return cls(points, keys, swipes, raw.get("wait_after_ms", 500))


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

    # 2026-09-19 用户要求：干跑模式**默认不开启**（首次启动即真实模式）；
    # 真实模式启动前仍有强制确认弹窗 + F8 急停兜底。
    dry_run: bool = False
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
    # 开发者调试：在顶部显示「开发者调试」标签页（含窗口诊断、干跑开关与 4 个输入测试）
    developer_mode: bool = False

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
            "developer_mode": self.developer_mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AutomationConfig:
        return cls(
            data.get("dry_run", False),
            data.get("window_title_keyword", "桃源深处有人家"),
            data.get("click_interval_ms", 800),
            data.get("post_click_wait_ms", 500),
            data.get("max_consecutive_failures", 3),
            data.get("failsafe_hotkey", "F8"),
            data.get("ask_elevation_on_start", True),
            data.get("restore_cursor_after_click", True),
            data.get("developer_mode", False),
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
