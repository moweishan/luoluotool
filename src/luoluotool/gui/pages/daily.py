"""日常任务配置页：启用、占位任务 A、按键序列、滑动序列、循环开关与间隔。"""

import logging
from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from luoluotool.config.models import (
    AppConfig,
    PlaceholderTaskParams,
    TaskConfig,
    format_keys_text,
    format_swipes_text,
    parse_keys_text,
    parse_swipes_text,
)

logger = logging.getLogger(__name__)
from luoluotool.gui.widgets import ScrollablePage

LOOP_MIN_SECONDS = 1
LOOP_MAX_SECONDS = 86400


class DailyPage(ScrollablePage):
    """绑定 features.daily_tasks.*；控件改动写回内存配置并回调脏标记。

    按键序列只做「文本 ↔ 配置」的转换与展示，解析规则在 `config.models.parse_keys_text`。
    """

    def __init__(self, config: AppConfig, on_changed: Callable[[], None]) -> None:
        super().__init__()
        self._config = config
        self._on_changed = on_changed
        layout = QVBoxLayout(self.content)
        self.enabled_box = QCheckBox("启用日常任务")
        self.task_a_box = QCheckBox("占位任务 A")
        self.loop_box = QCheckBox("循环执行")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(LOOP_MIN_SECONDS, LOOP_MAX_SECONDS)
        self.interval_spin.setSuffix(" 秒")
        self.keys_edit = QLineEdit()
        self.keys_edit.setPlaceholderText("例如：ctrl+s, w*800, enter（*后为长按毫秒）")
        self.keys_edit.setToolTip(
            "按顺序执行的按键序列，用逗号分隔：\n"
            "· 组合键：ctrl+s、alt+f4、shift+space\n"
            "· 长按：w*800 表示按住 800 毫秒后松开\n"
            "· 可用键名见 automation/real_input.py 的 KEY_NAME_TO_VK（a-z、0-9、f1-f24、"
            "enter/esc/tab/space/up/down/left/right 等）\n"
            "执行时每次按键前都会校验并把游戏窗口置于最顶层；无法确保时不会按键。"
        )
        self.swipes_edit = QLineEdit()
        self.swipes_edit.setPlaceholderText("例如：100,200 > 400,600; 400,600 > 100,200*800")
        self.swipes_edit.setToolTip(
            "鼠标滑动（按住左键拖拽）序列，用分号分隔：\n"
            "· 基本写法：x1,y1 > x2,y2（从起点滑到终点，默认 400 毫秒）\n"
            "· 指定时长：x1,y1 > x2,y2*800（用时 800 毫秒，范围 50–10000）\n"
            "坐标是游戏客户区坐标；执行时每次滑动前都会校验并把游戏窗口置于最顶层，"
            "无法确保时不会滑动；滑动期间按急停键会立即中断并松开左键。"
        )
        loop_row = QHBoxLayout()
        loop_row.addWidget(self.loop_box)
        loop_row.addWidget(QLabel("间隔"))
        loop_row.addWidget(self.interval_spin)
        loop_row.addStretch(1)
        keys_row = QHBoxLayout()
        keys_row.addWidget(QLabel("按键序列"))
        keys_row.addWidget(self.keys_edit)
        swipes_row = QHBoxLayout()
        swipes_row.addWidget(QLabel("滑动序列"))
        swipes_row.addWidget(self.swipes_edit)
        layout.addWidget(self.enabled_box)
        layout.addWidget(self.task_a_box)
        layout.addLayout(keys_row)
        layout.addLayout(swipes_row)
        layout.addLayout(loop_row)
        layout.addStretch(1)
        self.enabled_box.toggled.connect(self._on_enabled_toggled)
        self.task_a_box.toggled.connect(self._on_task_a_toggled)
        self.loop_box.toggled.connect(self._on_loop_toggled)
        self.interval_spin.valueChanged.connect(self._on_interval_changed)
        self.keys_edit.editingFinished.connect(self._on_keys_edited)
        self.swipes_edit.editingFinished.connect(self._on_swipes_edited)
        self.set_config(config)

    def set_config(self, config: AppConfig) -> None:
        """重新绑定配置并刷新控件（不触发脏标记）。"""
        self._config = config
        daily = config.features.daily_tasks
        task = daily.tasks.get("placeholder_task_a")
        self.enabled_box.blockSignals(True)
        self.enabled_box.setChecked(daily.enabled)
        self.enabled_box.blockSignals(False)
        self.task_a_box.blockSignals(True)
        self.task_a_box.setChecked(bool(task and task.enabled))
        self.task_a_box.blockSignals(False)
        self.loop_box.blockSignals(True)
        self.loop_box.setChecked(daily.loop.enabled)
        self.loop_box.blockSignals(False)
        self.interval_spin.blockSignals(True)
        self.interval_spin.setValue(daily.loop.interval_seconds)
        self.interval_spin.blockSignals(False)
        self.keys_edit.blockSignals(True)
        self.keys_edit.setText(self._keys_text())
        self.keys_edit.blockSignals(False)
        self.swipes_edit.blockSignals(True)
        self.swipes_edit.setText(self._swipes_text())
        self.swipes_edit.blockSignals(False)

    def _params(self) -> PlaceholderTaskParams:
        task = self._config.features.daily_tasks.tasks.get("placeholder_task_a")
        return PlaceholderTaskParams.from_dict(task.params if task else None)

    def _keys_text(self) -> str:
        return format_keys_text(self._params().keys)

    def _swipes_text(self) -> str:
        return format_swipes_text(self._params().swipes)

    def _on_swipes_edited(self) -> None:
        """把滑动输入框写回配置；格式非法则回退显示（不写坏配置），并说明被丢弃的原因。"""
        text = self.swipes_edit.text()
        try:
            steps = parse_swipes_text(text, self._params().wait_after_ms)
        except ValueError as exc:
            # 评审 P3-2：静默回退违反"不许吞异常"，必须写日志 + 给出可读提示
            logger.warning("滑动步骤输入被丢弃（保留原值）：%s（输入：%r）", exc, text)
            self._rollback_swipes()
            return
        task = self._config.features.daily_tasks.tasks.setdefault("placeholder_task_a", TaskConfig())
        params = PlaceholderTaskParams.from_dict(task.params)
        params.swipes = steps
        task.params = params.to_dict()
        self._on_changed()

    def _rollback_swipes(self) -> None:
        self.swipes_edit.blockSignals(True)
        self.swipes_edit.setText(self._swipes_text())
        self.swipes_edit.blockSignals(False)

    def _on_keys_edited(self) -> None:
        """把输入框文本写回配置；格式非法则回退显示（不写坏配置），并说明被丢弃的原因。"""
        text = self.keys_edit.text()
        try:
            steps = parse_keys_text(text, self._params().wait_after_ms)
        except ValueError as exc:
            logger.warning("按键序列输入被丢弃（保留原值）：%s（输入：%r）", exc, text)
            self.keys_edit.blockSignals(True)
            self.keys_edit.setText(self._keys_text())
            self.keys_edit.blockSignals(False)
            return
        task = self._config.features.daily_tasks.tasks.setdefault("placeholder_task_a", TaskConfig())
        params = PlaceholderTaskParams.from_dict(task.params)
        params.keys = steps
        task.params = params.to_dict()
        self._on_changed()

    def _on_enabled_toggled(self) -> None:
        self._config.features.daily_tasks.enabled = self.enabled_box.isChecked()
        self._on_changed()

    def _on_task_a_toggled(self) -> None:
        task = self._config.features.daily_tasks.tasks.setdefault("placeholder_task_a", TaskConfig())
        task.enabled = self.task_a_box.isChecked()
        self._on_changed()

    def _on_loop_toggled(self) -> None:
        self._config.features.daily_tasks.loop.enabled = self.loop_box.isChecked()
        self._on_changed()

    def _on_interval_changed(self, value: int) -> None:
        self._config.features.daily_tasks.loop.interval_seconds = value
        self._on_changed()
