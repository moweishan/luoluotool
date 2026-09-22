"""日常任务页的设计稿数据与命名契约（从 `daily.py` 拆出的叶子模块）。

为什么单开一个模块（2026-09-22）：这三个名字（`BUILDINGS` 与三个"字段名/控件名"助手）被
`daily.py`（页面）、`daily_images.py`（参考图显示 mixin）、`daily_media.py`（参考图控制器）
同时使用；留在 `daily.py` 里会让后两者反向依赖页面模块（循环 import）。
**纯搬运，一行未改**；`daily.py` 仍然再导出它们，旧导入路径不变。

硬契约（见 AGENTS「日常任务页」条款）：控件名＝设计稿的 `id`、配置字段名＝设计稿的 `data-key`，
**不许按前缀自己派生**（鸡舍那个文件框在设计稿里叫 `coop_island_ref_image`）。
"""

from __future__ import annotations


BUILDINGS: tuple[tuple[str, str, str, str, str], ...] = (
    ("鸡舍", "coop", "鸡舍", "coop_island_ref_image", "capture_game_screen"),
    ("土地", "land", "土地", "land_ref_image", "land_capture_screen"),
    ("水产养殖", "aqua", "水产养殖", "aqua_ref_image", "aqua_capture_screen"),
)


def building_title(prefix: str) -> str:
    """建筑前缀 → 中文名（做对话框标题、截图文件名时用）。"""
    for title, item_prefix, _word, _ref_id, _capture_id in BUILDINGS:
        if item_prefix == prefix:
            return title
    raise KeyError(f"未知的建筑前缀：{prefix}")


def island_field(prefix: str) -> str:
    """该建筑的岛屿编号在配置里的字段名（＝设计稿的 `data-key`）。"""
    return f"{prefix}_island"


def ref_image_field(prefix: str) -> str:
    """该建筑的参考图路径在配置里的字段名（＝设计稿的 `data-key`）。"""
    for _title, item_prefix, _word, ref_id, _capture_id in BUILDINGS:
        if item_prefix == prefix:
            return ref_id
    raise KeyError(f"未知的建筑前缀：{prefix}")
