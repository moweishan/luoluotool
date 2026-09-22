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

# 缩略图条（参考图可以多选，见 `ThumbnailStrip`）
THUMBNAIL_SIZE = QSize(56, 42)
THUMBNAIL_SPACING = 6
THUMBNAIL_PADDING = 3
THUMBNAIL_SELECTED_BORDER = "#2f7fd0"   # 当前选中的那张：蓝色边框


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


class ThumbnailStrip(QFrame):
    """参考图缩略图条：横排小图，**点选看大图、双击放大、右键移除/清空**。

    为什么要它（2026-09-22 用户要求「选择图片…可以多选」）：一个建筑可能配多张参考图
    （不同角度/时机），界面得让用户看见"到底选了哪几张"、挑一张看大图，并能撤掉选错的。
    图片由控制器在**后台线程**解码后交进来（`set_images` / `set_image_at`），
    本控件只负责显示与交互，不碰文件（AGENTS §1.5 的 UI/业务分离）。

    张数上限由 `config.models.MAX_REFERENCE_IMAGES`（＝10）管；缩略图固定 `THUMBNAIL_SIZE`，
    10 张排在一行约 620px，够放在建筑分组里（放不下时右侧会被裁掉，但上限保证不会到那一步）。
    """

    image_selected = Signal(int)      # 点选了第 i 张（0 起）
    image_activated = Signal(int)     # 双击第 i 张（＝放大看）
    remove_requested = Signal(int)    # 右键「移除这张」
    clear_requested = Signal()        # 右键「清空全部」

    def __init__(self, empty_text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._images: list[QImage | None] = []
        self._selected = 0
        self._empty_text = empty_text
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(THUMBNAIL_SIZE.height() + THUMBNAIL_PADDING * 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    # ---------------------------------------------------------------- 数据
    def set_images(self, images: list[QImage | None]) -> None:
        """整批换掉（图片可以是 None＝还在后台解码）。"""
        self._images = list(images)
        self._selected = min(self._selected, max(0, len(self._images) - 1))
        self.update()

    def set_image_at(self, index: int, image: QImage | None) -> None:
        """只换第 index 张（后台解码完成一张就调一次）。"""
        if 0 <= index < len(self._images):
            self._images[index] = image
            self.update()

    def images(self) -> tuple[QImage | None, ...]:
        return tuple(self._images)

    def image_at(self, index: int) -> QImage | None:
        return self._images[index] if 0 <= index < len(self._images) else None

    def count(self) -> int:
        return len(self._images)

    def selected_index(self) -> int:
        return self._selected

    def select(self, index: int) -> None:
        """选中第 index 张（越界夹到有效范围；空列表时保持 0）。不改数据，只改高亮。"""
        if not self._images:
            return
        self._selected = max(0, min(len(self._images) - 1, index))
        self.update()

    def empty_text(self) -> str:
        return self._empty_text

    # ---------------------------------------------------------------- 几何
    def _item_rect(self, index: int) -> QRect:
        """第 index 张的方框（缩略图固定大小 + 间距，从左上角铺开）。"""
        return QRect(
            THUMBNAIL_PADDING + index * (THUMBNAIL_SIZE.width() + THUMBNAIL_SPACING),
            THUMBNAIL_PADDING,
            THUMBNAIL_SIZE.width(),
            THUMBNAIL_SIZE.height(),
        )

    def _index_at(self, pos) -> int | None:
        """鼠标落在第几张（不在任何缩略图上返回 None）。"""
        for index in range(len(self._images)):
            if self._item_rect(index).contains(pos):
                return index
        return None

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:                 # noqa: N802 (Qt 命名)
        super().paintEvent(event)
        painter = QPainter(self)
        if not self._images:
            painter.setPen(QColor(PREVIEW_TEXT_COLOR))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             self._empty_text)
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for index, image in enumerate(self._images):
            rect = self._item_rect(index)
            painter.fillRect(rect, QColor(PREVIEW_BACKGROUND))
            if image is not None and not image.isNull():
                painter.drawImage(rect, image, image.rect())
            border = THUMBNAIL_SELECTED_BORDER if index == self._selected else PREVIEW_BORDER
            painter.setPen(QColor(border))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            painter.setPen(QColor(PREVIEW_TEXT_COLOR))
            painter.drawText(rect.adjusted(3, 2, -3, -2),
                             Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                             str(index + 1))

    # ---------------------------------------------------------------- 交互
    def mousePressEvent(self, event) -> None:            # noqa: N802 (Qt 命名)
        index = self._index_at(event.position().toPoint())
        if index is not None and event.button() == Qt.MouseButton.LeftButton:
            self.select(index)
            self.image_selected.emit(index)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:      # noqa: N802 (Qt 命名)
        index = self._index_at(event.position().toPoint())
        if index is not None:
            self.select(index)
            self.image_activated.emit(index)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _on_context_menu(self, pos) -> None:
        """右键菜单：移除鼠标下那张 / 清空全部（列表为空时不弹）。"""
        if not self._images:
            return
        from PySide6.QtWidgets import QMenu

        index = self._index_at(pos)
        menu = QMenu(self)
        if index is not None:
            remove = menu.addAction(f"移除第 {index + 1} 张")
            remove.triggered.connect(lambda _checked=False, i=index: self.remove_requested.emit(i))
        clear = menu.addAction("清空全部")
        clear.triggered.connect(lambda _checked=False: self.clear_requested.emit())
        menu.exec(self.mapToGlobal(pos))
