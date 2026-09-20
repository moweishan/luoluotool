"""框选视图的**显示变换**部分：滚轮缩放、中键/空格平移、1:1 显示、放大镜、鼠标坐标。

拆分说明（2026-09-21，原 `crop_view.py` 694 行超 600 硬线）：这里是**纯搬运** ——
`fit_scale`/`image_rect`/`zoom_*`/`_set_zoom`/`_clamp_pan`/`_scale`/`wheelEvent`/
`magnifier_*`/`_paint_magnifier` 与相关常量原样搬来（函数体一字未改），
以 mixin 形式被 `crop_view.CropView(ZoomPanMixin, QWidget)` 继承；
`crop_view` 把这批名字**再导出**，`from ...crop_view import MIN_ZOOM` 等旧写法继续可用。

状态仍由 `CropView.__init__` 建立（`_zoom`/`_pan`/`_magnifier_enabled`/`_cursor_widget`/
`_cursor_in_image`），本模块只提供读写这些状态的方法，不碰文件与业务。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen

# 视图缩放（用户 2026-09-20 要求：滚轮缩放 + 中键/空格平移 + 1:1 显示）
MIN_ZOOM = 0.5                  # 相对"适配比例"的最小倍数
MAX_ZOOM = 8.0
WHEEL_ZOOM_STEP = 1.25          # 滚轮每格缩放倍数
MIN_VISIBLE_PX = 60             # 平移时图像至少留这么多像素可见（不会被拖没）

# 放大镜（鼠标旁显示放大后的像素 + 坐标）
MAGNIFIER_SIZE_PX = 132         # 放大镜控件边长
MAGNIFIER_SCALE = 6             # 放大倍数（整数倍 → 像素块边缘清晰）
MAGNIFIER_SOURCE_PX = MAGNIFIER_SIZE_PX // MAGNIFIER_SCALE   # 取样区域边长（图像像素）
MAGNIFIER_BORDER_COLOR = QColor(0, 220, 255)
CROSSHAIR_COLOR = QColor(255, 64, 64)


class ZoomPanMixin:
    """缩放 / 平移 / 放大镜的一组方法（由 `CropView` 继承，依赖它建立的状态）。"""

    def fit_scale(self) -> float:
        """适配比例：整张图刚好放进控件时的缩放倍数（缩放倍数是相对它算的）。"""
        width, height = self.image_size
        if width <= 0 or height <= 0 or self.width() <= 0 or self.height() <= 0:
            return 0.0
        return min(self.width() / width, self.height() / height)

    def image_rect(self) -> QRect:
        """图像在控件内的显示区域：适配比例 × 缩放倍数，再按平移量偏移。"""
        base = self.fit_scale()
        if base <= 0:
            return QRect()
        width, height = self.image_size
        drawn_w = max(1, int(round(width * base * self._zoom)))
        drawn_h = max(1, int(round(height * base * self._zoom)))
        # 居中用「(控件尺寸 - 图像尺寸) / 2」四舍五入：QRect.center() 在奇数尺寸上会少 1 像素
        # （480 宽控件取到 239），整图适配时会算成 (-1, -1)，与"恰好铺满"的预期差一像素。
        left = int(round((self.width() - drawn_w) / 2.0)) + self._pan.x()
        top = int(round((self.height() - drawn_h) / 2.0)) + self._pan.y()
        return QRect(left, top, drawn_w, drawn_h)

    def zoom_percent(self) -> int:
        """当前显示倍率（100% ＝ 1 个图像像素占 1 个控件像素）。"""
        return int(round(self._scale() * 100))

    def zoom_relative_percent(self) -> int:
        """相对"整图适配"的缩放百分比（100%＝整图刚好铺满；弹窗滑条用这个口径）。"""
        return int(round(self._zoom * 100))

    def set_zoom_relative(self, zoom: float) -> bool:
        """按"相对整图适配的倍数"设置缩放，锚点＝选区中心（没选区则图像中心），画面不跳走。"""
        return self._set_zoom(zoom, anchor_widget=self._zoom_anchor_widget())

    def cursor_position(self) -> QPoint | None:
        """鼠标处的图像（客户区）坐标；鼠标不在图上时为 None（HUD 用）。"""
        return self._cursor_in_image

    def set_magnifier_enabled(self, enabled: bool) -> None:
        """放大镜开关（关掉后鼠标旁不再显示放大像素）。"""
        self._magnifier_enabled = bool(enabled)
        self.update()

    def zoom_to_fit(self) -> None:
        """回到"整图适配"（缩放归 1、平移归零）。"""
        self._zoom, self._pan = 1.0, QPoint(0, 0)
        self.update()
        self.view_changed.emit()

    def zoom_to_actual(self) -> None:
        """1:1 显示（1 图像像素 ＝ 1 控件像素），以选区/图像中心为锚点避免画面跳走。"""
        base = self.fit_scale()
        if base <= 0:
            return
        self.set_zoom_relative(1.0 / base)

    def _zoom_anchor_widget(self) -> QPoint:
        """缩放锚点：有选区就取选区中心，否则取图像中心。"""
        if self._image_selection is not None and not self._image_selection.isNull():
            target = self._image_selection.center()
        else:
            width, height = self.image_size
            target = QPoint(width // 2, height // 2)
        display = self.image_rect()
        scale = self._scale() or 1.0
        return QPoint(
            int(round(display.x() + target.x() * scale)),
            int(round(display.y() + target.y() * scale)),
        )

    def set_zoom(self, zoom: float, anchor_widget: QPoint | None = None) -> bool:
        """设置缩放倍数（夹在 [MIN_ZOOM, MAX_ZOOM]），`anchor_widget` 处的图像像素保持不动。"""
        return self._set_zoom(zoom, anchor_widget=anchor_widget)

    def _set_zoom(self, zoom: float, anchor_widget: QPoint | None = None) -> bool:
        zoom = max(MIN_ZOOM, min(float(zoom), MAX_ZOOM))
        if abs(zoom - self._zoom) < 1e-6:
            return False
        anchor = anchor_widget if anchor_widget is not None else self.rect().center()
        image_point = self._widget_point_in_image(anchor)     # 用旧变换算锚点
        self._zoom = zoom
        display = self.image_rect()                            # 新变换下的显示区域
        scale = self._scale() or 1.0
        want = QPoint(
            int(round(display.x() + image_point.x() * scale)),
            int(round(display.y() + image_point.y() * scale)),
        )
        self._pan += anchor - want                             # 把锚点拉回原处
        self._clamp_pan()
        self.update()
        self.view_changed.emit()
        return True

    def _clamp_pan(self) -> None:
        """平移不能把图像拖没：至少留 MIN_VISIBLE_PX 像素在控件里。"""
        display = self.image_rect()
        if display.isEmpty():
            return
        dx = dy = 0
        if display.right() < MIN_VISIBLE_PX:
            dx = MIN_VISIBLE_PX - display.right()
        elif display.left() > self.width() - MIN_VISIBLE_PX:
            dx = (self.width() - MIN_VISIBLE_PX) - display.left()
        if display.bottom() < MIN_VISIBLE_PX:
            dy = MIN_VISIBLE_PX - display.bottom()
        elif display.top() > self.height() - MIN_VISIBLE_PX:
            dy = (self.height() - MIN_VISIBLE_PX) - display.top()
        if dx or dy:
            self._pan += QPoint(dx, dy)

    def _scale(self) -> float:
        width, _ = self.image_size
        drawn = self.image_rect().width()
        return drawn / width if width else 1.0

    def wheelEvent(self, event) -> None:           # noqa: N802
        """滚轮缩放：以鼠标位置为锚点（鼠标下的那块画面不动）。"""
        delta = event.angleDelta().y()
        if not delta:
            super().wheelEvent(event)
            return
        factor = WHEEL_ZOOM_STEP if delta > 0 else 1 / WHEEL_ZOOM_STEP
        self._set_zoom(self._zoom * factor, anchor_widget=event.position().toPoint())
        event.accept()

    # ------------------------------------------------------------- 放大镜
    def magnifier_rect(self) -> QRect:
        """放大镜在控件里的位置（贴着鼠标，靠边自动翻到另一侧）；不显示时返回空矩形。"""
        if (
            not self._magnifier_enabled
            or self._cursor_widget is None
            or self._cursor_in_image is None
            or self.image_rect().isEmpty()          # 图还没显示时没什么可放大
        ):
            return QRect()
        x = self._cursor_widget.x() + 18
        y = self._cursor_widget.y() + 18
        if x + MAGNIFIER_SIZE_PX > self.width():
            x = self._cursor_widget.x() - MAGNIFIER_SIZE_PX - 18
        if y + MAGNIFIER_SIZE_PX > self.height():
            y = self._cursor_widget.y() - MAGNIFIER_SIZE_PX - 18
        return QRect(max(0, x), max(0, y), MAGNIFIER_SIZE_PX, MAGNIFIER_SIZE_PX)

    def magnifier_source_rect(self) -> QRect:
        """放大镜取样的图像区域（以鼠标处为中心，夹在图像内）。"""
        if self._cursor_in_image is None:
            return QRect()
        half = MAGNIFIER_SOURCE_PX // 2
        image_w, image_h = self.image_size
        x = max(0, min(self._cursor_in_image.x() - half, max(0, image_w - MAGNIFIER_SOURCE_PX)))
        y = max(0, min(self._cursor_in_image.y() - half, max(0, image_h - MAGNIFIER_SOURCE_PX)))
        return QRect(x, y, MAGNIFIER_SOURCE_PX, MAGNIFIER_SOURCE_PX)

    def _paint_magnifier(self, painter: QPainter) -> None:
        """画放大镜：整数倍放大 → 像素块清晰，中心十字标出当前像素。"""
        target = self.magnifier_rect()
        source = self.magnifier_source_rect()
        if target.isEmpty() or source.isEmpty():
            return
        painter.drawImage(target, self._qimage, source)
        painter.setPen(QPen(MAGNIFIER_BORDER_COLOR, 1))
        painter.drawRect(target.adjusted(0, 0, -1, -1))
        center = target.center()
        painter.setPen(QPen(CROSSHAIR_COLOR, 1))
        painter.drawLine(center.x() - 6, center.y(), center.x() + 6, center.y())
        painter.drawLine(center.x(), center.y() - 6, center.x(), center.y() + 6)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            target.adjusted(0, 0, -2, -2),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
            f"({self._cursor_in_image.x()}, {self._cursor_in_image.y()})",
        )

    def leaveEvent(self, event) -> None:           # noqa: N802
        """鼠标移出控件 → 收起放大镜与坐标（否则会停在最后一次的位置，像画错的补丁）。"""
        self._cursor_widget = None
        self._cursor_in_image = None
        self.update()
        self.view_changed.emit()
        super().leaveEvent(event)
