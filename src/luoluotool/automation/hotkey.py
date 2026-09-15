"""全局急停热键：RegisterHotKey 薄封装（支持配置热键，无 PySide6 依赖）。"""

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

VK_F8 = 0x77
MOD_NOREPEAT = 0x4000
DEFAULT_HOTKEY_ID = 0xF8
DEFAULT_HOTKEY_NAME = "F8"
WM_HOTKEY = 0x0312

# 支持的急停热键（名称 → 虚拟键码）
VK_BY_NAME: dict[str, int] = {
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}


def resolve_vk(name: str) -> int | None:
    """把配置中的热键名解析为虚拟键码；不支持的名称返回 None。"""
    return VK_BY_NAME.get(name.strip().upper())


def supported_hotkeys() -> list[str]:
    """返回支持的热键名（排序）。"""
    return sorted(VK_BY_NAME)


class HotkeyRegistrar:
    """注册/注销全局热键；失败路径可观测（日志），不影响主流程。"""

    def __init__(
        self,
        hotkey_id: int = DEFAULT_HOTKEY_ID,
        vk: int = VK_F8,
        modifiers: int = MOD_NOREPEAT,
        name: str = DEFAULT_HOTKEY_NAME,
    ) -> None:
        self.hotkey_id = hotkey_id
        self.vk = vk
        self.modifiers = modifiers
        self.name = name
        self._registered = False

    def register(self, hwnd: int = 0) -> bool:
        """注册全局热键；重复注册或非 Windows 平台安全返回。"""
        if sys.platform != "win32":
            logger.warning("非 Windows 平台，跳过全局热键注册")
            return False
        if self._registered:
            return True
        ok = bool(ctypes.windll.user32.RegisterHotKey(hwnd, self.hotkey_id, self.modifiers, self.vk))
        if not ok:
            logger.error("注册全局急停热键 %s 失败（可能被其他程序占用）", self.name)
            return False
        self._registered = True
        logger.info("已注册全局急停热键：%s", self.name)
        return True

    def unregister(self, hwnd: int = 0) -> None:
        """注销全局热键（幂等）。"""
        if not self._registered:
            return
        ctypes.windll.user32.UnregisterHotKey(hwnd, self.hotkey_id)
        self._registered = False
        logger.info("已注销全局急停热键：%s", self.name)
