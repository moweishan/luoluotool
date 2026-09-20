"""框选截图生成模板：把游戏窗口截图放大显示，鼠标拖框选区 → 存成模板 PNG。

为什么需要它：手工用截图工具裁剪模板很容易裁到"会变化的区域"或裁偏；
这里直接拿工具自己截的图、在同一个坐标系里框选，保存的就是识别要用的那部分像素。

坐标说明：选区对外暴露为**图像像素坐标**，而图像就是游戏窗口的客户区截图，
因此选区左上角就是客户区坐标（与点击/滑动/识别结果同一坐标系）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from luoluotool.automation.vision import save_image

logger = logging.getLogger(__name__)

MIN_SELECTION_SIZE = 8          # 选区小于该像素数视为无效（点一下、手抖）
NEAR_FULL_RATIO = 0.95          # 选区面积 ≥ 整屏的该比例时提示"几乎等于整屏"
BACKGROUND_COLOR = QColor(32, 32, 32)
SELECTION_COLOR = QColor(0, 220, 255)
HANDLE_SIZE_PX = 10             # 手柄命中范围（控件像素）：缩放后也要好点中

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


class CropView(QWidget):
    """显示截图并支持左键拖拽框选；选区以图像像素坐标对外暴露。

    交互（用户 2026-09-20 要求"框选完还能改"）：
    - **选区外**按下拖拽 → 重新框选；
    - **选区内部**按下拖拽 → 整体移动（贴到图像边界即停，尺寸不变）；
    - **四角/四边手柄**上按下拖拽 → 改大小（对角固定、最小 MIN_SELECTION_SIZE 像素）。
    """

    selection_changed = Signal()

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
        self.setMinimumSize(360, 240)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------- 几何换算
    @property
    def image_size(self) -> tuple[int, int]:
        height, width = self._image.shape[:2]
        return int(width), int(height)

    def image_rect(self) -> QRect:
        """图像在控件内的显示区域（等比缩放 + 居中）。"""
        width, height = self.image_size
        if width <= 0 or height <= 0 or self.width() <= 0 or self.height() <= 0:
            return QRect()
        scale = min(self.width() / width, self.height() / height)
        drawn_w, drawn_h = int(width * scale), int(height * scale)
        return QRect((self.width() - drawn_w) // 2, (self.height() - drawn_h) // 2, drawn_w, drawn_h)

    def _scale(self) -> float:
        width, _ = self.image_size
        drawn = self.image_rect().width()
        return drawn / width if width else 1.0

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

    def _apply_resize(self, point: QPoint) -> None:
        """拖手柄改大小：被拖的边跟随指针（右/下为"不含边界"），对角固定、不小于最小尺寸。"""
        if self._start_rect is None or self._handle is None:
            return
        rect = self._start_rect.normalized()
        left, top = rect.left(), rect.top()
        right = left + rect.width()             # 不含边界（与拖拽创建时的宽高语义一致）
        bottom = top + rect.height()
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
        if event.button() != Qt.MouseButton.LeftButton:
            return
        widget_point = event.position().toPoint()
        point = self._widget_point_in_image(widget_point)
        hit = self.hit_test(widget_point)
        if hit == "inside" or hit in HANDLE_CURSORS:
            # 改已有选区：内部＝整体移动，手柄＝改大小（起点与初始选区都要记下来）
            self._start_rect = (self._image_selection or QRect()).normalized()
            self._origin = point
            self._handle = None if hit == "inside" else hit
            self._mode = "move" if hit == "inside" else "resize"
            self.setCursor(
                Qt.CursorShape.ClosedHandCursor if hit == "inside" else HANDLE_CURSORS[hit]
            )
        else:
            # 选区外：重新框选
            self._mode = "create"
            self._handle = None
            self._start_rect = None
            self._origin = point
            self._set_selection_from_points(point, point)
        self.update()
        self.selection_changed.emit()

    def mouseMoveEvent(self, event) -> None:       # noqa: N802
        widget_point = event.position().toPoint()
        if self._origin is None:
            self._update_cursor(widget_point)      # 没按住时只更新指针形状（提示能改哪里）
            return
        point = self._widget_point_in_image(widget_point)
        if self._mode == "move":
            self._apply_move(point)
        elif self._mode == "resize":
            self._apply_resize(point)
        else:
            self._set_selection_from_points(self._origin, point)
        self.update()
        self.selection_changed.emit()

    def mouseReleaseEvent(self, event) -> None:    # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = None
            self._mode = None
            self._handle = None
            self._start_rect = None
            self._update_cursor(event.position().toPoint())
            self.selection_changed.emit()

    def _update_cursor(self, widget_point: QPoint) -> None:
        """悬停提示：手柄上给对应方向的缩放指针，选区内给"可移动"指针，外部给十字。"""
        hit = self.hit_test(widget_point)
        if hit in HANDLE_CURSORS:
            self.setCursor(HANDLE_CURSORS[hit])
        elif hit == "inside":
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, event) -> None:           # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND_COLOR)
        display = self.image_rect()
        if not display.isEmpty():
            painter.drawImage(display, self._qimage)
        selection = self._image_rect_on_widget()
        if not selection.isEmpty():
            painter.setPen(QPen(SELECTION_COLOR, 2))
            painter.drawRect(selection)
            # 八个手柄：让用户看得见"这里可以拖"
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(SELECTION_COLOR)
            for handle in self.handle_rects().values():
                painter.drawRect(handle)
            painter.setBrush(Qt.BrushStyle.NoBrush)


class TemplateCropDialog(QDialog):
    """框选截图生成模板：拖拽选区 → 「保存为模板」写入 save_dir。"""

    def __init__(
        self,
        image_bgr: np.ndarray,
        window_size: tuple[int, int],
        save_dir: Path | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("框选截图生成模板")
        self._image = image_bgr
        self._save_dir = Path(save_dir) if save_dir is not None else None
        self.saved_path: Path | None = None

        width, height = int(window_size[0]), int(window_size[1])
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"在下面的截图里按住左键拖出要识别的区域（截图＝游戏客户区 {width}x{height}）。\n"
            "框好之后还能改：**拖选区内部＝整体移动**，**拖四角/四边的小方块＝改大小**，"
            "在选区外重新拖＝重新框选。\n"
            "建议框选画面中**不会变化**的局部（数字、倒计时等变动区域会让匹配不稳定）。"
        ))
        self.view = CropView(image_bgr)
        self.crop_view = self.view            # 语义化别名
        self.info_label = QLabel("尚未选择区域")
        self.view.selection_changed.connect(self._refresh_info)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.info_label)

        buttons = QDialogButtonBox()
        self.save_button = QPushButton("保存为模板")
        self.cancel_button = QPushButton("取消")
        buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        # 保存按钮必须走"裁剪 + 落盘"，不能直接 accept()：否则对话框一关就什么都没存
        # （历史缺陷：这里原是 connect(self.accept)，导致「保存为模板」实际只关窗口，
        #   主窗口随后报"未选择有效区域"—— 见 tests/test_gui_crop.py 的按钮回归测试）
        self.save_button.clicked.connect(self._on_save_clicked)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.resize(900, 640)

    # ------------------------------------------------------------- 选区
    def selection(self) -> tuple[int, int, int, int] | None:
        return self.view.selection_in_image()

    def set_selection_in_image(self, x: int, y: int, width: int, height: int) -> None:
        self.view.set_selection_in_image(x, y, width, height)

    def selection_text(self) -> str:
        """人读描述：尺寸 + 客户区左上角坐标（未选区时给出提示）。"""
        selection = self.selection()
        if selection is None:
            return "尚未选择区域（按住左键拖拽框选）"
        x, y, width, height = selection
        text = f"选区 {width}x{height}，客户区左上 ({x}, {y})，中心 ({x + width // 2}, {y + height // 2})"
        image_w, image_h = self.view.image_size
        if width * height >= image_w * image_h * NEAR_FULL_RATIO:
            text += "　⚠ 选区几乎等于整屏，这样的模板基本没有辨识度（可能框错了）"
        return text

    def _refresh_info(self) -> None:
        self.info_label.setText(self.selection_text())

    # ------------------------------------------------------------- 保存
    def _on_save_clicked(self) -> None:
        """「保存为模板」：只把**手动框选的那块区域**裁剪存盘，成功后才关闭对话框。

        没有有效选区（没拖、或框得太小）时不写文件、也不关闭，只在提示行说明原因，
        让用户继续框 —— 避免"点了保存却什么都没存"这种静默失败。
        """
        if self.selection() is None:
            self.info_label.setText(
                f"请先按住左键拖拽框选要保存的区域（至少 {MIN_SELECTION_SIZE}x{MIN_SELECTION_SIZE} 像素）"
            )
            return
        if self.save_selection() is None:
            self.info_label.setText("保存失败：请检查模板目录是否可写（详情见日志）")
            return
        self.accept()

    def save_selection(self) -> Path | None:
        """把选区裁剪成模板 PNG；无有效选区时返回 None（不写文件）。"""
        selection = self.selection()
        if selection is None:
            logger.warning("未选择有效区域（至少 %dx%d 像素）", MIN_SELECTION_SIZE, MIN_SELECTION_SIZE)
            return None
        if self._save_dir is None:
            logger.warning("未配置模板保存目录")
            return None
        x, y, width, height = selection
        crop = self._image[y : y + height, x : x + width]
        path = self._save_dir / f"anchor_{datetime.now():%Y%m%d_%H%M%S}.png"
        try:
            # 评审 P2-8：mkdir 必须在 try 内 —— 目录不可写时旧实现直接冒 OSError 进 Qt 槽，
            # 调用方那句"保存失败：请检查模板目录是否可写"永远走不到。
            self._save_dir.mkdir(parents=True, exist_ok=True)
            self.saved_path = save_image(path, crop)
            logger.info(
                "模板已保存：%s（只保存框选区域 %dx%d，客户区左上 (%d, %d)）",
                path, width, height, x, y,
            )
        except Exception as exc:                 # 磁盘/编码/权限异常 → 记录并返回 None
            logger.exception("保存模板失败：%s", exc)
            self.saved_path = None
        return self.saved_path
