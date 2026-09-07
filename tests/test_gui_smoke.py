"""GUI 离屏冒烟测试（QT_QPA_PLATFORM=offscreen）。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from luoluotool import __version__
from luoluotool.gui.main_window import TAB_TITLES, MainWindow


def test_main_window_has_five_tabs_and_version() -> None:
    """主窗口：标题为 LuoLooTool，五个页签名正确，状态栏含版本号。"""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle() == "LuoLooTool"
    assert window.size().width() == 960
    assert window.size().height() == 640
    assert window.tabs.count() == 5
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == list(TAB_TITLES)
    assert __version__ in window.statusBar().currentMessage()
    window.close()
    app.processEvents()


def test_smoke_gui_cli_exits_zero() -> None:
    """--smoke-gui 离屏创建窗口成功后退出码 0。"""
    from luoluotool.__main__ import main

    assert main(["--smoke-gui"]) == 0
