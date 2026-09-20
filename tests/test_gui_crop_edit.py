"""框选弹窗的**选区编辑**用例（离屏）：拖动移动、八向手柄缩放、Alt 中心缩放、空格/右键移动、
键盘微调（方向键 / Ctrl 单边）、Esc 撤销、双击清空、选区外压暗、拖拽尺寸气泡。

与 `tests/test_gui_crop.py` 的分工：那边测"几何换算 + 保存落盘"，这边测"怎么把选区改对"。
两边共用同一套最小夹具（本文件自带 `_image`/`_scaled_view`/拖拽辅助，避免跨文件共享夹具）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
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


def _scaled_view(image_size: tuple[int, int], scale: int = 2) -> CropView:
    """造一个 1:scale 显示的视图（图像坐标 = 控件坐标 / scale），方便写断言。"""
    width, height = image_size
    view = CropView(_image(width, height))
    view.resize(width * scale, height * scale)
    return view


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


def _send_mouse(view: CropView, kind: str, pos, *, modifiers=None) -> None:
    """手动构造鼠标事件（QTest.mousePress 在本版 PySide6 不支持 modifier= 参数）。"""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    modifiers = modifiers or Qt.KeyboardModifier.NoModifier
    types = {
        "press": QMouseEvent.Type.MouseButtonPress,
        "move": QMouseEvent.Type.MouseMove,
        "release": QMouseEvent.Type.MouseButtonRelease,
    }
    button = Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == "move" else button
    event = QMouseEvent(
        types[kind], QPointF(pos), view.mapToGlobal(pos), button, buttons, modifiers
    )
    {"press": view.mousePressEvent, "move": view.mouseMoveEvent, "release": view.mouseReleaseEvent}[
        kind
    ](event)


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


# ------------------------------------------- 批 1：遮罩 / Esc / 双击 / 尺寸气泡 / Alt / 空格


def test_double_click_clears_selection() -> None:
    """双击＝清空选区（重新框）。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)
    view.show()
    _APP.processEvents()

    QTest.mouseDClick(view, Qt.MouseButton.LeftButton, pos=QPoint(120, 120))
    _APP.processEvents()

    assert view.selection_in_image() is None
    view.close()
    view.deleteLater()


def test_escape_cancels_drag_and_restores_previous_selection() -> None:
    """拖拽中按 Esc＝撤销这次拖拽（回到按下之前），不是整块丢掉。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)
    view.show()
    _APP.processEvents()

    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(120, 120))   # 选区内部
    QTest.mouseMove(view, QPoint(200, 200))
    assert view.selection_in_image() != (50, 50, 40, 30)                      # 已经移动了
    QTest.keyClick(view, Qt.Key.Key_Escape)
    _APP.processEvents()

    assert view.selection_in_image() == (50, 50, 40, 30)                      # 回到原样
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(200, 200))
    assert view.selection_in_image() == (50, 50, 40, 30)                      # 松手也不会再改
    view.close()
    view.deleteLater()


def test_escape_clears_selection_when_not_dragging() -> None:
    """没在拖拽时按 Esc＝清空选区。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.selection_in_image() is None
    view.deleteLater()


def test_escape_without_selection_reaches_the_dialog() -> None:
    """既没拖拽也没有选区时，Esc 不该被吃掉（应继续传给对话框 → 关窗）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    view = _scaled_view((200, 200))
    event = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    view.keyPressEvent(event)
    assert event.isAccepted() is False
    view.deleteLater()


def _send_mouse(view: CropView, kind: str, pos, *, modifiers=None) -> None:
    """手动构造鼠标事件（QTest.mousePress 在本版 PySide6 不支持 modifier= 参数）。"""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    modifiers = modifiers or Qt.KeyboardModifier.NoModifier
    types = {
        "press": QMouseEvent.Type.MouseButtonPress,
        "move": QMouseEvent.Type.MouseMove,
        "release": QMouseEvent.Type.MouseButtonRelease,
    }
    button = Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == "move" else button
    event = QMouseEvent(
        types[kind], QPointF(pos), view.mapToGlobal(pos), button, buttons, modifiers
    )
    {"press": view.mousePressEvent, "move": view.mouseMoveEvent, "release": view.mouseReleaseEvent}[
        kind
    ](event)


def test_alt_drag_resizes_around_the_selection_center() -> None:
    """Alt+拖手柄＝以选区中心为锚点对称缩放（中心不动，两边一起变）。"""
    from PySide6.QtCore import QPoint, Qt

    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)          # 中心 (70, 65)
    rect = view._image_rect_on_widget()
    view.show()
    _APP.processEvents()

    # 拖到图像 (95, 85)：距中心 (±25, ±20) → 宽 50、高 40，中心仍是 (70, 65)
    start = QPoint(rect.right(), rect.bottom())
    target = QPoint(190, 170)
    alt = Qt.KeyboardModifier.AltModifier
    _send_mouse(view, "press", start, modifiers=alt)
    _send_mouse(view, "move", target, modifiers=alt)
    _send_mouse(view, "release", target, modifiers=alt)
    _APP.processEvents()

    x, y, width, height = view.selection_in_image()
    assert (x, y, width, height) == (45, 45, 50, 40)
    assert (x + width // 2, y + height // 2) == (70, 65)      # 中心没动
    view.close()
    view.deleteLater()


def test_space_drag_moves_selection_even_on_a_handle() -> None:
    """空格+拖拽＝无论按在哪（含手柄）都是移动选区。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)
    rect = view._image_rect_on_widget()
    view.show()
    _APP.processEvents()

    QTest.keyPress(view, Qt.Key.Key_Space)                 # 按住空格
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(rect.right(), rect.bottom()))
    QTest.mouseMove(view, QPoint(rect.right() + 20, rect.bottom() + 20))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton,
                       pos=QPoint(rect.right() + 20, rect.bottom() + 20))
    QTest.keyRelease(view, Qt.Key.Key_Space)
    _APP.processEvents()

    assert view.selection_in_image() == (60, 60, 40, 30)      # 整体移动，尺寸不变
    view.close()
    view.deleteLater()


def test_right_button_drag_moves_selection() -> None:
    """右键拖拽＝移动选区（左键保留给"重新框选"）。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    view = _scaled_view((200, 200))
    view.set_selection_in_image(50, 50, 40, 30)
    view.show()
    _APP.processEvents()

    QTest.mousePress(view, Qt.MouseButton.RightButton, pos=QPoint(120, 120))
    QTest.mouseMove(view, QPoint(160, 120))
    QTest.mouseRelease(view, Qt.MouseButton.RightButton, pos=QPoint(160, 120))
    _APP.processEvents()

    assert view.selection_in_image() == (70, 50, 40, 30)
    view.close()
    view.deleteLater()


def test_dim_mask_darkens_outside_selection() -> None:
    """选区外要压暗（截图工具标配），选区内保持原样。"""
    from PySide6.QtCore import QPoint

    view = _scaled_view((100, 100))
    view.show()
    _APP.processEvents()
    before = view.grab().toImage()

    view.set_selection_in_image(20, 20, 20, 20)
    _APP.processEvents()
    after = view.grab().toImage()

    inside_point = view._image_rect_on_widget().center()      # 选区内
    display = view.image_rect()
    outside_point = display.bottomRight() - QPoint(2, 2)      # 图像右下角（最亮、且在选区外）
    assert after.pixelColor(outside_point).value() < before.pixelColor(outside_point).value()
    assert after.pixelColor(inside_point).value() == before.pixelColor(inside_point).value()
    view.close()
    view.deleteLater()


def test_drag_bubble_reports_size_while_dragging() -> None:
    """拖拽时鼠标旁要有尺寸气泡（内容＝宽×高 + 客户区左上角）。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    view = _scaled_view((200, 200))
    view.show()
    _APP.processEvents()

    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(40, 40))
    QTest.mouseMove(view, QPoint(120, 100))
    _APP.processEvents()

    assert view.drag_bubble_text() == "40×30 @ (20, 20)"      # 控件位移 80x60 → 图像 40x30
    assert view.drag_bubble_rect().isEmpty() is False
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(120, 100))
    assert view.drag_bubble_text() == ""                      # 松手后不再画
    view.close()
    view.deleteLater()
