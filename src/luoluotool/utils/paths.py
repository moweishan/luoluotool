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


def get_anchors_dir() -> Path:
    """返回**框选产物**目录 assets/anchors（不存在则创建）。

    开发者调试页「框选截图生成模板」保存的文件（`anchor_<时间戳>.png`）落在这里。
    原始素材，已在 .gitignore 中排除（目录本身靠 `.gitkeep` 入库）。
    """
    return _ensure_dir(PROJECT_ROOT / "assets" / "anchors")


def get_screenshots_dir() -> Path:
    """返回**识别底图**目录 assets/screenshots（不存在则创建）。

    用户 2026-09-20 明确：这里放**用来当识别底图**的画面截图，来源是**工具自带的截图功能**
    （即"先截一张图 → 再用这张图去识别"里的那张图，用于页面信息太多、实时取景不好识别的场景）。
    原始素材，已在 .gitignore 中排除（目录本身靠 `.gitkeep` 入库）。
    """
    return _ensure_dir(PROJECT_ROOT / "assets" / "screenshots")


def get_templates_dir() -> Path:
    """返回识别图片目录 assets/templates（不存在则创建）。

    三个图片目录的分工（2026-09-20 用户要求）：
    - `assets/templates/`：**用户自己整理/命名的识别图片**（如 `鸡舍_白天.png`）——
      调试页「添加图片…」对话框默认打开这里；**按用户要求这些图片要入库**（人工整理、体积小）；
    - `assets/screenshots/`：**识别底图**（用工具自带截图功能截的画面），原始素材不入库；
    - `assets/anchors/`：**框选产物**（开发者调试页框选生成的 `anchor_<时间戳>.png`），原始素材不入库。

    目录本身靠 `.gitkeep` 入库；"模板必须入库、截图与框选产物必须不入库"的守卫见 `tests/test_paths.py`。
    """
    return _ensure_dir(PROJECT_ROOT / "assets" / "templates")
