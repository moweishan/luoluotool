"""设置页：干跑、点击间隔、失败上限、失焦暂停；急停键只读展示。"""

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from luoluotool.automation.hotkey import DEFAULT_HOTKEY_NAME, supported_hotkeys
from luoluotool.config.models import (
    INPUT_MODE_REAL_INPUT,
    INPUT_MODE_WINDOW_ALIGN,
    INPUT_MODE_WINDOW_MESSAGE,
    AppConfig,
)

CLICK_INTERVAL_MIN_MS = 100
CLICK_INTERVAL_MAX_MS = 5000
FAILURES_MIN = 1
FAILURES_MAX = 100


class SettingsPage(QWidget):
    """绑定 automation.dry_run/click_interval_ms/max_consecutive_failures/
    pause_on_window_focus_loss；急停键只读展示。"""

    def __init__(self, config: AppConfig, on_changed: Callable[[], None]) -> None:
        super().__init__()
        self._config = config
        self._on_changed = on_changed
        layout = QVBoxLayout(self)
        self.dry_run_box = QCheckBox("干跑模式（仅模拟输出日志，不产生真实键鼠操作）")
        self.focus_loss_box = QCheckBox("窗口失焦时暂停")
        self.click_interval_spin = QSpinBox()
        self.click_interval_spin.setRange(CLICK_INTERVAL_MIN_MS, CLICK_INTERVAL_MAX_MS)
        self.click_interval_spin.setSuffix(" ms")
        self.failures_spin = QSpinBox()
        self.failures_spin.setRange(FAILURES_MIN, FAILURES_MAX)
        self.hotkey_combo = QComboBox()
        self.hotkey_combo.addItems(supported_hotkeys())
        self.diagnose_button = QPushButton("窗口诊断（查找游戏窗口并截图）")
        self.elevation_hint_label = QLabel()
        self.elevation_hint_label.setWordWrap(True)
        self.elevation_hint_label.setVisible(False)
        self.restart_admin_button = QPushButton("以管理员身份重启")
        self.restart_admin_button.setToolTip(
            "游戏以管理员权限运行时，本工具需要同等权限才能置前/截图；"
            "点击后经系统 UAC 确认以管理员身份重启"
        )
        self.ask_elevation_box = QCheckBox(
            "启动时询问是否提权（取消勾选 = 不再询问，直接以管理员身份重启）"
        )
        self.input_mode_combo = QComboBox()
        self.input_mode_combo.addItem("窗口消息（默认，不抢前台、不动光标）", INPUT_MODE_WINDOW_MESSAGE)
        self.input_mode_combo.addItem("对齐窗口点击（点准且不动光标，游戏窗口会短暂位移）", INPUT_MODE_WINDOW_ALIGN)
        self.input_mode_combo.addItem("真实鼠标键盘（SendInput；每次输入前把游戏窗口置顶，会抢前台）",
                                      INPUT_MODE_REAL_INPUT)
        self.input_mode_combo.setToolTip(
            "窗口消息：零侵入，但被「按真实光标取点」的游戏忽略坐标。\n"
            "对齐窗口点击：点击前把目标坐标搬到静止光标下方（移动窗口而非光标），点完还原窗口位置。\n"
            "真实鼠标键盘：真实移动光标并模拟真实键鼠；每次点击/按键前都会校验游戏窗口是否在最顶层，"
            "不在则先置顶再置前；点击后按下方开关决定是否把鼠标移回原位。"
        )
        self.restore_cursor_box = QCheckBox("每次点击后把真实鼠标移回原位置（仅真实鼠标键盘方式生效）")
        click_row = QHBoxLayout()
        click_row.addWidget(QLabel("点击间隔"))
        click_row.addWidget(self.click_interval_spin)
        click_row.addStretch(1)
        failures_row = QHBoxLayout()
        failures_row.addWidget(QLabel("连续失败上限"))
        failures_row.addWidget(self.failures_spin)
        failures_row.addStretch(1)
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(QLabel("急停热键"))
        hotkey_row.addWidget(self.hotkey_combo)
        hotkey_row.addStretch(1)
        layout.addWidget(self.dry_run_box)
        layout.addWidget(self.focus_loss_box)
        layout.addLayout(click_row)
        layout.addLayout(failures_row)
        layout.addLayout(hotkey_row)
        layout.addWidget(self.ask_elevation_box)
        layout.addWidget(QLabel("输入方式"))
        layout.addWidget(self.input_mode_combo)
        layout.addWidget(self.restore_cursor_box)
        layout.addWidget(self.diagnose_button)
        layout.addWidget(self.elevation_hint_label)
        layout.addWidget(self.restart_admin_button)
        layout.addStretch(1)
        self.dry_run_box.toggled.connect(self._on_dry_run_toggled)
        self.focus_loss_box.toggled.connect(self._on_focus_loss_toggled)
        self.click_interval_spin.valueChanged.connect(self._on_click_interval_changed)
        self.failures_spin.valueChanged.connect(self._on_failures_changed)
        self.ask_elevation_box.toggled.connect(self._on_ask_elevation_toggled)
        self.input_mode_combo.currentIndexChanged.connect(self._on_input_mode_changed)
        self.restore_cursor_box.toggled.connect(self._on_restore_cursor_toggled)
        self.hotkey_combo.currentTextChanged.connect(self._on_hotkey_changed)
        self.set_config(config)

    def set_config(self, config: AppConfig) -> None:
        """重新绑定配置并刷新控件（不触发脏标记）。"""
        self._config = config
        automation = config.automation
        self.dry_run_box.blockSignals(True)
        self.dry_run_box.setChecked(automation.dry_run)
        self.dry_run_box.blockSignals(False)
        self.focus_loss_box.blockSignals(True)
        self.focus_loss_box.setChecked(automation.pause_on_window_focus_loss)
        self.focus_loss_box.blockSignals(False)
        self.click_interval_spin.blockSignals(True)
        self.click_interval_spin.setValue(automation.click_interval_ms)
        self.click_interval_spin.blockSignals(False)
        self.failures_spin.blockSignals(True)
        self.failures_spin.setValue(automation.max_consecutive_failures)
        self.failures_spin.blockSignals(False)
        self.ask_elevation_box.blockSignals(True)
        self.ask_elevation_box.setChecked(automation.ask_elevation_on_start)
        self.ask_elevation_box.blockSignals(False)
        self.input_mode_combo.blockSignals(True)
        index = self.input_mode_combo.findData(automation.input_mode)
        self.input_mode_combo.setCurrentIndex(index if index >= 0 else 0)
        self.input_mode_combo.blockSignals(False)
        self.restore_cursor_box.blockSignals(True)
        self.restore_cursor_box.setChecked(automation.restore_cursor_after_click)
        self.restore_cursor_box.blockSignals(False)
        self.hotkey_combo.blockSignals(True)
        self.hotkey_combo.setCurrentText(automation.failsafe_hotkey or DEFAULT_HOTKEY_NAME)
        self.hotkey_combo.blockSignals(False)

    def _on_dry_run_toggled(self) -> None:
        self._config.automation.dry_run = self.dry_run_box.isChecked()
        self._on_changed()

    def _on_focus_loss_toggled(self) -> None:
        self._config.automation.pause_on_window_focus_loss = self.focus_loss_box.isChecked()
        self._on_changed()

    def _on_click_interval_changed(self, value: int) -> None:
        self._config.automation.click_interval_ms = value
        self._on_changed()

    def _on_failures_changed(self, value: int) -> None:
        self._config.automation.max_consecutive_failures = value
        self._on_changed()

    def _on_ask_elevation_toggled(self) -> None:
        self._config.automation.ask_elevation_on_start = self.ask_elevation_box.isChecked()
        self._on_changed()

    def _on_input_mode_changed(self) -> None:
        mode = self.input_mode_combo.currentData()
        if mode:
            self._config.automation.input_mode = mode
            self._on_changed()

    def _on_restore_cursor_toggled(self) -> None:
        self._config.automation.restore_cursor_after_click = self.restore_cursor_box.isChecked()
        self._on_changed()

    def _on_hotkey_changed(self, name: str) -> None:
        self._config.automation.failsafe_hotkey = name
        self._on_changed()
