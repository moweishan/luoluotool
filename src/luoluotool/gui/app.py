"""GUI 入口：QApplication 创建与主窗口加载。"""

import logging
import os
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from luoluotool.gui.main_window import MainWindow
from luoluotool.utils import logging_setup

logger = logging.getLogger(__name__)


def run(argv: Sequence[str], *, smoke: bool = False) -> int:
    """创建 QApplication 与主窗口并进入事件循环。

    smoke=True 时强制离屏平台，窗口创建成功后立即退出（冒烟测试用）。
    返回退出码：0 成功。
    """
    if smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    logging_setup.setup_logging()
    app = QApplication.instance() or QApplication(list(argv))
    window = MainWindow()
    window.show()
    if smoke:
        app.processEvents()
        window.close()
        app.processEvents()
        logger.info("离屏冒烟完成：主窗口创建成功")
        return 0
    logger.info("GUI 启动（五页签空窗口）")
    return app.exec()
