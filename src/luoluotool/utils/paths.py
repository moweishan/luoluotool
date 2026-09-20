"""运行时路径解析：user_data/ 与 logs/ 目录，以及 assets/ 下的图片目录。"""

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


def get_screenshots_dir() -> Path:
    """返回截图/框选产物目录 assets/screenshots（不存在则创建）。

    用户 2026-09-20 明确：这里放**用 LuoLuoTool 的截图与框选功能产出的图片** ——
    「框选截图生成模板」落盘的 `anchor_<时间戳>.png`，以及将来保存的整屏截图（离线识别底图）。
    原始截图属个人素材，已在 .gitignore 中排除（目录本身靠 `.gitkeep` 入库）。
    """
    return _ensure_dir(PROJECT_ROOT / "assets" / "screenshots")


def get_templates_dir() -> Path:
    """返回识别图片目录 assets/templates（不存在则创建）。

    与 `get_screenshots_dir()` 的分工（2026-09-20 用户要求）：
    - `assets/templates/`：**用户自己整理/命名的识别图片**（如 `鸡舍_白天.png`）——
      调试页「添加图片…」对话框默认打开这里；**按用户要求这些图片要入库**（人工整理、体积小）；
    - `assets/screenshots/`：**工具截图与框选产物**（原始素材，不入库）。

    目录本身靠 `.gitkeep` 入库；"模板必须入库、截图必须不入库"两条守卫见 `tests/test_paths.py`。
    """
    return _ensure_dir(PROJECT_ROOT / "assets" / "templates")
