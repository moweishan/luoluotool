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
BACKGROUND_COLOR = QColor(32, 32, 32)
SELECTION_COLOR = QColor(0, 220, 255)


def to_qimage(image_bgr: np.ndarray) -> QImage:
    """BGR numpy 数组 → QImage（Qt 用 RGB，必须交换通道，否则颜色会错）。"""
    rgb = np.ascontiguousarray(image_bgr[:, :, ::-1])
    height, width = rgb.shape[:2]
    return QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()


class CropView(QWidget):
    """显示截图并支持左键拖拽框选；选区以图像像素坐标对外暴露。"""

    selection_changed = Signal()

    def __init__(self, image_bgr: np.ndarray, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = image_bgr
        self._qimage = to_qimage(image_bgr)
        self._origin: QPoint | None = None
        # 选区以**图像像素坐标**为准（显示时再换算到控件坐标，避免缩放取整来回丢精度）
        self._image_selection: QRect | None = None
        self.setMinimumSize(360, 240)
        self.setMouseTracking(True)

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

    # ------------------------------------------------------------- 交互
    def mousePressEvent(self, event) -> None:      # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            point = self._widget_point_in_image(event.position().toPoint())
            self._origin = point
            self._set_selection_from_points(point, point)
            self.update()
            self.selection_changed.emit()

    def mouseMoveEvent(self, event) -> None:       # noqa: N802
        if self._origin is not None:
            point = self._widget_point_in_image(event.position().toPoint())
            self._set_selection_from_points(self._origin, point)
            self.update()
            self.selection_changed.emit()

    def mouseReleaseEvent(self, event) -> None:    # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = None
            self.selection_changed.emit()

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
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.resize(900, 640)

    # ------------------------------------------------------------- 选区
    def selection(self) -> tuple[int, int, int, int] | None:
        return self.view.selection_in_image()

    def set_selection_in_image(self, x: int, y: int, width: int, height: int) -> None:
        self.view.set_selection_in_image(x, y, width, height)

    def selection_text(self) -> str:
        """人读描述：尺寸 + 客户区左下角坐标（未选区时给出提示）。"""
        selection = self.selection()
        if selection is None:
            return "尚未选择区域（按住左键拖拽框选）"
        x, y, width, height = selection
        return f"选区 {width}x{height}，客户区左上 ({x}, {y})，中心 ({x + width // 2}, {y + height // 2})"

    def _refresh_info(self) -> None:
        self.info_label.setText(self.selection_text())

    # ------------------------------------------------------------- 保存
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
        self._save_dir.mkdir(parents=True, exist_ok=True)
        path = self._save_dir / f"anchor_{datetime.now():%Y%m%d_%H%M%S}.png"
        try:
            self.saved_path = save_image(path, crop)
        except Exception as exc:                 # 磁盘/编码异常 → 记录并返回 None
            logger.exception("保存模板失败：%s", exc)
            self.saved_path = None
        return self.saved_path
