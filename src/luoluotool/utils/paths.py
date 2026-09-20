"""运行时路径解析：user_data/ 与 logs/ 目录。"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 项目根目录（开发期锚点）：src/luoluotool/utils/paths.py 向上三级
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _ensure_dir(path: Path) -> Path:
    """尽力创建目录（评审 P3-7）：权限不足/只读盘时不冒原始 traceback。

    创建失败只写 WARNING 并把路径返回 —— 后续真正的写操作会给出更具体的错误，
    而目录已经存在时这里什么也不做。
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("无法创建目录 %s（%s）：后续写入可能失败，请检查权限/磁盘", path, exc)
    return path


def get_user_data_dir() -> Path:
    """返回 user_data 目录路径（不存在则创建）。"""
    return _ensure_dir(PROJECT_ROOT / "user_data")


def get_logs_dir() -> Path:
    """返回 logs 目录路径（不存在则创建）。"""
    return _ensure_dir(PROJECT_ROOT / "logs")


def get_icons_dir() -> Path:
    """返回 assets/icons 静态资源目录路径。"""
    return PROJECT_ROOT / "assets" / "icons"


def get_debug_dir() -> Path:
    """返回 user_data/debug 目录路径（不存在则创建）。"""
    return _ensure_dir(get_user_data_dir() / "debug")


def get_anchors_dir() -> Path:
    """返回图像识别模板（锚点截图）目录 assets/anchors（不存在则创建）。

    该目录已在 .gitignore 中排除 *.png：模板属于个人素材，不入库。
    """
    return _ensure_dir(PROJECT_ROOT / "assets" / "anchors")
