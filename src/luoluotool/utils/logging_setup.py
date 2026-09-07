"""日志初始化：控制台 + logs/ 滚动文件（固定 2MB × 3 份）。"""

import logging
from logging.handlers import RotatingFileHandler

from luoluotool.utils.paths import get_logs_dir

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_FILE_MAX_MB = 2
LOG_BACKUP_COUNT = 3


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化根日志器：控制台 + 滚动文件；重复调用不叠加 handler。"""
    root = logging.getLogger()
    if root.handlers:
        return root
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        get_logs_dir() / "luoluotool.log",
        maxBytes=LOG_FILE_MAX_MB * 1024 * 1024,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    return root
