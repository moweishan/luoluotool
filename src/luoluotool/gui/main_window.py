"""主窗口：五页签配置 + 保存/重载/恢复默认 + 启动/停止 + 日志面板 + F8 急停。"""

import logging
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from luoluotool import __version__
from luoluotool.automation.hotkey import HotkeyRegistrar
from luoluotool.config import store
from luoluotool.config.models import AppConfig
from luoluotool.core.runner import Runner
from luoluotool.gui.pages.daily import DailyPage
from luoluotool.gui.pages.feature3 import Feature3Page
from luoluotool.gui.pages.feature4 import Feature4Page
from luoluotool.gui.pages.order_hold import OrderHoldPage
from luoluotool.gui.pages.settings import SettingsPage
from luoluotool.gui.widgets import HotkeyEventFilter, LogPanelHandler
from luoluotool.utils.paths import get_icons_dir

logger = logging.getLogger(__name__)

WINDOW_TITLE = "LuoLooTool"
TAB_TITLES: tuple[str, ...] = ("日常任务", "卡订单", "功能三", "功能四", "设置")
WINDOW_ICON_FILES = ("luoluoTool.png", "luoluoTool.ico")
_ICO_MAGIC = b"\x00\x00\x01\x00"
_PNG_MAGIC = b"\x89PNG"
STATUS_RUNNING_DRY = "运行中 · 干跑"
THREAD_WAIT_TIMEOUT_MS = 2000
LOG_PANEL_MAX_BLOCKS = 1000


def _is_valid_icon_file(path: Path) -> bool:
    """按魔数校验图标格式（拦截伪装成 .ico 的 PNG 等）。"""
    try:
        with open(path, "rb") as fp:
            head = fp.read(4)
    except OSError:
        return False
    expected = _PNG_MAGIC if path.suffix == ".png" else _ICO_MAGIC
    return head == expected


def load_window_icon() -> QIcon:
    """从 assets/icons 加载窗口图标；文件缺失或格式非法时降级为空图标。"""
    icon = QIcon()
    icons_dir = get_icons_dir()
    for name in WINDOW_ICON_FILES:
        path = icons_dir / name
        if not path.is_file():
            continue
        if not _is_valid_icon_file(path):
            logger.warning("图标文件格式非法，已跳过：%s", path)
            continue
        icon.addFile(str(path))
    if icon.isNull():
        logger.warning("未找到可用的窗口图标：%s", icons_dir)
    return icon


def _default_runner_factory(config: AppConfig) -> Runner:
    return Runner(config)


class _RunnerThread(QThread):
    """在工作线程中执行 Runner.start()（阻塞主循环）。"""

    def __init__(self, runner: Runner, parent=None) -> None:
        super().__init__(parent)
        self._runner = runner

    def run(self) -> None:
        self._runner.start()


class MainWindow(QMainWindow):
    """LuoLooTool 主窗口：仅展示与绑定；文件/任务逻辑调用 config/core 模块。"""

    def __init__(
        self,
        config: AppConfig,
        config_path: Path,
        runner_factory: Callable[[AppConfig], Runner] | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._config_path = config_path
        self._runner_factory = runner_factory or _default_runner_factory
        self._runner: Runner | None = None
        self._thread: _RunnerThread | None = None
        self._dirty = False
        self._idle_status = f"版本 {__version__}"
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(960, 640)
        self.setWindowIcon(load_window_icon())
        self.tabs: QTabWidget = QTabWidget(self)
        pages = (
            DailyPage(self._config, self._mark_dirty),
            OrderHoldPage(self._config, self._mark_dirty),
            Feature3Page(self._config, self._mark_dirty),
            Feature4Page(self._config, self._mark_dirty),
            SettingsPage(self._config, self._mark_dirty),
        )
        (
            self.daily_page,
            self.order_hold_page,
            self.feature3_page,
            self.feature4_page,
            self.settings_page,
        ) = pages
        for page, title in zip(pages, TAB_TITLES):
            self.tabs.addTab(page, title)
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self._save)
        self.reload_button = QPushButton("重新加载")
        self.reload_button.clicked.connect(self._reload)
        self.reset_button = QPushButton("恢复默认")
        self.reset_button.clicked.connect(self._reset)
        self.start_button = QPushButton("启动")
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop)
        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setMaximumBlockCount(LOG_PANEL_MAX_BLOCKS)
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.reload_button)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self.tabs)
        layout.addLayout(buttons)
        layout.addWidget(self.log_panel)
        self.setCentralWidget(central)
        self.statusBar().showMessage(self._idle_status)
        self._log_handler = LogPanelHandler(self.log_panel)
        logging.getLogger().addHandler(self._log_handler)
        self._hotkey = HotkeyRegistrar()
        self._hotkey_filter = HotkeyEventFilter(self._hotkey.hotkey_id, self._on_failsafe)
        QApplication.instance().installNativeEventFilter(self._hotkey_filter)
        self._hotkey.register()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop()
        self._hotkey.unregister()
        QApplication.instance().removeNativeEventFilter(self._hotkey_filter)
        logging.getLogger().removeHandler(self._log_handler)
        super().closeEvent(event)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._refresh_title()

    def _refresh_title(self) -> None:
        self.setWindowTitle(f"{WINDOW_TITLE} *" if self._dirty else WINDOW_TITLE)

    def _save(self) -> None:
        store.save(self._config, self._config_path)
        self._dirty = False
        self._refresh_title()

    def _reload(self) -> None:
        self._config = store.load(self._config_path)
        self._apply_config()

    def _reset(self) -> None:
        self._config = AppConfig.default()
        self._apply_config()
        self._mark_dirty()

    def _apply_config(self) -> None:
        for page in (
            self.daily_page,
            self.order_hold_page,
            self.feature3_page,
            self.feature4_page,
            self.settings_page,
        ):
            page.set_config(self._config)
        self._dirty = False
        self._refresh_title()

    def _start(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self._runner = self._runner_factory(self._config)
        self._thread = _RunnerThread(self._runner, self)
        self._thread.finished.connect(self._on_runner_finished)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.statusBar().showMessage(STATUS_RUNNING_DRY)
        self._thread.start()

    def _stop(self) -> None:
        if self._runner is not None:
            self._runner.request_stop()
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(THREAD_WAIT_TIMEOUT_MS)

    def _on_runner_finished(self) -> None:
        self._thread = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.statusBar().showMessage(self._idle_status)

    def _on_failsafe(self) -> None:
        logger.info("急停触发（F8）")
        self._stop()
