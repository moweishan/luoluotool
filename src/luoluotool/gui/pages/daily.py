"""日常任务配置页：启用、占位任务 A、循环开关与间隔。"""

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from luoluotool.config.models import AppConfig, TaskConfig

LOOP_MIN_SECONDS = 1
LOOP_MAX_SECONDS = 86400


class DailyPage(QWidget):
    """绑定 features.daily_tasks.*；控件改动写回内存配置并回调脏标记。"""

    def __init__(self, config: AppConfig, on_changed: Callable[[], None]) -> None:
        super().__init__()
        self._config = config
        self._on_changed = on_changed
        layout = QVBoxLayout(self)
        self.enabled_box = QCheckBox("启用日常任务")
        self.task_a_box = QCheckBox("占位任务 A")
        self.loop_box = QCheckBox("循环执行")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(LOOP_MIN_SECONDS, LOOP_MAX_SECONDS)
        self.interval_spin.setSuffix(" 秒")
        loop_row = QHBoxLayout()
        loop_row.addWidget(self.loop_box)
        loop_row.addWidget(QLabel("间隔"))
        loop_row.addWidget(self.interval_spin)
        loop_row.addStretch(1)
        layout.addWidget(self.enabled_box)
        layout.addWidget(self.task_a_box)
        layout.addLayout(loop_row)
        layout.addStretch(1)
        self.enabled_box.toggled.connect(self._on_enabled_toggled)
        self.task_a_box.toggled.connect(self._on_task_a_toggled)
        self.loop_box.toggled.connect(self._on_loop_toggled)
        self.interval_spin.valueChanged.connect(self._on_interval_changed)
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
