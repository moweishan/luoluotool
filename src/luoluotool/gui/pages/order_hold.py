"""卡订单配置页：主开关 + 两个预留开关（纯占位）。"""

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout

from luoluotool.config.models import AppConfig
from luoluotool.gui.widgets import ScrollablePage


class OrderHoldPage(ScrollablePage):
    """绑定 features.order_hold.*；预留开关无任何行为。"""

    def __init__(self, config: AppConfig, on_changed: Callable[[], None]) -> None:
        super().__init__()
        self._config = config
        self._on_changed = on_changed
        layout = QVBoxLayout(self.content)
        self.enabled_box = QCheckBox("启用卡订单")
        self.reserved_box_1 = QCheckBox("预留开关 1")
        self.reserved_box_2 = QCheckBox("预留开关 2")
        layout.addWidget(self.enabled_box)
        layout.addWidget(self.reserved_box_1)
        layout.addWidget(self.reserved_box_2)
        layout.addWidget(QLabel("说明：预留开关当前无任何实际行为，仅保存与展示（规划中）。"))
        layout.addStretch(1)
        self.enabled_box.toggled.connect(self._on_enabled_toggled)
        self.reserved_box_1.toggled.connect(self._on_reserved_1_toggled)
        self.reserved_box_2.toggled.connect(self._on_reserved_2_toggled)
        self.set_config(config)

    def set_config(self, config: AppConfig) -> None:
        """重新绑定配置并刷新控件（不触发脏标记）。"""
        self._config = config
        order_hold = config.features.order_hold
        self.enabled_box.blockSignals(True)
        self.enabled_box.setChecked(order_hold.enabled)
        self.enabled_box.blockSignals(False)
        self.reserved_box_1.blockSignals(True)
        self.reserved_box_1.setChecked(order_hold.reserved_switch_1)
        self.reserved_box_1.blockSignals(False)
        self.reserved_box_2.blockSignals(True)
        self.reserved_box_2.setChecked(order_hold.reserved_switch_2)
        self.reserved_box_2.blockSignals(False)

    def _on_enabled_toggled(self) -> None:
        self._config.features.order_hold.enabled = self.enabled_box.isChecked()
        self._on_changed()

    def _on_reserved_1_toggled(self) -> None:
        self._config.features.order_hold.reserved_switch_1 = self.reserved_box_1.isChecked()
        self._on_changed()

    def _on_reserved_2_toggled(self) -> None:
        self._config.features.order_hold.reserved_switch_2 = self.reserved_box_2.isChecked()
        self._on_changed()
