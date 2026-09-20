"""日志初始化：控制台 + logs/ 滚动文件（默认 2MB × 3 份，可由配置覆盖）。"""

import logging
from logging.handlers import RotatingFileHandler

from luoluotool.utils.paths import get_logs_dir

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_FILE_MAX_MB = 2
LOG_BACKUP_COUNT = 3


def setup_logging(
    level: int = logging.INFO,
    max_file_mb: int = LOG_FILE_MAX_MB,
    backup_count: int = LOG_BACKUP_COUNT,
) -> logging.Logger:
    """初始化根日志器：控制台 + 滚动文件（可重复调用；参数变化时重建文件 handler）。

    评审 P2-2：`config.logging.level/max_file_mb/backup_count` 以前被定义、被校验、被持久化，
    却对运行期零影响（永远用硬编码常量）。现在这三项真正生效：重复调用时按新参数重建
    滚动文件 handler（GUI 先按默认初始化以便记录加载期日志，读到配置后再按配置重建）。
    """
    root = logging.getLogger()
    root.setLevel(level)

    if not any(isinstance(handler, logging.StreamHandler) and not isinstance(
        handler, RotatingFileHandler) for handler in root.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(console_handler)

    file_handler = next(
        (handler for handler in root.handlers if isinstance(handler, RotatingFileHandler)), None
    )
    if (
        file_handler is not None
        and file_handler.maxBytes == max_file_mb * 1024 * 1024
        and file_handler.backupCount == backup_count
    ):
        return root
    if file_handler is not None:
        root.removeHandler(file_handler)
        file_handler.close()
    new_handler = RotatingFileHandler(
        get_logs_dir() / "luoluotool.log",
        maxBytes=max_file_mb * 1024 * 1024,
        backupCount=backup_count,
        encoding="utf-8",
    )
    new_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(new_handler)
    return root
