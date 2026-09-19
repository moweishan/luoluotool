"""按键名 / 组合键解析（叶子层工具，config 与 automation 共用）。

放在 `utils` 是因为它必须同时被配置层（校验组合键文本、GUI 即时提示）和自动化层
（真正注入按键）使用，且不依赖任何 GUI/win32 代码。
"""

from __future__ import annotations

VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN = 0x10, 0x11, 0x12, 0x5B

MODIFIER_KEYS: dict[str, int] = {
    "ctrl": VK_CONTROL,
    "control": VK_CONTROL,
    "alt": VK_MENU,
    "shift": VK_SHIFT,
    "win": VK_LWIN,
    "super": VK_LWIN,
}

# 需要 EXTENDEDKEY 标志的键（否则部分游戏/程序识别不到）
EXTENDED_VKS = frozenset({
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,  # PgUp PgDn End Home ←↑→↓
    0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x90, 0xA3, 0xA5,  # Insert Delete Win Apps Ctrl(右) Alt(右)
    0x6F,  # 数字键盘 /
})

KEY_NAME_TO_VK: dict[str, int] = {
    **{chr(code).lower(): 0x41 + (code - 0x41) for code in range(0x41, 0x5B)},  # a-z（键名一律小写）
    **{str(digit): 0x30 + digit for digit in range(10)},               # 0-9
    **{f"f{index}": 0x6F + index for index in range(1, 25)},           # f1-f24
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "tab": 0x09, "space": 0x20, "backspace": 0x08, "back": 0x08,
    "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdn": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    "minus": 0xBD, "equals": 0xBB, "comma": 0xBC, "period": 0xBE, "slash": 0xBF,
    "semicolon": 0xBA, "quote": 0xDE, "grave": 0xC0,
    "bracketleft": 0xDB, "bracketright": 0xDD, "backslash": 0xDC,
    "ctrl": VK_CONTROL, "control": VK_CONTROL, "alt": VK_MENU, "shift": VK_SHIFT, "win": VK_LWIN,
    "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62, "numpad3": 0x63,
    "numpad4": 0x64, "numpad5": 0x65, "numpad6": 0x66, "numpad7": 0x67,
    "numpad8": 0x68, "numpad9": 0x69, "numpadmultiply": 0x6A, "numpadadd": 0x6B,
    "numpadsubtract": 0x6D, "numpaddecimal": 0x6E, "numpaddivide": 0x6F,
}


def parse_combo(text: str) -> tuple[tuple[int, ...], int]:
    """把 `"ctrl+shift+a"` 解析为 (修饰键 vk 元组, 主键 vk)。

    未知键名/空文本/重复修饰键都会抛 `ValueError`（消息可读，便于 GUI 即时提示与配置校验）。
    允许单独的修饰键（如 `"ctrl"`，此时修饰键元组为空、主键为 Ctrl）。
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("按键组合不能为空")
    parts = [part.strip() for part in raw.lower().split("+")]
    if any(not part for part in parts):
        raise ValueError(f"按键组合格式非法（存在空片段，应形如 ctrl+s）：{text!r}")
    modifiers: list[int] = []
    for part in parts[:-1]:
        vk = MODIFIER_KEYS.get(part)
        if vk is None:
            raise ValueError(f"未知修饰键 {part!r}（支持 ctrl/alt/shift/win）：{text!r}")
        if vk in modifiers:
            raise ValueError(f"修饰键重复：{part!r}（{text!r}）")
        modifiers.append(vk)
    main_vk = KEY_NAME_TO_VK.get(parts[-1])
    if main_vk is None:
        raise ValueError(f"未知按键名 {parts[-1]!r}：{text!r}")
    return tuple(modifiers), main_vk
