"""GUI 入口：QApplication 创建、配置加载与主窗口展示。"""

import ctypes
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import QApplication

from luoluotool.automation.window import is_process_elevated
from luoluotool.config import store
from luoluotool.gui.main_window import MainWindow, load_window_icon
from luoluotool.utils import logging_setup
from luoluotool.utils.paths import get_user_data_dir

logger = logging.getLogger(__name__)

APP_USER_MODEL_ID = "luoluotool"


def _apply_taskbar_identity() -> None:
    """Windows：声明独立 AppUserModelID，让任务栏按本应用身份渲染图标。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except OSError as exc:
        logger.warning("设置 AppUserModelID 失败：%s", exc)


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
    logger.info("进程以管理员权限运行：%s", is_process_elevated())
    _apply_taskbar_identity()
    app = QApplication.instance() or QApplication(list(argv))
    app.setWindowIcon(load_window_icon())
    path = Path(config_path) if config_path else get_user_data_dir() / "config.json"
    config = store.load(path)
    # 评审 P2-2：先把配置读出来，再让 logging 的三项配置真正生效（加载期日志仍按默认写入）
    logging_setup.setup_logging(
        level=logging.getLevelName(config.logging.level.upper()),
        max_file_mb=config.logging.max_file_mb,
        backup_count=config.logging.backup_count,
    )
    logger.info(
        "日志配置生效：level=%s max_file_mb=%d backup_count=%d",
        config.logging.level, config.logging.max_file_mb, config.logging.backup_count,
    )
    window = MainWindow(config, path, auto_elevate=not smoke)
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
