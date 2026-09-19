"""开发者调试页：窗口诊断、布局测量、干跑开关与输入测试（单点/连点/滑动/键盘）。

页面只做「参数收集 + 按钮 + 结果展示」，实际动作交给 `core.debug` 在后台线程执行；
测试动作与正式任务共用同一输入通道（干跑只写日志、真实模式每次输入前校验并置顶窗口）。

**开发者调试未开启时本页所有选项都不生效**（用户 2026-09-19 要求）：整页禁用、
干跑开关的改动不写入配置；主窗口还会拒绝本页发出的动作请求。
"""

import logging
from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from luoluotool.automation.vision import DEFAULT_THRESHOLD as DEFAULT_VISION_THRESHOLD
from luoluotool.config.models import AppConfig
from luoluotool.gui.widgets import ScrollablePage

logger = logging.getLogger(__name__)

PAGE_TITLE = "开发者调试"
COORDINATE_MAX = 10000
COUNT_RANGE = (1, 200)
INTERVAL_RANGE_MS = (50, 5000)
DURATION_RANGE_MS = (50, 10000)
VISION_THRESHOLD_MIN = 0.30


def _spin(maximum: int, minimum: int = 0, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setValue(minimum if minimum > 0 else 0)
    if suffix:
        box.setSuffix(suffix)
    return box


class DebugPage(ScrollablePage):
    """开发者调试页：显示由设置页的「开发者调试」开关控制。

    信号 `test_requested(kind, params)`：请求主窗口在后台线程执行测试动作；
    `diagnose_requested()`：请求执行窗口诊断（复用主窗口既有线程）；
    `layout_measure_requested()`：请求测量各页签布局占用（纯几何，无副作用）。
    """

    test_requested = Signal(str, dict)
    diagnose_requested = Signal()
    layout_measure_requested = Signal()
    crop_requested = Signal()

    def __init__(self, config: AppConfig, on_changed: Callable[[], None]) -> None:
        super().__init__()
        self._config = config
        self._on_changed = on_changed
        # 内容自动进入 QScrollArea（见 ScrollablePage）：本页控件最多，若直接铺在页面上
        # 会成为 QTabWidget 的最小高度并顶高所有页签。
        layout = QVBoxLayout(self.content)

        # ---- 干跑模式（从设置页移入） ----
        self.dry_run_box = QCheckBox("干跑模式（仅模拟输出日志，不产生真实键鼠操作）")
        self.dry_run_box.toggled.connect(self._on_dry_run_toggled)
        layout.addWidget(self.dry_run_box)

        # ---- 窗口诊断 + 布局测量（从设置页移入 / 布局回归工具） ----
        diagnose_row = QHBoxLayout()
        self.diagnose_button = QPushButton("窗口诊断（查找游戏窗口并截图）")
        diagnose_row.addWidget(self.diagnose_button)
        self.layout_measure_button = QPushButton("布局测量（检查页签高度是否互相影响）")
        diagnose_row.addWidget(self.layout_measure_button)
        diagnose_row.addStretch(1)
        layout.addLayout(diagnose_row)
        self.diagnose_button.clicked.connect(self.diagnose_requested.emit)
        self.layout_measure_button.clicked.connect(self.layout_measure_requested.emit)

        # ---- 图片识别匹配测试（放在最前面：它是常用入口，避免被挤到需要滚动的位置） ----
        vision_group = QGroupBox("图片识别匹配测试（在游戏窗口里查找图片并给出坐标）")
        vision_grid = QGridLayout(vision_group)
        self.vision_path_edit = QLineEdit()
        self.vision_path_edit.setPlaceholderText("模板图片路径（PNG/JPG，支持中文路径）")
        self.vision_path_edit.setToolTip(
            "要查找的图片：从游戏里裁下来的按钮/图标/面板都可以；\n"
            "建议截取画面中**不会变化**的局部（数字、倒计时等变动区域会让匹配变得不稳定）。"
        )
        self.vision_browse_button = QPushButton("选择图片…")
        self.vision_threshold_spin = QDoubleSpinBox()
        self.vision_threshold_spin.setRange(VISION_THRESHOLD_MIN, 1.0)
        self.vision_threshold_spin.setSingleStep(0.01)
        self.vision_threshold_spin.setDecimals(2)
        self.vision_threshold_spin.setValue(DEFAULT_VISION_THRESHOLD)
        self.vision_threshold_spin.setToolTip("相似度阈值：越高越严格（默认 0.85）")
        self.vision_button = QPushButton("图片识别匹配测试")
        self.crop_button = QPushButton("框选截图生成模板")
        self.crop_button.setToolTip(
            "截取游戏窗口后拖拽框选 → 保存成模板并自动填入上面的图片路径，\n"
            "省去手工裁剪：框的就是识别要找的那部分像素。"
        )
        vision_grid.addWidget(QLabel("图片"), 0, 0)
        vision_grid.addWidget(self.vision_path_edit, 0, 1, 1, 2)
        vision_grid.addWidget(self.vision_browse_button, 0, 3)
        vision_grid.addWidget(QLabel("阈值"), 1, 0)
        vision_grid.addWidget(self.vision_threshold_spin, 1, 1)
        vision_grid.addWidget(self.vision_button, 1, 2)
        vision_grid.addWidget(self.crop_button, 1, 3)
        self.vision_button.clicked.connect(self._on_vision_clicked)
        self.vision_browse_button.clicked.connect(self._on_vision_browse_clicked)
        self.crop_button.clicked.connect(self.crop_requested.emit)
        layout.addWidget(vision_group)

        layout.addWidget(QLabel("提示：真实模式下测试按钮会真的操作鼠标键盘；"
                                "勾选「干跑模式」则只写日志、零真实输入。"
                                "图片识别本身不产生任何输入。"))

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
        """重新绑定配置并刷新控件（不触发脏标记）；同时按开发者调试开关决定整页是否可用。"""
        self._config = config
        self.dry_run_box.blockSignals(True)
        self.dry_run_box.setChecked(config.automation.dry_run)
        self.dry_run_box.blockSignals(False)
        self.setEnabled(bool(config.automation.developer_mode))

    def set_busy(self, busy: bool) -> None:
        """执行期间禁用所有测试按钮，避免重复触发。"""
        for button in (self.single_button, self.repeat_button, self.swipe_button,
                       self.key_button, self.diagnose_button, self.layout_measure_button,
                       self.vision_button, self.vision_browse_button, self.crop_button):
            button.setEnabled(not busy)

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    # ------------------------------------------------------------------ 槽

    def _on_dry_run_toggled(self) -> None:
        """干跑开关：仅在「开发者调试」开启时生效；未开启则回滚勾选、不写配置。"""
        if not self._config.automation.developer_mode:
            logger.warning("开发者调试未开启，忽略干跑开关变更（本页选项不生效）")
            self.dry_run_box.blockSignals(True)
            self.dry_run_box.setChecked(self._config.automation.dry_run)
            self.dry_run_box.blockSignals(False)
            self.set_status("开发者调试未开启：本页所有选项不生效（干跑开关未修改）")
            return
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

    def _on_vision_clicked(self) -> None:
        self.test_requested.emit("vision", {
            "image": self.vision_path_edit.text().strip(),
            "threshold": self.vision_threshold_spin.value(),
        })

    def _on_vision_browse_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模板图片", "", "图片 (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self.vision_path_edit.setText(path)
