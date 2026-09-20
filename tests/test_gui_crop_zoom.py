"""框选弹窗的**视图变换**用例（离屏）：滚轮缩放、中键/空格平移、1:1 显示、滚动夹取、
放大镜（位置/取样/真的画出像素）以及信息行的缩放倍率与鼠标客户区坐标。

与 `tests/test_gui_crop_edit.py` 的分工：那边测"选区怎么改"，这边测"画面怎么看"。
本文件自带最小夹具（`_image`/`_scaled_view`），与兄弟文件一致，避免跨文件共享夹具。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from luoluotool.gui.dialogs.crop_dialog import CropView, TemplateCropDialog

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


# ------------------------------------------- 批 2：滚轮缩放 / 平移 / 1:1 / HUD / 放大镜


def _wheel(view: CropView, delta: int, pos) -> None:
    """给框选图发一次滚轮事件（delta>0 放大）。"""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    event = QWheelEvent(
        QPointF(pos), view.mapToGlobal(QPoint(pos)), QPoint(0, 0), QPoint(0, delta * 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    view.wheelEvent(event)


def _move_mouse(view: CropView, pos) -> None:
    """直接发鼠标移动事件（不依赖 QTest 的按钮状态跟踪）。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    view.mouseMoveEvent(QMouseEvent(
        QMouseEvent.Type.MouseMove, QPoint(pos), view.mapToGlobal(QPoint(pos)),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    ))


def test_wheel_zoom_scales_and_keeps_cursor_anchor() -> None:
    """滚轮缩放：以鼠标为中心 —— 鼠标下的那块画面不动。"""
    from PySide6.QtCore import QPoint

    view = _scaled_view((200, 200))          # 适配比例 2 倍 → 起始 200%
    view.show()
    _APP.processEvents()
    assert view.zoom_percent() == 200

    anchor = QPoint(150, 150)
    anchor_image = view._widget_point_in_image(anchor)
    _wheel(view, +1, anchor)
    _APP.processEvents()

    assert view.zoom_percent() == 250                      # 2.0 × 1.25
    assert view._widget_point_in_image(anchor) == anchor_image   # 锚点没跑
    view.close()
    view.deleteLater()


def test_zoom_actual_makes_one_image_pixel_one_widget_pixel() -> None:
    """「1:1 显示」：缩放倍率变成 100%（1 图像像素 = 1 控件像素）。"""
    view = _scaled_view((200, 200))          # 适配 2 倍
    view.show()
    _APP.processEvents()

    view.zoom_to_actual()

    assert view.zoom_percent() == 100
    assert view.image_rect().width() == 200
    view.close()
    view.deleteLater()


def test_zoom_fit_restores_the_initial_view() -> None:
    """「适配窗口」：回到整图适配（缩放相对适配为 1 → 显示倍率＝适配比例的百分比）。"""
    view = _scaled_view((200, 200))
    fit_rect = view.image_rect()
    view.zoom_to_actual()
    assert view.image_rect() != fit_rect

    view.zoom_to_fit()

    assert view.image_rect() == fit_rect
    assert view.zoom_percent() == 200
    view.deleteLater()


def test_zoom_is_clamped_to_limits() -> None:
    """缩放有上下限（狂滚也不会把画面缩成一点或涨到看不见）。"""
    from PySide6.QtCore import QPoint

    from luoluotool.gui.dialogs.crop_view import MAX_ZOOM, MIN_ZOOM

    view = _scaled_view((200, 200))
    view.show()
    _APP.processEvents()
    for _ in range(30):
        _wheel(view, +1, QPoint(100, 100))
    assert view._zoom == MAX_ZOOM
    for _ in range(60):
        _wheel(view, -1, QPoint(100, 100))
    assert view._zoom == MIN_ZOOM
    view.close()
    view.deleteLater()


def test_middle_button_drag_pans_the_image() -> None:
    """中键拖拽＝平移画面（显示区域跟着位移，图像本身不动）。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    view = _scaled_view((200, 200))
    view.show()
    _APP.processEvents()
    before = view.image_rect()

    QTest.mousePress(view, Qt.MouseButton.MiddleButton, pos=QPoint(200, 200))
    QTest.mouseMove(view, QPoint(240, 220))
    QTest.mouseRelease(view, Qt.MouseButton.MiddleButton, pos=QPoint(240, 220))
    _APP.processEvents()

    after = view.image_rect()
    assert (after.x() - before.x(), after.y() - before.y()) == (40, 20)
    view.close()
    view.deleteLater()


def test_magnifier_follows_cursor_and_stays_inside_view() -> None:
    """放大镜位置：贴着鼠标；靠近右下角时自动翻到另一侧、始终在控件内。"""
    from PySide6.QtCore import QPoint

    from luoluotool.gui.dialogs.crop_view import MAGNIFIER_SIZE_PX

    view = _scaled_view((200, 200))
    view.resize(400, 400)

    _move_mouse(view, QPoint(60, 60))
    left_top = view.magnifier_rect()
    assert left_top.topLeft().x() > 60 and left_top.topLeft().y() > 60      # 在鼠标右下方

    _move_mouse(view, QPoint(390, 390))
    bottom_right = view.magnifier_rect()
    assert bottom_right.right() <= view.width()                            # 没被裁掉
    assert bottom_right.bottom() <= view.height()
    assert bottom_right.width() == MAGNIFIER_SIZE_PX

    view.set_magnifier_enabled(False)
    assert view.magnifier_rect().isEmpty()
    view.deleteLater()


def test_magnifier_source_rect_is_clamped_to_image() -> None:
    """放大镜取样区域夹在图像内（鼠标贴着边缘时不越界）。"""
    from PySide6.QtCore import QPoint

    from luoluotool.gui.dialogs.crop_view import MAGNIFIER_SOURCE_PX

    view = _scaled_view((200, 200))
    for pos in (QPoint(0, 0), QPoint(399, 399)):
        _move_mouse(view, pos)
        source = view.magnifier_source_rect()
        assert source.width() == MAGNIFIER_SOURCE_PX
        assert source.left() >= 0 and source.top() >= 0
        assert source.right() < 200 and source.bottom() < 200
    view.deleteLater()


def test_magnifier_paints_the_pixel_under_the_cursor() -> None:
    """放大镜真的画出像素：中心那块颜色 = 鼠标处图像像素的颜色。"""
    from PySide6.QtCore import QPoint

    image = _image(100, 100)                 # B=x, G=y → (60,20) 处颜色唯一
    view = CropView(image)
    view.resize(400, 400)                    # 适配 4 倍 → 图像 (60,20) → 控件 (240, 80)
    view.show()
    _APP.processEvents()
    _move_mouse(view, QPoint(240, 80))
    _APP.processEvents()

    magnifier = view.magnifier_rect()
    source = view.magnifier_source_rect()
    assert source.contains(QPoint(60, 20))
    # 取放大镜左上角内侧 3px 处（避开中心十字与右下角的坐标文字），
    # 6 倍整数放大 → 该点对应取样区域的第一个像素。
    probe = magnifier.topLeft() + QPoint(3, 3)
    painted = view.grab().toImage().pixelColor(probe)
    expected = image[source.top(), source.left()]
    assert (painted.blue(), painted.green()) == (int(expected[0]), int(expected[1]))
    view.close()
    view.deleteLater()


def test_info_label_shows_zoom_and_cursor_position() -> None:
    """HUD：信息行要同时给出选区、缩放倍率与鼠标处的客户区坐标。"""
    from PySide6.QtCore import QPoint

    dialog = TemplateCropDialog(_image(200, 200), (200, 200), save_dir=None)
    dialog.view.resize(400, 400)
    dialog.set_selection_in_image(50, 50, 40, 30)
    _move_mouse(dialog.view, QPoint(120, 120))

    text = dialog.info_label.text()
    assert "选区 40x30" in text
    assert "缩放 200%" in text
    assert "鼠标客户区 (60, 60)" in text

    dialog.zoom_actual_button.click()
    assert "缩放 100%" in dialog.info_label.text()
    dialog.zoom_fit_button.click()
    assert "缩放 200%" in dialog.info_label.text()
    dialog.deleteLater()


def test_hovering_repaints_so_the_magnifier_follows_the_cursor() -> None:
    """只移动鼠标（没按住）也必须重绘：放大镜是"贴着鼠标画"的，不重绘就停在原处。"""
    from PySide6.QtCore import QPoint

    class CountingView(CropView):
        paints = 0

        def paintEvent(self, event) -> None:      # noqa: N802
            type(self).paints += 1
            super().paintEvent(event)

    view = CountingView(_image(200, 200))
    view.resize(400, 400)
    view.show()
    _APP.processEvents()
    before = CountingView.paints

    _move_mouse(view, QPoint(120, 120))
    _APP.processEvents()

    assert CountingView.paints > before
    view.close()
    view.deleteLater()


def test_mouse_leave_hides_the_magnifier_and_the_coordinate_hint() -> None:
    """鼠标移出框选图 → 放大镜收起、坐标提示回到"移入后显示"（不留残影）。"""
    from PySide6.QtCore import QEvent, QPoint

    dialog = TemplateCropDialog(_image(200, 200), (200, 200), save_dir=None)
    dialog.view.resize(400, 400)
    _move_mouse(dialog.view, QPoint(120, 120))
    assert dialog.view.magnifier_rect().isEmpty() is False

    QApplication.sendEvent(dialog.view, QEvent(QEvent.Type.Leave))

    assert dialog.view.magnifier_rect().isEmpty()
    assert dialog.view.cursor_position() is None
    assert "移入截图后显示坐标" in dialog.info_label.text()
    dialog.deleteLater()
