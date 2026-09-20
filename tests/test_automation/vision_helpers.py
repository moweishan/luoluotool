"""automation.vision 测试共享的合成图像辅助。

文件名不以 `test_` 开头，pytest 不会把它当成测试模块收集；
只由同目录的测试文件显式导入。
"""

import numpy as np


def _haystack(height: int = 120, width: int = 200) -> np.ndarray:
    """造一张背景（带轻微纹理，避免全黑导致模板匹配退化）。"""
    canvas = np.full((height, width, 3), 40, dtype=np.uint8)
    canvas[::7, :] = 60
    canvas[:, ::11] = 55
    return canvas
