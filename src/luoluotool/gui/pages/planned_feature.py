"""功能三/功能四共用的"预留配置页"基类（评审 P3-10：两页原来是逐行复制粘贴）。

用法：子类只声明标题、开关文案、说明文案，以及读写哪个 feature 开关。
"""

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout

from luoluotool.config.models import AppConfig, FeatureConfig
from luoluotool.gui.widgets import ScrollablePage


class PlannedFeaturePage(ScrollablePage):
    """预留功能页：一个启用开关 + 一句"功能规划中"。"""

    #: 子类覆写：页面标题（与页签文案一致）
    title = "功能"
    #: 子类覆写：说明文案
    note = "功能规划中"

    def __init__(self, config: AppConfig, on_changed: Callable[[], None]) -> None:
        super().__init__()
        self._config = config
        self._on_changed = on_changed
        layout = QVBoxLayout(self.content)
        self.enabled_box = QCheckBox(f"启用{self.title}")
        layout.addWidget(self.enabled_box)
        layout.addWidget(QLabel(self.note))
        layout.addStretch(1)
        self.enabled_box.toggled.connect(self._on_toggled)
        self.set_config(config)

    # ------------------------------------------------------------ 子类实现

    def _feature(self, config: AppConfig) -> FeatureConfig:
        """返回本页绑定的 feature 配置对象（子类必须覆写）。"""
        raise NotImplementedError

    # ------------------------------------------------------------ 绑定

    def set_config(self, config: AppConfig) -> None:
        """重新绑定配置并刷新控件（不触发脏标记）。"""
        self._config = config
        self.enabled_box.blockSignals(True)
        self.enabled_box.setChecked(self._feature(config).enabled)
        self.enabled_box.blockSignals(False)

    def _on_toggled(self) -> None:
        self._feature(self._config).enabled = self.enabled_box.isChecked()
        self._on_changed()
