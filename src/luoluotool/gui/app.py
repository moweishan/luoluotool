"""GUI 入口：QApplication 创建、配置加载与主窗口展示。"""

import logging
import os
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import QApplication

from luoluotool.config import store
from luoluotool.gui.main_window import MainWindow
from luoluotool.utils import logging_setup
from luoluotool.utils.paths import get_user_data_dir

logger = logging.getLogger(__name__)


def run(
    argv: Sequence[str],
    *,
    smoke: bool = False,
    config_path: Path | None = None,
) -> int:
    """创建 QApplication 与主窗口并进入事件循环。

    smoke=True 时强制离屏平台，窗口创建成功后立即退出（冒烟测试用）。
    config_path 缺省时使用 user_data/config.json。返回退出码：0 成功。
    """
    if smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    logging_setup.setup_logging()
    app = QApplication.instance() or QApplication(list(argv))
    path = Path(config_path) if config_path else get_user_data_dir() / "config.json"
    config = store.load(path)
    window = MainWindow(config, path)
    window.show()
    if smoke:
        app.processEvents()
        window.close()
        window.deleteLater()
        app.processEvents()
        logger.info("离屏冒烟完成：主窗口创建成功")
        return 0
    logger.info("GUI 启动（五页签配置窗口）")
    return app.exec()
