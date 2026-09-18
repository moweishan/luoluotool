"""配置页绑定测试（offscreen）：控件→配置写回、set_config 刷新、加载不触发脏标记。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from luoluotool.config.models import AppConfig
from luoluotool.gui.pages.daily import DailyPage
from luoluotool.gui.pages.feature3 import Feature3Page
from luoluotool.gui.pages.feature4 import Feature4Page
from luoluotool.gui.pages.order_hold import OrderHoldPage
from luoluotool.gui.pages.settings import SettingsPage

_APP = QApplication.instance() or QApplication([])


def test_daily_page_binds_fields_and_refreshes() -> None:
    config = AppConfig.default()
    changes: list[str] = []
    page = DailyPage(config, lambda: changes.append("dirty"))
    assert page.enabled_box.isChecked() is False
    page.enabled_box.setChecked(True)
    assert config.features.daily_tasks.enabled is True
    page.task_a_box.setChecked(True)
    assert config.features.daily_tasks.tasks["placeholder_task_a"].enabled is True
    page.loop_box.setChecked(True)
    page.interval_spin.setValue(600)
    assert config.features.daily_tasks.loop.enabled is True
    assert config.features.daily_tasks.loop.interval_seconds == 600
    assert changes == ["dirty"] * 4
    config2 = AppConfig.default()
    config2.features.daily_tasks.enabled = True
    config2.features.daily_tasks.loop.interval_seconds = 1234
    page.set_config(config2)
    assert page.enabled_box.isChecked() is True
    assert page.interval_spin.value() == 1234
    assert changes == ["dirty"] * 4  # 刷新控件不触发脏标记
    page.close()


def test_order_hold_page_binds_reserved_switches() -> None:
    config = AppConfig.default()
    page = OrderHoldPage(config, lambda: None)
    page.enabled_box.setChecked(True)
    page.reserved_box_1.setChecked(True)
    page.reserved_box_2.setChecked(True)
    assert config.features.order_hold.enabled is True
    assert config.features.order_hold.reserved_switch_1 is True
    assert config.features.order_hold.reserved_switch_2 is True
    config2 = AppConfig.default()
    config2.features.order_hold.reserved_switch_2 = True
    page.set_config(config2)
    assert page.reserved_box_2.isChecked() is True
    assert page.reserved_box_1.isChecked() is False
    page.close()


def test_feature_pages_bind_enabled() -> None:
    config = AppConfig.default()
    page3 = Feature3Page(config, lambda: None)
    page4 = Feature4Page(config, lambda: None)
    page3.enabled_box.setChecked(True)
    page4.enabled_box.setChecked(True)
    assert config.features.feature_3.enabled is True
    assert config.features.feature_4.enabled is True
    config2 = AppConfig.default()
    page3.set_config(config2)
    assert page3.enabled_box.isChecked() is False
    page3.close()
    page4.close()


def test_settings_page_binds_and_hotkey_readonly() -> None:
    config = AppConfig.default()
    page = SettingsPage(config, lambda: None)
    page.dry_run_box.setChecked(False)
    assert config.automation.dry_run is False
    page.click_interval_spin.setValue(4321)
    assert config.automation.click_interval_ms == 4321
    page.failures_spin.setValue(7)
    assert config.automation.max_consecutive_failures == 7
    assert "窗口诊断" in page.diagnose_button.text()
    assert "管理员" in page.restart_admin_button.text()
    page.close()


def test_settings_page_binds_hotkey_combo() -> None:
    """急停键改为可编辑下拉框：可选值有限、写回配置、刷新同步。"""
    config = AppConfig.default()
    page = SettingsPage(config, lambda: None)
    assert page.hotkey_combo.currentText() == "F8"
    assert "F9" in [page.hotkey_combo.itemText(i) for i in range(page.hotkey_combo.count())]
    page.hotkey_combo.setCurrentText("F9")
    assert config.automation.failsafe_hotkey == "F9"
    config2 = AppConfig.default()
    page.set_config(config2)
    assert page.hotkey_combo.currentText() == "F8"
    page.close()


def test_settings_page_binds_ask_elevation_switch() -> None:
    """设置页「启动时自动询问提权」绑定 automation.ask_elevation_on_start。"""
    config = AppConfig.default()
    page = SettingsPage(config, lambda: None)
    assert page.ask_elevation_box.isChecked() is True
    page.ask_elevation_box.setChecked(False)
    assert config.automation.ask_elevation_on_start is False
    config2 = AppConfig.default()
    page.set_config(config2)
    assert page.ask_elevation_box.isChecked() is True
    page.close()


def test_settings_page_binds_restore_cursor_switch() -> None:
    """设置页「每次点击后把真实鼠标移回原位置」绑定 automation.restore_cursor_after_click。"""
    config = AppConfig.default()
    page = SettingsPage(config, lambda: None)
    assert page.restore_cursor_box.isChecked() is True  # 默认还原
    page.restore_cursor_box.setChecked(False)
    assert config.automation.restore_cursor_after_click is False
    config2 = AppConfig.default()
    config2.automation.restore_cursor_after_click = False
    page.set_config(config2)
    assert page.restore_cursor_box.isChecked() is False
    page.close()
