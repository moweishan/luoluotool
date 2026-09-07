"""主窗口：五个空页签 + 状态栏版本号（Phase 0 骨架）。"""

from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget

from luoluotool import __version__

TAB_TITLES: tuple[str, ...] = ("日常任务", "卡订单", "功能三", "功能四", "设置")


class MainWindow(QMainWindow):
    """LuoLooTool 主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LuoLooTool")
        self.resize(960, 640)
        self.tabs: QTabWidget = QTabWidget(self)
        for title in TAB_TITLES:
            self.tabs.addTab(QWidget(self.tabs), title)
        self.setCentralWidget(self.tabs)
        self.statusBar().showMessage(f"版本 {__version__}")
