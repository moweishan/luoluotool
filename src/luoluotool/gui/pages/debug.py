"""开发者调试页：窗口诊断、干跑开关与输入测试（单点/连点/滑动/键盘）。

页面只做「参数收集 + 按钮 + 结果展示」，实际动作交给 `core.debug` 在后台线程执行；
测试动作与正式任务共用同一输入通道（干跑只写日志、真实模式每次输入前校验并置顶窗口）。
"""

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from luoluotool.config.models import AppConfig

COORDINATE_MAX = 10000
COUNT_RANGE = (1, 200)
INTERVAL_RANGE_MS = (50, 5000)
DURATION_RANGE_MS = (50, 10000)


def _spin(maximum: int, minimum: int = 0, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setValue(minimum if minimum > 0 else 0)
    if suffix:
        box.setSuffix(suffix)
    return box


class DebugPage(QWidget):
    """开发者调试页：显示由设置页的「开发者调试」开关控制。

    信号 `test_requested(kind, params)`：请求主窗口在后台线程执行测试动作；
    `diagnose_requested()`：请求执行窗口诊断（复用主窗口既有线程）。
    """

    test_requested = Signal(str, dict)
    diagnose_requested = Signal()

    def __init__(self, config: AppConfig, on_changed: Callable[[], None]) -> None:
        super().__init__()
        self._config = config
        self._on_changed = on_changed
        # 内容必须放进 QScrollArea：本页控件较多（最小高度近 500px），若直接铺在页面上，
        # 它会成为 QTabWidget 的最小高度，勾选「开发者调试」时把整个页签区顶高
        # （窗口最小高度 381 → 658），表现为所有页签高度都变了、日志面板被压扁。
        # 放进滚动区后本页最小高度不随内容增长，页签区高度与是否挂载调试页无关。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        self.scroll_area.setWidget(content)
        outer.addWidget(self.scroll_area)

        # ---- 干跑模式（从设置页移入） ----
        self.dry_run_box = QCheckBox("干跑模式（仅模拟输出日志，不产生真实键鼠操作）")
        self.dry_run_box.toggled.connect(self._on_dry_run_toggled)
        layout.addWidget(self.dry_run_box)

        # ---- 窗口诊断（从设置页移入） ----
        self.diagnose_button = QPushButton("窗口诊断（查找游戏窗口并截图）")
        layout.addWidget(self.diagnose_button)
        self.diagnose_button.clicked.connect(self.diagnose_requested.emit)

        layout.addWidget(QLabel("提示：真实模式下测试按钮会真的操作鼠标键盘；"
                                "勾选「干跑模式」则只写日志、零真实输入。"))

        # ---- 鼠标单点 ----
        click_group = QGroupBox("鼠标单点测试")
        click_grid = QGridLayout(click_group)
        self.single_x_spin = _spin(COORDINATE_MAX)
        self.single_y_spin = _spin(COORDINATE_MAX)
        self.single_button = QPushButton("单点测试")
        click_grid.addWidget(QLabel("X"), 0, 0)
        click_grid.addWidget(self.single_x_spin, 0, 1)
        click_grid.addWidget(QLabel("Y"), 0, 2)
        click_grid.addWidget(self.single_y_spin, 0, 3)
        click_grid.addWidget(self.single_button, 0, 4)
        self.single_button.clicked.connect(self._on_single_clicked)
        layout.addWidget(click_group)

        # ---- 鼠标连点 ----
        repeat_group = QGroupBox("鼠标连点测试")
        repeat_grid = QGridLayout(repeat_group)
        self.repeat_x_spin = _spin(COORDINATE_MAX)
        self.repeat_y_spin = _spin(COORDINATE_MAX)
        self.repeat_count_spin = _spin(COUNT_RANGE[1], COUNT_RANGE[0])
        self.repeat_count_spin.setValue(5)
        self.repeat_interval_spin = _spin(INTERVAL_RANGE_MS[1], INTERVAL_RANGE_MS[0], " ms")
        self.repeat_interval_spin.setValue(500)
        self.repeat_button = QPushButton("连点测试")
        repeat_grid.addWidget(QLabel("X"), 0, 0)
        repeat_grid.addWidget(self.repeat_x_spin, 0, 1)
        repeat_grid.addWidget(QLabel("Y"), 0, 2)
        repeat_grid.addWidget(self.repeat_y_spin, 0, 3)
        repeat_grid.addWidget(QLabel("次数"), 1, 0)
        repeat_grid.addWidget(self.repeat_count_spin, 1, 1)
        repeat_grid.addWidget(QLabel("间隔"), 1, 2)
        repeat_grid.addWidget(self.repeat_interval_spin, 1, 3)
        repeat_grid.addWidget(self.repeat_button, 0, 4, 2, 1)
        self.repeat_button.clicked.connect(self._on_repeat_clicked)
        layout.addWidget(repeat_group)

        # ---- 鼠标滑动 ----
        swipe_group = QGroupBox("鼠标屏幕滑动测试")
        swipe_grid = QGridLayout(swipe_group)
        self.swipe_from_x_spin = _spin(COORDINATE_MAX)
        self.swipe_from_y_spin = _spin(COORDINATE_MAX)
        self.swipe_to_x_spin = _spin(COORDINATE_MAX)
        self.swipe_to_x_spin.setValue(200)
        self.swipe_to_y_spin = _spin(COORDINATE_MAX)
        self.swipe_duration_spin = _spin(DURATION_RANGE_MS[1], DURATION_RANGE_MS[0], " ms")
        self.swipe_duration_spin.setValue(500)
        self.swipe_button = QPushButton("滑动测试")
        swipe_grid.addWidget(QLabel("起点 X"), 0, 0)
        swipe_grid.addWidget(self.swipe_from_x_spin, 0, 1)
        swipe_grid.addWidget(QLabel("起点 Y"), 0, 2)
        swipe_grid.addWidget(self.swipe_from_y_spin, 0, 3)
        swipe_grid.addWidget(QLabel("终点 X"), 1, 0)
        swipe_grid.addWidget(self.swipe_to_x_spin, 1, 1)
        swipe_grid.addWidget(QLabel("终点 Y"), 1, 2)
        swipe_grid.addWidget(self.swipe_to_y_spin, 1, 3)
        swipe_grid.addWidget(QLabel("用时"), 2, 0)
        swipe_grid.addWidget(self.swipe_duration_spin, 2, 1)
        swipe_grid.addWidget(self.swipe_button, 0, 4, 3, 1)
        self.swipe_button.clicked.connect(self._on_swipe_clicked)
        layout.addWidget(swipe_group)

        # ---- 键盘点击 ----
        key_group = QGroupBox("键盘点击测试")
        key_grid = QGridLayout(key_group)
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("例如：a、enter、ctrl+s（键名见文档）")
        self.key_count_spin = _spin(COUNT_RANGE[1], COUNT_RANGE[0])
        self.key_count_spin.setValue(1)
        self.key_interval_spin = _spin(INTERVAL_RANGE_MS[1], INTERVAL_RANGE_MS[0], " ms")
        self.key_interval_spin.setValue(300)
        self.key_button = QPushButton("键盘测试")
        key_grid.addWidget(QLabel("按键"), 0, 0)
        key_grid.addWidget(self.key_edit, 0, 1, 1, 2)
        key_grid.addWidget(QLabel("次数"), 1, 0)
        key_grid.addWidget(self.key_count_spin, 1, 1)
        key_grid.addWidget(QLabel("间隔"), 1, 2)
        key_grid.addWidget(self.key_interval_spin, 1, 3)
        key_grid.addWidget(self.key_button, 0, 4, 2, 1)
        self.key_button.clicked.connect(self._on_key_clicked)
        layout.addWidget(key_group)

        self.status_label = QLabel("就绪")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self.set_config(config)

    # ------------------------------------------------------------------ 绑定

    def set_config(self, config: AppConfig) -> None:
        """重新绑定配置并刷新控件（不触发脏标记）。"""
        self._config = config
        self.dry_run_box.blockSignals(True)
        self.dry_run_box.setChecked(config.automation.dry_run)
        self.dry_run_box.blockSignals(False)

    def set_busy(self, busy: bool) -> None:
        """执行期间禁用所有测试按钮，避免重复触发。"""
        for button in (self.single_button, self.repeat_button, self.swipe_button,
                       self.key_button, self.diagnose_button):
            button.setEnabled(not busy)

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    # ------------------------------------------------------------------ 槽

    def _on_dry_run_toggled(self) -> None:
        self._config.automation.dry_run = self.dry_run_box.isChecked()
        self._on_changed()

    def _on_single_clicked(self) -> None:
        self.test_requested.emit("single_click", {
            "x": self.single_x_spin.value(), "y": self.single_y_spin.value(),
        })

    def _on_repeat_clicked(self) -> None:
        self.test_requested.emit("repeat_click", {
            "x": self.repeat_x_spin.value(), "y": self.repeat_y_spin.value(),
            "count": self.repeat_count_spin.value(),
            "interval_ms": self.repeat_interval_spin.value(),
        })

    def _on_swipe_clicked(self) -> None:
        self.test_requested.emit("swipe", {
            "from_x": self.swipe_from_x_spin.value(), "from_y": self.swipe_from_y_spin.value(),
            "to_x": self.swipe_to_x_spin.value(), "to_y": self.swipe_to_y_spin.value(),
            "duration_ms": self.swipe_duration_spin.value(),
        })

    def _on_key_clicked(self) -> None:
        self.test_requested.emit("key", {
            "combo": self.key_edit.text(),
            "count": self.key_count_spin.value(),
            "interval_ms": self.key_interval_spin.value(),
        })
