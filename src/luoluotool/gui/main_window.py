"""主窗口：五页签配置界面 + 保存/重新加载/恢复默认 + 脏标记。"""

import logging
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QPushButton, QTabWidget, QVBoxLayout, QWidget

from luoluotool import __version__
from luoluotool.config import store
from luoluotool.config.models import AppConfig
from luoluotool.gui.pages.daily import DailyPage
from luoluotool.gui.pages.feature3 import Feature3Page
from luoluotool.gui.pages.feature4 import Feature4Page
from luoluotool.gui.pages.order_hold import OrderHoldPage
from luoluotool.gui.pages.settings import SettingsPage
from luoluotool.utils.paths import get_icons_dir

logger = logging.getLogger(__name__)

WINDOW_TITLE = "LuoLooTool"
TAB_TITLES: tuple[str, ...] = ("日常任务", "卡订单", "功能三", "功能四", "设置")
WINDOW_ICON_FILES = ("luoluoTool.png", "luoluoTool.ico")
_ICO_MAGIC = b"\x00\x00\x01\x00"
_PNG_MAGIC = b"\x89PNG"


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


class MainWindow(QMainWindow):
    """LuoLooTool 主窗口：仅展示与绑定，文件操作调用 config 模块。"""

    def __init__(self, config: AppConfig, config_path: Path) -> None:
        super().__init__()
        self._config = config
        self._config_path = config_path
        self._dirty = False
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
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.reload_button)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self.tabs)
        layout.addLayout(buttons)
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"版本 {__version__}")

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
