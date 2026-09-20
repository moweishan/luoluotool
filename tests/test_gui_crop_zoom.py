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

    from luoluotool.gui.dialogs.crop_dialog import zoom_percent_to_slider

    dialog = TemplateCropDialog(_image(200, 200), (200, 200), save_dir=None)
    dialog.view.resize(400, 400)
    dialog.set_selection_in_image(50, 50, 40, 30)
    _move_mouse(dialog.view, QPoint(120, 120))

    text = dialog.info_label.text()
    assert "选区 40x30" in text
    assert "缩放 200%" in text
    assert "鼠标客户区 (60, 60)" in text

    # 滑条拖到"相对整图适配 50%" → 显示倍率变成 100%（适配是 200%）
    dialog.zoom_slider.setValue(zoom_percent_to_slider(50))
    assert "缩放 100%" in dialog.info_label.text()
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


# ---------------------------------------- 缩放滑条 + 重置（用户 2026-09-21 要求）
#
# 用户要求：把「适配窗口 / 1:1 显示」两个按钮换成**可以左右拉的滑条**，另加一个「重置」按钮。
# 滑条刻度＝**相对"整图适配"的倍数**（50%–800%，固定不变，与截图/窗口大小无关），
# 采用**对数刻度**：每 1/4 行程翻一倍（50 → 100 → 200 → 400 → 800），所以 100%（＝整图适配）
# 正好落在 1/4 处，往左是缩小、往右是放大，手感均匀。
# 「重置」＝**恢复弹窗初始状态**：缩放回到整图适配、画面归位，并把当前选区一起清空。


def test_zoom_slider_scale_maps_to_relative_percent() -> None:
    """滑条刻度换算：两端是 50% / 800%，1/4 处是整图适配（100%），每 1/4 行程翻一倍。"""
    from luoluotool.gui.dialogs.crop_dialog import (
        ZOOM_SLIDER_STEPS,
        zoom_percent_to_slider,
        zoom_slider_to_percent,
    )

    assert zoom_slider_to_percent(0) == 50                       # 最左＝缩到适配的一半
    assert zoom_slider_to_percent(ZOOM_SLIDER_STEPS) == 800      # 最右＝放大到适配的 8 倍
    assert zoom_slider_to_percent(ZOOM_SLIDER_STEPS // 4) == 100  # 1/4 处＝整图适配
    assert zoom_slider_to_percent(ZOOM_SLIDER_STEPS // 2) == 200  # 中点＝2 倍
    assert zoom_slider_to_percent(ZOOM_SLIDER_STEPS * 3 // 4) == 400
    for percent in (50, 60, 75, 100, 125, 150, 200, 400, 800):   # 往返一致（拖出去再拖回来不漂移）
        assert zoom_slider_to_percent(zoom_percent_to_slider(percent)) == percent


def test_zoom_slider_drag_sets_the_view_zoom(tmp_path) -> None:
    """拖滑条＝改缩放：相对适配 200% 时显示倍率是适配比例的两倍，数值标签同步。"""
    from luoluotool.gui.dialogs.crop_dialog import zoom_percent_to_slider

    dialog = TemplateCropDialog(_image(200, 200), (200, 200), save_dir=tmp_path)
    dialog.view.resize(400, 400)                     # 适配比例 2 倍 → 显示 200%
    dialog.set_selection_in_image(40, 40, 60, 60)

    dialog.zoom_slider.setValue(zoom_percent_to_slider(200))

    assert dialog.view.zoom_relative_percent() == 200
    assert dialog.view.zoom_percent() == 400         # 显示倍率 = 适配 200% × 相对 2 倍
    assert "200%" in dialog.zoom_value_label.text()
    dialog.deleteLater()


def test_zoom_slider_drag_keeps_the_selection_in_place(tmp_path) -> None:
    """拖滑条时以选区中心为锚点：选区在图片里的坐标不该被缩放带跑。"""
    from luoluotool.gui.dialogs.crop_dialog import zoom_percent_to_slider

    dialog = TemplateCropDialog(_image(200, 200), (200, 200), save_dir=tmp_path)
    dialog.view.resize(400, 400)
    dialog.set_selection_in_image(40, 40, 60, 60)
    center_before = dialog.view._image_rect_on_widget().center()      # noqa: SLF001（离屏用例）

    dialog.zoom_slider.setValue(zoom_percent_to_slider(200))
    center_after = dialog.view._image_rect_on_widget().center()

    assert dialog.selection() == (40, 40, 60, 60)                     # 选区（图像坐标）没变
    assert abs(center_after.x() - center_before.x()) <= 2             # 选区在屏幕上基本没动
    assert abs(center_after.y() - center_before.y()) <= 2
    dialog.deleteLater()


def test_zoom_slider_follows_wheel_zoom(tmp_path) -> None:
    """两个缩放入口共用同一份状态：滚轮缩放后滑条与数值标签必须跟着走。"""
    from PySide6.QtCore import QPoint

    from luoluotool.gui.dialogs.crop_dialog import ZOOM_SLIDER_STEPS

    dialog = TemplateCropDialog(_image(200, 200), (200, 200), save_dir=tmp_path)
    dialog.view.resize(400, 400)
    dialog.view.show()
    _APP.processEvents()
    start = dialog.zoom_slider.value()

    _wheel(dialog.view, +1, QPoint(100, 100))        # 相对适配 100% → 125%
    _APP.processEvents()

    assert dialog.view.zoom_relative_percent() == 125
    assert dialog.zoom_slider.value() > start
    assert "125%" in dialog.zoom_value_label.text()

    for _ in range(40):                              # 一路滚到顶也不能超出刻度范围
        _wheel(dialog.view, +1, QPoint(100, 100))
    assert dialog.view.zoom_relative_percent() == 800
    assert dialog.zoom_slider.value() == ZOOM_SLIDER_STEPS
    dialog.close()
    dialog.deleteLater()


def test_zoom_controls_are_a_slider_and_a_reset_button(tmp_path) -> None:
    """界面收敛：只留 [滑条] + [重置]，原来的「适配窗口 / 1:1 显示」两个按钮已撤掉。"""
    from luoluotool.gui.dialogs.crop_dialog import (
        ZOOM_SLIDER_STEPS,
        zoom_percent_to_slider,
    )

    dialog = TemplateCropDialog(_image(200, 200), (200, 200), save_dir=tmp_path)

    assert dialog.zoom_slider.minimum() == 0
    assert dialog.zoom_slider.maximum() == ZOOM_SLIDER_STEPS
    assert dialog.zoom_slider.value() == zoom_percent_to_slider(100)   # 打开就是整图适配
    assert dialog.zoom_reset_button.text() == "重置"
    assert not hasattr(dialog, "zoom_fit_button")
    assert not hasattr(dialog, "zoom_actual_button")
    dialog.deleteLater()


def test_zoom_slider_does_not_steal_the_keyboard_focus(tmp_path) -> None:
    """滑条不许抢键盘焦点：方向键要留给"微调选区"，不能被 QSlider 吃掉。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    dialog = TemplateCropDialog(_image(200, 200), (200, 200), save_dir=tmp_path)
    dialog.show()
    _APP.processEvents()
    dialog.set_selection_in_image(40, 40, 60, 60)

    assert dialog.zoom_slider.focusPolicy() == Qt.FocusPolicy.NoFocus
    before = dialog.zoom_slider.value()
    QTest.mouseClick(dialog.zoom_slider, Qt.MouseButton.LeftButton,
                     pos=QPoint(dialog.zoom_slider.width() // 2, dialog.zoom_slider.height() // 2))
    _APP.processEvents()
    assert dialog.zoom_slider.value() != before            # 点滑条确实改了值（控件可交互）
    assert dialog.focusWidget() is dialog.view             # 但焦点没被抢走

    QTest.keyClick(dialog.view, Qt.Key.Key_Right)          # 方向键仍然微调选区
    assert dialog.selection() == (41, 40, 60, 60)
    dialog.close()
    dialog.deleteLater()


def test_reset_button_restores_the_initial_dialog_state(tmp_path) -> None:
    """「重置」＝恢复弹窗初始状态：缩放回整图适配、画面归位、选区清空。"""
    from PySide6.QtCore import QPoint

    from luoluotool.gui.dialogs.crop_dialog import (
        ZOOM_SLIDER_STEPS,
        zoom_percent_to_slider,
    )

    dialog = TemplateCropDialog(_image(200, 200), (200, 200), save_dir=tmp_path)
    dialog.view.resize(400, 400)
    dialog.view.show()
    _APP.processEvents()
    fit_rect = dialog.view.image_rect()
    dialog.set_selection_in_image(40, 40, 60, 60)
    dialog.zoom_slider.setValue(zoom_percent_to_slider(800))
    _wheel(dialog.view, -1, QPoint(200, 200))        # 再平移一下，确认会被归零
    dialog.view.set_probe_rects([dialog.view.image_rect()])   # 假装刚试识别过

    dialog.zoom_reset_button.click()

    assert dialog.view.zoom_relative_percent() == 100
    assert dialog.zoom_slider.value() == zoom_percent_to_slider(100)
    assert dialog.view.image_rect() == fit_rect                     # 缩放与平移都归位
    assert dialog.selection() is None                               # 选区也一起清掉
    assert dialog.view.probe_rects() == []                          # 试识别结论作废
    assert "尚未试识别" in dialog.probe_result_label.text()
    assert "尚未选择区域" in dialog.info_label.text()
    assert dialog.probe_button.isEnabled() is False                 # 没选区 → 试识别按钮跟着禁用
    assert dialog.zoom_slider.maximum() == ZOOM_SLIDER_STEPS        # 刻度范围不受重置影响
    assert dialog.focusWidget() is dialog.view                      # 重置完焦点交回框选图
    dialog.close()
    dialog.deleteLater()
