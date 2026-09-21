"""运行时路径工具测试（`utils/paths.py`）：三个图片目录的约定 + 入库/不入库守卫。

用户 2026-09-20 明确的目录分工：

| 目录 | 放什么 | 是否入库 |
|---|---|---|
| `assets/templates/` | 用户自己整理/命名的识别图片（调试页「添加图片…」默认打开它） | **入库**（人工整理的小素材） |
| `assets/screenshots/` | **识别底图** —— 用工具自带的截图功能截的画面（"先截一张图 → 再用这张图去识别"） | **不入库**（原始素材） |
| `assets/anchors/` | **框选产物** —— 调试页 `anchor_<时间戳>.png`、日常任务页 `{建筑}_岛屿{N}_<时间戳>.png` | **不入库**（原始素材） |

目录本身一律靠 `.gitkeep` 占位，保证克隆下来就有这三个文件夹。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from luoluotool.utils.paths import (
    PROJECT_ROOT,
    get_anchors_dir,
    get_screenshots_dir,
    get_templates_dir,
    resolve_config_path,
    to_config_path,
)

TEMPLATES_DIR = PROJECT_ROOT / "assets" / "templates"
SCREENSHOTS_DIR = PROJECT_ROOT / "assets" / "screenshots"
ANCHORS_DIR = PROJECT_ROOT / "assets" / "anchors"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


def _git(*args: str) -> str:
    """跑一条 git 命令。

    **必须显式 `-c core.quotePath=false`**（评审 P2-5）：git 默认会把非 ASCII 路径转义成
    `"assets/templates/\\351\\270\\241..."` 这种八进制串，于是 `ls-files` 的输出里没有真文件名，
    入库守卫在本机"恰好"通过（全局配置是 false），换台机器就误报"图片还没入库"。
    """
    git = shutil.which("git")
    if git is None:
        pytest.skip("环境没有 git，跳过索引检查")
    result = subprocess.run(
        [git, "-c", "core.quotePath=false", *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, f"git {' '.join(args)} 失败：{result.stderr}"
    return result.stdout


def test_templates_dir_is_assets_templates_and_is_created() -> None:
    """识别图片目录固定为 `assets/templates`，调用即保证存在（不存在则创建）。"""
    path = get_templates_dir()
    assert path == TEMPLATES_DIR
    assert path.is_dir()


def test_screenshots_dir_is_assets_screenshots_and_is_created() -> None:
    """识别底图目录固定为 `assets/screenshots`（用工具自带截图功能截的画面）。"""
    path = get_screenshots_dir()
    assert path == SCREENSHOTS_DIR
    assert path.is_dir()


def test_anchors_dir_is_assets_anchors_and_is_created() -> None:
    """框选产物目录固定为 `assets/anchors`（调试页框选生成的 `anchor_<时间戳>.png`）。"""
    path = get_anchors_dir()
    assert path == ANCHORS_DIR
    assert path.is_dir()


def test_all_dirs_keep_gitkeep() -> None:
    """目录本身要入库：靠 `.gitkeep` 占位，否则克隆下来没有这三个文件夹。"""
    for directory in (TEMPLATES_DIR, SCREENSHOTS_DIR, ANCHORS_DIR):
        assert (directory / ".gitkeep").is_file(), f"{directory.name}/.gitkeep 缺失"


def test_raw_images_are_gitignored() -> None:
    """原始素材（识别底图 + 框选产物）都必须被 `.gitignore` 排除。"""
    text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "assets/anchors/*.png" in text
    for suffix in IMAGE_SUFFIXES:
        pattern = f"assets/screenshots/*{suffix}"
        assert pattern in text, f".gitignore 缺少图片忽略规则：{pattern}"


def test_raw_image_dirs_are_not_tracked() -> None:
    """守卫：git 索引里不得出现识别底图与框选产物（这两个目录只允许 `.gitkeep`）。"""
    for folder, path in (("assets/screenshots", SCREENSHOTS_DIR), ("assets/anchors", ANCHORS_DIR)):
        tracked = [line.strip() for line in _git("ls-files", folder).splitlines() if line.strip()]
        assert tracked == [f"{folder}/.gitkeep"], (
            f"{path.name}/ 不应入库其它文件（只允许 .gitkeep）：{tracked}"
        )


def test_template_images_are_tracked() -> None:
    """守卫（用户 2026-09-20 要求）：`assets/templates/` 里的识别图片**必须入库**。

    这条与上面的原始素材守卫方向相反 —— 模板是人工整理的小素材，要跟着仓库走；
    往这里放图片后如果没有 `git add`，这个测试会红。
    """
    images = sorted(
        p for p in TEMPLATES_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )
    tracked = {
        line.strip() for line in _git("ls-files", "assets/templates").splitlines() if line.strip()
    }
    untracked = [
        p.relative_to(PROJECT_ROOT).as_posix() for p in images
        if p.relative_to(PROJECT_ROOT).as_posix() not in tracked
    ]
    assert untracked == [], f"这些识别图片还没入库（请 git add）：{untracked}"


def test_template_image_suffix_is_not_ignored() -> None:
    """`assets/templates/` 下不得有任何图片忽略规则（否则上面的入库守卫永远看不到文件）。"""
    text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    for suffix in IMAGE_SUFFIXES:
        pattern = f"assets/templates/*{suffix}"
        assert pattern not in text, f".gitignore 不应忽略模板目录的图片：{pattern}"


# ---------------------------------------------------------------- 配置里的图片路径
# 日常任务页把"选好的参考图"记进配置（用户 2026-09-22）：仓库内的用**相对仓库根**的 POSIX
# 路径（换盘符/换目录仍可读），仓库外的退化成绝对路径；读的时候两种都认。


def test_config_path_is_relative_inside_the_repo_and_absolute_outside(tmp_path) -> None:
    inside = TEMPLATES_DIR / "鸡舍_岛屿1.png"
    assert to_config_path(inside) == "assets/templates/鸡舍_岛屿1.png"

    outside = tmp_path / "外面的图.png"
    assert to_config_path(outside) == outside.resolve().as_posix()
    assert Path(to_config_path(outside)).is_absolute()


def test_resolve_config_path_accepts_both_forms_and_empty(tmp_path) -> None:
    assert resolve_config_path("") is None
    assert resolve_config_path(None) is None
    assert resolve_config_path("   ") is None
    assert resolve_config_path("assets/templates/鸡舍_岛屿1.png") == (
        PROJECT_ROOT / "assets" / "templates" / "鸡舍_岛屿1.png"
    )
    absolute = tmp_path / "某处.png"
    assert resolve_config_path(absolute.as_posix()) == absolute.resolve()


def test_resolve_config_path_normalizes_dots() -> None:
    """第五轮评审 P3-2：含 `.` / `..` 的路径先归一化再返回（同一个文件得到同一个路径）。

    **这不是安全边界**：仓库外的绝对路径本来就允许（设计如此，`to_config_path` 保留绝对路径）；
    这里只统一"表示形式"，方便比较与当缓存键。
    """
    expected = PROJECT_ROOT / "assets" / "templates" / "x.png"
    assert resolve_config_path("assets/../assets/templates/x.png") == expected
    assert resolve_config_path("./assets/templates/x.png") == expected

    escaped = resolve_config_path("../../外面.png")
    assert escaped is not None and not escaped.is_relative_to(PROJECT_ROOT)


def test_config_path_round_trips() -> None:
    """写进配置再读回来必须还是同一张图（两个函数互为逆运算）。"""
    original = ANCHORS_DIR / "鸡舍_岛屿7_20260922_0100.png"
    assert resolve_config_path(to_config_path(original)) == original.resolve()
