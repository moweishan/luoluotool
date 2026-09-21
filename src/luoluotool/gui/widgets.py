"""通用小组件：日志面板 Handler + 页签滚动基类 + 图片显示区。"""

import logging

from PySide6.QtCore import QObject, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget

# 所有页签统一上报的建议尺寸：`QTabWidget` 的建议高度取「最高页签的 sizeHint」，
# 若各页签建议高度不同，挂载/卸载某个页签就会改变页签区高度、挤动其它页签与日志面板。
PAGE_SIZE_HINT = QSize(520, 240)

# 图片显示区的样式（与 `pages/daily.py` 的虚线占位框同一套观感）
PREVIEW_BACKGROUND = "#f2f2f2"
PREVIEW_BORDER = "#b8b8b8"
PREVIEW_TEXT_COLOR = "#888888"
PREVIEW_MIN_SIZE = QSize(160, 84)


class LogPanelHandler(logging.Handler, QObject):
    """把 logging 记录转发到日志面板（跨线程经 Qt 信号投递到 UI 线程）。"""

    record_emitted = Signal(str)

    def __init__(self, panel: QPlainTextEdit) -> None:
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.record_emitted.connect(panel.appendPlainText)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self.record_emitted.emit(self.format(record))


class ScrollablePage(QWidget):
    """**所有页签**的基类：内容自动放进 `QScrollArea`，并上报统一的建议尺寸。

    为什么所有页签都要这样（2026-09-19 用户实测）：页签内容是 `QTabWidget` 高度来源——
    ① **最小高度**取所有页签里的最大值：某个页签内容过高会把页签区顶高、撑大窗口
    （实测 381 → 658）；② **建议高度**同样取最大值：实测调试页让页签区从 284 → 316、
    日志面板 284 → 252、所有页签高度随之变化。
    因此这里同时做两件事：内容进滚动区（压住最小高度）+ 建议尺寸常量化（压住建议高度）。

    派生类用法：`layout = QVBoxLayout(self.content)`。
    不要把布局建在 `self` 上——那样内容不会进入滚动区，本规则失效（有测试守卫）。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.content = QWidget()
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidget(self.content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll_area)

    def sizeHint(self) -> QSize:      # noqa: N802 (Qt 命名)
        """统一建议尺寸：与内容多少无关，保证页签区高度不随页签集合变化。"""
        return PAGE_SIZE_HINT


class ImagePreview(QFrame):
    """图片显示区：等比缩放显示一张 `QImage`，没图时显示一句灰字提示。

    用途：日常任务页每个建筑分组的「选择的图片」（用户 2026-09-21 要求）——
    让用户一眼看到**自己选的那张**长什么样，而不是只有一个路径字符串。

    约定：
    - **等比缩放**（`KeepAspectRatio` + 平滑），绝不拉伸变形；放不下时以左上为基准裁掉多余部分；
    - **双击**发 `double_clicked`（有图才发）—— 页面把它转成"请求放大预览"的信号，
      真正的弹窗由主窗口做（页面不碰文件，见 AGENTS §1.5 的 UI/业务分离）；
    - 最小尺寸与虚线占位框一致（160x84），换掉占位框不会改变页签高度（`--measure-layout` 的硬要求）。
    """

    double_clicked = Signal()

    def __init__(self, empty_text: str = "尚未选择图片", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._empty_text = empty_text
        self._image: QImage | None = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"background: {PREVIEW_BACKGROUND}; border: 1px dashed {PREVIEW_BORDER};"
        )
        self.setMinimumSize(PREVIEW_MIN_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ---------------------------------------------------------------- 数据
    def set_image(self, image: QImage | None) -> None:
        """设置要显示的图片；传 None＝清空（回到"尚未选择图片"）。"""
        self._image = image
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if image is not None else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def image(self) -> QImage | None:
        return self._image

    def empty_text(self) -> str:
        return self._empty_text

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:                 # noqa: N802 (Qt 命名)
        super().paintEvent(event)
        painter = QPainter(self)
        if self._image is None:
            painter.setPen(QColor(PREVIEW_TEXT_COLOR))   # 与虚线占位框里的灰字同一色号
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_text)
            return
        target = self._fitted_rect(self._image.size())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, self._image)

    def _fitted_rect(self, image_size: QSize) -> QRect:
        """等比缩放到控件内（不放大超过原图？不限制——放大镜式的放大由双击预览负责）。"""
        if image_size.isEmpty() or self.width() <= 0 or self.height() <= 0:
            return QRect()
        scale = min(self.width() / image_size.width(), self.height() / image_size.height())
        width = max(1, int(image_size.width() * scale))
        height = max(1, int(image_size.height() * scale))
        return QRect(0, 0, min(width, self.width()), min(height, self.height()))

    # ---------------------------------------------------------------- 交互
    def mouseDoubleClickEvent(self, event) -> None:      # noqa: N802 (Qt 命名)
        if self._image is not None:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
