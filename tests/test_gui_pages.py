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
    page.click_interval_spin.setValue(4321)
    assert config.automation.click_interval_ms == 4321
    page.failures_spin.setValue(7)
    assert config.automation.max_consecutive_failures == 7
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


def test_daily_page_binds_keys_text() -> None:
    """日常任务页「按键序列」输入框：文本 ↔ params.keys 双向绑定，非法输入回退不写坏配置。"""
    from luoluotool.gui.pages.daily import DailyPage

    config = AppConfig.default()
    page = DailyPage(config, lambda: None)
    assert page.keys_edit.text() == ""  # 默认空

    page.keys_edit.setText("ctrl+s, w*800")
    page.keys_edit.editingFinished.emit()
    stored = config.features.daily_tasks.tasks["placeholder_task_a"].params["keys"]
    assert [(item["combo"], item["hold_ms"]) for item in stored] == [("ctrl+s", 0), ("w", 800)]

    # 非法文本：回退显示已保存的内容，配置不被破坏
    page.keys_edit.setText("ctrl+")
    page.keys_edit.editingFinished.emit()
    assert page.keys_edit.text() == "ctrl+s, w*800"
    assert len(config.features.daily_tasks.tasks["placeholder_task_a"].params["keys"]) == 2

    # set_config 会按配置刷新显示
    config2 = AppConfig.default()
    config2.features.daily_tasks.tasks["placeholder_task_a"].params = {
        "click_points": [], "keys": [{"combo": "enter"}], "wait_after_ms": 500,
    }
    page.set_config(config2)
    assert page.keys_edit.text() == "enter"
    page.close()


def test_daily_page_binds_swipes_text() -> None:
    """日常任务页「滑动序列」输入框：文本 ↔ params.swipes 双向绑定，非法输入回退。"""
    from luoluotool.gui.pages.daily import DailyPage

    config = AppConfig.default()
    page = DailyPage(config, lambda: None)
    assert page.swipes_edit.text() == ""

    page.swipes_edit.setText("100,200 > 400,600; 10,10 > 20,20*800")
    page.swipes_edit.editingFinished.emit()
    stored = config.features.daily_tasks.tasks["placeholder_task_a"].params["swipes"]
    assert [(item["from"], item["to"], item["duration_ms"]) for item in stored] == [
        ([100, 200], [400, 600], 400),
        ([10, 10], [20, 20], 800),
    ]

    # 非法文本：回退显示已保存内容，配置不被破坏
    page.swipes_edit.setText("100,200 >")
    page.swipes_edit.editingFinished.emit()
    assert page.swipes_edit.text() == "100,200 > 400,600; 10,10 > 20,20*800"
    assert len(config.features.daily_tasks.tasks["placeholder_task_a"].params["swipes"]) == 2

    config2 = AppConfig.default()
    config2.features.daily_tasks.tasks["placeholder_task_a"].params = {
        "click_points": [], "keys": [], "swipes": [{"from": [1, 1], "to": [2, 2]}],
        "wait_after_ms": 500,
    }
    page.set_config(config2)
    assert page.swipes_edit.text() == "1,1 > 2,2"
    page.close()


def test_settings_page_binds_developer_switch() -> None:
    """设置页「开发者调试」开关绑定 automation.developer_mode（默认关闭）。"""
    config = AppConfig.default()
    page = SettingsPage(config, lambda: None)
    assert page.developer_box.isChecked() is False
    page.developer_box.setChecked(True)
    assert config.automation.developer_mode is True
    config2 = AppConfig.default()
    config2.automation.developer_mode = True
    page.set_config(config2)
    assert page.developer_box.isChecked() is True
    page.close()


def test_debug_page_binds_dry_run_and_emits_test_requests() -> None:
    """调试页：开发者调试开启时，干跑开关绑定 dry_run；四个测试按钮发出带参数的请求信号。"""
    from luoluotool.gui.pages.debug import DebugPage

    config = AppConfig.default()
    config.automation.developer_mode = True      # 未开启调试时本页选项一律不生效（另有用例）
    page = DebugPage(config, lambda: None)
    requests: list[tuple] = []
    page.test_requested.connect(lambda kind, params: requests.append((kind, params)))

    # 干跑开关
    page.dry_run_box.setChecked(False)
    assert config.automation.dry_run is False
    page.dry_run_box.setChecked(True)
    assert config.automation.dry_run is True

    # 单点：X/Y
    page.single_x_spin.setValue(120)
    page.single_y_spin.setValue(80)
    page.single_button.click()
    # 连点：X/Y + 次数 + 间隔
    page.repeat_x_spin.setValue(10)
    page.repeat_y_spin.setValue(20)
    page.repeat_count_spin.setValue(3)
    page.repeat_interval_spin.setValue(400)
    page.repeat_button.click()
    # 滑动：起终点 + 用时
    page.swipe_from_x_spin.setValue(1)
    page.swipe_from_y_spin.setValue(2)
    page.swipe_to_x_spin.setValue(300)
    page.swipe_to_y_spin.setValue(400)
    page.swipe_duration_spin.setValue(700)
    page.swipe_button.click()
    # 键盘：按键 + 次数 + 间隔
    page.key_edit.setText("ctrl+s")
    page.key_count_spin.setValue(2)
    page.key_interval_spin.setValue(250)
    page.key_button.click()

    assert requests == [
        ("single_click", {"x": 120, "y": 80}),
        ("repeat_click", {"x": 10, "y": 20, "count": 3, "interval_ms": 400}),
        ("swipe", {"from_x": 1, "from_y": 2, "to_x": 300, "to_y": 400, "duration_ms": 700}),
        ("key", {"combo": "ctrl+s", "count": 2, "interval_ms": 250}),
    ]
    page.close()


def test_debug_page_options_are_inert_when_developer_mode_off() -> None:
    """开发者调试未开启：调试页所有选项都不生效（整页禁用 + 干跑开关不写配置）。"""
    from luoluotool.gui.pages.debug import DebugPage

    config = AppConfig.default()          # developer_mode 默认 false
    config.automation.dry_run = True
    page = DebugPage(config, lambda: None)
    assert page.isEnabled() is False      # 整页禁用（即使被程序化显示出来也点不动）

    page.dry_run_box.setChecked(False)    # 尝试改动干跑开关
    assert config.automation.dry_run is True        # 配置未被修改
    assert page.dry_run_box.isChecked() is True     # 勾选状态被回滚
    assert "不生效" in page.status_label.text()
    page.close()


def test_debug_page_options_are_active_when_developer_mode_on() -> None:
    """开发者调试开启：整页启用，选项正常生效。"""
    from luoluotool.gui.pages.debug import DebugPage

    config = AppConfig.default()
    config.automation.developer_mode = True
    page = DebugPage(config, lambda: None)
    assert page.isEnabled() is True
    page.dry_run_box.setChecked(False)
    assert config.automation.dry_run is False
    page.close()


def test_debug_page_vision_group_emits_image_and_threshold() -> None:
    """调试页「图片识别匹配测试」：图片路径 + 阈值随请求发出（开发者调试开启时生效）。"""
    from luoluotool.gui.pages.debug import DebugPage

    config = AppConfig.default()
    config.automation.developer_mode = True
    page = DebugPage(config, lambda: None)
    requests: list[tuple] = []
    page.test_requested.connect(lambda kind, params: requests.append((kind, params)))

    page.vision_path_edit.setText(r"D:\shots\按钮.png")
    page.vision_threshold_spin.setValue(0.91)
    page.vision_button.click()

    assert requests == [("vision", {"image": r"D:\shots\按钮.png", "threshold": 0.91})]
    assert round(page.vision_threshold_spin.minimum(), 2) == 0.30
    assert round(page.vision_threshold_spin.maximum(), 2) == 1.00
    assert "识别" in page.vision_button.text()          # 按钮文案即"图片识别匹配测试"
    page.close()


def test_debug_page_vision_group_is_visible_without_scrolling() -> None:
    """回归：图片识别匹配测试必须排在最前面（曾排在页尾，需要滚动才能看到）。"""
    from PySide6.QtWidgets import QGroupBox

    from luoluotool.gui.pages.debug import DebugPage

    config = AppConfig.default()
    config.automation.developer_mode = True
    page = DebugPage(config, lambda: None)
    page.resize(900, 500)
    page.show()
    _APP.processEvents()
    content = page.scroll_area.widget()
    groups = page.findChildren(QGroupBox)
    assert groups and "图片识别匹配" in groups[0].title(), (
        "图片识别匹配测试应是调试页第一个分组，实际：" + " / ".join(g.title() for g in groups)
    )
    top = groups[0].mapTo(content, groups[0].rect().topLeft()).y()
    assert top < page.scroll_area.viewport().height()   # 首屏可见
    page.close()


def test_debug_page_vision_button_respects_busy_state() -> None:
    """执行期间「识别图片 / 选择图片」按钮同样被禁用。"""
    from luoluotool.gui.pages.debug import DebugPage

    config = AppConfig.default()
    config.automation.developer_mode = True
    page = DebugPage(config, lambda: None)
    page.set_busy(True)
    assert page.vision_button.isEnabled() is False
    assert page.vision_browse_button.isEnabled() is False
    page.set_busy(False)
    assert page.vision_button.isEnabled() is True
    page.close()


def test_debug_page_crop_button_requests_capture() -> None:
    """调试页「框选截图生成模板」按钮：发出 crop_requested；忙碌时一并禁用。"""
    from luoluotool.gui.pages.debug import DebugPage

    config = AppConfig.default()
    config.automation.developer_mode = True
    page = DebugPage(config, lambda: None)
    fired: list[str] = []
    page.crop_requested.connect(lambda: fired.append("crop"))

    assert "框选" in page.crop_button.text()
    page.crop_button.click()
    assert fired == ["crop"]

    page.set_busy(True)
    assert page.crop_button.isEnabled() is False
    page.set_busy(False)
    assert page.crop_button.isEnabled() is True
    page.close()


def test_debug_page_busy_disables_buttons_and_status() -> None:
    """执行期间禁用全部测试按钮，并显示状态文案。"""
    from luoluotool.gui.pages.debug import DebugPage

    config = AppConfig.default()
    config.automation.developer_mode = True     # 未开启调试时整页禁用，与本用例无关
    page = DebugPage(config, lambda: None)
    page.set_busy(True)
    for button in (page.single_button, page.repeat_button, page.swipe_button,
                   page.key_button, page.diagnose_button):
        assert button.isEnabled() is False
    page.set_status("执行中…")
    assert page.status_label.text() == "执行中…"
    page.set_busy(False)
    assert page.single_button.isEnabled() is True
    page.close()
