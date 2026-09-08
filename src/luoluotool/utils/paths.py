"""运行时路径解析：user_data/ 与 logs/ 目录。"""

from pathlib import Path

# 项目根目录（开发期锚点）：src/luoluotool/utils/paths.py 向上三级
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def get_user_data_dir() -> Path:
    """返回 user_data 目录路径（不存在则创建）。"""
    path = PROJECT_ROOT / "user_data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_logs_dir() -> Path:
    """返回 logs 目录路径（不存在则创建）。"""
    path = PROJECT_ROOT / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_icons_dir() -> Path:
    """返回 assets/icons 静态资源目录路径。"""
    return PROJECT_ROOT / "assets" / "icons"
