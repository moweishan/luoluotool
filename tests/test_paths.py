"""运行时路径工具测试（`utils/paths.py`）：图像识别图片目录的约定 + 「个人素材不入库」守卫。

约定（2026-09-20 用户要求）：图像识别要用的图片统一放在 `assets/templates/`；
`assets/anchors/` 继续只放「框选截图生成模板」自动落盘的文件（命名 `anchor_<时间戳>.png`）。
两个目录里的图片都是个人素材，一律不入库 —— 目录本身靠 `.gitkeep` 占位。
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from luoluotool.utils.paths import PROJECT_ROOT, get_templates_dir

TEMPLATES_DIR = PROJECT_ROOT / "assets" / "templates"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


def test_templates_dir_is_assets_templates_and_is_created() -> None:
    """识别图片目录固定为 `assets/templates`，调用即保证存在（不存在则创建）。"""
    path = get_templates_dir()
    assert path == TEMPLATES_DIR
    assert path.is_dir()


def test_templates_dir_keeps_gitkeep() -> None:
    """目录本身要入库：靠 `.gitkeep` 占位，否则克隆下来没有这个文件夹。"""
    assert (TEMPLATES_DIR / ".gitkeep").is_file()


def test_recognition_images_are_gitignored() -> None:
    """两个图片目录下的常见图片格式都必须被 `.gitignore` 排除。"""
    text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "assets/anchors/*.png" in text
    for suffix in IMAGE_SUFFIXES:
        pattern = f"assets/templates/*{suffix}"
        assert pattern in text, f".gitignore 缺少图片忽略规则：{pattern}"


def test_no_recognition_image_is_tracked() -> None:
    """守卫：git 索引里不得出现识别图片（两个目录只允许 `.gitkeep`）。"""
    git = shutil.which("git")
    if git is None:
        pytest.skip("环境没有 git，跳过索引检查")
    result = subprocess.run(
        [git, "ls-files", "assets/templates", "assets/anchors"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"git ls-files 失败：{result.stderr}"
    tracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    offenders = [path for path in tracked if path.lower().endswith(IMAGE_SUFFIXES)]
    assert offenders == [], f"这些识别图片不应入库：{offenders}"
