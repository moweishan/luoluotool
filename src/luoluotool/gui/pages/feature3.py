"""功能三预留配置页：启用开关 + 规划中说明。"""

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from luoluotool.config.models import AppConfig


class Feature3Page(QWidget):
    """绑定 features.feature_3.enabled。"""

    def __init__(self, config: AppConfig, on_changed: Callable[[], None]) -> None:
        super().__init__()
        self._config = config
        self._on_changed = on_changed
        layout = QVBoxLayout(self)
        self.enabled_box = QCheckBox("启用功能三")
        layout.addWidget(self.enabled_box)
        layout.addWidget(QLabel("功能规划中"))
        layout.addStretch(1)
        self.enabled_box.toggled.connect(self._on_toggled)
        self.set_config(config)

    def set_config(self, config: AppConfig) -> None:
        """重新绑定配置并刷新控件（不触发脏标记）。"""
        self._config = config
        self.enabled_box.blockSignals(True)
        self.enabled_box.setChecked(config.features.feature_3.enabled)
        self.enabled_box.blockSignals(False)

    def _on_toggled(self) -> None:
        self._config.features.feature_3.enabled = self.enabled_box.isChecked()
        self._on_changed()
