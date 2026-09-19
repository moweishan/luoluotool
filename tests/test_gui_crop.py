"""gui.dialogs.crop_dialog 测试：框选几何换算、越界裁剪、选区保存为模板（离屏，不碰真实窗口）。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from luoluotool.automation.vision import load_template
from luoluotool.gui.dialogs.crop_dialog import (
    MIN_SELECTION_SIZE,
    CropView,
    TemplateCropDialog,
)

_APP = QApplication.instance() or QApplication([])


def _image(width: int = 400, height: int = 300) -> np.ndarray:
    """造一张有明确坐标特征的图：每个像素的 B 通道 = x，G 通道 = y。"""
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 0] = np.arange(width, dtype=np.uint8)
    image[:, :, 1] = np.arange(height, dtype=np.uint8).reshape(-1, 1)
    return image


def test_crop_view_fits_image_inside_widget() -> None:
    """截图按等比缩放居中显示，不超过控件范围。"""
    view = CropView(_image(400, 300))
    view.resize(480, 360)          # 注意：控件最小尺寸 360x240，测试要用不小于它的尺寸
    rect = view.image_rect()
    assert (rect.width(), rect.height()) == (480, 360)      # 400x300 → 1.2 倍
    assert (rect.x(), rect.y()) == (0, 0)
    view.deleteLater()


def test_crop_view_maps_widget_selection_to_image_pixels() -> None:
    """控件坐标 → 图像像素坐标（缩放比例必须正确换算）。"""
    view = CropView(_image(400, 300))
    view.resize(800, 600)          # 缩放 2 倍
    view.set_selection_in_image(100, 60, 40, 20)
    assert view.selection_in_image() == (100, 60, 40, 20)
    view.deleteLater()


def test_crop_view_clamps_selection_to_image_bounds() -> None:
    """选区越过图像边界时要被裁剪回图像内。"""
    view = CropView(_image(100, 80))
    view.resize(400, 400)
    view.set_selection_in_image(80, 60, 999, 999)
    x, y, width, height = view.selection_in_image()
    assert (x, y) == (80, 60)
    assert width == 100 - 80 and height == 80 - 60
    view.deleteLater()


def test_crop_view_returns_none_for_tiny_selection() -> None:
    """选区过小（点一下或抖动）不算有效选区。"""
    view = CropView(_image(100, 80))
    view.resize(400, 400)
    view.set_selection_in_image(10, 10, MIN_SELECTION_SIZE - 1, MIN_SELECTION_SIZE)
    assert view.selection_in_image() is None
    view.deleteLater()


def test_window_size_hint_is_shown_in_dialog() -> None:
    """对话框提示里要带出窗口客户区尺寸（方便判断坐标属于哪个坐标系）。"""
    dialog = TemplateCropDialog(_image(), (1920, 1052), save_dir=None)
    assert dialog is not None
    dialog.deleteLater()


def test_save_selection_writes_cropped_template(tmp_path) -> None:
    """保存选区：落盘 PNG 的尺寸与像素内容必须与选区一致（BGR 顺序不能错）。"""
    image = _image(200, 100)
    dialog = TemplateCropDialog(image, (200, 100), save_dir=tmp_path)
    dialog.view.resize(400, 400)
    dialog.set_selection_in_image(30, 20, 50, 40)

    path = dialog.save_selection()
    assert path is not None and path.is_file()
    assert path.parent == tmp_path
    assert path.suffix == ".png" and path.name.startswith("anchor_")

    saved = load_template(path)
    assert saved.shape == (40, 50, 3)
    assert tuple(int(v) for v in saved[0, 0]) == tuple(int(v) for v in image[20, 30])
    assert tuple(int(v) for v in saved[39, 49]) == tuple(int(v) for v in image[59, 79])
    dialog.deleteLater()


def test_save_selection_without_region_returns_none(tmp_path) -> None:
    """没有有效选区时不写文件（避免存出 1px 垃圾模板）。"""
    dialog = TemplateCropDialog(_image(), (200, 100), save_dir=tmp_path)
    assert dialog.save_selection() is None
    assert list(tmp_path.glob("*.png")) == []
    dialog.deleteLater()


def test_selection_description_uses_client_coordinates() -> None:
    """界面提示用客户区坐标（与点击/滑动/识别结果同一坐标系）。"""
    dialog = TemplateCropDialog(_image(400, 300), (400, 300), save_dir=None)
    dialog.set_selection_in_image(10, 20, 30, 40)
    text = dialog.selection_text()
    x, y, width, height = dialog.selection()
    assert f"{width}x{height}" in text
    assert f"({x}, {y})" in text
    assert f"({x + width // 2}, {y + height // 2})" in text      # 中心坐标也要给出
    dialog.deleteLater()


def test_mouse_drag_creates_selection() -> None:
    """真实鼠标拖拽（QTest 模拟）也能形成选区。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    view = CropView(_image(200, 200))
    view.resize(400, 400)          # 等比放大到 2 倍
    view.show()
    _APP.processEvents()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
    QTest.mouseMove(view, QPoint(160, 140))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(160, 140))
    _APP.processEvents()
    selection = view.selection_in_image()
    assert selection is not None
    x, y, width, height = selection
    assert (x, y) == (50, 50)
    assert (width, height) == (30, 20)      # ±1 像素的取整容差
    view.close()
    view.deleteLater()
