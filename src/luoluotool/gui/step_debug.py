"""单步运行（调试）的界面部分：执行线程 → GUI 线程的桥 + 主窗口那两个按钮的接线。

用户 2026-09-22 要求：开发者调试页最上方加「单步运行」开关；**停止按钮最右边**加
「上一步」「下一步」；**只有勾了单步运行这两个按钮才显示**，其余情况都不显示。

为什么单独一个模块：
- `core` 不许 import PySide6（AGENTS §1.4），单步控制器（`core/step_mode.py`）只接受普通回调，
  那个回调由**任务线程**调用 —— `StepModeBridge` 负责把它转成 Qt 信号（自动排队到 GUI 线程）；
- 加完这一批 `main_window.py` 到 649 行（超 AGENTS §2 的 600 行硬线），
  按 `elevation_flow.ElevationFlowMixin` 的同一套做法把"单步运行"收成一个 mixin。

约定 —— 本 mixin 假设宿主是 `QMainWindow`，并提供 `self.debug_page` / `self._idle_status` /
`self.statusBar()`；调用顺序：`build_step_controls()`（**必须在 `_apply_developer_mode()` 之前**，
因为它会复位单步）→ 布局里 `add_step_buttons(layout)` → 需要时 `reset_step_mode()`。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QPushButton

from luoluotool.core.step_mode import StepController


class StepModeBridge(QObject):
    """执行线程 → GUI 线程：单步状态变化（参数是 `core.step_mode.StepSnapshot`）。"""

    state_changed = Signal(object)

    def publish(self, snapshot) -> None:
        """由执行线程调用（**不要**在这里直接改界面控件，只发信号）。"""
        self.state_changed.emit(snapshot)


class StepDebugMixin:
    """「单步运行」在界面上的全部接线（由 `MainWindow` 继承；见模块说明里的约定）。"""

    def build_step_controls(self) -> None:
        """建控制器、跨线程桥与两个按钮（两个按钮默认隐藏）。"""
        self._step_bridge = StepModeBridge(self)
        self._stepper = StepController(on_change=self._step_bridge.publish)
        self._step_bridge.state_changed.connect(self._on_step_state_changed)

        self.previous_button = QPushButton("上一步")
        self.previous_button.setToolTip(
            "回到上一步的运动状态：只把步骤指针退一格、把光标移回那一步的位置，\n"
            "**不会重放**上一步的点击/按键/滑动（调试用）。"
        )
        self.previous_button.clicked.connect(self._on_previous_step)
        self.next_button = QPushButton("下一步")
        self.next_button.setToolTip(
            "放行一步：脚本里的一个动作（点击 / 滑动 / 按键）算一步。\n"
            "只有勾了开发者调试页的「单步运行」才需要按它。"
        )
        self.next_button.clicked.connect(self._on_next_step)
        self._step_buttons: tuple[QPushButton, ...] = (self.previous_button, self.next_button)
        for button in self._step_buttons:
            button.setVisible(False)          # 只有勾了「单步运行」才显示（用户要求）

    def add_step_buttons(self, layout: QHBoxLayout) -> None:
        """把两个按钮放到主界面按钮行的**停止按钮右边**（调用方保证顺序）。"""
        for button in self._step_buttons:
            layout.addWidget(button)

    def reset_step_mode(self) -> None:
        """复位单步（关掉控制器、藏起两个按钮）—— 关闭「开发者调试」时用。"""
        self.debug_page.set_step_mode(False)
        self._on_step_mode_toggled(False)

    # ---------------------------------------------------------------- 槽
    def _on_step_mode_toggled(self, enabled: bool) -> None:
        """调试页的「单步运行」开关：切换控制器 + 显示/隐藏两个按钮（**不写配置**）。"""
        self._stepper.set_enabled(bool(enabled))
        for button in self._step_buttons:
            button.setVisible(bool(enabled))
        if enabled:
            self.statusBar().showMessage(
                "单步运行已开启：点「启动」后每点一次「下一步」走一步"
                "（「上一步」只回退状态、不重放动作）"
            )
        else:
            self.statusBar().showMessage(self._idle_status)

    def _on_next_step(self) -> None:
        """「下一步」：放行一步（真正执行在任务线程里）。"""
        if not self._stepper.enabled():
            return
        if not self._stepper.request_next():
            self.statusBar().showMessage("单步：当前没有停在某一步上（先点「启动」开始）")

    def _on_previous_step(self) -> None:
        """「上一步」：指针退一格 + 由任务线程把光标移回那一步的位置（**不执行**那一步的动作）。"""
        if not self._stepper.enabled():
            return
        index, restore = self._stepper.request_previous()
        snapshot = self._stepper.snapshot()
        total = f"/{snapshot.total}" if snapshot.total else ""
        hint = f"，光标回位到 {restore}" if restore is not None else ""
        self.statusBar().showMessage(
            f"单步：已回到第 {index + 1}{total} 步（未执行任何动作{hint}）"
        )

    def _on_step_state_changed(self, snapshot) -> None:
        """任务线程报告"停在某一步门口"（经 `StepModeBridge` 排队到 GUI 线程）。"""
        if not self._stepper.enabled():
            return
        if snapshot.waiting:
            self.statusBar().showMessage(
                f"单步：停在第 {snapshot.index + 1}/{snapshot.total} 步（{snapshot.label}）"
                f"—— 点「下一步」继续，或「上一步」退回上一步"
            )

    def attach_stepper_to_runner(self, runner, is_main_window: QMainWindow | None = None) -> None:
        """把单步控制器交给 Runner（**没勾单步就什么都不做**：非单步路径零开销）。"""
        if runner is not None and self._stepper.enabled():
            runner.stepper = self._stepper
