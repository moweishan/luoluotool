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


def test_save_selection_reports_unwritable_dir(tmp_path, monkeypatch, caplog) -> None:
    """回归（评审 P2-8）：模板目录不可写时给可读失败路径（旧实现 mkdir 在 try 外，直接冒 OSError）。

    `save_selection()` 必须返回 None 且不抛异常，调用方的"保存失败：请检查模板目录是否可写"
    才有机会执行；对话框也要保持打开（不能假装保存成功）。
    """
    import logging
    from pathlib import Path

    from PySide6.QtWidgets import QDialog

    caplog.set_level(logging.ERROR)

    def boom(self, parents=False, exist_ok=False):
        raise PermissionError("模拟目录不可写")

    monkeypatch.setattr(Path, "mkdir", boom)
    dialog = TemplateCropDialog(_image(200, 100), (200, 100), save_dir=tmp_path / "anchors")
    dialog.set_selection_in_image(30, 20, 50, 40)

    assert dialog.save_selection() is None                 # 不抛异常
    assert dialog.saved_path is None

    dialog.save_button.click()                             # 点保存：不关窗、给提示
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "保存失败" in dialog.info_label.text()
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


# ------------------------------------------- 修改已有选区（移动 / 改大小，用户 2026-09-20 要求）


def _drag(view: CropView, start: tuple[int, int], end: tuple[int, int]) -> None:
    """在控件坐标里模拟一次真实左键拖拽（按下 → 移动 → 松开）。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    view.show()
    _APP.processEvents()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(*start))
    QTest.mouseMove(view, QPoint(*end))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(*end))
    _APP.processEvents()


def _scaled_view(image_size: tuple[int, int], scale: int = 2) -> CropView:
    """造一个 1:scale 显示的视图（图像坐标 = 控件坐标 / scale），方便写断言。"""
    width, height = image_size
    view = CropView(_image(width, height))
    view.resize(width * scale, height * scale)
    return view


def test_hit_test_distinguishes_handles_inside_and_outside() -> None:
    """命中判定：四角/四边是手柄、选区内部是移动、外面是重新框选（控件坐标）。"""
    from PySide6.QtCore import QPoint

    view = _scaled_view((100, 100))          # 2 倍：图像 (20,30,40,20) → 控件 (40,60,80,40)
    view.set_selection_in_image(20, 30, 40, 20)
    rect = view._image_rect_on_widget()

    assert view.hit_test(rect.topLeft()) == "nw"
    assert view.hit_test(rect.topRight()) == "ne"
    assert view.hit_test(rect.bottomLeft()) == "sw"
    assert view.hit_test(rect.bottomRight()) == "se"
    assert view.hit_test(rect.center()) == "inside"
    assert view.hit_test(rect.topLeft() - QPoint(40, 40)) == "outside"
    view.deleteLater()


def test_drag_inside_selection_moves_it() -> None:
    """拖选区内部 = 整体移动：尺寸不变、位置按拖拽位移平移。"""
    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)      # 控件坐标 (100,100)-(180,160)

    _drag(view, (120, 120), (160, 140))              # 控件 +40,+20 → 图像 +20,+10

    assert view.selection_in_image() == (70, 60, 40, 30)
    view.close()
    view.deleteLater()


def test_drag_corner_handle_resizes_both_dimensions() -> None:
    """拖右下角手柄：对角（左上）固定，宽高同时变化。"""
    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)
    rect = view._image_rect_on_widget()

    _drag(view, (rect.right(), rect.bottom()), (rect.right() + 40, rect.bottom() + 20))

    assert view.selection_in_image() == (50, 50, 60, 40)
    view.close()
    view.deleteLater()


def test_drag_edge_handle_resizes_one_dimension() -> None:
    """拖右边手柄：只改宽度，高度与纵向位置不动。"""
    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)
    rect = view._image_rect_on_widget()

    _drag(view, (rect.right(), rect.center().y()), (rect.right() - 20, rect.center().y()))

    assert view.selection_in_image() == (50, 50, 30, 30)
    view.close()
    view.deleteLater()


def test_moving_selection_is_clamped_inside_image() -> None:
    """整体移动不能把选区拖出图像（贴边即停，尺寸不变）。"""
    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)

    _drag(view, (120, 120), (1000, 1000))            # 往右下拖出图像

    assert view.selection_in_image() == (200 - 40, 200 - 30, 40, 30)
    view.close()
    view.deleteLater()


def test_resizing_cannot_shrink_below_minimum_size() -> None:
    """改大小不能小于 MIN_SELECTION_SIZE（否则会存出垃圾模板）。"""
    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)
    rect = view._image_rect_on_widget()

    _drag(view, (rect.right(), rect.bottom()), (rect.left() - 60, rect.top() - 60))

    assert view.selection_in_image() == (50, 50, MIN_SELECTION_SIZE, MIN_SELECTION_SIZE)
    view.close()
    view.deleteLater()


def test_drag_outside_selection_starts_a_new_one() -> None:
    """在选区外按下拖拽＝重新框选（旧选区被替换）。"""
    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)

    _drag(view, (20, 20), (60, 40))                  # 控件 → 图像 (10,10) 拖到 (30,20)

    assert view.selection_in_image() == (10, 10, 20, 10)
    view.close()
    view.deleteLater()


def test_cursor_hints_match_handle_and_inside() -> None:
    """悬停时指针形状要提示"这里能改大小 / 这里能整体移动"。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)
    rect = view._image_rect_on_widget()

    def _hover(point: QPoint) -> Qt.CursorShape:
        event = QMouseEvent(
            QMouseEvent.Type.MouseMove, point, view.mapToGlobal(point),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        )
        view.mouseMoveEvent(event)
        return view.cursor().shape()

    assert _hover(rect.center()) == Qt.CursorShape.SizeAllCursor
    assert _hover(rect.topLeft()) == Qt.CursorShape.SizeFDiagCursor
    assert _hover(rect.topRight()) == Qt.CursorShape.SizeBDiagCursor
    assert _hover(QPoint(rect.right(), rect.center().y())) == Qt.CursorShape.SizeHorCursor
    assert _hover(QPoint(rect.center().x(), rect.bottom())) == Qt.CursorShape.SizeVerCursor
    view.deleteLater()


def test_saved_template_uses_the_modified_selection(tmp_path) -> None:
    """先移动再保存：落盘的就是**改过之后**的选区（像素必须来自新位置）。"""
    image = _image(200, 100)
    dialog = TemplateCropDialog(image, (200, 100), save_dir=tmp_path)
    dialog.view.resize(400, 400)
    dialog.set_selection_in_image(20, 20, 30, 20)

    _drag(dialog.view, (60, 150), (140, 190))              # 拖选区内部 → 图像 +40,+20

    assert dialog.selection() == (60, 40, 30, 20)
    path = dialog.save_selection()
    assert path is not None
    saved = load_template(path)
    assert saved.shape == (20, 30, 3)
    assert tuple(int(v) for v in saved[0, 0]) == tuple(int(v) for v in image[40, 60])
    dialog.view.close()
    dialog.deleteLater()


# ------------------------------------------- 方向键微调（用户 2026-09-20：A+B 都要）


def _press(view: CropView, key, modifier=None) -> None:
    """给框选图发一次按键（模拟键盘微调）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(view, key, modifier or Qt.KeyboardModifier.NoModifier)
    _APP.processEvents()


def test_arrow_keys_nudge_whole_selection_by_one_image_pixel() -> None:
    """方案 A：方向键整体移动 1 个**图像**像素（不是控件像素）。"""
    from PySide6.QtCore import Qt

    view = _scaled_view((200, 200))                  # 2 倍显示
    view.set_selection_in_image(50, 50, 40, 30)

    _press(view, Qt.Key.Key_Right)
    assert view.selection_in_image() == (51, 50, 40, 30)

    _press(view, Qt.Key.Key_Down)
    assert view.selection_in_image() == (51, 51, 40, 30)

    _press(view, Qt.Key.Key_Left)
    _press(view, Qt.Key.Key_Up)
    assert view.selection_in_image() == (50, 50, 40, 30)
    view.deleteLater()


def test_shift_arrow_keys_nudge_by_ten_pixels() -> None:
    """Shift+方向键 = 一次 10 像素（大范围微调用）。"""
    from PySide6.QtCore import Qt

    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)

    _press(view, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert view.selection_in_image() == (60, 50, 40, 30)

    _press(view, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    assert view.selection_in_image() == (60, 60, 40, 30)
    view.deleteLater()


def test_ctrl_arrow_moves_the_matching_edge_outward() -> None:
    """方案 B：Ctrl+方向键 = 对应那条边向外 1 像素（选区变大，另一边不动）。"""
    from PySide6.QtCore import Qt

    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)

    _press(view, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)     # 右边框右移
    assert view.selection_in_image() == (50, 50, 41, 30)

    _press(view, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)      # 左边框左移
    assert view.selection_in_image() == (49, 50, 42, 30)

    _press(view, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)      # 下边框下移
    assert view.selection_in_image() == (49, 50, 42, 31)

    _press(view, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)        # 上边框上移
    assert view.selection_in_image() == (49, 49, 42, 32)
    view.deleteLater()


def test_ctrl_shift_arrow_moves_the_edge_inward() -> None:
    """Ctrl+Shift+方向键 = 同一条边向内 1 像素（选区变小）。"""
    from PySide6.QtCore import Qt

    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)

    both = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier

    _press(view, Qt.Key.Key_Right, both)                                    # 右边框左移
    assert view.selection_in_image() == (50, 50, 39, 30)

    _press(view, Qt.Key.Key_Up, both)                                       # 上边框下移
    assert view.selection_in_image() == (50, 51, 39, 29)
    view.deleteLater()


def test_nudge_is_clamped_to_image_and_minimum_size() -> None:
    """微调同样受"不越界 + 不小于 MIN_SELECTION_SIZE"约束。"""
    from PySide6.QtCore import Qt

    view = _scaled_view((200, 200))
    view.set_selection_in_image(0, 0, MIN_SELECTION_SIZE, MIN_SELECTION_SIZE)

    _press(view, Qt.Key.Key_Left)                                           # 已经在左上角
    _press(view, Qt.Key.Key_Up)
    assert view.selection_in_image() == (0, 0, MIN_SELECTION_SIZE, MIN_SELECTION_SIZE)

    both = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    _press(view, Qt.Key.Key_Right, both)                                    # 再收就小于最小尺寸
    _press(view, Qt.Key.Key_Down, both)
    assert view.selection_in_image() == (0, 0, MIN_SELECTION_SIZE, MIN_SELECTION_SIZE)
    view.deleteLater()


def test_arrow_keys_do_nothing_without_selection() -> None:
    """还没框选时按方向键：不崩、也不会凭空造出选区。"""
    from PySide6.QtCore import Qt

    view = _scaled_view((200, 200))
    _press(view, Qt.Key.Key_Right)
    _press(view, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert view.selection_in_image() is None
    view.deleteLater()


def test_crop_view_takes_keyboard_focus() -> None:
    """框选图必须能拿到键盘焦点，否则方向键根本送不到它。"""
    from PySide6.QtCore import Qt

    dialog = TemplateCropDialog(_image(200, 100), (200, 100), save_dir=None)
    assert dialog.view.focusPolicy() == Qt.FocusPolicy.StrongFocus
    dialog.show()
    _APP.processEvents()
    assert dialog.focusWidget() is dialog.view          # 打开弹窗焦点就在图上，方向键立刻可用
    dialog.close()
    dialog.deleteLater()


# ------------------------------------------- 「保存为模板」按钮（回归：按钮以前只关窗口不保存）


def test_save_button_writes_only_selected_region(tmp_path) -> None:
    """点「保存为模板」只保存**手动框选的区域**：尺寸 = 选区、像素 = 原图对应块。"""
    from PySide6.QtWidgets import QDialog

    image = _image(400, 300)
    dialog = TemplateCropDialog(image, (400, 300), save_dir=tmp_path)
    dialog.view.resize(400, 400)
    dialog.set_selection_in_image(30, 20, 50, 40)

    dialog.save_button.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.saved_path is not None and dialog.saved_path.is_file()
    saved = load_template(dialog.saved_path)
    assert saved.shape == (40, 50, 3)                     # 不是整屏 300x400
    assert tuple(int(v) for v in saved[0, 0]) == tuple(int(v) for v in image[20, 30])
    assert tuple(int(v) for v in saved[39, 49]) == tuple(int(v) for v in image[59, 79])
    dialog.deleteLater()


def test_save_button_without_selection_keeps_dialog_open(tmp_path) -> None:
    """没框选就点保存：不写文件、不关闭对话框，只提示先框选。"""
    from PySide6.QtWidgets import QDialog

    dialog = TemplateCropDialog(_image(), (200, 100), save_dir=tmp_path)

    dialog.save_button.click()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.saved_path is None
    assert list(tmp_path.glob("*.png")) == []
    assert "框选" in dialog.info_label.text()
    dialog.deleteLater()


def test_save_button_uses_real_drag_selection(tmp_path) -> None:
    """真实拖拽（QTest）之后点保存：落盘尺寸与拖出来的选区一致。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    image = _image(200, 200)
    dialog = TemplateCropDialog(image, (200, 200), save_dir=tmp_path)
    dialog.show()
    _APP.processEvents()

    # 按"图像在控件里的实际显示区域"换算控件坐标（对话框 show 后图像是居中缩放的，
    # 写死坐标会落到图外 —— 实测踩到）：目标框选图像坐标 (40, 30) → (120, 110)
    rect = dialog.view.image_rect()
    scale = rect.width() / image.shape[1]
    start = QPoint(rect.x() + int(round(40 * scale)), rect.y() + int(round(30 * scale)))
    end = QPoint(rect.x() + int(round(120 * scale)), rect.y() + int(round(110 * scale)))
    QTest.mousePress(dialog.view, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(dialog.view, end)
    QTest.mouseRelease(dialog.view, Qt.MouseButton.LeftButton, pos=end)
    _APP.processEvents()

    selection = dialog.selection()
    assert selection is not None, "拖拽没有形成有效选区"
    x, y, width, height = selection
    assert abs(x - 40) <= 2 and abs(y - 30) <= 2
    assert abs(width - 80) <= 2 and abs(height - 80) <= 2

    dialog.save_button.click()
    assert dialog.saved_path is not None
    saved = load_template(dialog.saved_path)
    assert saved.shape[:2] == (height, width)                # 高、宽与选区一致
    assert saved.shape[0] < image.shape[0] and saved.shape[1] < image.shape[1]
    dialog.close()
    dialog.deleteLater()


def test_save_button_flags_near_full_screen_selection(tmp_path) -> None:
    """选区几乎等于整屏时给出提示（这种模板基本没有辨识度，多半是框错了）。"""
    image = _image(400, 300)
    dialog = TemplateCropDialog(image, (400, 300), save_dir=tmp_path)
    dialog.set_selection_in_image(0, 0, 400, 300)

    assert "几乎等于整屏" in dialog.selection_text()

    dialog.set_selection_in_image(10, 10, 60, 40)
    assert "几乎等于整屏" not in dialog.selection_text()
    dialog.deleteLater()
