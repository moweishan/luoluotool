"""窗口图标加载：从 assets 里挑可用图标（.ico 优先），校验文件头避免空壳图。

分层：gui 层。只读 `assets/`，不做任何业务逻辑。

拆分说明（2026-09-20）：本模块由 `gui/main_window.py` 原样搬出（行为零变化），
`main_window` 仍导入 `load_window_icon` 使用，`gui.app` 的导入路径不变。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QIcon

from luoluotool.utils.paths import get_icons_dir

logger = logging.getLogger(__name__)

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
