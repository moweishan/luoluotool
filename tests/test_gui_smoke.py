"""GUI 离屏冒烟测试（QT_QPA_PLATFORM=offscreen）。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from luoluotool import __version__
from luoluotool.config.models import AppConfig
from luoluotool.gui.main_window import TAB_TITLES, WINDOW_TITLE, MainWindow

_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def window_factory(request):
    """创建主窗口并注册清理：即使断言失败也确定性销毁 C++ 对象，避免 GC 崩溃。"""
    created = []

    def make(path):
        window = MainWindow(AppConfig.default(), path, auto_elevate=False)
        created.append(window)
        return window

    def cleanup():
        for window in created:
            window.close()
            window.deleteLater()
        _APP.processEvents()

    request.addfinalizer(cleanup)
    return make


def test_main_window_has_five_tabs_and_version(window_factory, tmp_path) -> None:
    """主窗口：标题、尺寸、页签顺序（设置在第一）、默认选中设置页、状态栏版本号。"""
    window = window_factory(tmp_path / "config.json")
    assert window.windowTitle() == WINDOW_TITLE
    assert window.size().width() == 960
    assert window.size().height() == 640
    assert window.tabs.count() == 5
    titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert titles == ["设置", "日常任务", "卡订单", "功能三", "功能四"]
    assert list(TAB_TITLES) == titles
    assert window.tabs.currentIndex() == 0
    assert window.tabs.currentWidget() is window.settings_page
    assert __version__ in window.statusBar().currentMessage()


def test_main_window_has_window_icon(window_factory, tmp_path) -> None:
    """主窗口从 assets/icons 成功加载窗口图标。"""
    window = window_factory(tmp_path / "config.json")
    assert not window.windowIcon().isNull()


def test_window_icon_missing_degrades_gracefully(window_factory, tmp_path, monkeypatch) -> None:
    """图标目录为空时降级为空图标，窗口仍可创建。"""
    from luoluotool.gui import main_window as mw

    monkeypatch.setattr(mw, "get_icons_dir", lambda: tmp_path)
    window = window_factory(tmp_path / "config.json")
    assert window.windowIcon().isNull()


def test_fake_ico_file_is_skipped(window_factory, tmp_path, monkeypatch) -> None:
    """伪装成 .ico 的 PNG 文件被魔数校验拦截。"""
    from luoluotool.gui import main_window as mw

    (tmp_path / "luoluoTool.ico").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    monkeypatch.setattr(mw, "get_icons_dir", lambda: tmp_path)
    window = window_factory(tmp_path / "config.json")
    assert window.windowIcon().isNull()


def test_smoke_gui_cli_exits_zero() -> None:
    """--smoke-gui 离屏创建窗口成功后退出码 0。"""
    from luoluotool.__main__ import main

    assert main(["--smoke-gui"]) == 0


def test_application_icon_set_after_smoke() -> None:
    """--smoke-gui 启动后应用级图标已设置（任务栏图标来源）。"""
    from luoluotool.__main__ import main

    assert main(["--smoke-gui"]) == 0
    app = QApplication.instance()
    assert app is not None
    assert not app.windowIcon().isNull()
