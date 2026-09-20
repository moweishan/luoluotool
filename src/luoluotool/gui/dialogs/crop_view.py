"""框选交互视图：显示截图 + 选区的新建/移动/缩放/微调（纯控件，不碰文件与业务）。

用户 2026-09-20 要求的三件事都在这里：**框选完还能改**（移动/八向手柄缩放）、**键盘微调**、
以及拖拽时的视觉反馈（选区外压暗、尺寸气泡、手柄、指针形状）。

坐标约定：对外一律暴露**图像像素坐标**（`selection_in_image()`），图像就是游戏客户区截图，
因此选区左上角即客户区坐标（与点击/滑动/识别结果同一坐标系）。
显示时按控件里的矩形换算（等比适配 + 居中），缩放取整误差只影响显示，不影响暴露的坐标。

拆分说明（2026-09-21，原文件 694 行超 600 硬线）：**显示变换**（滚轮缩放 / 中键·空格平移 /
1:1 显示 / 放大镜 / 鼠标坐标）已纯搬运到 `gui/dialogs/crop_view_zoom.py` 的 `ZoomPanMixin`，
本模块的 `CropView(ZoomPanMixin, QWidget)` 直接继承，并把那批常量**再导出**（旧导入路径不变）。
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from luoluotool.gui.dialogs.crop_view_zoom import (      # 再导出：旧导入路径不变
    CROSSHAIR_COLOR,
    MAGNIFIER_BORDER_COLOR,
    MAGNIFIER_SCALE,
    MAGNIFIER_SIZE_PX,
    MAGNIFIER_SOURCE_PX,
    MAX_ZOOM,
    MIN_VISIBLE_PX,
    MIN_ZOOM,
    WHEEL_ZOOM_STEP,
    ZoomPanMixin,
)


MIN_SELECTION_SIZE = 8          # 选区小于该像素数视为无效（点一下、手抖）
NEAR_FULL_RATIO = 0.95          # 选区面积 ≥ 整屏的该比例时提示"几乎等于整屏"
BACKGROUND_COLOR = QColor(32, 32, 32)
SELECTION_COLOR = QColor(0, 220, 255)
HANDLE_SIZE_PX = 10             # 手柄命中范围（控件像素）：缩放后也要好点中
DIM_COLOR = QColor(0, 0, 0, 120)        # 选区外遮罩（让选中的那块跳出来，用户 2026-09-20 要求）
BUBBLE_COLOR = QColor(0, 0, 0, 200)     # 拖拽时的尺寸气泡底色
BUBBLE_PADDING_PX = 6


# 八个手柄（四角 + 四边）与它们的指针形状：拖动它们改选区大小（用户 2026-09-20 要求）
HANDLE_CURSORS: dict[str, Qt.CursorShape] = {
    "nw": Qt.CursorShape.SizeFDiagCursor,
    "n": Qt.CursorShape.SizeVerCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor,
    "w": Qt.CursorShape.SizeHorCursor,
    "e": Qt.CursorShape.SizeHorCursor,
    "sw": Qt.CursorShape.SizeBDiagCursor,
    "s": Qt.CursorShape.SizeVerCursor,
    "se": Qt.CursorShape.SizeFDiagCursor,
}


def to_qimage(image_bgr: np.ndarray) -> QImage:
    """BGR numpy 数组 → QImage（Qt 用 RGB，必须交换通道，否则颜色会错）。"""
    rgb = np.ascontiguousarray(image_bgr[:, :, ::-1])
    height, width = rgb.shape[:2]
    return QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()


class CropView(ZoomPanMixin, QWidget):
    """显示截图并支持左键拖拽框选；选区以图像像素坐标对外暴露。

    交互（用户 2026-09-20 要求"框选完还能改"）：
    - **选区外**按下拖拽 → 重新框选；
    - **选区内部**按下拖拽 → 整体移动（贴到图像边界即停，尺寸不变）；
    - **四角/四边手柄**上按下拖拽 → 改大小（对角固定、最小 MIN_SELECTION_SIZE 像素）。
    """

    selection_changed = Signal()
    view_changed = Signal()               # 鼠标位置 / 缩放变化（HUD 刷新用）

    def __init__(self, image_bgr: np.ndarray, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = image_bgr
        self._qimage = to_qimage(image_bgr)
        self._origin: QPoint | None = None
        # 选区以**图像像素坐标**为准（显示时再换算到控件坐标，避免缩放取整来回丢精度）
        self._image_selection: QRect | None = None
        # 修改已有选区用的状态：create=重新框选 / move=整体移动 / resize=拖手柄改大小
        self._mode: str | None = None
        self._handle: str | None = None
        self._start_rect: QRect | None = None
        self._space_down = False                    # 空格按住时拖拽＝移动选区
        self._cursor_in_image: QPoint | None = None  # 鼠标处的图像坐标（HUD/放大镜用）
        self._cursor_widget: QPoint | None = None    # 鼠标处的控件坐标（气泡/放大镜定位用）
        self._selection_before_drag: QRect | None = None   # Esc 撤销拖拽用
        self._symmetric_resize = False                     # Alt：以中心为锚点对称缩放
        self._zoom = 1.0                                   # 相对"适配比例"的倍数
        self._pan = QPoint(0, 0)                            # 平移量（控件像素）
        self._pan_origin: QPoint | None = None              # 平移起点（控件坐标）
        self._pan_start = QPoint(0, 0)
        self._magnifier_enabled = True                      # 放大镜（默认开，截图工具习惯）
        self.setMinimumSize(360, 240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)     # 方向键微调需要键盘焦点
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------- 几何换算
    @property
    def image_size(self) -> tuple[int, int]:
        height, width = self._image.shape[:2]
        return int(width), int(height)

    def selection_in_image(self) -> tuple[int, int, int, int] | None:
        """当前选区（图像像素坐标, 已裁剪到图像内）；过小或未选返回 None。"""
        if self._image_selection is None:
            return None
        image_w, image_h = self.image_size
        rect = self._image_selection.normalized()
        x = max(0, min(rect.left(), image_w - 1))
        y = max(0, min(rect.top(), image_h - 1))
        width = max(0, min(rect.width(), image_w - x))
        height = max(0, min(rect.height(), image_h - y))
        if width < MIN_SELECTION_SIZE or height < MIN_SELECTION_SIZE:
            return None
        return x, y, width, height

    def set_selection_in_image(self, x: int, y: int, width: int, height: int) -> None:
        """按图像坐标设置选区（供测试与程序化调用）。"""
        self._image_selection = QRect(int(x), int(y), int(width), int(height))
        self.update()
        self.selection_changed.emit()

    def _widget_point_in_image(self, point: QPoint) -> QPoint:
        """控件坐标 → 图像坐标（按当前缩放比例换算，并夹到图像范围内）。"""
        display = self.image_rect()
        scale = self._scale() or 1.0
        image_w, image_h = self.image_size
        x = int(round((point.x() - display.x()) / scale))
        y = int(round((point.y() - display.y()) / scale))
        return QPoint(max(0, min(x, image_w - 1)), max(0, min(y, image_h - 1)))

    def _image_rect_on_widget(self) -> QRect:
        """图像坐标选区 → 控件坐标矩形（仅用于绘制）。"""
        if self._image_selection is None:
            return QRect()
        display = self.image_rect()
        scale = self._scale() or 1.0
        rect = self._image_selection.normalized()
        return QRect(
            display.x() + int(round(rect.left() * scale)),
            display.y() + int(round(rect.top() * scale)),
            max(1, int(round(rect.width() * scale))),
            max(1, int(round(rect.height() * scale))),
        ).intersected(display)

    def _set_selection_from_points(self, start: QPoint, end: QPoint) -> None:
        """用两个图像坐标点更新选区。

        注意 Qt 的 `QRect(左上, 右下)` 右下角是**包含式**的（宽度会 +1），
        因此这里按「左上 + 宽高」构造，保证选区宽度与用户拖拽的像素数一致。
        """
        left, top = min(start.x(), end.x()), min(start.y(), end.y())
        self._image_selection = QRect(
            left, top, abs(end.x() - start.x()), abs(end.y() - start.y())
        )

    # ------------------------------------------------------------- 手柄与命中
    def handle_rects(self) -> dict[str, QRect]:
        """当前选区八个手柄的控件矩形（命中判定与绘制共用）。"""
        rect = self._image_rect_on_widget()
        if rect.isEmpty():
            return {}
        half = HANDLE_SIZE_PX // 2
        left, right = rect.left(), rect.right()
        top, bottom = rect.top(), rect.bottom()
        center = rect.center()
        anchors = {
            "nw": (left, top), "n": (center.x(), top), "ne": (right, top),
            "w": (left, center.y()), "e": (right, center.y()),
            "sw": (left, bottom), "s": (center.x(), bottom), "se": (right, bottom),
        }
        return {
            name: QRect(x - half, y - half, HANDLE_SIZE_PX, HANDLE_SIZE_PX)
            for name, (x, y) in anchors.items()
        }

    def hit_test(self, point: QPoint) -> str:
        """控件坐标命中判定：手柄名 / `"inside"` / `"outside"`（四角优先于四边）。"""
        rect = self._image_rect_on_widget()
        if rect.isEmpty():
            return "outside"
        for name in ("nw", "ne", "sw", "se", "n", "e", "s", "w"):
            if self.handle_rects()[name].contains(point):
                return name
        return "inside" if rect.contains(point) else "outside"

    def _apply_move(self, point: QPoint) -> None:
        """整体平移选区：夹在图像内（贴边即停），尺寸不变。"""
        if self._start_rect is None or self._origin is None:
            return
        rect = self._start_rect.normalized()
        image_w, image_h = self.image_size
        dx = point.x() - self._origin.x()
        dy = point.y() - self._origin.y()
        dx = max(-rect.left(), min(dx, image_w - (rect.left() + rect.width())))
        dy = max(-rect.top(), min(dy, image_h - (rect.top() + rect.height())))
        self._image_selection = QRect(rect.left() + dx, rect.top() + dy, rect.width(), rect.height())

    def _apply_resize(self, point: QPoint, *, symmetric: bool = False) -> None:
        """拖手柄改大小：被拖的边跟随指针（右/下为"不含边界"），对角固定、不小于最小尺寸。

        `symmetric=True`（按住 Alt，用户 2026-09-20 要求）时改为**以选区中心为锚点对称缩放**：
        拖某个手柄会让两边一起变，中心保持不动。
        """
        if self._start_rect is None or self._handle is None:
            return
        rect = self._start_rect.normalized()
        left, top = rect.left(), rect.top()
        right = left + rect.width()             # 不含边界（与拖拽创建时的宽高语义一致）
        bottom = top + rect.height()
        if symmetric:
            center_x, center_y = left + rect.width() / 2, top + rect.height() / 2
            if "w" in self._handle or "e" in self._handle:
                half = max(abs(point.x() - center_x), MIN_SELECTION_SIZE / 2)
                left, right = int(round(center_x - half)), int(round(center_x + half))
            if "n" in self._handle or "s" in self._handle:
                half = max(abs(point.y() - center_y), MIN_SELECTION_SIZE / 2)
                top, bottom = int(round(center_y - half)), int(round(center_y + half))
            left, top = max(0, left), max(0, top)
            right = min(self.image_size[0], max(right, left + MIN_SELECTION_SIZE))
            bottom = min(self.image_size[1], max(bottom, top + MIN_SELECTION_SIZE))
            self._image_selection = QRect(left, top, right - left, bottom - top)
            return
        if "n" in self._handle:
            top = min(point.y(), bottom - MIN_SELECTION_SIZE)
        if "s" in self._handle:
            bottom = max(point.y(), top + MIN_SELECTION_SIZE)
        if "w" in self._handle:
            left = min(point.x(), right - MIN_SELECTION_SIZE)
        if "e" in self._handle:
            right = max(point.x(), left + MIN_SELECTION_SIZE)
        self._image_selection = QRect(left, top, right - left, bottom - top)

    # ------------------------------------------------------------- 交互
    def mousePressEvent(self, event) -> None:      # noqa: N802 (Qt 命名)
        button = event.button()
        widget_point = event.position().toPoint()
        self._cursor_widget = widget_point
        point = self._widget_point_in_image(widget_point)
        # 记下按下之前的选区：Esc 撤销这次拖拽时要还原它
        self._selection_before_drag = self._image_selection
        if button == Qt.MouseButton.MiddleButton or (
            button == Qt.MouseButton.LeftButton and self._space_down and self._image_selection is None
        ):
            # 中键拖拽 / 空格+左键（没有选区时）＝平移画面
            self._mode = "pan"
            self._pan_origin = widget_point
            self._pan_start = self._pan
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if button == Qt.MouseButton.RightButton:
            # 右键拖拽＝移动选区（左键保留给"重新框选"）
            if self._image_selection is None:
                return
            self._begin_move(point)
            self.update()
            self.selection_changed.emit()
            return
        if button != Qt.MouseButton.LeftButton:
            return
        hit = self.hit_test(widget_point)
        if self._space_down and self._image_selection is not None:
            self._begin_move(point)               # 空格+拖拽＝无论按在哪都移动
        elif hit == "inside" or hit in HANDLE_CURSORS:
            if hit == "inside":
                self._begin_move(point)
            else:
                # 改大小：手柄＝改大小（起点、初始选区、按下时是否按着 Alt 都要记下来）
                self._start_rect = (self._image_selection or QRect()).normalized()
                self._origin = point
                self._handle = hit
                self._symmetric_resize = bool(
                    event.modifiers() & Qt.KeyboardModifier.AltModifier
                )
                self._mode = "resize"
                self.setCursor(HANDLE_CURSORS[hit])
        else:
            # 选区外：重新框选
            self._mode = "create"
            self._handle = None
            self._start_rect = None
            self._origin = point
            self._set_selection_from_points(point, point)
        self.update()
        self.selection_changed.emit()

    def _begin_move(self, point: QPoint) -> None:
        """进入"移动选区"模式（内部拖拽 / 空格拖拽 / 右键拖拽共用）。"""
        self._start_rect = (self._image_selection or QRect()).normalized()
        self._origin = point
        self._handle = None
        self._mode = "move"
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:       # noqa: N802
        widget_point = event.position().toPoint()
        self._cursor_widget = widget_point
        self._cursor_in_image = self._widget_point_in_image(widget_point)
        if self._mode == "pan" and self._pan_origin is not None:
            self._pan = self._pan_start + (widget_point - self._pan_origin)
            self._clamp_pan()
            self.update()
            self.view_changed.emit()
            return
        if self._origin is None:
            self._update_cursor(widget_point)      # 没按住时只更新指针形状（提示能改哪里）
            # 放大镜与坐标提示是"贴着鼠标画"的：不重绘就会停在上一帧位置
            self.update()
            self.view_changed.emit()
            return
        point = self._widget_point_in_image(widget_point)
        if self._mode == "move":
            self._apply_move(point)
        elif self._mode == "resize":
            # Alt 在按下时或拖动中按下都算（对称缩放＝以选区中心为锚点）
            symmetric = self._symmetric_resize or bool(
                event.modifiers() & Qt.KeyboardModifier.AltModifier
            )
            self._apply_resize(point, symmetric=symmetric)
        else:
            self._set_selection_from_points(self._origin, point)
        self.update()
        self.selection_changed.emit()

    def mouseDoubleClickEvent(self, event) -> None:    # noqa: N802
        """双击＝清空选区（重新框）。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._image_selection = None
            self._reset_drag_state()
            self.update()
            self.selection_changed.emit()
            event.accept()

    def mouseReleaseEvent(self, event) -> None:    # noqa: N802
        if event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.MiddleButton,
        ):
            self._reset_drag_state()
            self._update_cursor(event.position().toPoint())
            self.selection_changed.emit()

    def _reset_drag_state(self) -> None:
        self._origin = None
        self._mode = None
        self._handle = None
        self._start_rect = None
        self._selection_before_drag = None
        self._pan_origin = None

    # ------------------------------------------------------------- 拖拽时的尺寸气泡
    def drag_bubble_text(self) -> str:
        """拖拽时气泡文字（宽×高 + 客户区左上角）；没在拖拽时为空。"""
        if self._origin is None or self._image_selection is None:
            return ""
        rect = self._image_selection.normalized()
        return f"{rect.width()}×{rect.height()} @ ({rect.left()}, {rect.top()})"

    def drag_bubble_rect(self) -> QRect:
        """气泡位置：贴着鼠标，靠边时自动翻到另一侧（避免被裁掉）。"""
        text = self.drag_bubble_text()
        if not text or self._cursor_widget is None:
            return QRect()
        metrics = QFontMetrics(self.font())
        width = metrics.horizontalAdvance(text) + 2 * BUBBLE_PADDING_PX
        height = metrics.height() + 2 * BUBBLE_PADDING_PX
        x = self._cursor_widget.x() + 16
        y = self._cursor_widget.y() + 16
        if x + width > self.width():
            x = self._cursor_widget.x() - width - 16
        if y + height > self.height():
            y = self._cursor_widget.y() - height - 16
        return QRect(max(0, x), max(0, y), width, height)

    def keyReleaseEvent(self, event) -> None:      # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            self._space_down = False
            if self._cursor_widget is not None:
                self._update_cursor(self._cursor_widget)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _update_cursor(self, widget_point: QPoint) -> None:
        """悬停提示：手柄＝缩放箭头、选区内＝可移动、平移模式＝手形、外部＝十字。"""
        if self._mode == "pan":
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self._space_down and self._image_selection is None:
            self.setCursor(Qt.CursorShape.OpenHandCursor)     # 空格＝平移画面
            return
        hit = self.hit_test(widget_point)
        if hit in HANDLE_CURSORS:
            self.setCursor(HANDLE_CURSORS[hit])
        elif hit == "inside":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------- 键盘微调
    def keyPressEvent(self, event) -> None:        # noqa: N802
        """方向键微调选区（用户 2026-09-20 要求）：

        - `←↑→↓`：整体移动 1 个**图像**像素；`Shift+方向键`＝10 像素；
        - `Ctrl+方向键`：对应那条边**向外** 1 像素（选区变大）；
        - `Ctrl+Shift+方向键`：同一条边**向内** 1 像素（选区变小）；
        - 还没有选区时不做事（不会凭空造出选区）。

        为什么需要它：截图是等比缩放显示的，鼠标一次只能挪 1 个**控件**像素
        （2 倍显示时＝图像 0.5 像素，取整后时而不动、时而跳 2 像素），键盘可以稳定 ±1。
        """
        deltas = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if event.key() == Qt.Key.Key_Space:
            self._space_down = True                       # 按住空格＝把拖拽变成"移动选区"
            if self._image_selection is not None:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            if self._origin is not None:                  # 拖拽中：撤销这次拖拽
                self._image_selection = self._selection_before_drag
                self._reset_drag_state()
                self.update()
                self.selection_changed.emit()
                event.accept()
                return
            if self._image_selection is not None:         # 有选区：清空
                self._image_selection = None
                self.update()
                self.selection_changed.emit()
                event.accept()
                return
            super().keyPressEvent(event)                  # 都没有：交给对话框（→ 关窗）
            return
        if event.key() not in deltas or self._image_selection is None:
            super().keyPressEvent(event)
            return
        dx, dy = deltas[event.key()]
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            inward = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            self._nudge_edge(dx, dy, inward=inward)
        else:
            step = 10 if modifiers & Qt.KeyboardModifier.ShiftModifier else 1
            self._nudge_whole(dx * step, dy * step)
        self.update()
        self.selection_changed.emit()
        event.accept()

    def _nudge_whole(self, dx: int, dy: int) -> None:
        """整体平移（与鼠标拖动同一套夹取规则：夹在图像内、尺寸不变）。"""
        if self._image_selection is None:
            return
        rect = self._image_selection.normalized()
        image_w, image_h = self.image_size
        dx = max(-rect.left(), min(dx, image_w - (rect.left() + rect.width())))
        dy = max(-rect.top(), min(dy, image_h - (rect.top() + rect.height())))
        self._image_selection = QRect(rect.left() + dx, rect.top() + dy, rect.width(), rect.height())

    def _nudge_edge(self, dx: int, dy: int, *, inward: bool) -> None:
        """只移动一条边：`dx/dy` 指向那条边，`inward=True` 时反向（往里收）。

        右/下边界仍是不含边界（与拖拽创建、拖手柄时的口径一致），并保证
        不小于 `MIN_SELECTION_SIZE`、不越出图像。
        """
        if self._image_selection is None:
            return
        rect = self._image_selection.normalized()
        left, top = rect.left(), rect.top()
        right, bottom = left + rect.width(), top + rect.height()
        image_w, image_h = self.image_size
        if dx:
            edge = (left if dx < 0 else right) + (-dx if inward else dx)
            edge = max(0, min(edge, image_w))
            if dx < 0:
                left = max(0, min(edge, right - MIN_SELECTION_SIZE))
            else:
                right = min(image_w, max(edge, left + MIN_SELECTION_SIZE))
        if dy:
            edge = (top if dy < 0 else bottom) + (-dy if inward else dy)
            edge = max(0, min(edge, image_h))
            if dy < 0:
                top = max(0, min(edge, bottom - MIN_SELECTION_SIZE))
            else:
                bottom = min(image_h, max(edge, top + MIN_SELECTION_SIZE))
        self._image_selection = QRect(left, top, right - left, bottom - top)

    def paintEvent(self, event) -> None:           # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND_COLOR)
        display = self.image_rect()
        if not display.isEmpty():
            painter.drawImage(display, self._qimage)
        selection = self._image_rect_on_widget()
        if not selection.isEmpty():
            self._paint_dim_mask(painter, selection)      # 选区外压暗：一眼看清选了哪块
            painter.setPen(QPen(SELECTION_COLOR, 2))
            painter.drawRect(selection)
            # 八个手柄：让用户看得见"这里可以拖"
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(SELECTION_COLOR)
            for handle in self.handle_rects().values():
                painter.drawRect(handle)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        bubble = self.drag_bubble_rect()
        if not bubble.isEmpty():
            painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
            painter.setBrush(BUBBLE_COLOR)
            painter.drawRoundedRect(bubble, 4, 4)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(bubble, Qt.AlignmentFlag.AlignCenter, self.drag_bubble_text())
            painter.setBrush(Qt.BrushStyle.NoBrush)
        self._paint_magnifier(painter)

    def _paint_dim_mask(self, painter: QPainter, selection: QRect) -> None:
        """把选区以外的区域压暗（四个矩形拼起来，避免动到选区内的像素）。"""
        width, height = self.width(), self.height()
        top = selection.top()
        bottom = selection.bottom()
        left, right = selection.left(), selection.right()
        painter.fillRect(QRect(0, 0, width, top), DIM_COLOR)
        painter.fillRect(QRect(0, bottom + 1, width, height - bottom - 1), DIM_COLOR)
        painter.fillRect(QRect(0, top, left, selection.height()), DIM_COLOR)
        painter.fillRect(QRect(right + 1, top, width - right - 1, selection.height()), DIM_COLOR)
