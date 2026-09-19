"""通用小组件：日志面板 Handler + 页签滚动基类。"""

import logging

from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget

# 所有页签统一上报的建议尺寸：`QTabWidget` 的建议高度取「最高页签的 sizeHint」，
# 若各页签建议高度不同，挂载/卸载某个页签就会改变页签区高度、挤动其它页签与日志面板。
PAGE_SIZE_HINT = QSize(520, 240)


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
