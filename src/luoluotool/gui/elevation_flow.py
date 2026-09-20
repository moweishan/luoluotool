"""提权（管理员）流程：检测游戏窗口是否需要提权、界面提示、"以管理员身份重启"。

分层：gui 层 → automation（`elevation` / `window`）+ config；不做输入注入。

拆分说明（2026-09-20）：这些方法原本是 `gui/main_window.py` 里 `MainWindow` 的一部分，
现原样搬成 mixin 由 `MainWindow` 继承（方法体逐字未改，`self.` 语义不变）。

注意（测试）：`is_process_elevated` / `is_window_elevated` / `find_window` / `restart_as_admin`
都在**本模块**命名空间里查 —— monkeypatch 目标是 `gui.elevation_flow`，不是 `gui.main_window`。
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox

from luoluotool.automation.elevation import (
    is_process_elevated,
    is_window_elevated,
    restart_as_admin,
)
from luoluotool.automation.window import find_window
from luoluotool.config import store

logger = logging.getLogger(__name__)


class ElevationFlowMixin:
    """提权流程（mixin）：由 `MainWindow` 继承使用，方法体与拆分前完全一致。"""

    def _show_elevation_hint(self) -> None:
        """设置页显示提权提示（自动检测到权限不足时）。"""
        self.settings_page.elevation_hint_label.setText(
            "检测到游戏以管理员权限运行，本工具为普通权限，无法置前/截图"
            "（后续键鼠模拟同样会被系统拦截）。请点击下方「以管理员身份重启」。"
        )
        self.settings_page.elevation_hint_label.setVisible(True)

    def _check_elevation_need(self) -> None:
        """启动时自动检测：游戏窗口权限更高而本工具未提权时给出提示。"""
        if is_process_elevated():
            return
        hwnd = find_window(self._config.automation.window_title_keyword)
        if hwnd is None or is_window_elevated(hwnd) is not True:
            return
        logger.warning("检测到游戏窗口以管理员权限运行，本工具为普通权限，建议以管理员身份重启")
        self._show_elevation_hint()

    def _startup_elevation_flow(self) -> None:
        """启动完成后：权限检测（提示条）+ 自动走一次提权重启流程。"""
        self._check_elevation_need()
        if not self._auto_elevate_enabled:
            return
        self._auto_elevate_if_needed()

    def _auto_elevate_if_needed(self) -> None:
        """非管理员时自动执行「以管理员身份重启」的询问流程。

        已是管理员时只记录日志与状态栏提示，不弹窗（避免每次启动都需确认）；
        配置为「不再询问」时不弹框，直接发起提权重启（UAC 取消则继续运行）。
        """
        if is_process_elevated():
            logger.info("当前已是管理员权限")
            self.statusBar().showMessage("当前已是管理员权限")
            return
        if not self._config.automation.ask_elevation_on_start:
            logger.info("已设置「不再询问」，直接以管理员身份重启")
            self._perform_elevated_restart()
            return
        logger.info("启动时未以管理员权限运行，询问是否提权重启")
        confirmed, dont_ask = self._ask_restart_confirmation(allow_dont_ask=True)
        if dont_ask:
            self._set_ask_elevation_on_start(False)
        if confirmed:
            self._perform_elevated_restart()
        else:
            self.statusBar().showMessage("已取消以管理员身份重启")

    def _set_ask_elevation_on_start(self, enabled: bool) -> None:
        """记录「不再询问」偏好并立即落盘（启动阶段尚无未保存改动）。"""
        self._config.automation.ask_elevation_on_start = enabled
        self.settings_page.set_config(self._config)
        store.save(self._config, self._config_path)
        logger.info("已更新「启动时自动询问提权」为 %s 并保存配置", enabled)

    def _relaunch_args(self) -> list[str]:
        return ["--config", str(self._config_path)]

    def _offer_elevated_restart(self) -> None:
        answer = QMessageBox.question(
            self,
            "需要管理员权限",
            "游戏以管理员权限运行，本工具权限不足，无法还原窗口/截图。\n是否立即以管理员身份重启本工具？",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._perform_elevated_restart()

    def _ask_restart_confirmation(self, allow_dont_ask: bool = False) -> tuple[bool, bool]:
        """弹确认框，返回 (是否重启, 是否勾选「不再询问」)。

        allow_dont_ask=True 时才显示「不再询问」勾选框（启动自动流程使用）。
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("以管理员身份重启")
        box.setText("将以管理员权限重新启动本工具（会弹出 UAC 确认），当前窗口会关闭。是否继续？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        dont_ask_box = None
        if allow_dont_ask:
            dont_ask_box = QCheckBox("不再询问（以后启动直接提权重启，可在设置页改回）")
            box.setCheckBox(dont_ask_box)
        answer = box.exec()
        return answer == QMessageBox.StandardButton.Yes, bool(dont_ask_box and dont_ask_box.isChecked())

    def _on_restart_admin_clicked(self) -> None:
        if is_process_elevated():
            QMessageBox.information(
                self,
                "已经是管理员权限",
                "本工具当前已以管理员权限运行，无需重启。",
            )
            self.statusBar().showMessage("当前已是管理员权限，无需重启")
            return
        confirmed, _ = self._ask_restart_confirmation()
        if confirmed:
            self._perform_elevated_restart()
        else:
            self.statusBar().showMessage("已取消以管理员身份重启")

    def _perform_elevated_restart(self) -> None:
        if restart_as_admin(self._relaunch_args()):
            self.statusBar().showMessage("正在以管理员身份重启…")
            self.close()
            QApplication.instance().quit()
        else:
            self.statusBar().showMessage("以管理员身份重启被取消或失败（详见日志）")
