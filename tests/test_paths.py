"""运行时路径工具测试（`utils/paths.py`）：三个图片目录的约定 + 入库/不入库守卫。

用户 2026-09-20 明确的目录分工：

| 目录 | 放什么 | 是否入库 |
|---|---|---|
| `assets/templates/` | 用户自己整理/命名的识别图片（调试页「添加图片…」默认打开它） | **入库**（人工整理的小素材） |
| `assets/screenshots/` | **识别底图** —— 用工具自带的截图功能截的画面（"先截一张图 → 再用这张图去识别"） | **不入库**（原始素材） |
| `assets/anchors/` | **框选产物** —— 开发者调试页「框选截图生成模板」落盘的 `anchor_<时间戳>.png` | **不入库**（原始素材） |

目录本身一律靠 `.gitkeep` 占位，保证克隆下来就有这三个文件夹。
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from luoluotool.utils.paths import (
    PROJECT_ROOT,
    get_anchors_dir,
    get_screenshots_dir,
    get_templates_dir,
)

TEMPLATES_DIR = PROJECT_ROOT / "assets" / "templates"
SCREENSHOTS_DIR = PROJECT_ROOT / "assets" / "screenshots"
ANCHORS_DIR = PROJECT_ROOT / "assets" / "anchors"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


def _git(*args: str) -> str:
    git = shutil.which("git")
    if git is None:
        pytest.skip("环境没有 git，跳过索引检查")
    result = subprocess.run(
        [git, *args], cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8"
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
