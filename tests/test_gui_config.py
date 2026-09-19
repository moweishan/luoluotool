"""主窗口配置集成测试（offscreen）：脏标记、保存/重载/恢复默认、重启持久化。"""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from luoluotool.config import store
from luoluotool.config.models import AppConfig
from luoluotool.gui.main_window import WINDOW_TITLE, MainWindow

_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def window_factory(request):
    """创建主窗口并注册清理：即使断言失败也确定性销毁 C++ 对象，避免 GC 崩溃。"""
    created = []

    def make(path, config=None):
        window = MainWindow(
            config if config is not None else AppConfig.default(), path, auto_elevate=False
        )
        created.append(window)
        return window

    def cleanup():
        for window in created:
            window.close()
            window.deleteLater()
        _APP.processEvents()

    request.addfinalizer(cleanup)
    return make


def test_toggle_marks_dirty_and_writes_back(window_factory, tmp_path) -> None:
    window = window_factory(tmp_path / "config.json")
    assert window.windowTitle() == WINDOW_TITLE
    window.daily_page.task_a_box.setChecked(True)
    assert window._config.features.daily_tasks.tasks["placeholder_task_a"].enabled is True
    assert window.windowTitle() == f"{WINDOW_TITLE} *"


def test_save_clears_dirty_and_persists(window_factory, tmp_path) -> None:
    window = window_factory(tmp_path / "config.json")
    window.settings_page.click_interval_spin.setValue(4321)
    assert window.windowTitle() == f"{WINDOW_TITLE} *"
    window._save()
    assert window.windowTitle() == WINDOW_TITLE
    data = json.loads(window._config_path.read_text(encoding="utf-8"))
    assert data["automation"]["click_interval_ms"] == 4321


def test_reload_restores_file_values(window_factory, tmp_path) -> None:
    window = window_factory(tmp_path / "config.json")
    window.order_hold_page.reserved_box_1.setChecked(True)
    window._save()
    window.order_hold_page.reserved_box_1.setChecked(False)
    assert window.windowTitle() == f"{WINDOW_TITLE} *"
    window._reload()
    assert window._config.features.order_hold.reserved_switch_1 is True
    assert window.order_hold_page.reserved_box_1.isChecked() is True
    assert window.windowTitle() == WINDOW_TITLE


@pytest.mark.real_defaults
def test_reset_restores_defaults_and_marks_dirty(window_factory, tmp_path) -> None:
    window = window_factory(tmp_path / "config.json")
    window.settings_page.developer_box.setChecked(True)   # 调试页选项需调试开关开启才生效
    window.debug_page.dry_run_box.setChecked(True)
    window._save()
    assert window._config.automation.dry_run is True
    window._reset()
    assert window._config.automation.dry_run is False      # 出厂默认：干跑不开启
    assert window.debug_page.dry_run_box.isChecked() is False
    assert window.windowTitle() == f"{WINDOW_TITLE} *"


def test_switches_persist_after_restart(window_factory, tmp_path) -> None:
    window = window_factory(tmp_path / "config.json")
    window.order_hold_page.reserved_box_1.setChecked(True)
    window.order_hold_page.reserved_box_2.setChecked(True)
    window.feature3_page.enabled_box.setChecked(True)
    window.feature4_page.enabled_box.setChecked(True)
    window._save()
    reloaded = window_factory(tmp_path / "config.json", store.load(tmp_path / "config.json"))
    assert reloaded.order_hold_page.reserved_box_1.isChecked() is True
    assert reloaded.order_hold_page.reserved_box_2.isChecked() is True
    assert reloaded.feature3_page.enabled_box.isChecked() is True
    assert reloaded.feature4_page.enabled_box.isChecked() is True


def test_widgets_reflect_config_file_values(window_factory, tmp_path) -> None:
    config = AppConfig.default()
    config.features.order_hold.reserved_switch_2 = True
    config.automation.click_interval_ms = 2000
    store.save(config, tmp_path / "config.json")
    window = window_factory(tmp_path / "config.json", store.load(tmp_path / "config.json"))
    assert window.order_hold_page.reserved_box_2.isChecked() is True
    assert window.settings_page.click_interval_spin.value() == 2000
